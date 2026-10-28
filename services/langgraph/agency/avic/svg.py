"""SceneIR -> native SVG (deterministic emitter) and the allowlist validator every SVG must pass.

The validator is an allowlist, not a denylist: an element or attribute it does not
name is rejected. It runs after the repository's ``svg_safety`` check (which it
reuses), then enforces local-only references, reference integrity, unique ids,
finite coordinates, resource ceilings and output-profile integrity (no raster in a
native profile). Text content is escaped by ElementTree, so exact text cannot inject
markup.
"""

from __future__ import annotations

import math
import re
from typing import Iterable, Optional
from xml.etree import ElementTree as ET

from services.langgraph.agency.execution_fabric.verifiers import svg_safety

from .contracts import NATIVE_PROFILES, Check, OutputProfile, Result, SceneIR, SceneObject

NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", NS)

MAX_ELEMENTS = 20_000
MAX_PATH_COMMANDS = 200_000
MAX_DEPTH = 24
MAX_ABS_COORD = 100_000

_COMMON = {"id", "transform", "fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "stroke-opacity",
           "fill-opacity", "opacity", "clip-path", "mask", "filter", "data-role", "data-req", "data-protected",
           "data-material", "fill-rule", "clip-rule", "vector-effect", "shape-rendering"}
_TEXT = {"x", "y", "dx", "dy", "font-family", "font-size", "font-weight", "letter-spacing", "text-anchor",
         "dominant-baseline", "xml:space"}
ALLOWED: dict[str, set[str]] = {
    "svg": {"width", "height", "viewBox", "role", "aria-labelledby", "preserveAspectRatio", "version"},
    "title": {"id"}, "desc": {"id"}, "defs": set(), "g": set(), "symbol": {"viewBox"},
    "use": {"href", "x", "y", "width", "height"},
    "rect": {"x", "y", "width", "height", "rx", "ry"}, "circle": {"cx", "cy", "r"}, "ellipse": {"cx", "cy", "rx", "ry"},
    "line": {"x1", "y1", "x2", "y2"}, "polygon": {"points"}, "polyline": {"points"}, "path": {"d", "pathLength"},
    "text": _TEXT, "tspan": _TEXT,
    "linearGradient": {"x1", "y1", "x2", "y2", "gradientUnits", "gradientTransform", "spreadMethod"},
    "radialGradient": {"cx", "cy", "r", "fx", "fy", "gradientUnits", "gradientTransform", "spreadMethod"},
    "stop": {"offset", "stop-color", "stop-opacity"},
    "clipPath": {"clipPathUnits"}, "mask": {"x", "y", "width", "height", "maskUnits", "maskContentUnits"},
    "filter": {"x", "y", "width", "height", "filterUnits", "color-interpolation-filters"},
    "feGaussianBlur": {"in", "stdDeviation", "result"},
    "feTurbulence": {"type", "baseFrequency", "numOctaves", "seed", "stitchTiles", "result"},
    "feColorMatrix": {"in", "type", "values", "result"}, "feComposite": {"in", "in2", "operator", "result"},
    "feBlend": {"in", "in2", "mode", "result"}, "feFlood": {"flood-color", "flood-opacity", "result"},
    "feOffset": {"in", "dx", "dy", "result"},
    "image": {"href", "x", "y", "width", "height", "preserveAspectRatio"},  # HYBRID_SVG only, data:image/png only
}
_TEXT_HOSTS = {"title", "desc", "text", "tspan"}
_URL = re.compile(r"url\(\s*#([A-Za-z][\w.-]*)\s*\)")
_NUM = re.compile(r"-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_DATA_PNG = re.compile(r"^data:image/png;base64,[A-Za-z0-9+/=]+$")


def _n(v: float) -> str:
    if not math.isfinite(v):
        raise ValueError("non-finite coordinate")
    t = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if t in {"-0", ""} else t


# ------------------------------------------------------------------ emit


def _attrs(o: SceneObject) -> dict[str, str]:
    a = {"id": o.object_id, "data-role": o.semantic_role}
    if o.requirement_refs:
        a["data-req"] = " ".join(o.requirement_refs)
    if o.protected:
        a["data-protected"] = "true"
    if o.material_ref:
        a["data-material"] = o.material_ref
    ap = o.appearance
    if ap.fill is not None:
        a["fill"] = ap.fill
    if ap.stroke is not None:
        a["stroke"] = ap.stroke
        a["stroke-width"] = _n(ap.stroke_width)
    if ap.opacity != 1.0:
        a["opacity"] = _n(ap.opacity)
    if ap.blur:
        a["filter"] = f"url(#fx-{ap.blur})"
    g = o.geometry
    if g.clip_to:
        a["clip-path"] = f"url(#clip-{g.clip_to})"
    if g.rotate:
        cx, cy = _center(o)
        a["transform"] = f"rotate({_n(g.rotate)} {_n(cx)} {_n(cy)})"
    return a


def _center(o: SceneObject) -> tuple[float, float]:
    p = o.geometry.params
    if "cx" in p:
        return p["cx"], p["cy"]
    if "width" in p:
        return p["x"] + p["width"] / 2, p["y"] + p["height"] / 2
    pts = o.geometry.points or tuple((c.coords[0], c.coords[1]) for c in o.geometry.path if c.coords)
    if pts:
        return sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts)
    return p.get("x", 0.0), p.get("y", 0.0)


