"""H1 bounded perceptual reconstruction: raster reference -> native SVG approximations, measured.

CPU-only, stdlib-only baseline (no DiffVG/LIVE/COVec dependency):

1. decode + downsample the reference to a working grid, convert to CIE Lab;
2. coarse-to-fine region split: repeatedly split the region with the largest Lab
   error (a quadtree driven by error, so detail is allocated where it is needed);
3. per region, fit a flat colour and a least-squares linear gradient along x and y,
   keeping the gradient only when it lowers error by a set margin;
4. emit native SVG (rects + linear gradients; no raster, ever) at several budgets;
5. keep the Pareto front over (perceptual error, element count, bytes).

Two error numbers are reported and labelled: ``estimated_*`` (analytic, on the
working grid) and ``measured_*`` (the SVG rendered by Chromium and compared with the
reference pixel by pixel). Only the measured numbers are evidence of fidelity. High
element counts are not evidence of anything by themselves.

Not implemented here (``PROPOSED``): differentiable rendering (DiffVG), layer-wise
path optimisation (LIVE), Bezier contour fitting, nonlinear equality-constraint
projection (``A d = -h(theta)`` with Jacobian rank/conditioning checks).
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Optional
from xml.etree import ElementTree as ET

from . import png
from .contracts import CapabilityState

STATE = CapabilityState.PARTIAL
PROPOSED_METHODS = ("diffvg_differentiable_rendering", "live_layerwise_paths", "bezier_contour_fitting",
                    "nonlinear_constraint_projection")
WORKING_SIZE = 96
GRADIENT_GAIN = 0.75   # keep a gradient only when it removes >= 25% of the flat-fit error
MAX_REGIONS = 4096
NS = "http://www.w3.org/2000/svg"

_LIN = [((c / 255) / 12.92) if c / 255 <= 0.04045 else (((c / 255) + 0.055) / 1.055) ** 2.4 for c in range(256)]


def _lab(r: int, g: int, b: int) -> tuple[float, float, float]:
    R, G, B = _LIN[r], _LIN[g], _LIN[b]
    x = (0.4124 * R + 0.3576 * G + 0.1805 * B) / 0.95047
    y = 0.2126 * R + 0.7152 * G + 0.0722 * B
    z = (0.0193 * R + 0.1192 * G + 0.9505 * B) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def _srgb_from_lab(L: float, a: float, b: float) -> tuple[int, int, int]:
    fy = (L + 16) / 116
    fx, fz = fy + a / 500, fy - b / 200

    def finv(t: float) -> float:
        return t ** 3 if t ** 3 > 0.008856 else (t - 16 / 116) / 7.787
    x, y, z = finv(fx) * 0.95047, finv(fy), finv(fz) * 1.08883
    rl = 3.2406 * x - 1.5372 * y - 0.4986 * z
    gl = -0.9689 * x + 1.8758 * y + 0.0415 * z
    bl = 0.0557 * x - 0.2040 * y + 1.0570 * z

    def enc(v: float) -> int:
        v = min(max(v, 0.0), 1.0)
        s = 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055
        return int(round(s * 255))
    return enc(rl), enc(gl), enc(bl)


@dataclass
class Region:
    x: int
    y: int
    w: int
    h: int
    mean: tuple[float, float, float]
    error: float            # sum of squared Lab error of the chosen fit
    gradient: Optional[tuple[str, tuple[float, float, float], tuple[float, float, float]]] = None  # axis, start, end


class Grid:
    def __init__(self, r: png.Raster):
        self.w, self.h = r.width, r.height
        self.lab = [_lab(*r.rgba[i:i + 3]) for i in range(0, len(r.rgba), 4)]

    def px(self, x: int, y: int) -> tuple[float, float, float]:
        return self.lab[y * self.w + x]


def _fit(g: Grid, x: int, y: int, w: int, h: int) -> Region:
    n = w * h
    pts = [(xx, yy, g.px(xx, yy)) for yy in range(y, y + h) for xx in range(x, x + w)]
    mean = tuple(sum(p[2][k] for p in pts) / n for k in range(3))
    flat = sum(sum((p[2][k] - mean[k]) ** 2 for k in range(3)) for p in pts)
    best = Region(x, y, w, h, mean, flat)  # type: ignore[arg-type]
    for axis, length in (("x", w), ("y", h)):
        if length < 2:
            continue
        # Least squares per channel: v = mean + slope * (t - tbar), t in [0, length-1]
        ts = [(p[0] - x) if axis == "x" else (p[1] - y) for p in pts]
        tbar = sum(ts) / n
        var = sum((t - tbar) ** 2 for t in ts)
        if var == 0:
            continue
        slopes = tuple(sum((t - tbar) * (p[2][k] - mean[k]) for t, p in zip(ts, pts)) / var for k in range(3))
        err = sum(sum((p[2][k] - (mean[k] + slopes[k] * (t - tbar))) ** 2 for k in range(3)) for t, p in zip(ts, pts))
        if err <= GRADIENT_GAIN * best.error:
            start = tuple(mean[k] + slopes[k] * (0 - tbar) for k in range(3))
            end = tuple(mean[k] + slopes[k] * (length - 1 - tbar) for k in range(3))
            best = Region(x, y, w, h, mean, err, (axis, start, end))  # type: ignore[arg-type]
    return best


def reconstruct(g: Grid, budget: int) -> list[Region]:
    """Error-driven coarse-to-fine split until ``budget`` regions (or nothing left to split)."""
    budget = max(1, min(budget, MAX_REGIONS))
    regions = [_fit(g, 0, 0, g.w, g.h)]
    while len(regions) < budget:
        i = max(range(len(regions)), key=lambda j: (regions[j].error, -j))
        r = regions[i]
        if r.error <= 1e-9 or (r.w < 2 and r.h < 2):
            break
        if r.w >= r.h:
            a, b = r.w // 2, r.w - r.w // 2
            kids = [_fit(g, r.x, r.y, a, r.h), _fit(g, r.x + a, r.y, b, r.h)]
        else:
            a, b = r.h // 2, r.h - r.h // 2
            kids = [_fit(g, r.x, r.y, r.w, a), _fit(g, r.x, r.y + a, r.w, b)]
        regions[i:i + 1] = kids
    return regions


def _hex(lab: tuple[float, float, float]) -> str:
    return "#%02x%02x%02x" % _srgb_from_lab(*lab)


def to_svg(regions: list[Region], *, grid_w: int, grid_h: int, width: int, height: int, title: str) -> str:
    sx, sy = width / grid_w, height / grid_h
    root = ET.Element(f"{{{NS}}}svg", {"width": str(width), "height": str(height), "viewBox": f"0 0 {width} {height}",
                                       "role": "img", "aria-labelledby": "avic-title", "shape-rendering": "crispEdges"})
    t = ET.SubElement(root, f"{{{NS}}}title", {"id": "avic-title"})
    t.text = title
    defs = ET.SubElement(root, f"{{{NS}}}defs")
    layer = ET.SubElement(root, f"{{{NS}}}g", {"id": "fidelity-layer", "data-role": "region"})
    for i, r in enumerate(regions):
        attrs = {"x": f"{r.x * sx:.2f}".rstrip("0").rstrip("."), "y": f"{r.y * sy:.2f}".rstrip("0").rstrip("."),
                 "width": f"{r.w * sx + 0.5:.2f}".rstrip("0").rstrip("."),
                 "height": f"{r.h * sy + 0.5:.2f}".rstrip("0").rstrip(".")}
        if r.gradient:
            axis, a, b = r.gradient
            gid = f"g{i}"
            # Pixel centres sit half a cell in from the region edges.
            n = (r.w if axis == "x" else r.h)
            o0, o1 = 0.5 / n, 1 - 0.5 / n
            lg = ET.SubElement(defs, f"{{{NS}}}linearGradient", {"id": gid, "x1": "0", "y1": "0",
                                                                  "x2": "1" if axis == "x" else "0", "y2": "0" if axis == "x" else "1"})
            ET.SubElement(lg, f"{{{NS}}}stop", {"offset": f"{o0:.4f}", "stop-color": _hex(a)})
            ET.SubElement(lg, f"{{{NS}}}stop", {"offset": f"{o1:.4f}", "stop-color": _hex(b)})
            attrs["fill"] = f"url(#{gid})"
        else:
            attrs["fill"] = _hex(r.mean)
        ET.SubElement(layer, f"{{{NS}}}rect", {"id": f"r{i}", **attrs})
    if not len(defs):
        root.remove(defs)
    return ET.tostring(root, encoding="unicode") + "\n"


def compare(reference: png.Raster, rendered: png.Raster, size: int = WORKING_SIZE) -> dict:
    """Measured error between two rasters at a common working size (alpha composited onto white)."""
    a, b = png.downsample(reference, size), png.downsample(rendered, size)
    if (a.width, a.height) != (b.width, b.height):
        b = png.downsample(rendered, max(a.width, a.height))
        if (a.width, a.height) != (b.width, b.height):
            return {"comparable": False}
    se = 0.0
    de = 0.0
    n = a.width * a.height
    for i in range(0, len(a.rgba), 4):
        pa, pb = a.rgba[i:i + 3], b.rgba[i:i + 3]
        se += sum((x - y) ** 2 for x, y in zip(pa, pb)) / 3
        la, lb = _lab(*pa), _lab(*pb)
        de += math.sqrt(sum((x - y) ** 2 for x, y in zip(la, lb)))
    mse = se / n
    return {"comparable": True, "compare_size": [a.width, a.height], "mse": round(mse, 3),
            "psnr_db": round(10 * math.log10(255 ** 2 / mse), 2) if mse > 0 else None, "mean_delta_e76": round(de / n, 3)}


def candidates(reference_png: bytes, *, budgets: tuple[int, ...] = (16, 64, 256), width: Optional[int] = None,
               height: Optional[int] = None) -> list[dict]:
    """One native-SVG candidate per budget with estimated error, element count and bytes."""
    ref = png.decode(reference_png)
    g = Grid(png.downsample(ref, WORKING_SIZE))
    W, H = width or ref.width, height or ref.height
    out = []
    for b in budgets:
        regions = reconstruct(g, b)
        text = to_svg(regions, grid_w=g.w, grid_h=g.h, width=W, height=H, title=f"Fidelity reconstruction, {len(regions)} regions")
        n = g.w * g.h
        est = math.sqrt(sum(r.error for r in regions) / n)
        out.append({"budget": b, "regions": len(regions), "gradients": sum(1 for r in regions if r.gradient),
                    "svg": text, "svg_bytes": len(text.encode()), "svg_sha256": hashlib.sha256(text.encode()).hexdigest(),
                    "estimated_rms_lab": round(est, 3)})
    return out


def pareto(rows: list[dict], keys: tuple[str, ...]) -> list[dict]:
    """Rows not dominated on every key (all minimised)."""
    front = []
    for r in rows:
        dominated = any(all(o[k] <= r[k] for k in keys) and any(o[k] < r[k] for k in keys) for o in rows if o is not r)
        if not dominated:
            front.append(r)
    return front


__all__ = ["PROPOSED_METHODS", "STATE", "WORKING_SIZE", "candidates", "compare", "pareto", "reconstruct", "to_svg"]
