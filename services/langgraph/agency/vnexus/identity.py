"""VNEXUS graphic design and identity production: deliverable specifications and deterministic validators.

Deliverables are composed from the bridged foundry genome (vector first) and
rendered through the media fabric's local providers, so a format is offered
only where a working encoder exists on this host (SVG always; PNG, WebP and
PDF through local Chromium and Pillow).

Validators measure things a machine can measure on the produced bytes or the
composition IR: reproduction at small sizes, optical centring, stroke
consistency, palette conformance, text contrast, safe areas, crop behaviour,
transparency and dimensions. Whether a design is good stays a human call.
"""

from __future__ import annotations

import io
import re
import statistics
from typing import Any, Optional
from xml.sax.saxutils import escape

from services.langgraph.agency.execution_fabric.verifiers import palette_conformance
from services.langgraph.agency.foundry import compose
from services.langgraph.agency.foundry.contracts import CompositionIR, CreativeGenome
from services.langgraph.agency.ui_ux.tokens import wcag_contrast_ratio

from .art_director import PLATFORM_PRESETS
from .genome import _Strict
from .media_fabric import Capability

IDENTITY_DELIVERABLES = ("logo_mark", "logo_lockup", "monogram", "icon_family", "color_system", "typography_specimen", "poster",
                         "social_graphics", "presentation", "editorial_layout", "brand_guidelines")
PROVIDER_FOR = {Capability.VECTOR_SVG: "local.svg", Capability.RASTER_PNG: "local.chromium_raster",
                Capability.RASTER_WEBP: "local.pillow_webp", Capability.DOCUMENT_PDF: "local.chromium_pdf",
                Capability.MOTION_MP4: "local.svg_motion"}


class OutputSpec(_Strict):
    deliverable: str
    name: str
    capability: Capability
    width: int
    height: int
    source: dict[str, Any]          # {"svg": ...} or {"html": ...}
    safe_margin: float = 0.06
    transparent: bool = False


def transparent_svg(svg: str, ir: CompositionIR, genome: CreativeGenome) -> str:
    """Drop the full-bleed background rectangle so the mark sits on transparency."""
    bg = f'<rect width="{ir.width}" height="{ir.height}" fill="{genome.palette.roles()[ir.background]}"/>'
    if bg not in svg:
        raise ValueError("background rectangle not found")
    return svg.replace(bg, "", 1)


def monogram_svg(genome: CreativeGenome, *, size: int = 512) -> str:
    pal = genome.palette.roles()
    letters = "".join(w[0] for w in re.findall(r"[A-Za-z0-9]+", genome.brand_name)[:2]).upper() or "?"
    family = ", ".join(genome.typography_rules["stacks"]["display"])
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}" role="img" '
            f'aria-label="{escape(genome.brand_name)} monogram"><title>{escape(genome.brand_name)} monogram</title>'
            f'<circle cx="{size / 2}" cy="{size / 2}" r="{size * 0.46:.2f}" fill="{pal["ink"]}"/>'
            f'<text x="{size / 2}" y="{size * 0.6:.2f}" text-anchor="middle" font-family="{escape(family, {chr(34): "&quot;"})}" '
            f'font-size="{size * 0.34:.2f}" font-weight="700" fill="{pal["paper"]}">{escape(letters)}</text></svg>\n')


def color_system_svg(genome: CreativeGenome, *, width: int = 1200, height: int = 720) -> str:
    pal = genome.palette.roles()
    cells = []
    n = len(pal)
    w = width / n
    for i, (role, value) in enumerate(pal.items()):
        on_ink = wcag_contrast_ratio(value, pal["ink"])
        on_paper = wcag_contrast_ratio(value, pal["paper"])
        label_fill = pal["ink"] if on_ink < on_paper and wcag_contrast_ratio(pal["ink"], value) >= 4.5 else pal["paper"]
        if wcag_contrast_ratio(label_fill, value) < 4.5:
            label_fill = pal["ink"] if wcag_contrast_ratio(pal["ink"], value) >= wcag_contrast_ratio(pal["paper"], value) else pal["paper"]
        x = i * w
        cells.append(f'<rect x="{x:.2f}" y="0" width="{w:.2f}" height="{height * 0.7:.2f}" fill="{value}"/>'
                     f'<text x="{x + 24:.2f}" y="{height * 0.7 - 60:.2f}" font-family="sans-serif" font-size="28" font-weight="700" '
                     f'fill="{label_fill}">{escape(role)}</text>'
                     f'<text x="{x + 24:.2f}" y="{height * 0.7 - 24:.2f}" font-family="monospace" font-size="20" fill="{label_fill}">'
                     f'{value}</text>'
                     f'<text x="{x + 24:.2f}" y="{height * 0.78:.2f}" font-family="monospace" font-size="18" fill="{pal["ink"]}">'
                     f'on paper {on_paper}:1</text>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" '
            f'aria-label="{escape(genome.brand_name)} colour system"><title>{escape(genome.brand_name)} colour system</title>'
            f'<rect width="{width}" height="{height}" fill="{pal["paper"]}"/>{"".join(cells)}</svg>\n')


