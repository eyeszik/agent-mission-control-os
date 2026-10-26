"""EVALUATE: independent checks over the produced bytes (PVSE role).

The evaluator reads the SVG text and the PNG bytes, not the compiler's in-memory
objects: exact text is read back from the SVG, colours from SVG attributes, pixels
from the decoded PNG. The ``SceneIR`` is consulted only for its declared
constraints (which objects a rule targets), never for the values being checked.
A check that could not run is ``NOT_MEASURED`` or ``BLOCKED``, never ``PASS``.
"""

from __future__ import annotations

import hashlib
import re
from typing import Optional
from xml.etree import ElementTree as ET

from services.langgraph.agency.execution_fabric.verifiers import palette_conformance
from services.langgraph.agency.ui_ux.tokens import wcag_contrast_ratio

from . import png, svg
from .contracts import BrandIR, Check, EvaluationReport, IntentIR, Result, SceneIR
from .scene import GLYPH_ADVANCE_EM

NONBLANK_MIN_COLOURS = 3
INK_DISTANCE = 150      # Manhattan RGB distance from the ground that counts as content (grain/lighting stay well below)
MARGIN_MIN_PIXELS = 4   # a single antialiasing speck is not content


def _attr_map(svg_text: str) -> dict[str, dict[str, str]]:
    return {el.attrib["id"]: dict(el.attrib) for el in ET.fromstring(svg_text).iter() if "id" in el.attrib}


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % rgb


