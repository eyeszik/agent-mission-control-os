"""Frame composition.

The renderer pre-builds every expensive layer once per scene and then composes
each frame from cheap operations:

* ``plate``   - oversized background (gradient + motif + vignette + grain).
                Cropped and resized per frame for the Ken Burns move.
* ``front``   - output-sized parallax layer, translated per frame.
* ``text``    - output-sized title block, translated and faded per frame.
* ``caption`` - one pre-rendered layer per caption cue.

That layout is what makes a full CPU render of a 30 second vertical video take
tens of seconds rather than tens of minutes, with no GPU and no AI inference.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterator, Optional, Sequence

from PIL import Image, ImageDraw, ImageFilter

from ..models import Scene
from .fonts import FontBook
from .motifs import gradient_plate, grain, render_motif, vignette
from .palette import Palette, mix, rgba

#: How much larger the plate is than the output frame. This is the headroom the
#: Ken Burns move pans and zooms inside.
PLATE_SCALE = 1.22


def ease_out_cubic(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 3


def ease_in_out(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


@dataclass
class CaptionCue:
    """One burned-in caption line with its own timing, in scene-local seconds."""

    start: float
    end: float
    text: str
    layer: Optional[Image.Image] = None


@dataclass
class LayoutMetrics:
    """Resolution-independent type and spacing scale."""

    width: int
    height: int

    @property
    def unit(self) -> float:
        """One layout unit. Derived from the short edge so 9:16, 1:1 and 16:9
        all get proportionate type."""
        return min(self.width, self.height) / 100.0

    @property
    def margin(self) -> int:
        return int(self.unit * 8)

    @property
    def headline_size(self) -> int:
        return int(self.unit * 9.2)

    @property
    def kicker_size(self) -> int:
        return int(self.unit * 3.1)

    @property
    def caption_size(self) -> int:
        return int(self.unit * 4.6)

    @property
    def caption_baseline(self) -> int:
        """Captions sit in the lower third but clear of platform UI chrome."""
        return int(self.height * 0.80)


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    """Greedy word wrap measured against the real font metrics."""
    words = (text or "").split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _letterspaced(
    draw: ImageDraw.ImageDraw, xy: tuple[float, float], text: str, font, fill, spacing: float
) -> float:
    """Draw text with manual tracking. Returns the advance width."""
    x, y = xy
    for char in text:
        draw.text((x, y), char, font=font, fill=fill)
        x += draw.textlength(char, font=font) + spacing
    return x - xy[0]


class SceneFrameRenderer:
    """Builds the layers for one scene and yields its frames."""

    def __init__(
        self,
        scene: Scene,
        *,
        width: int,
        height: int,
        fps: int,
        palette: Palette,
        fonts: FontBook,
        style_font: str = "display_bold",
        captions: Sequence[CaptionCue] = (),
        burn_captions: bool = True,
        is_first: bool = False,
        is_last: bool = False,
    ) -> None:
        self.scene = scene
        self.width = width
        self.height = height
        self.fps = fps
        self.palette = palette
        self.fonts = fonts
        self.style_font = style_font
        self.captions = list(captions)
        self.burn_captions = burn_captions
        self.is_first = is_first
        self.is_last = is_last
        self.metrics = LayoutMetrics(width, height)
        self.frame_count = max(1, int(round(scene.duration * fps)))

        self.plate_size = (
            int(width * PLATE_SCALE) + (int(width * PLATE_SCALE) % 2),
            int(height * PLATE_SCALE) + (int(height * PLATE_SCALE) % 2),
        )
        self._plate: Optional[Image.Image] = None
        self._front: Optional[Image.Image] = None
        self._text: Optional[Image.Image] = None
        # RGB, not RGBA: the plate is fully opaque once composed, and dropping
        # the alpha channel removes 25% of the bytes moved by every frame's
        # crop/resize - the single hottest operation in the render loop.
        self._backdrop = Image.new("RGB", (width, height), palette.bg_a)
        self._headline_top_fraction = 0.30

    # -- layer construction ---------------------------------------------
    def build(self) -> None:
        """Render every reusable layer. Safe to call once; frames need it."""
        if self._plate is not None:
            return
        palette = self.palette
        # Text is laid out first so the motif can be placed away from it.
        self._text = self._render_text_layer()
        focal_y = (
            0.30 if self._headline_top_fraction > 0.45 else 0.66
        )
        motif = render_motif(
            self.scene.visual.motif, self.plate_size, palette, self.scene.seed, focal_y
        )
        plate = gradient_plate(self.plate_size, palette)
        plate = Image.alpha_composite(plate, motif.back)
        plate = Image.alpha_composite(plate, vignette(self.plate_size, 0.5))
        plate = Image.alpha_composite(plate, grain(self.plate_size, self.scene.seed, 9))
        self._plate = plate.convert("RGB")

        self._front = motif.front.resize((self.width, self.height), Image.BILINEAR)
        if self.burn_captions:
            for cue in self.captions:
                cue.layer = self._render_caption_layer(cue.text)

    def _render_text_layer(self) -> Image.Image:
        """Kicker + rule + headline, composed once at output resolution."""
        metrics = self.metrics
        layer = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        palette = self.palette
        margin = metrics.margin
        max_width = self.width - margin * 2

        headline_font = self.fonts.get(self.style_font, metrics.headline_size)
        kicker_font = self.fonts.get("sans_bold", metrics.kicker_size)

        lines = wrap_text(draw, self.scene.content.text_overlay, headline_font, max_width)
        # Shrink the headline until it fits the allotted block rather than
        # letting a long title overflow the frame.
        size = metrics.headline_size
        while len(lines) > 4 and size > metrics.unit * 4:
            size = int(size * 0.88)
            headline_font = self.fonts.get(self.style_font, size)
            lines = wrap_text(draw, self.scene.content.text_overlay, headline_font, max_width)

        line_height = int(size * 1.16)
        block_height = line_height * len(lines)

        composition = self.scene.visual.composition
        if "lower third" in composition:
            top = int(self.height * 0.56)
        elif "wide resolve" in self.scene.visual.shot_size or "calm" in composition:
            top = int((self.height - block_height) * 0.44)
        else:
            top = int(self.height * 0.30)
        top = max(margin * 2, min(top, int(self.height * 0.62) - block_height))
        self._headline_top_fraction = top / max(1, self.height)

        kicker = (self.scene.content.kicker or "").upper()
        if kicker:
            tracking = metrics.kicker_size * 0.18
            _letterspaced(
                draw,
                (margin, top - int(metrics.kicker_size * 3.0)),
                kicker,
                kicker_font,
                rgba(palette.accent, 240),
                tracking,
            )
            rule_y = top - int(metrics.kicker_size * 1.35)
            draw.line(
                [(margin, rule_y), (margin + int(metrics.unit * 14), rule_y)],
                fill=rgba(palette.accent, 220),
                width=max(2, int(metrics.unit * 0.55)),
            )

        # A soft scrim behind the type guarantees legibility over any motif.
        scrim = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        ImageDraw.Draw(scrim).rounded_rectangle(
            [margin - int(metrics.unit * 3),
             top - int(metrics.kicker_size * 4.4),
             self.width - margin + int(metrics.unit * 3),
             top + block_height + int(metrics.unit * 3)],
            radius=int(metrics.unit * 2.5),
            fill=rgba(mix(palette.bg_a, (0, 0, 0) if palette.is_dark else (255, 255, 255), 0.35), 92),
        )
        scrim = scrim.filter(ImageFilter.GaussianBlur(metrics.unit * 1.2))
        layer = Image.alpha_composite(scrim, layer)
        draw = ImageDraw.Draw(layer)

        for index, line in enumerate(lines):
            y = top + index * line_height
            # Drop shadow first, then ink: cheap, and it survives any palette.
            draw.text((margin + max(1, int(metrics.unit * 0.35)),
                       y + max(1, int(metrics.unit * 0.35))),
                      line, font=headline_font, fill=rgba((0, 0, 0), 120))
            draw.text((margin, y), line, font=headline_font, fill=rgba(palette.ink, 255))
        return layer

    def _render_caption_layer(self, text: str) -> Image.Image:
        metrics = self.metrics
        palette = self.palette
        layer = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        font = self.fonts.get("sans_bold", metrics.caption_size)
        max_width = int(self.width * 0.82)
        lines = wrap_text(draw, text, font, max_width)[:3]
        if not lines:
            return layer

        line_height = int(metrics.caption_size * 1.26)
        pad_x = int(metrics.unit * 3.2)
        pad_y = int(metrics.unit * 2.0)
        block_h = line_height * len(lines)
        block_w = int(max(draw.textlength(line, font=font) for line in lines))
        left = (self.width - block_w) // 2 - pad_x
        top = metrics.caption_baseline - block_h // 2 - pad_y

        draw.rounded_rectangle(
            [left, top, left + block_w + pad_x * 2, top + block_h + pad_y * 2],
            radius=int(metrics.unit * 1.8),
            fill=rgba(palette.caption_plate, 214),
        )
        ink = rgba(palette.caption_ink, 255)
        for index, line in enumerate(lines):
            line_w = draw.textlength(line, font=font)
            x = (self.width - line_w) / 2
            draw.text((x, top + pad_y + index * line_height), line, font=font, fill=ink)
        return layer

    # -- per-frame composition ------------------------------------------
    def _plate_crop(self, progress: float) -> Image.Image:
        """Ken Burns: crop a moving, scaling window out of the oversized plate."""
        assert self._plate is not None
        motion = self.scene.motion
        eased = ease_in_out(progress)
        zoom = motion.zoom_start + (motion.zoom_end - motion.zoom_start) * eased

        plate_w, plate_h = self.plate_size
        # The visible window shrinks as zoom grows.
        win_w = min(plate_w, self.width / zoom * PLATE_SCALE)
        win_h = min(plate_h, self.height / zoom * PLATE_SCALE)
        slack_x = max(0.0, plate_w - win_w)
        slack_y = max(0.0, plate_h - win_h)

        # pan in [-1, 1] maps across the available slack.
        pan_t = (eased - 0.5) * 2.0
        left = slack_x * 0.5 + motion.pan_x * pan_t * slack_x * 0.5
        top = slack_y * 0.5 + motion.pan_y * pan_t * slack_y * 0.5
        left = max(0.0, min(slack_x, left))
        top = max(0.0, min(slack_y, top))

        box = (int(left), int(top), int(left + win_w), int(top + win_h))
        return self._plate.resize((self.width, self.height), Image.BILINEAR, box=box)

    def _text_alpha_and_offset(self, t: float) -> tuple[float, int]:
        """Headline entrance: rise and fade in; settle and fade out at the end."""
        duration = self.scene.duration
        rise = min(0.55, duration * 0.28)
        fall_start = max(rise, duration - 0.42)
        if t < rise:
            p = ease_out_cubic(t / rise) if rise else 1.0
            return p, int((1.0 - p) * self.metrics.unit * 3.2)
        if t > fall_start and duration > 0:
            p = 1.0 - ease_in_out((t - fall_start) / max(0.01, duration - fall_start))
            return max(0.0, p) * 0.92 + 0.08, 0
        return 1.0, 0

    def _transition_alpha(self, t: float) -> float:
        """Fade in from / out to the scene's own background.

        Baked into the clip so scene durations stay exact. Overlapping
        transitions would shift every caption downstream.
        """
        fade = max(0.12, min(self.scene.motion.transition_seconds, self.scene.duration * 0.2))
        alpha = 1.0
        if t < fade:
            alpha = min(alpha, ease_in_out(t / fade))
        remaining = self.scene.duration - t
        if remaining < fade:
            alpha = min(alpha, ease_in_out(max(0.0, remaining) / fade))
        return alpha

    def frames(self) -> Iterator[Image.Image]:
        """Yield every RGB frame for this scene."""
        self.build()
        assert self._front is not None and self._text is not None
        parallax = self.scene.motion.parallax
        travel = self.metrics.unit * 3.0 * parallax

        for index in range(self.frame_count):
            progress = index / max(1, self.frame_count - 1)
            t = index / self.fps

            frame = self._plate_crop(progress)

            offset = int((progress - 0.5) * 2.0 * travel)
            frame.paste(self._front, (offset, -offset // 2), self._front)

            alpha, rise = self._text_alpha_and_offset(t)
            if alpha > 0.01:
                text = self._text
                if alpha < 0.999:
                    text = text.copy()
                    text.putalpha(text.getchannel("A").point(lambda v: int(v * alpha)))
                frame.paste(text, (0, rise), text)

            if self.burn_captions:
                for cue in self.captions:
                    if cue.layer is not None and cue.start <= t < cue.end:
                        pop = ease_out_cubic(min(1.0, (t - cue.start) / 0.18))
                        layer = cue.layer
                        if pop < 0.999:
                            layer = layer.copy()
                            layer.putalpha(
                                layer.getchannel("A").point(lambda v: int(v * pop))
                            )
                        frame.paste(layer, (0, int((1.0 - pop) * self.metrics.unit)), layer)
                        break

            fade = self._transition_alpha(t)
            if fade < 0.999:
                frame = Image.blend(self._backdrop, frame, fade)

            yield frame

    # -- stills ----------------------------------------------------------
    def still(self, at: float = 0.6) -> Image.Image:
        """A representative still, used for thumbnails and previews."""
        self.build()
        index = max(0, min(self.frame_count - 1, int(self.frame_count * at)))
        for position, frame in enumerate(self.frames()):
            if position >= index:
                return frame
        return Image.new("RGB", (self.width, self.height), self.palette.bg_a)


def render_thumbnail(
    scene: Scene,
    *,
    width: int,
    height: int,
    palette: Palette,
    fonts: FontBook,
    title: str,
    style_font: str = "display_bold",
) -> Image.Image:
    """A dedicated title card rather than a frame grab.

    A grabbed frame is mid-animation by definition; a purpose-built card gives a
    thumbnail with settled type and full contrast.
    """
    metrics = LayoutMetrics(width, height)
    card = Scene(
        id=scene.id,
        index=scene.index,
        duration=1.0,
        seed=scene.seed,
        content=type(scene.content)(
            narrative_function="hook",
            voiceover="",
            text_overlay=title,
            kicker=scene.content.kicker,
        ),
        visual=scene.visual,
        motion=type(scene.motion)(
            zoom_start=1.02, zoom_end=1.02, transition_seconds=0.0, parallax=0.0
        ),
    )
    renderer = SceneFrameRenderer(
        card,
        width=width,
        height=height,
        fps=1,
        palette=palette,
        fonts=fonts,
        style_font=style_font,
        captions=(),
        burn_captions=False,
    )
    renderer.build()
    frame = renderer._plate_crop(0.5)
    text = renderer._text
    if text is not None:
        frame.paste(text, (0, 0), text)
    front = renderer._front
    if front is not None:
        frame.paste(front, (0, 0), front)
    _ = metrics
    return frame.convert("RGB")