def typography_specimen_svg(genome: CreativeGenome, *, width: int = 1200, height: int = 800) -> str:
    pal = genome.palette.roles()
    display = ", ".join(genome.typography_rules["stacks"]["display"])
    text = ", ".join(genome.typography_rules["stacks"]["text"])
    ratio = float(genome.typography_rules.get("scale_ratio", 1.333))
    steps, y, rows = [16 * ratio ** k for k in range(5, -1, -1)], 120.0, []
    for size in steps:
        rows.append(f'<text x="64" y="{y:.2f}" font-family="{escape(display, {chr(34): "&quot;"})}" font-size="{size:.2f}" '
                    f'font-weight="{genome.typography_rules.get("display_weight", 700)}" fill="{pal["ink"]}">'
                    f'{escape(genome.brand_name)} {size:.0f}px</text>')
        y += size * 1.3
    rows.append(f'<text x="64" y="{height - 64}" font-family="{escape(text, {chr(34): "&quot;"})}" font-size="18" fill="{pal["ink"]}">'
                f'Body: {escape(genome.typography_rules["stacks"]["text"][0])}, minimum {genome.typography_rules.get("min_body_px", 16)}px; '
                f'scale ratio {ratio}</text>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" '
            f'aria-label="{escape(genome.brand_name)} typography specimen"><title>Typography specimen</title>'
            f'<rect width="{width}" height="{height}" fill="{pal["paper"]}"/>{"".join(rows)}</svg>\n')


