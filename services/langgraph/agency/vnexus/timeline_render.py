"""Bounded procedural timeline compositor, using the existing timeline and media owners.

The timeline is the authority for exact frame positions and cutdown lineage;
this module only turns approved procedural shot sources into SVG frames. It
has no persistence, approval, provider, audio or publication authority. The
media fabric must still render, reopen and verify the output. The generated
WebVTT is an alternative for *visible copy in a silent animation*, not a
transcript of spoken audio. Human visual/accessibility review remains required.
"""
from __future__ import annotations

from fractions import Fraction
from html import escape
from typing import Mapping

from services.langgraph.agency.foundry.contracts import CreativeGenome
from services.langgraph.agency.timeline import Timeline, parse_rate, validate_cutdown
from services.langgraph.agency.vnexus.video import Shot, ShotKind, _ease, _headline_lines, shot_frame

MAX_FRAMES = 900
MAX_PIXELS = 400_000_000


def _validate(master: Timeline, edit: Timeline, shots: Mapping[str, Shot], width: int, height: int) -> int:
    if master.kind != "master":
        raise ValueError("a master timeline is required")
    if edit.kind == "cutdown":
        validate_cutdown(master, edit, target_seconds=edit.total_seconds())
    elif edit != master:
        raise ValueError("master edit must be the supplied master timeline")
    fps = parse_rate(master.timebase.fps)
    if fps.denominator != 1 or not 1 <= fps.numerator <= 30:
        raise ValueError("procedural renderer requires an integer frame rate from 1 to 30")
    if (width < 160 or height < 160 or width > 1920 or height > 1920 or width % 2 or height % 2
            or edit.total_frames() > MAX_FRAMES or width * height * edit.total_frames() > MAX_PIXELS):
        raise ValueError("procedural timeline exceeds frame, dimension or pixel budget")
    if set(shots) != {clip.clip_id for clip in master.clips}:
        raise ValueError("shot sources must match exactly the master clips")
    for clip in master.clips:
        shot = shots[clip.clip_id]
        if (clip.shot_ref != clip.clip_id or shot.shot_id != clip.clip_id or shot.path != "A_PROCEDURAL"
                or shot.kind not in {ShotKind.MARK_REVEAL, ShotKind.HEADLINE, ShotKind.VALUE_POINTS, ShotKind.CALL_TO_ACTION}
                or not shot.text or any(not text.strip() or "NOT PROVIDED" in text for text in shot.text)):
            raise ValueError(f"shot {clip.clip_id} is blocked, incomplete or not procedural")
        if (clip.role == "cta") != (shot.kind is ShotKind.CALL_TO_ACTION):
            raise ValueError(f"shot {clip.clip_id} does not match its CTA role")
    return fps.numerator


def compose_frames(master: Timeline, edit: Timeline, shots: Mapping[str, Shot], genome: CreativeGenome,
                   *, width: int, height: int) -> list[str]:
    """Render a master or trims-only re-edit from the same procedural shot sources.

    Dissolves blend the two actual SVG frames over the overlap, not merely a
    label. A three-way overlap is refused because this compositor implements
    two layers only. The provider independently validates every generated SVG.
    """
    _validate(master, edit, shots, width, height)
    starts = edit.starts()
    sources = {clip.clip_id: clip for clip in master.clips}
    frames: list[str] = []
    for position in range(edit.total_frames()):
        active = [(i, clip, position - start) for i, (clip, start) in enumerate(zip(edit.clips, starts))
                  if start <= position < start + clip.duration_frames]
        if not active or len(active) > 2:
            raise ValueError("timeline has a gap or unsupported three-way overlap")
        layers = []
        for index, clip, local in active:
            source_id = clip.shot_ref if edit.kind == "cutdown" else clip.clip_id
            source = sources[source_id]
            # A cutdown keeps the beginning of its master shot and may trim its
            # tail; it never stretches or invents a new source frame.
            t = local / max(1, source.duration_frames - 1)
            svg = shot_frame(shots[source_id], genome, t, width=width, height=height)
            if index == active[0][0]:
                layers.append(svg)
            else:
                overlap = clip.overlap_frames
                if clip.transition_in != "dissolve" or overlap <= 0:
                    raise ValueError("overlapping frames need a dissolve")
                opacity = local / (overlap - 1) if overlap > 1 else 0.5
                layers.append(f'<g opacity="{max(0.0, min(1.0, opacity)):.6f}">{svg}</g>')
        if len(layers) == 1:
            frames.append(layers[0])
        else:
            frames.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
                          f'viewBox="0 0 {width} {height}">{"".join(layers)}</svg>')
    return frames


