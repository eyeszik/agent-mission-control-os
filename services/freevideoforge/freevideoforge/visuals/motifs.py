"""Procedural background motifs.

These are what stop the mandatory CPU renderer from looking like a solid colour
with text on it. Every motif is drawn from a seeded RNG, is resolution
independent, and is deliberately abstract - it carries rhythm, depth and a
sense of subject without claiming to depict the subject.

Each motif returns two RGBA layers:

* ``back``  - drawn into the plate and therefore subject to the Ken Burns move.
* ``front`` - composited at output resolution and translated for parallax.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFilter

from .palette import Palette, lerp, mix, rgba

MOTIF_NAMES = ("rings", "grid", "waveform", "strata", "orbit", "contour", "beam")


@dataclass
class MotifLayers:
    back: Image.Image
    front: Image.Image


def _blank(size: tuple[int, int]) -> Image.Image:
    return Image.new("RGBA", size, (0, 0, 0, 0))


def gradient_plate(size: tuple[int, int], palette: Palette, angle: float = 0.35) -> Image.Image:
    """A smooth two-stop gradient rendered cheaply.

    The gradient is built as a small image and upscaled, which is ~100x faster
    than per-pixel work at 1080x1920 and visually identical once blurred by the
    resample.
    """
    width, height = size
    steps = 256
    strip = Image.new("RGB", (steps, steps))
    pixels = strip.load()
    for y in range(steps):
        for x in range(steps):
            # Diagonal interpolation; angle biases between vertical and diagonal.
            t = (y / (steps - 1)) * (1.0 - angle) + (x / (steps - 1)) * angle
            pixels[x, y] = lerp(palette.bg_a, palette.bg_b, t)
    return strip.resize((width, height), Image.BICUBIC).convert("RGBA")


def vignette(size: tuple[int, int], strength: float = 0.55) -> Image.Image:
    """A radial darkening mask. Built at thumbnail size and upscaled, which is
    two orders of magnitude cheaper than per-pixel work at full resolution."""
    width, height = size
    small_w = 96
    small_h = max(8, int(96 * height / max(1, width)))
    mask = Image.new("L", (small_w, small_h), 0)
    pixels = mask.load()
    cx, cy = small_w / 2.0, small_h / 2.0
    max_r = math.hypot(cx, cy) or 1.0
    for y in range(small_h):
        for x in range(small_w):
            radius = math.hypot(x - cx, y - cy) / max_r
            falloff = min(1.0, max(0.0, (radius - 0.35) / 0.65)) ** 1.6
            pixels[x, y] = int(255 * strength * falloff)
    layer = Image.new("RGBA", (small_w, small_h), (0, 0, 0, 255))
    layer.putalpha(mask)
    return layer.resize(size, Image.BICUBIC)


def grain(size: tuple[int, int], seed: int, amount: int = 10) -> Image.Image:
    """Low-amplitude noise that keeps large flat gradients from banding."""
    rng = random.Random(seed)
    small = (max(8, size[0] // 4), max(8, size[1] // 4))
    noise = Image.new("L", small)
    noise.putdata([rng.randint(0, 255) for _ in range(small[0] * small[1])])
    noise = noise.resize(size, Image.BILINEAR).filter(ImageFilter.GaussianBlur(0.6))
    layer = Image.new("RGBA", size, (255, 255, 255, 0))
    layer.putalpha(noise.point(lambda v: int(v * amount / 255)))
    return layer


# --------------------------------------------------------------------------
# Individual motifs
# --------------------------------------------------------------------------


def _rings(size, palette, rng, scale, focal_y):
    back, front = _blank(size), _blank(size)
    db, df = ImageDraw.Draw(back), ImageDraw.Draw(front)
    cx = size[0] * rng.uniform(0.35, 0.65)
    cy = size[1] * (focal_y + rng.uniform(-0.04, 0.04))
    base = min(size) * 0.16
    for i in range(9):
        r = base * (1.0 + i * 0.42)
        alpha = int(78 * (1.0 - i / 10.0))
        width = max(1, int(scale * (3 if i % 3 else 5)))
        db.ellipse([cx - r, cy - r, cx + r, cy + r],
                   outline=rgba(palette.muted, alpha), width=width)
    for i in range(3):
        r = base * (0.5 + i * 0.3)
        df.ellipse([cx - r, cy - r, cx + r, cy + r],
                   outline=rgba(palette.accent, 150 - i * 40), width=max(1, int(scale * 4)))
    return MotifLayers(back, front)


def _grid(size, palette, rng, scale, focal_y):
    back, front = _blank(size), _blank(size)
    db, df = ImageDraw.Draw(back), ImageDraw.Draw(front)
    step = max(24, int(min(size) / 12))
    for x in range(0, size[0] + step, step):
        db.line([(x, 0), (x, size[1])], fill=rgba(palette.muted, 34), width=max(1, int(scale)))
    for y in range(0, size[1] + step, step):
        db.line([(0, y), (size[0], y)], fill=rgba(palette.muted, 26), width=max(1, int(scale)))
    dot = max(2, int(scale * 4))
    for _ in range(26):
        gx = rng.randrange(0, size[0] + step, step)
        gy = rng.randrange(0, size[1] + step, step)
        df.ellipse([gx - dot, gy - dot, gx + dot, gy + dot],
                   fill=rgba(palette.accent, rng.randint(90, 190)))
    return MotifLayers(back, front)


def _waveform(size, palette, rng, scale, focal_y):
    back, front = _blank(size), _blank(size)
    db, df = ImageDraw.Draw(back), ImageDraw.Draw(front)
    bars = 34
    gap = size[0] / bars
    baseline = size[1] * focal_y
    phase = rng.uniform(0, math.tau)
    for i in range(bars):
        x = i * gap
        envelope = math.sin(math.pi * (i / bars)) ** 0.7
        height = size[1] * 0.20 * envelope * (0.35 + 0.65 * abs(math.sin(phase + i * 0.55)))
        width = gap * 0.42
        db.rounded_rectangle(
            [x, baseline - height, x + width, baseline + height],
            radius=width / 2, fill=rgba(palette.muted, 52),
        )
    for i in range(0, bars, 5):
        x = i * gap
        envelope = math.sin(math.pi * (i / bars)) ** 0.7
        height = size[1] * 0.22 * envelope
        width = gap * 0.42
        df.rounded_rectangle(
            [x, baseline - height, x + width, baseline + height],
            radius=width / 2, fill=rgba(palette.accent, 165),
        )
    return MotifLayers(back, front)


def _strata(size, palette, rng, scale, focal_y):
    back, front = _blank(size), _blank(size)
    db, df = ImageDraw.Draw(back), ImageDraw.Draw(front)
    layers = 7
    for i in range(layers):
        t = i / (layers - 1)
        y = size[1] * (focal_y - 0.26 + 0.62 * t)
        amp = size[1] * 0.035 * (1.0 - t)
        points = []
        for step in range(0, size[0] + 40, 40):
            offset = math.sin(step / size[0] * math.pi * (1.4 + i * 0.4) + i) * amp
            points.append((step, y + offset))
        points += [(size[0], size[1]), (0, size[1])]
        shade = mix(palette.bg_b, palette.muted, 0.12 + 0.07 * i)
        db.polygon(points, fill=rgba(shade, 150))
    y = size[1] * max(0.08, focal_y - 0.28)
    df.line([(0, y), (size[0], y * 0.98)], fill=rgba(palette.accent, 140),
            width=max(2, int(scale * 3)))
    return MotifLayers(back, front)


def _orbit(size, palette, rng, scale, focal_y):
    back, front = _blank(size), _blank(size)
    db, df = ImageDraw.Draw(back), ImageDraw.Draw(front)
    cx, cy = size[0] * 0.5, size[1] * focal_y
    for i in range(4):
        rx = min(size) * (0.22 + i * 0.14)
        ry = rx * (0.34 + i * 0.05)
        db.ellipse([cx - rx, cy - ry, cx + rx, cy + ry],
                   outline=rgba(palette.muted, 70 - i * 12), width=max(1, int(scale * 2)))
    body = min(size) * 0.085
    df.ellipse([cx - body, cy - body, cx + body, cy + body], fill=rgba(palette.accent, 235))
    glow = body * 1.9
    df_layer = _blank(size)
    ImageDraw.Draw(df_layer).ellipse(
        [cx - glow, cy - glow, cx + glow, cy + glow], fill=rgba(palette.accent, 62)
    )
    front = Image.alpha_composite(df_layer.filter(ImageFilter.GaussianBlur(glow * 0.22)), front)
    for i, angle in enumerate((0.7, 2.4, 4.3)):
        rx = min(size) * (0.22 + i * 0.14)
        ry = rx * (0.34 + i * 0.05)
        px, py = cx + math.cos(angle) * rx, cy + math.sin(angle) * ry
        dot = max(3, int(min(size) * 0.012))
        ImageDraw.Draw(front).ellipse([px - dot, py - dot, px + dot, py + dot],
                                      fill=rgba(palette.ink, 190))
    return MotifLayers(back, front)


def _contour(size, palette, rng, scale, focal_y):
    back, front = _blank(size), _blank(size)
    db = ImageDraw.Draw(back)
    df = ImageDraw.Draw(front)
    lines = 16
    for i in range(lines):
        t = i / lines
        amp = size[1] * 0.06 * (0.4 + t)
        freq = 1.2 + t * 1.8
        y0 = size[1] * (0.12 + 0.82 * t)
        points = [
            (x, y0 + math.sin(x / size[0] * math.pi * freq + i * 0.6) * amp)
            for x in range(0, size[0] + 24, 24)
        ]
        db.line(points, fill=rgba(palette.muted, 46), width=max(1, int(scale * 2)), joint="curve")
    y0 = size[1] * focal_y
    points = [
        (x, y0 + math.sin(x / size[0] * math.pi * 1.9) * size[1] * 0.05)
        for x in range(0, size[0] + 24, 24)
    ]
    df.line(points, fill=rgba(palette.accent, 170), width=max(2, int(scale * 4)), joint="curve")
    return MotifLayers(back, front)


def _beam(size, palette, rng, scale, focal_y):
    back, front = _blank(size), _blank(size)
    db = ImageDraw.Draw(back)
    origin = (size[0] * rng.uniform(0.1, 0.35), -size[1] * 0.1)
    for i in range(7):
        spread = size[0] * (0.10 + i * 0.09)
        db.polygon(
            [origin,
             (origin[0] + spread, size[1] * 1.05),
             (origin[0] + spread * 1.7, size[1] * 1.05)],
            fill=rgba(mix(palette.bg_b, palette.accent, 0.10), 30),
        )
    glow = _blank(size)
    r = min(size) * 0.3
    ImageDraw.Draw(glow).ellipse(
        [origin[0] - r, origin[1] - r, origin[0] + r, origin[1] + r],
        fill=rgba(palette.accent, 70),
    )
    front = glow.filter(ImageFilter.GaussianBlur(r * 0.28))
    return MotifLayers(back, front)


_RENDERERS = {
    "rings": _rings,
    "grid": _grid,
    "waveform": _waveform,
    "strata": _strata,
    "orbit": _orbit,
    "contour": _contour,
    "beam": _beam,
}


def render_motif(
    name: str,
    size: tuple[int, int],
    palette: Palette,
    seed: int,
    focal_y: float = 0.62,
) -> MotifLayers:
    """Render a named motif at ``size``.

    ``focal_y`` is where the motif's visual centre of gravity sits, as a
    fraction of the frame height. The frame renderer passes the complement of
    the headline block so artwork and type never fight for the same space.
    Unknown names fall back to 'rings'.
    """
    renderer = _RENDERERS.get(name, _rings)
    rng = random.Random(seed)
    scale = max(1.0, min(size) / 540.0)
    return renderer(size, palette, rng, scale, max(0.12, min(0.88, focal_y)))