def specs(genome: CreativeGenome, deliverables: tuple[str, ...], *, copy: dict[str, str], constraints: list[dict[str, Any]],
          genome_ref: str, guidelines: Optional[tuple[str, int, int]] = None) -> tuple[list[OutputSpec], dict[str, CompositionIR]]:
    """Output specifications. ``guidelines`` is the brand book HTML and page size rendered from the approved
    projection by ``vnexus.brandbook`` (the guidelines are never a fixed template with invented rules)."""
    unknown = sorted(set(deliverables) - set(IDENTITY_DELIVERABLES))
    if unknown:
        raise ValueError(f"unknown identity deliverables: {unknown}")
    out: list[OutputSpec] = []
    irs: dict[str, CompositionIR] = {}
    S = OutputSpec
    want = set(deliverables)
    if "logo_mark" in want:
        ir = compose.mark(genome, size=512)
        irs["logo_mark"] = ir
        svg = compose.to_svg(ir, genome)
        out += [S(deliverable="logo_mark", name="logo-mark.svg", capability=Capability.VECTOR_SVG, width=512, height=512, source={"svg": svg}),
                S(deliverable="logo_mark", name="logo-mark-transparent.png", capability=Capability.RASTER_PNG, width=512, height=512,
                  source={"svg": transparent_svg(svg, ir, genome)}, transparent=True)]
    if "logo_lockup" in want:
        ir = compose.lockup(genome, width=1200, height=360)
        irs["logo_lockup"] = ir
        svg = compose.to_svg(ir, genome)
        out += [S(deliverable="logo_lockup", name="logo-lockup.svg", capability=Capability.VECTOR_SVG, width=1200, height=360, source={"svg": svg}),
                S(deliverable="logo_lockup", name="logo-lockup.pdf", capability=Capability.DOCUMENT_PDF, width=1200, height=360, source={"svg": svg})]
    if "monogram" in want:
        out.append(S(deliverable="monogram", name="monogram.svg", capability=Capability.VECTOR_SVG, width=512, height=512,
                     source={"svg": monogram_svg(genome)}))
    if "icon_family" in want:
        for name in sorted(compose.ICON_PATHS):
            out.append(S(deliverable="icon_family", name=f"icon-{name}.svg", capability=Capability.VECTOR_SVG, width=48, height=48,
                         source={"svg": compose.icon_svg(genome, name)}))
    if "color_system" in want:
        svg = color_system_svg(genome)
        out += [S(deliverable="color_system", name="color-system.svg", capability=Capability.VECTOR_SVG, width=1200, height=720, source={"svg": svg}),
                S(deliverable="color_system", name="color-system.pdf", capability=Capability.DOCUMENT_PDF, width=1200, height=720, source={"svg": svg})]
    if "typography_specimen" in want:
        out.append(S(deliverable="typography_specimen", name="typography-specimen.svg", capability=Capability.VECTOR_SVG, width=1200,
                     height=800, source={"svg": typography_specimen_svg(genome)}))
    headline, subhead, cta, meta = (copy.get(k, "") for k in ("headline", "subhead", "cta", "meta"))
    if not headline:
        headline = genome.brand_name
    if "poster" in want:
        ir = compose.poster(genome, headline=headline, subhead=subhead, cta=cta, meta=meta, width=1200, height=1697)
        irs["poster"] = ir
        svg = compose.to_svg(ir, genome)
        out += [S(deliverable="poster", name="poster.svg", capability=Capability.VECTOR_SVG, width=1200, height=1697, source={"svg": svg}),
                S(deliverable="poster", name="poster.png", capability=Capability.RASTER_PNG, width=1200, height=1697, source={"svg": svg}),
                S(deliverable="poster", name="poster.pdf", capability=Capability.DOCUMENT_PDF, width=1200, height=1697, source={"svg": svg})]
    if "social_graphics" in want:
        for preset in ("social.square", "social.portrait_4x5", "web.open_graph"):
            spec = PLATFORM_PRESETS[preset]
            ir = compose.poster(genome, headline=headline, subhead=subhead, cta=cta, width=spec.width, height=spec.height)
            irs[f"social_graphics:{preset}"] = ir
            svg = compose.to_svg(ir, genome)
            stem = preset.replace(".", "-")
            out += [S(deliverable="social_graphics", name=f"{stem}.png", capability=Capability.RASTER_PNG, width=spec.width,
                      height=spec.height, source={"svg": svg}, safe_margin=spec.safe_margin),
                    S(deliverable="social_graphics", name=f"{stem}.webp", capability=Capability.RASTER_WEBP, width=spec.width,
                      height=spec.height, source={"svg": svg}, safe_margin=spec.safe_margin)]
    if "presentation" in want:
        ir = compose.poster(genome, headline=headline, subhead=subhead, meta=meta, width=1920, height=1080)
        irs["presentation"] = ir
        svg = compose.to_svg(ir, genome)
        out += [S(deliverable="presentation", name="title-slide.svg", capability=Capability.VECTOR_SVG, width=1920, height=1080, source={"svg": svg}),
                S(deliverable="presentation", name="title-slide.pdf", capability=Capability.DOCUMENT_PDF, width=1920, height=1080, source={"svg": svg})]
    if "editorial_layout" in want:
        ir = compose.poster(genome, headline=headline, subhead=subhead, meta=meta, width=794, height=1123)
        irs["editorial_layout"] = ir
        out.append(S(deliverable="editorial_layout", name="editorial-a4.pdf", capability=Capability.DOCUMENT_PDF, width=794, height=1123,
                     source={"svg": compose.to_svg(ir, genome)}))
    if "brand_guidelines" in want:
        if guidelines is None:
            raise ValueError("brand_guidelines is rendered from the approved projection; pass the brand book HTML")
        html, width, height = guidelines
        out.append(S(deliverable="brand_guidelines", name="brand-guidelines.pdf", capability=Capability.DOCUMENT_PDF, width=width,
                     height=height, source={"html": html}))
    return out, irs


# --------------------------------------------------------------------------- validators


def _check(name: str, passed: Optional[bool], detail: str, *, severity: str = "ERROR") -> dict[str, Any]:
    return {"check": name, "passed": passed, "detail": detail, "severity": severity,
            "status": "NOT_RUN" if passed is None else ("PASSED" if passed else "FAILED")}


def text_contrast(ir: CompositionIR, genome: CreativeGenome) -> dict[str, Any]:
    pal = genome.palette.roles()
    bad = []
    for t in ir.text:
        ratio = wcag_contrast_ratio(pal[t.fill], pal[ir.background])
        floor = 3.0 if t.size >= 24 else 4.5  # WCAG large text: 24px regular / 18.66px bold
        if ratio < floor:
            bad.append(f"{t.role} {ratio}:1 < {floor}:1")
    return _check("text_contrast", not bad, "; ".join(bad) or f"{len(ir.text)} text block(s) meet WCAG 2.2 AA")


def _text_box(t: Any) -> tuple[float, float, float, float]:
    width = len(t.text) * t.size * 0.55
    x0 = t.x - (width if t.anchor == "end" else width / 2 if t.anchor == "middle" else 0)
    return x0, t.y - t.size * 0.8, x0 + width, t.y + t.size * 0.2


def safe_area(ir: CompositionIR, margin: float) -> dict[str, Any]:
    m = margin * min(ir.width, ir.height)
    outside = []
    for t in ir.text:
        x0, y0, x1, y1 = _text_box(t)
        if x0 < m - 1 or y0 < m - 1 or x1 > ir.width - m + 1 or y1 > ir.height - m + 1:
            outside.append(t.role)
    return _check("safe_area", not outside, f"text outside the {margin:.0%} safe area: {sorted(set(outside))}" if outside else
                  f"all text inside a {margin:.0%} safe area (estimated text widths)")


