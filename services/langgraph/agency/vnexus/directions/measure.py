"""Deterministic measurements on stored candidate bytes. Facts about pixels and geometry, never creative judgments.

Pixels come from the stored bytes only: PNG is decoded by the stdlib codec (``avic.png``); SVG is rendered by local
Chromium (``visual.browser.rasterize_svg``). Without Chromium an SVG has geometry facts but no pixel facts, and every
pixel-dependent check reports NOT_RUN instead of a value.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Optional

from services.langgraph.agency.avic import png
from services.langgraph.agency.avic.optimize import _lab
from services.langgraph.agency.execution_fabric.verifiers import svg_safety

from ..brandbook.assets import classify_svg

MEASURE_VERSION = "amc-vnexus-directions-measure/1.0.0"
WORKING = 128
OFF_PALETTE_DELTA_E = 10.0
_NS = "{http://www.w3.org/2000/svg}"
_PII = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|\+?\d[\d ()-]{7,}\d")
_SHAPES = ("path", "rect", "circle", "ellipse", "polygon", "polyline", "line")


def hex_rgb(h: str) -> tuple[int, int, int]:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def delta_e(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    la, lb = _lab(*a), _lab(*b)
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(la, lb)))


def _lum(rgb: tuple[int, ...]) -> float:
    def ch(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(rgb[0]) + 0.7152 * ch(rgb[1]) + 0.0722 * ch(rgb[2])


def contrast(a: tuple[int, ...], b: tuple[int, ...]) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return round((la + 0.05) / (lb + 0.05), 2)


def raster_for(data: bytes, mime: str, *, width: Optional[int], height: Optional[int], work: Path) -> tuple[Optional[png.Raster], str]:
    if mime == "image/png":
        try:
            return png.decode(data), "decoded stored PNG bytes"
        except png.PngError as exc:
            return None, f"PNG_UNDECODABLE: {exc}"
    if mime == "image/svg+xml":
        from services.langgraph.agency.visual.browser import probe_browser, rasterize_svg

        probe = probe_browser()
        if not probe.get("available"):
            return None, "NOT_RUN: local Chromium unavailable (" + ", ".join(probe.get("blockers", [])) + ")"
        w, h = svg_size(data.decode("utf-8", errors="replace"))
        r = rasterize_svg(data.decode("utf-8", errors="replace"), width=width or w or 512, height=height or h or 512, out_dir=work)
        if r["status"] != "PASSED":
            return None, "RENDER_FAILED: " + ", ".join(r["findings"])
        return png.decode(Path(r["capture"]).read_bytes()), "rendered stored SVG bytes in local Chromium"
    return None, f"NO_DECODER_FOR:{mime}"


def svg_size(svg: str) -> tuple[Optional[int], Optional[int]]:
    try:
        root = ET.fromstring(svg)
    except ET.ParseError:
        return None, None
    vb = (root.get("viewBox") or "").replace(",", " ").split()

    def num(v: Optional[str]) -> Optional[int]:
        try:
            return int(float(re.sub(r"px$", "", v or ""))) or None
        except ValueError:
            return None
    w, h = num(root.get("width")), num(root.get("height"))
    if (w is None or h is None) and len(vb) == 4:
        try:
            w, h = w or int(float(vb[2])), h or int(float(vb[3]))
        except ValueError:
            pass
    return w, h


def pixels(r: png.Raster, palette: dict[str, str]) -> dict[str, Any]:
    """Dominant colours, palette conformance, dominant-pair contrast, small-size retention and a perceptual hash."""
    small = png.downsample(r, WORKING)
    n = small.width * small.height
    buckets: dict[tuple[int, int, int], list[int]] = {}
    for i in range(0, len(small.rgba), 4):
        rgb = small.rgba[i:i + 3]
        key = (rgb[0] >> 3, rgb[1] >> 3, rgb[2] >> 3)
        acc = buckets.setdefault(key, [0, 0, 0, 0])
        acc[0] += rgb[0]
        acc[1] += rgb[1]
        acc[2] += rgb[2]
        acc[3] += 1
    ranked = sorted(buckets.values(), key=lambda a: -a[3])
    dominant = []
    for acc in ranked:
        share = acc[3] / n
        if share < 0.02 or len(dominant) >= 8:
            break
        rgb = (acc[0] // acc[3], acc[1] // acc[3], acc[2] // acc[3])
        near = min(((role, delta_e(rgb, hex_rgb(hx))) for role, hx in palette.items()), key=lambda t: t[1], default=(None, None))
        dominant.append({"hex": "#%02x%02x%02x" % rgb, "share": round(share, 4), "nearest_role": near[0],
                         "delta_e76": round(near[1], 2) if near[1] is not None else None})
    covered = sum(d["share"] for d in dominant)
    off = sum(d["share"] for d in dominant if d["delta_e76"] is None or d["delta_e76"] > OFF_PALETTE_DELTA_E)
    pair = contrast(hex_rgb(dominant[0]["hex"]), hex_rgb(dominant[1]["hex"])) if len(dominant) >= 2 else None
    ink = sum(1 for i in range(0, len(small.rgba), 4) if dominant and
              delta_e(tuple(small.rgba[i:i + 3]), hex_rgb(dominant[0]["hex"])) > OFF_PALETTE_DELTA_E) / n
    return {"width": r.width, "height": r.height, "unique_colour_buckets": len(buckets), "nonblank": len(buckets) > 1,
            "dominant": dominant, "dominant_coverage": round(covered, 4), "off_palette_share": round(off, 4),
            "unclassified_share": round(1 - covered, 4), "dominant_pair_contrast": pair,
            "figure_share": round(ink, 4), "aspect": round(r.width / r.height, 4),
            "retention_32": _retention(r, 32), "retention_16": _retention(r, 16), "dhash": dhash(r)}


def _std_lum(r: png.Raster) -> float:
    vals = [_lum(tuple(r.rgba[i:i + 3])) for i in range(0, len(r.rgba), 4)]
    mean = sum(vals) / len(vals)
    return math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals))


def _retention(r: png.Raster, size: int) -> Optional[float]:
    """Luminance spread kept when the asset is reduced to ``size`` px (1.0 = all of it). A proxy, labelled INFERRED."""
    base = _std_lum(png.downsample(r, WORKING))
    if base <= 1e-6:
        return None
    return round(min(1.0, _std_lum(png.downsample(r, size)) / base), 3)


def dhash(r: png.Raster) -> str:
    s = png.downsample(r, 9)
    # Resample onto an exact 9x8 grid from whatever aspect the downsample produced.
    lum = [[_lum(s.pixel(min(s.width - 1, x * s.width // 9), min(s.height - 1, y * s.height // 8))[:3]) for x in range(9)]
           for y in range(8)]
    bits = "".join("1" if row[x] > row[x + 1] else "0" for row in lum for x in range(8))
    return "%016x" % int(bits, 2)


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def geometry(svg: str) -> dict[str, Any]:
    """Structural facts about an SVG. ``vector`` is true only for parseable, safe SVG with native shapes and no raster."""
    out: dict[str, Any] = {"parseable": False, "classification": classify_svg(svg).value}
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as exc:
        out["error"] = f"SVG_MALFORMED: {exc}"
        out["vector"] = False
        return out
    safety = svg_safety(svg)
    tags = [el.tag.replace(_NS, "") for el in root.iter()]
    texts = ["".join(el.itertext()) for el in root.iter() if el.tag == f"{_NS}text"]
    path_nodes = sum(len(re.findall(r"[MLHVCSQTAZmlhvcsqtaz]", el.get("d") or "")) for el in root.iter() if el.tag == f"{_NS}path")
    hrefs = [v for el in root.iter() for k, v in el.attrib.items() if k.endswith("href")]
    fills = sorted({(el.get("fill") or "").lower() for el in root.iter() if (el.get("fill") or "").startswith("#")})
    out.update({"parseable": True, "safe": safety.passed, "safety_detail": safety.detail, "view_box": root.get("viewBox"),
                "shapes": sum(1 for t in tags if t in _SHAPES), "path_nodes": path_nodes, "elements": len(tags),
                "text_elements": texts, "external_refs": [h for h in hrefs if not h.startswith("#")], "fills": fills,
                "clip_paths": tags.count("clipPath"), "gradients": tags.count("linearGradient") + tags.count("radialGradient"),
                "pii_like_text": [_redact(t) for t in texts if _PII.search(t)]})
    out["vector"] = bool(out["classification"] == "VECTOR" and safety.passed and out["shapes"] + len(texts) > 0
                         and not out["external_refs"])
    return out


def _redact(text: str) -> str:
    return _PII.sub("[PII]", text)


__all__ = ["MEASURE_VERSION", "OFF_PALETTE_DELTA_E", "contrast", "delta_e", "dhash", "geometry", "hamming", "hex_rgb", "pixels",
           "raster_for", "svg_size"]
