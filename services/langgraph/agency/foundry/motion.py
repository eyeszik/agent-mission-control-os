"""Cinematic motion: CreativeGenome -> MotionIR -> real frames -> encoded MP4.

Frames are SVG documents computed from keyframes (pure, deterministic), rendered
by local Chromium and encoded by the existing ``agency.visual.renderers.encode_video``
(FFmpeg, libx264). FreeVideoForge is the repository's video pipeline for
narrated explainers; it has no keyframed vector-animation stage, so brand motion
uses this path instead (recorded as a rejected route, not silently skipped).

Every template has a reduced-motion alternative: the final frame as a still.
There is no text-to-video model here and none is claimed.
"""

from __future__ import annotations

import math
from typing import Callable
from xml.sax.saxutils import escape

from . import compose
from .contracts import CreativeGenome, Keyframe, MotionIR, MotionLayer

EASING: dict[str, Callable[[float], float]] = {
    "linear": lambda t: t,
    "ease_in": lambda t: t * t,
    "ease_out": lambda t: 1 - (1 - t) ** 2,
    "ease_in_out": lambda t: 2 * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 2 / 2,
    "spring": lambda t: 1 - math.exp(-6 * t) * math.cos(10 * t) if t < 1 else 1.0,
}


def logo_reveal(genome: CreativeGenome, *, width: int = 960, height: int = 540, fps: int = 24,
                duration_s: float | None = None) -> MotionIR:
    easing = genome.motion_rules.get("easing", "ease_out")
    d = float(duration_s or genome.motion_rules.get("base_duration_s", 2.5))
    K = Keyframe
    return MotionIR(template="logo_reveal", width=width, height=height, fps=fps, duration_s=d, genome_hash=genome.content_hash,
                    layers=(
                        MotionLayer(layer_id="mark", target="mark", keyframes=(
                            K(t=0, props={"opacity": 0, "scale": 0.6}), K(t=0.45, props={"opacity": 1, "scale": 1}, easing=easing),
                            K(t=1, props={"opacity": 1, "scale": 1}))),
                        MotionLayer(layer_id="rule", target="rule", keyframes=(
                            K(t=0, props={"reveal": 0}), K(t=0.3, props={"reveal": 0}),
                            K(t=0.6, props={"reveal": 1}, easing="ease_in_out"), K(t=1, props={"reveal": 1}))),
                        MotionLayer(layer_id="wordmark", target="wordmark", keyframes=(
                            K(t=0, props={"opacity": 0, "ty": 24}), K(t=0.4, props={"opacity": 0, "ty": 24}),
                            K(t=0.75, props={"opacity": 1, "ty": 0}, easing="ease_out"), K(t=1, props={"opacity": 1, "ty": 0}))),
                    ))


def sample(layer: MotionLayer, t: float) -> dict[str, float]:
    ks = layer.keyframes
    if t <= ks[0].t:
        return dict(ks[0].props)
    for a, b in zip(ks, ks[1:]):
        if a.t <= t <= b.t:
            span = (b.t - a.t) or 1.0
            e = EASING[b.easing]((t - a.t) / span)
            return {k: a.props.get(k, v) + (v - a.props.get(k, v)) * e for k, v in b.props.items()}
    return dict(ks[-1].props)


def frame_svg(ir: MotionIR, genome: CreativeGenome, index: int) -> str:
    t = index / max(1, ir.frame_count - 1)
    pal = genome.palette.roles()
    props = {layer.target: sample(layer, t) for layer in ir.layers}
    mark_ir = compose.mark(genome, size=200)
    mark_body = "".join(compose._shape(p, pal) for p in mark_ir.primitives)  # noqa: SLF001 - same renderer, no copy
    m = props["mark"]
    cx, cy = ir.width * 0.3, ir.height * 0.5
    s = max(0.0, m.get("scale", 1))
    mark_g = (f'<g opacity="{max(0, min(1, m.get("opacity", 1))):.3f}" transform="translate({cx - 100 * s:.2f} {cy - 100 * s:.2f}) '
              f'scale({s:.4f})">{mark_body}</g>')
    r = props["rule"]
    rule = (f'<rect x="{ir.width * 0.44:.2f}" y="{cy + 34:.2f}" width="{ir.width * 0.42 * max(0, min(1, r.get("reveal", 1))):.2f}" '
            f'height="6" fill="{pal["accent"]}"/>')
    w = props["wordmark"]
    family = ", ".join(genome.typography_rules["stacks"]["display"])
    word = (f'<text x="{ir.width * 0.44:.2f}" y="{cy + 10 + w.get("ty", 0):.2f}" opacity="{max(0, min(1, w.get("opacity", 1))):.3f}" '
            f'font-family="{escape(family, {chr(34): "&quot;"})}" font-size="{ir.height * 0.12:.2f}" '
            f'font-weight="{genome.typography_rules.get("display_weight", 700)}" fill="{pal["ink"]}">{escape(genome.brand_name)}</text>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{ir.width}" height="{ir.height}" viewBox="0 0 {ir.width} {ir.height}">'
            f'<rect width="{ir.width}" height="{ir.height}" fill="{pal["paper"]}"/>{mark_g}{rule}{word}</svg>')


def frames(ir: MotionIR, genome: CreativeGenome) -> list[str]:
    return [frame_svg(ir, genome, i) for i in range(ir.frame_count)]


__all__ = ["EASING", "frame_svg", "frames", "logo_reveal", "sample"]