def _dist(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    return sum(abs(x - y) for x, y in zip(a[:3], b[:3]))


def pixel_stats(r: png.Raster) -> dict:
    small = png.downsample(r, 128)
    colours = {small.rgba[i:i + 3] for i in range(0, len(small.rgba), 4)}
    lum = [0.2126 * small.rgba[i] + 0.7152 * small.rgba[i + 1] + 0.0722 * small.rgba[i + 2] for i in range(0, len(small.rgba), 4)]
    mean = sum(lum) / len(lum)
    std = (sum((v - mean) ** 2 for v in lum) / len(lum)) ** 0.5
    return {"distinct_colours_128px": len(colours), "luminance_mean": round(mean, 2), "luminance_std": round(std, 2)}


def ink_fraction(r: png.Raster, *, box: tuple[float, float, float, float], ink: str, tolerance: int = 90) -> float:
    """Share of pixels inside ``box`` (x, y, w, h) close to ``ink``: did the text actually render there?"""
    x0, y0 = max(0, int(box[0])), max(0, int(box[1]))
    x1, y1 = min(r.width, int(box[0] + box[2])), min(r.height, int(box[1] + box[3]))
    target = tuple(int(ink[i:i + 2], 16) for i in (1, 3, 5))
    n = hit = 0
    for y in range(y0, y1, 2):
        for x in range(x0, x1, 2):
            n += 1
            if _dist(r.pixel(x, y), target) <= tolerance:
                hit += 1
    return hit / n if n else 0.0


def margin_band_ink(r: png.Raster, *, margin: float, ground: str) -> list[str]:
    """Edges whose outer half-margin holds content (pixels far from the ground colour): right, bottom, left, top.

    Measured on the rendered pixels, so it sees an overflow the glyph-advance estimate cannot.
    """
    half = max(1, int(margin // 2))
    g = tuple(int(ground[i:i + 2], 16) for i in (1, 3, 5))
    W, H, buf = r.width, r.height, r.rgba

    def strong(x: int, y: int) -> bool:
        i = (y * W + x) * 4
        return abs(buf[i] - g[0]) + abs(buf[i + 1] - g[1]) + abs(buf[i + 2] - g[2]) > INK_DISTANCE

    def count(xs: range, ys: range) -> int:
        return sum(1 for y in ys for x in xs if strong(x, y))

    bands = {"right": (range(max(0, W - half), W), range(H)), "bottom": (range(W), range(max(0, H - half), H)),
             "left": (range(min(half, W)), range(H)), "top": (range(W), range(min(half, H)))}
    return [edge for edge, (xs, ys) in bands.items() if count(xs, ys) >= MARGIN_MIN_PIXELS]


def evaluate(scene: SceneIR, svg_text: str, *, intent: IntentIR, brand: BrandIR, png_bytes: Optional[bytes],
             renderer: str, renderer_version: Optional[str], parent_svg: Optional[str] = None,
             metrics: Optional[dict] = None) -> EvaluationReport:
    checks: list[Check] = []

    def add(name: str, level: str, result: Result, detail: str) -> None:
        checks.append(Check(check=name, level=level, result=result, detail=detail[:600]))

    def ok(b: bool) -> Result:
        return Result.PASS if b else Result.FAIL

    W, H = scene.document.width, scene.document.height
    checks += list(svg.validate(svg_text, profile=scene.document.output_profile, max_bytes=scene.compilation.max_svg_bytes,
                                expect_size=(W, H)))
    if any(c.result != Result.PASS for c in checks if c.check in {"svg_safety", "allowlist_elements"}):
        return EvaluationReport(scene_hash=scene.scene_hash, svg_sha256=hashlib.sha256(svg_text.encode()).hexdigest(),
                                renderer=renderer, renderer_version=renderer_version, checks=tuple(checks), metrics=metrics or {})
    attrs = _attr_map(svg_text)
    texts = svg.text_content(svg_text)
    # Q5 exact text, read back from the SVG.
    exact = dict(zip(intent.exact_text_ids(), intent.exact_text))
    for con in scene.constraints:
        if con.kind == "exact_text":
            want = exact.get(con.requirement_refs[0]) if con.requirement_refs else None
            got = texts.get(con.target[0])
            add(f"exact_text.{con.target[0]}", "Q5", ok(want is not None and got == want),
                f"expected {want!r}, SVG has {got!r}")
    # Q5 palette: every literal colour within dE76 of the brand palette.
    pv = palette_conformance(svg_text, brand.palette.values(), tolerance=2.3)
    add("palette", "Q5", ok(pv.passed), pv.detail)
    # Accent budget: distinct brand accent colours that appear.
    accents = {brand.palette[k] for r, k in brand.roles.items() if r.startswith("accent")}
    used = {c.lower() for c in re.findall(r"#[0-9a-fA-F]{6}", svg_text)} & accents
    add("accent_budget", "Q5", ok(len(used) <= brand.max_signal_accents), f"{len(used)} accent colour(s) used: {sorted(used)}")
    ground = attrs.get("background", {}).get("fill")
    for con in scene.constraints:
        if con.kind != "contrast":
            continue
        fg_attrs = attrs.get(con.target[0], {})
        fg = fg_attrs.get("fill") if fg_attrs.get("fill", "none") not in {"none"} else fg_attrs.get("stroke")
        if not (fg and ground and fg.startswith("#") and ground.startswith("#")):
            add(con.constraint_id, "Q5", Result.NOT_MEASURED, "foreground or ground is not a solid colour")
            continue
        ratio = wcag_contrast_ratio(fg, ground)
        add(con.constraint_id, "Q5", ok(ratio >= (con.tolerance or 4.5)), f"{fg} on {ground} = {ratio:.2f}:1 "
            f"(floor {con.tolerance})")
    # Text fits the canvas (estimate from SVG attributes, labelled as an estimate).
    for tid, text in texts.items():
        a = attrs.get(tid, {})
        try:
            x, fs = float(a.get("x", 0)), float(a.get("font-size", 16))
        except ValueError:
            add(f"text_fit.{tid}", "Q3", Result.FAIL, "unparseable text position")
            continue
        right = x + len(text) * fs * GLYPH_ADVANCE_EM
        add(f"text_fit.{tid}", "Q3", ok(right <= W), f"estimated right edge {right:.0f}px of {W}px (glyph-advance estimate)")
    # Protected geometry vs the parent version.
    protected = [t for c in scene.constraints if c.kind == "protected_geometry" for t in c.target]
    if parent_svg is not None:
        changed = [t for t in protected if svg.element_signature(parent_svg, t) != svg.element_signature(svg_text, t)]
        add("protected_geometry", "Q5", ok(not changed), f"changed: {changed}" if changed else f"{len(protected)} protected unchanged")
    # Q7 independent rendering.
    if png_bytes is None:
        add("render", "Q7", Result.BLOCKED, "no rendered preview (renderer unavailable or failed)")
    else:
        try:
            raster = png.decode(png_bytes)
        except png.PngError as exc:
            add("render", "Q7", Result.FAIL, f"preview does not decode: {exc}")
        else:
            add("render_dimensions", "Q7", ok((raster.width, raster.height) == (W, H)), f"{raster.width}x{raster.height}")
            stats = pixel_stats(raster)
            add("nonblank", "Q7", ok(stats["distinct_colours_128px"] >= NONBLANK_MIN_COLOURS and stats["luminance_std"] > 2),
                f"{stats}")
            if ground and ground.startswith("#") and len(ground) == 7:
                bleed = margin_band_ink(raster, margin=scene.composition.margin, ground=ground)
                add("margin_bands", "Q3", ok(not bleed),
                    f"content in the outer half-margin on: {', '.join(bleed)}" if bleed else "outer half-margin is clear")
            head = attrs.get("headline")
            if head and head.get("fill", "").startswith("#"):
                fs = float(head.get("font-size", 16))
                box = (float(head["x"]), float(head["y"]) - fs * 0.8, len(texts.get("headline", "")) * fs * GLYPH_ADVANCE_EM,
                       fs * 0.8)
                frac = ink_fraction(raster, box=box, ink=head["fill"])
                add("headline_rendered", "Q7", ok(frac >= 0.05), f"{frac:.1%} of the headline box is headline ink")
            metrics = {**(metrics or {}), **stats}
    return EvaluationReport(scene_hash=scene.scene_hash, svg_sha256=hashlib.sha256(svg_text.encode()).hexdigest(),
                            png_sha256=hashlib.sha256(png_bytes).hexdigest() if png_bytes else None, renderer=renderer,
                            renderer_version=renderer_version, checks=tuple(checks), metrics=metrics or {})


__all__ = ["evaluate", "ink_fraction", "margin_band_ink", "pixel_stats"]