def _shape(parent: ET.Element, o: SceneObject, *, with_attrs: bool = True) -> ET.Element:
    g, p = o.geometry, o.geometry.params
    attrs = _attrs(o) if with_attrs else {}
    if g.primitive == "rect":
        el = ET.SubElement(parent, f"{{{NS}}}rect", {**attrs, **{k: _n(p[k]) for k in ("x", "y", "width", "height")},
                                                      **({"rx": _n(p["rx"])} if "rx" in p else {})})
    elif g.primitive == "circle":
        el = ET.SubElement(parent, f"{{{NS}}}circle", {**attrs, **{k: _n(p[k]) for k in ("cx", "cy", "r")}})
    elif g.primitive == "ellipse":
        el = ET.SubElement(parent, f"{{{NS}}}ellipse", {**attrs, **{k: _n(p[k]) for k in ("cx", "cy", "rx", "ry")}})
    elif g.primitive == "polygon":
        el = ET.SubElement(parent, f"{{{NS}}}polygon", {**attrs, "points": " ".join(f"{_n(x)},{_n(y)}" for x, y in g.points)})
    elif g.primitive == "path":
        d = " ".join(c.op + (" " + " ".join(_n(v) for v in c.coords) if c.coords else "") for c in g.path)
        el = ET.SubElement(parent, f"{{{NS}}}path", {**attrs, "d": d})
    elif g.primitive == "text":
        ap = o.appearance
        ta = {**attrs, "x": _n(p["x"]), "y": _n(p["y"]), "font-family": "Helvetica Neue, Arial, sans-serif"}
        if ap.font_size:
            ta["font-size"] = _n(ap.font_size)
        if ap.font_weight:
            ta["font-weight"] = str(ap.font_weight)
        if ap.letter_spacing is not None:
            ta["letter-spacing"] = _n(ap.letter_spacing)
        if ap.text_anchor:
            ta["text-anchor"] = ap.text_anchor
        el = ET.SubElement(parent, f"{{{NS}}}text", ta)
        el.text = o.text
    else:  # group
        el = ET.SubElement(parent, f"{{{NS}}}g", attrs)
    return el


