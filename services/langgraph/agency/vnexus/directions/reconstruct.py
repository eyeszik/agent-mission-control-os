"""Stage 7: conditional vector reconstruction of a human-selected candidate, with a rendered fidelity comparison.

Only roles that need editable paths enter this route (``vector_need``): photography and texture keep their raster;
an SVG candidate that is already native vector needs nothing. Two methods:

* ``controlled_trace``: the AVIC H1 region split (``avic.optimize``) on the selected PNG, every fill snapped to the
  nearest approved palette role. Identity text is never traced: the operator marks the generated lettering's region,
  it is masked out, and the exact strings are set as editable ``<text>`` in the approved display face.
* ``native_path_import``: SVG built or refined by a designer, validated and measured exactly the same way.

Nothing is called "vector" unless it parses, passes the SVG safety verifier, has native shapes and no embedded raster
or external reference. Fidelity is claimed only from a Chromium render compared pixel by pixel with the source (text
region excluded on both sides, because it was rebuilt rather than traced). Without Chromium the result is
NOT_VERIFIED. A parse or a path count is never evidence of a better design.
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Optional
from xml.sax.saxutils import escape

from services.langgraph.agency.avic import optimize, png

from ..brandbook.render import font_name
from . import measure
from .records import AssetRole, CreativeIntent, GenerationCandidate, VectorNeed

FIDELITY_MAX_DELTA_E = 8.0
TRACE_BUDGETS = (256, 1024)
TEXT_ROLES = frozenset({AssetRole.WORDMARK, AssetRole.LOCKUP})


class NotRequired(ValueError):
    pass


def decide(intent: CreativeIntent, cand: GenerationCandidate) -> tuple[str, str]:
    """RECONSTRUCT | OPTIONAL | NOT_REQUIRED | KEEP_RASTER, with the reason."""
    if intent.vector_need is VectorNeed.KEEP_RASTER:
        return "KEEP_RASTER", f"{intent.asset_role.value} keeps its raster master; vectorization adds no value"
    if cand.observed.format_class == "VECTOR":
        return "NOT_REQUIRED", "the selected candidate is already native vector"
    if intent.vector_need is VectorNeed.REQUIRED:
        return "RECONSTRUCT", "the selected raster needs editable paths for this role"
    return "OPTIONAL", "reconstruction is optional for this role and runs only on explicit request"


def _mask(r: png.Raster, box: tuple[int, int, int, int], rgb: tuple[int, int, int]) -> png.Raster:
    x, y, w, h = box
    buf = bytearray(r.rgba)
    for yy in range(max(0, y), min(r.height, y + h)):
        for xx in range(max(0, x), min(r.width, x + w)):
            i = (yy * r.width + xx) * 4
            buf[i:i + 4] = bytes((*rgb, 255))
    return png.Raster(r.width, r.height, bytes(buf))


def _ground(r: png.Raster) -> tuple[int, int, int]:
    px = measure.pixels(r, {})
    return measure.hex_rgb(px["dominant"][0]["hex"]) if px["dominant"] else (255, 255, 255)


_FILL = re.compile(r'(fill|stop-color)="(#[0-9a-fA-F]{6})"')


def snap_to_palette(svg: str, palette: dict[str, str]) -> str:
    targets = [measure.hex_rgb(v) for v in palette.values() if re.fullmatch(r"#[0-9a-fA-F]{6}", v or "")]
    if not targets:
        return svg

    def nearest(m: re.Match) -> str:
        rgb = measure.hex_rgb(m.group(2))
        best = min(targets, key=lambda t: measure.delta_e(rgb, t))
        return f'{m.group(1)}="#%02x%02x%02x"' % best
    return _FILL.sub(nearest, svg)


_GRADIENT = re.compile(r'<linearGradient id="(g\d+)"[^>]*>([\s\S]*?)</linearGradient>')
_STOP = re.compile(r'stop-color="(#[0-9a-fA-F]{6})"')


def flatten_gradients(svg: str) -> str:
    """Replace each region gradient by the mean of its stops (palette snapping follows); masters carry flat fills."""
    means = {}
    for gid, body in _GRADIENT.findall(svg):
        stops = [measure.hex_rgb(h) for h in _STOP.findall(body)]
        if stops:
            means[gid] = "#%02x%02x%02x" % tuple(round(sum(c[i] for c in stops) / len(stops)) for i in range(3))
    svg = _GRADIENT.sub("", svg)
    svg = re.sub(r"<defs>\s*</defs>|<defs\s*/>", "", svg)
    return re.sub(r'fill="url\(#(g\d+)\)"', lambda m: f'fill="{means.get(m.group(1), "#000000")}"', svg)


def _with_text(svg: str, texts: list[str], box: tuple[int, int, int, int], face: Optional[str], fill: str) -> str:
    x, y, w, h = box
    size = max(6, int(h * 0.7 / max(1, len(texts))))
    family = escape(font_name(face) if face else "sans-serif")
    lines = "".join(f'<text x="{x + w / 2:.1f}" y="{y + (i + 1) * h / (len(texts) + 0.5):.1f}" font-family="{family}" '
                    f'font-size="{size}" text-anchor="middle" fill="{fill}">{escape(t)}</text>' for i, t in enumerate(texts))
    return svg.rstrip().removesuffix("</svg>").rstrip() + lines + "</svg>\n"


def validate(svg: str, intent: CreativeIntent) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    geo = measure.geometry(svg)
    checks: list[dict[str, Any]] = []

    def check(name: str, status: str, detail: str) -> None:
        checks.append({"check": name, "status": status, "detail": detail})
    check("svg_safety", "PASS" if geo.get("parseable") and geo.get("safe") and not geo.get("external_refs") else "FAIL",
          geo.get("safety_detail") or geo.get("error") or "")
    check("native_geometry", "PASS" if geo.get("vector") else "FAIL",
          "embedded raster is raster, not vector" if geo.get("classification") == "RASTER_IN_SVG" else
          f"{geo.get('shapes', 0)} shapes, {geo.get('path_nodes', 0)} path commands")
    check("view_box", "PASS" if geo.get("view_box") else "FAIL", geo.get("view_box") or "missing viewBox")
    palette = {v.lower() for v in intent.vector_instructions.get("palette_roles", {}).values() if isinstance(v, str)}
    off = [f for f in geo.get("fills", []) if f not in palette]
    if intent.asset_role in TEXT_ROLES or intent.asset_role in (AssetRole.LOGO_MARK, AssetRole.ICON):
        check("palette_only_fills", "PASS" if not off and geo.get("gradients", 0) == 0 else "FAIL",
              f"off-palette fills {off}" if off else f"{geo.get('gradients', 0)} gradients" if geo.get("gradients") else "palette roles only")
    exact = intent.vector_instructions.get("exact_text") or []
    if exact:
        missing = [t for t in exact if t not in (geo.get("text_elements") or [])]
        check("editable_exact_text", "FAIL" if missing else "PASS", f"missing {missing}" if missing else "set verbatim as editable text")
    else:
        check("editable_exact_text", "NOT_APPLICABLE", "no identity text in the brief")
    check("clipping", "PASS" if not geo.get("clip_paths") else "NOT_VERIFIED", f"{geo.get('clip_paths', 0)} clip paths")
    check("self_intersections", "NOT_VERIFIED", "no geometry kernel is installed; inspect paths in an editor")
    check("curve_quality_and_nodes", "NOT_VERIFIED", f"{geo.get('path_nodes', 0)} path commands; curve quality needs a designer")
    cls = "REJECTED" if not (geo.get("parseable") and geo.get("safe")) or geo.get("external_refs") else \
        ("RASTER_IN_SVG" if geo.get("classification") == "RASTER_IN_SVG" else "VECTOR")
    return cls, checks, geo


def fidelity(svg: str, reference: png.Raster, *, text_box: Optional[tuple[int, int, int, int]], work: Path) -> dict[str, Any]:
    from services.langgraph.agency.visual.browser import probe_browser, rasterize_svg

    probe = probe_browser()
    if not probe.get("available"):
        return {"status": "NOT_RUN", "reason": "local Chromium unavailable: " + ", ".join(probe.get("blockers", []))}
    r = rasterize_svg(svg, width=reference.width, height=reference.height, out_dir=work)
    if r["status"] != "PASSED":
        return {"status": "NOT_RUN", "reason": "render failed: " + ", ".join(r["findings"])}
    rendered = png.decode(Path(r["capture"]).read_bytes())
    ref = reference
    if text_box:
        ground = _ground(reference)
        ref, rendered = _mask(reference, text_box, ground), _mask(rendered, text_box, ground)
    cmp = optimize.compare(ref, rendered)
    if not cmp.get("comparable"):
        return {"status": "NOT_RUN", "reason": "rendered size not comparable"}
    ok = cmp["mean_delta_e76"] <= FIDELITY_MAX_DELTA_E
    return {"status": "PASS" if ok else "FAIL", "measured": cmp, "threshold_mean_delta_e76": FIDELITY_MAX_DELTA_E,
            "text_region_excluded": bool(text_box), "renderer": "local Chromium", "rendered_sha256": hashlib.sha256(
                Path(r["capture"]).read_bytes()).hexdigest(),
            "note": "measured agreement with the selected candidate; not a claim that the design is better"}


def reference_raster(cand: GenerationCandidate, data: bytes, work: Path) -> png.Raster:
    raster, note = measure.raster_for(data, cand.observed.mime, width=cand.observed.width, height=cand.observed.height, work=work)
    if raster is None:
        raise ValueError(f"the selected candidate cannot be decoded for reconstruction: {note}")
    return raster


def trace(intent: CreativeIntent, cand: GenerationCandidate, data: bytes, *, text_box: Optional[tuple[int, int, int, int]],
          work: Path) -> tuple[str, dict[str, Any]]:
    if cand.observed.mime != "image/png":
        raise ValueError("controlled_trace reads PNG candidates; import a designer SVG with native_path_import instead")
    exact = intent.vector_instructions.get("exact_text") or []
    if exact and intent.asset_role in TEXT_ROLES and text_box is None:
        raise ValueError("identity text is never traced: mark the generated lettering's region (text_region) so the exact text is "
                         "set from the approved face, or import designer geometry")
    ref = png.decode(data)
    source = _mask(ref, text_box, _ground(ref)) if text_box else ref
    palette = {k: v for k, v in intent.vector_instructions.get("palette_roles", {}).items() if isinstance(v, str)}
    attempts = []
    for row in optimize.candidates(png.encode(source), budgets=TRACE_BUDGETS, width=ref.width, height=ref.height):
        svg = flatten_gradients(row["svg"])
        svg = snap_to_palette(svg, palette)
        if exact and text_box:
            face = intent.vector_instructions.get("approved_faces", {}).get("display")
            svg = _with_text(svg, exact, text_box, face, palette.get("ink", "#000000"))
        attempts.append({"budget": row["budget"], "regions": row["regions"], "svg": svg})
    return attempts[-1]["svg"], {"budgets": [a["budget"] for a in attempts], "regions": attempts[-1]["regions"],
                                 "method_state": "PARTIAL: rectangle regions snapped to palette; Bezier contour fitting is PROPOSED"}


def check_svg_import(svg: str) -> str:
    try:
        ET.fromstring(svg)
    except ET.ParseError as exc:
        raise ValueError(f"SVG_MALFORMED: {exc}") from exc
    return svg


__all__ = ["FIDELITY_MAX_DELTA_E", "NotRequired", "TEXT_ROLES", "check_svg_import", "decide", "fidelity", "reference_raster",
           "snap_to_palette", "trace", "validate"]
