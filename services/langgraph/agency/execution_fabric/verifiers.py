"""Deterministic output verifiers. No model, no network, no randomness.

Each verifier states exactly what it measures. Where the framework names a
stronger technique than the one implemented, the docstring says so rather than
borrowing the name:

* colour: CIE76 delta-E in CIELAB (D65), not CIEDE2000;
* code: an AST *structural* diff (node-type multiset distance plus changed
  top-level definitions), not a spectral graph comparison;
* DOM: Levenshtein distance over the pre-order tag sequence, not a full
  Zhang-Shasha tree edit distance.
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Iterable
from xml.etree import ElementTree

HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}\b")
# Just-noticeable difference commonly used for CIE76.
JND_DELTA_E = 2.3


@dataclass(frozen=True)
class Verdict:
    validator_id: str
    passed: bool
    detail: str

    def as_dict(self) -> dict:
        return {"validator_id": self.validator_id, "passed": self.passed, "detail": self.detail}


# ---------------------------------------------------------------- colour

def _srgb_to_lab(hex_value: str) -> tuple[float, float, float]:
    h = hex_value.lstrip("#")
    rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    x = (lin[0] * 0.4124 + lin[1] * 0.3576 + lin[2] * 0.1805) / 0.95047
    y = (lin[0] * 0.2126 + lin[1] * 0.7152 + lin[2] * 0.0722) / 1.0
    z = (lin[0] * 0.0193 + lin[1] * 0.1192 + lin[2] * 0.9505) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 216 / 24389 else (24389 / 27 * t + 16) / 116

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e76(a: str, b: str) -> float:
    la, lb = _srgb_to_lab(a), _srgb_to_lab(b)
    return round(sum((p - q) ** 2 for p, q in zip(la, lb)) ** 0.5, 3)


def colors_in(text: str) -> tuple[str, ...]:
    return tuple(sorted({c.lower() for c in HEX_COLOR.findall(text)}))


def palette_conformance(text: str, palette: Iterable[str], *, tolerance: float = JND_DELTA_E) -> Verdict:
    """Every literal colour in ``text`` lies within ``tolerance`` of a palette colour."""
    allowed = tuple(sorted({p.lower() for p in palette}))
    offending = [c for c in colors_in(text) if min(delta_e76(c, p) for p in allowed) > tolerance]
    if offending:
        return Verdict("palette_delta_e", False, f"off-palette colours (dE76>{tolerance}): {offending}")
    return Verdict("palette_delta_e", True, f"{len(colors_in(text))} colour(s) within dE76<={tolerance} of the palette")


# ---------------------------------------------------------------- SVG

_SVG_NS = "{http://www.w3.org/2000/svg}"
_FORBIDDEN_SVG = {"script", "foreignObject", "iframe", "object", "embed"}


def svg_safety(svg_text: str, *, max_bytes: int = 512_000) -> Verdict:
    """Well-formed SVG root, no active content, no external references."""
    if len(svg_text.encode("utf-8")) > max_bytes:
        return Verdict("svg_safety", False, "SVG exceeds the size limit")
    if "<!DOCTYPE" in svg_text or "<!ENTITY" in svg_text:
        return Verdict("svg_safety", False, "DTD/entity declarations are not allowed")
    try:
        root = ElementTree.fromstring(svg_text)
    except ElementTree.ParseError as exc:
        return Verdict("svg_safety", False, f"not well-formed XML: {exc}")
    if root.tag != f"{_SVG_NS}svg":
        return Verdict("svg_safety", False, "root element is not <svg>")
    for el in root.iter():
        local = el.tag.split("}", 1)[-1]
        if local in _FORBIDDEN_SVG:
            return Verdict("svg_safety", False, f"forbidden element <{local}>")
        for name, value in el.attrib.items():
            attr = name.split("}", 1)[-1].lower()
            if attr.startswith("on"):
                return Verdict("svg_safety", False, f"event handler attribute {attr}")
            if attr == "href" and not value.startswith("#"):
                return Verdict("svg_safety", False, "external href")
            if "javascript:" in value.lower() or "url(http" in value.lower():
                return Verdict("svg_safety", False, "active or remote reference in an attribute")
    return Verdict("svg_safety", True, "well-formed SVG without active content or external references")


# ---------------------------------------------------------------- code

def _defs(tree: ast.Module) -> dict[str, str]:
    return {
        node.name: ast.dump(node, include_attributes=False)
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


def ast_structural_diff(before: str, after: str) -> dict:
    """Structural change between two Python sources. Raises SyntaxError if
    ``after`` does not parse: an unparseable patch is never accepted."""
    old = ast.parse(before or "")
    new = ast.parse(after)
    a = Counter(type(n).__name__ for n in ast.walk(old))
    b = Counter(type(n).__name__ for n in ast.walk(new))
    distance = sum(((a - b) + (b - a)).values())
    old_defs, new_defs = _defs(old), _defs(new)
    return {
        "node_type_distance": distance,
        "added": sorted(set(new_defs) - set(old_defs)),
        "removed": sorted(set(old_defs) - set(new_defs)),
        "changed": sorted(n for n in set(old_defs) & set(new_defs) if old_defs[n] != new_defs[n]),
    }


# ---------------------------------------------------------------- DOM

class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[str] = []
        self.elements: list[tuple[str, dict[str, str]]] = []
        self._text_stack: list[str] = []
        self.text_by_tag: list[tuple[str, dict[str, str], str]] = []
        self._open: list[tuple[str, dict[str, str], list[str]]] = []

    def handle_starttag(self, tag, attrs):
        attributes = {k: (v or "") for k, v in attrs}
        self.tags.append(tag)
        self.elements.append((tag, attributes))
        if tag not in {"img", "meta", "link", "br", "hr", "input"}:
            self._open.append((tag, attributes, []))

    def handle_endtag(self, tag):
        for i in range(len(self._open) - 1, -1, -1):
            if self._open[i][0] == tag:
                name, attributes, parts = self._open.pop(i)
                self.text_by_tag.append((name, attributes, "".join(parts).strip()))
                break

    def handle_data(self, data):
        for _, _, parts in self._open:
            parts.append(data)


def parse_dom(html: str) -> _Collector:
    collector = _Collector()
    collector.feed(html)
    collector.close()
    return collector


def dom_tag_edit_distance(a: str, b: str) -> int:
    """Levenshtein distance over pre-order tag sequences."""
    x, y = parse_dom(a).tags, parse_dom(b).tags
    prev = list(range(len(y) + 1))
    for i, tx in enumerate(x, 1):
        cur = [i]
        for j, ty in enumerate(y, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (tx != ty)))
        prev = cur
    return prev[-1]


__all__ = [
    "JND_DELTA_E",
    "Verdict",
    "ast_structural_diff",
    "colors_in",
    "delta_e76",
    "dom_tag_edit_distance",
    "palette_conformance",
    "parse_dom",
    "svg_safety",
]