def emit(scene: SceneIR) -> str:
    d = scene.document
    root = ET.Element(f"{{{NS}}}svg", {"width": str(d.width), "height": str(d.height), "viewBox": f"0 0 {d.width} {d.height}",
                                       "role": "img", "aria-labelledby": "avic-title"})
    title = ET.SubElement(root, f"{{{NS}}}title", {"id": "avic-title"})
    title.text = d.title
    defs = ET.SubElement(root, f"{{{NS}}}defs")
    for gr in scene.gradients:
        tag = "linearGradient" if gr.kind == "linear" else "radialGradient"
        el = ET.SubElement(defs, f"{{{NS}}}{tag}", {"id": gr.gradient_id, **{k: _n(v) for k, v in sorted(gr.coords.items())}})
        for st in gr.stops:
            sa = {"offset": _n(st.offset), "stop-color": st.color}
            if st.opacity != 1.0:
                sa["stop-opacity"] = _n(st.opacity)
            ET.SubElement(el, f"{{{NS}}}stop", sa)
    blurs = {o.appearance.blur for o in scene.objects if o.appearance.blur}
    if "soft" in blurs:
        f = ET.SubElement(defs, f"{{{NS}}}filter", {"id": "fx-soft", "x": "-50%", "y": "-50%", "width": "200%", "height": "200%"})
        ET.SubElement(f, f"{{{NS}}}feGaussianBlur", {"stdDeviation": _n(max(d.width, d.height) * 0.012)})
    if "grain" in blurs:
        f = ET.SubElement(defs, f"{{{NS}}}filter", {"id": "fx-grain", "x": "0", "y": "0", "width": "100%", "height": "100%"})
        ET.SubElement(f, f"{{{NS}}}feTurbulence", {"type": "fractalNoise", "baseFrequency": "0.9", "numOctaves": "2",
                                                  "seed": str(scene.compilation.seed % 1000), "stitchTiles": "stitch",
                                                  "result": "noise"})
        ET.SubElement(f, f"{{{NS}}}feColorMatrix", {"in": "noise", "type": "saturate", "values": "0", "result": "mono"})
        ET.SubElement(f, f"{{{NS}}}feComposite", {"in": "mono", "in2": "SourceGraphic", "operator": "in"})
    for target in sorted({o.geometry.clip_to for o in scene.objects if o.geometry.clip_to}):
        cp = ET.SubElement(defs, f"{{{NS}}}clipPath", {"id": f"clip-{target}"})
        _shape(cp, scene.object(target), with_attrs=False)
    if not len(defs):
        root.remove(defs)
    elements: dict[str, ET.Element] = {}
    for o in scene.objects:
        parent = elements.get(o.parent_id, root) if o.parent_id else root
        elements[o.object_id] = _shape(parent, o)
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode") + "\n"


# ------------------------------------------------------------------ validate


def _numbers(value: str) -> Iterable[float]:
    for m in _NUM.findall(value):
        yield float(m)