def crop_behavior(ir: CompositionIR, aspect: float) -> dict[str, Any]:
    """Which text survives a centre crop to ``aspect`` (w/h). Informational: crops are a layout decision."""
    if ir.width / ir.height > aspect:
        cw, ch = ir.height * aspect, ir.height
    else:
        cw, ch = ir.width, ir.width / aspect
    left, top = (ir.width - cw) / 2, (ir.height - ch) / 2
    clipped = sorted({t.role for t in ir.text if (b := _text_box(t)) and (b[0] < left or b[2] > left + cw or b[1] < top or b[3] > top + ch)})
    return _check(f"crop_{aspect:.2f}", not clipped, f"clipped by a centre crop: {clipped}" if clipped else "all text survives",
                  severity="WARNING")


def stroke_consistency(svgs: list[str]) -> dict[str, Any]:
    widths = [float(w) for svg in svgs for w in re.findall(r'stroke-width="([0-9.]+)"', svg)]
    if not widths:
        return _check("stroke_consistency", None, "no strokes found")
    spread = (statistics.pstdev(widths) / statistics.mean(widths)) if len(widths) > 1 else 0.0
    return _check("stroke_consistency", spread <= 0.05, f"{len(widths)} strokes, coefficient of variation {spread:.3f}")


def palette_check(svg: str, genome: CreativeGenome) -> dict[str, Any]:
    v = palette_conformance(svg, genome.palette.roles().values())
    return _check("palette_conformance", v.passed, v.detail)


def raster_metrics(png: bytes) -> dict[str, Any]:
    from PIL import Image

    with Image.open(io.BytesIO(png)) as im:
        rgba = im.convert("RGBA")
        w, h = rgba.size
        px = rgba.load()
        corners = [px[0, 0][3], px[w - 1, 0][3], px[0, h - 1][3], px[w - 1, h - 1][3]]
        total = sx = sy = 0
        for y in range(0, h, max(1, h // 128)):
            for x in range(0, w, max(1, w // 128)):
                a = px[x, y][3]
                if a > 16:
                    total += a
                    sx += x * a
                    sy += y * a
        mode = im.mode
    centroid = (sx / total / w, sy / total / h) if total else (None, None)
    return {"mode": mode, "size": (w, h), "corner_alpha": corners, "centroid": centroid}


def transparency(png: bytes) -> dict[str, Any]:
    m = raster_metrics(png)
    ok = m["mode"] in ("RGBA", "LA") and max(m["corner_alpha"]) == 0
    return _check("transparency", ok, f"mode {m['mode']}, corner alpha {m['corner_alpha']}")


def optical_centre(png: bytes, *, tolerance: float = 0.06) -> dict[str, Any]:
    cx, cy = raster_metrics(png)["centroid"]
    if cx is None:
        return _check("optical_centre", False, "no visible pixels")
    off = max(abs(cx - 0.5), abs(cy - 0.5))
    return _check("optical_centre", off <= tolerance, f"ink centroid offset {off:.3f} of the canvas (tolerance {tolerance})",
                  severity="WARNING")


def min_reproduction(svg: str, *, sizes: tuple[int, ...] = (16, 24, 32), work: Any) -> dict[str, Any]:
    """Render the mark small in Chromium and require visible, non-solid coverage at every size."""
    from PIL import Image

    from services.langgraph.agency.visual.browser import capture_svg_sizes, probe_browser

    if not probe_browser().get("available"):
        return _check("min_reproduction", None, "NOT_RUN: local Chromium unavailable")
    run = capture_svg_sizes(svg, sizes=sizes, out_dir=work)
    results = []
    for entry in run.get("result", {}).get("sizes", []):
        with Image.open(work / entry["capture"]) as im:
            g = im.convert("L")
            hist = g.histogram()
            n = sum(hist)
            background = max(range(256), key=lambda i: hist[i])
            fg = sum(c for i, c in enumerate(hist) if abs(i - background) > 24) / n
        results.append((entry["size"], round(fg, 3)))
    ok = len(results) == len(sizes) and all(0.03 <= f <= 0.97 for _, f in results)
    return _check("min_reproduction", ok, "foreground coverage by size: " + ", ".join(f"{s}px {f:.0%}" for s, f in results))


__all__ = ["IDENTITY_DELIVERABLES", "OutputSpec", "PROVIDER_FOR", "color_system_svg", "crop_behavior",
           "min_reproduction", "monogram_svg", "optical_centre", "palette_check", "raster_metrics", "safe_area", "specs",
           "stroke_consistency", "text_contrast", "transparency", "transparent_svg", "typography_specimen_svg"]