def captions(master: Timeline, edit: Timeline, shots: Mapping[str, Shot], *, width: int, height: int) -> str:
    """Text alternatives begin once visible copy reaches half opacity.

    Cues end at the middle of a dissolve so they never overlap. The estimate
    uses the same procedural easing and blend as the compositor; actual font
    geometry, visual legibility and accessibility still need human review.
    """
    fps = _validate(master, edit, shots, width, height)
    starts = edit.starts()
    boundaries = [0] + [starts[i] + edit.clips[i].overlap_frames // 2 for i in range(1, len(edit.clips))] + [edit.total_frames()]
    if any(a >= b for a, b in zip(boundaries, boundaries[1:])):
        raise ValueError("timeline cannot produce nonempty caption cues")
    sources = {clip.clip_id: clip for clip in master.clips}

    def first_visible(index: int, source_id: str) -> int:
        clip, shot = edit.clips[index], shots[source_id]
        source = sources[source_id]
        if shot.kind in {ShotKind.HEADLINE, ShotKind.CALL_TO_ACTION}:
            wrapped, _ = _headline_lines(shot.text[0], width=width, height=height, kind=shot.kind)
        else:
            wrapped = []
        for position in range(boundaries[index], boundaries[index + 1]):
            local = position - starts[index]
            t = local / max(1, source.duration_frames - 1)
            if shot.kind is ShotKind.MARK_REVEAL:
                opacity = _ease((t - 0.4) / 0.4)
            elif shot.kind in {ShotKind.HEADLINE, ShotKind.CALL_TO_ACTION}:
                opacity = min(_ease((t - i * 0.1) / 0.35) for i in range(len(wrapped)))
            else:
                n = len(shot.text)
                opacity = min(_ease((t - i / (n + 0.6)) / 0.25) for i in range(n))
            blend = 1.0
            if clip.transition_in == "dissolve" and local < clip.overlap_frames:
                blend = local / (clip.overlap_frames - 1) if clip.overlap_frames > 1 else 0.5
            if opacity * blend >= 0.5:
                return position
        raise ValueError(f"text for {clip.clip_id} is not sufficiently visible before the next cue")

    def timestamp(frame: int) -> str:
        milliseconds = int(Fraction(frame * 1000, fps) + Fraction(1, 2))
        hours, rem = divmod(milliseconds, 3_600_000)
        minutes, rem = divmod(rem, 60_000)
        seconds, millis = divmod(rem, 1000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"

    lines = ["WEBVTT", "", "NOTE Silent animation: cues describe on-screen copy; no spoken audio.",
             "NOTE Timing estimates visible copy at half opacity; visual accessibility review is required.", ""]
    for index, clip in enumerate(edit.clips):
        source = clip.shot_ref if edit.kind == "cutdown" else clip.clip_id
        start = first_visible(index, source)
        # Normalize newlines and escape WebVTT markup, so approved copy cannot
        # create extra cues or be interpreted as tag markup.
        text = escape(" / ".join(" ".join(item.split()) for item in shots[source].text), quote=False)
        lines += [str(index + 1), f"{timestamp(start)} --> {timestamp(boundaries[index + 1])}", text, ""]
    return "\n".join(lines)


__all__ = ["captions", "compose_frames"]