def validate(svg_text: str, *, profile: OutputProfile, max_bytes: int = 512_000, expect_size: Optional[tuple[int, int]] = None,
             ) -> tuple[Check, ...]:
    """Every check the SVG must pass. Returns all findings (not just the first) so repair can see them."""
    checks: list[Check] = []

    def add(name: str, level: str, ok: bool, detail: str) -> None:
        checks.append(Check(check=name, level=level, result=Result.PASS if ok else Result.FAIL, detail=detail[:600]))

    base = svg_safety(svg_text, max_bytes=max_bytes)
    add("svg_safety", "Q4", base.passed, base.detail)
    if not base.passed:
        return tuple(checks)
    if "<?xml-stylesheet" in svg_text or re.search(r"<\?(?!xml\s)", svg_text):
        add("processing_instructions", "Q4", False, "processing instructions are not allowed")
        return tuple(checks)
    root = ET.fromstring(svg_text)
    ids: list[str] = []
    bad_el, bad_attr, bad_ref, bad_num, raster, depth_hit, text_misplaced = [], [], [], [], 0, False, []
    path_cmds = 0
    elements = 0

    def walk(el: ET.Element, depth: int) -> None:
        nonlocal raster, depth_hit, path_cmds, elements
        elements += 1
        if depth > MAX_DEPTH:
            depth_hit = True
        if not el.tag.startswith(f"{{{NS}}}"):
            bad_el.append(el.tag)
            return
        local = el.tag[len(NS) + 2:]
        allowed = ALLOWED.get(local)
        if allowed is None:
            bad_el.append(local)
            return
        if (el.text or "").strip() and local not in _TEXT_HOSTS:
            text_misplaced.append(local)
        for name, value in el.attrib.items():
            attr = name.split("}", 1)[-1] if name.startswith("{") else name
            if name.startswith("{http://www.w3.org/1999/xlink}"):
                attr = "href"
            if name.startswith("{http://www.w3.org/XML/1998/namespace}"):
                attr = "xml:" + attr
            if attr not in allowed and attr not in _COMMON:
                bad_attr.append(f"{local}@{attr}")
                continue
            if attr == "id":
                ids.append(value)
            if attr == "href":
                if local == "image":
                    raster += 1
                    if not _DATA_PNG.match(value):
                        bad_ref.append("image href must be an inline data:image/png")
                elif not value.startswith("#"):
                    bad_ref.append(f"{local} href {value[:40]}")
            if "url(" in value and not _URL.fullmatch(value.strip()):
                bad_ref.append(f"{local}@{attr} non-local url()")
            if attr in {"d", "points", "x", "y", "width", "height", "cx", "cy", "r", "rx", "ry", "x1", "y1", "x2", "y2",
                        "font-size", "stroke-width", "transform", "viewBox"}:
                for v in _numbers(value):
                    if not math.isfinite(v) or abs(v) > MAX_ABS_COORD:
                        bad_num.append(f"{local}@{attr}")
                        break
                if attr == "d":
                    path_cmds += len(re.findall(r"[MLCQZHVSTAmlcqzhvsta]", value))
                if "nan" in value.lower() or "inf" in value.lower():
                    bad_num.append(f"{local}@{attr}")
        for child in el:
            walk(child, depth + 1)

    walk(root, 0)
    add("allowlist_elements", "Q4", not bad_el, f"disallowed elements: {sorted(set(bad_el))}" if bad_el else "all elements allowlisted")
    add("allowlist_attributes", "Q4", not bad_attr,
        f"disallowed attributes: {sorted(set(bad_attr))[:20]}" if bad_attr else "all attributes allowlisted")
    add("text_placement", "Q3", not text_misplaced, f"character data in {sorted(set(text_misplaced))}" if text_misplaced else "ok")
    dup = sorted({i for i in ids if ids.count(i) > 1})
    add("unique_ids", "Q3", not dup, f"duplicate ids: {dup}" if dup else f"{len(ids)} unique ids")
    known = set(ids)
    for el in root.iter():
        for value in el.attrib.values():
            for ref in _URL.findall(value):
                if ref not in known:
                    bad_ref.append(f"dangling url(#{ref})")
            if value.startswith("#") and len(value) > 1 and not re.fullmatch(r"#[0-9a-fA-F]{3,8}", value) and value[1:] not in known:
                bad_ref.append(f"dangling {value}")
    add("reference_integrity", "Q4", not bad_ref, f"{sorted(set(bad_ref))[:10]}" if bad_ref else "all references local and resolved")
    add("finite_coordinates", "Q3", not bad_num, f"non-finite or out-of-range numbers in {sorted(set(bad_num))[:10]}"
        if bad_num else "all coordinates finite and bounded")
    add("resource_ceiling", "Q4", elements <= MAX_ELEMENTS and path_cmds <= MAX_PATH_COMMANDS and not depth_hit,
        f"{elements} elements, {path_cmds} path commands, depth<={MAX_DEPTH}: {not depth_hit}")
    native = profile in NATIVE_PROFILES
    add("profile_integrity", "Q3", (raster == 0) if native else profile == OutputProfile.HYBRID_SVG,
        f"{profile.value}: {raster} embedded raster element(s)" + ("" if not native or raster == 0 else
                                                                   " - raster is never native vectorization"))
    if expect_size is not None:
        w, h = root.attrib.get("width"), root.attrib.get("height")
        add("dimensions", "Q3", (w, h) == (str(expect_size[0]), str(expect_size[1])),
            f"declared {w}x{h}, expected {expect_size[0]}x{expect_size[1]}")
    return tuple(checks)


def text_content(svg_text: str) -> dict[str, str]:
    """Text of every <text> element by id, as authored (the exact-text oracle)."""
    root = ET.fromstring(svg_text)
    return {el.attrib.get("id", ""): "".join(el.itertext()) for el in root.iter(f"{{{NS}}}text")}


def element_signature(svg_text: str, element_id: str) -> Optional[dict[str, str]]:
    """Geometry-relevant attributes of one element (protected-geometry oracle)."""
    for el in ET.fromstring(svg_text).iter():
        if el.attrib.get("id") == element_id:
            return {k: v for k, v in sorted(el.attrib.items()) if k not in {"fill", "stroke", "opacity"}}
    return None


__all__ = ["ALLOWED", "MAX_ELEMENTS", "NS", "element_signature", "emit", "text_content", "validate"]
