"""Deterministic brand book rendering: page packages -> self-contained HTML pages.

* The page format comes from the approved genome (``production.output.page_format``);
  without one the default is used and labelled provisional. Not every brand gets
  the same aspect ratio.
* Nothing is clipped: there is no ``overflow:hidden``. Content is paginated by an
  estimate first (continuation pages keep the page id), then measured in local
  Chromium; a page that still overflows goes through the overflow ladder
  (hide decoration, then optional annotations, then split) and is reported if it
  still fails. Required content is never dropped or shrunk below the minimum size.
* Colours and faces come from the approved (or, in a draft, labelled proposed)
  genome. Without approved colours the page uses neutral rendering colours and says so.
* Every copy element carries ``data-copy`` so the rendered text can be compared with
  the package exactly. CSS never transforms text case.
"""

from __future__ import annotations

import math
import re
from html import escape
from typing import Any, Optional

from services.langgraph.agency.execution.canonical import canonical_hash

from .assets import MarkAsset
from .compiler import BookPackage, PagePackage

RENDERER_VERSION = "amc-brandbook-render/1.0.0"
PAGE_FORMATS: dict[str, tuple[int, int]] = {
    "a4-portrait": (794, 1123), "a4-landscape": (1123, 794), "letter-portrait": (816, 1056), "letter-landscape": (1056, 816),
    "16x9": (1600, 900), "square": (1080, 1080),
}
DEFAULT_FORMAT = "a4-portrait"
MIN_FONT_PX = 10
NEUTRAL = {"ink": "#1a1a1a", "paper": "#ffffff", "accent": "#4a4a4a", "muted": "#5c5c5c"}
PAD, HEAD, FOOT = 56, 64, 44


def page_format(fields: dict[str, Any]) -> tuple[str, int, int, bool]:
    """(name, width, height, provisional)."""
    value = fields.get("production.output.page_format")
    if isinstance(value, str) and value in PAGE_FORMATS:
        return (value, *PAGE_FORMATS[value], False)
    return (DEFAULT_FORMAT, *PAGE_FORMATS[DEFAULT_FORMAT], True)


def style_values(book: BookPackage) -> dict[str, Any]:
    """Resolved style inputs, read from the overview page's field states (it declares every style key)."""
    fields: dict[str, Any] = {}
    for page in book.pages:
        for f in page.fields:
            if f.printable:
                fields.setdefault(f.path, f.value)
    return fields


def palette_for(fields: dict[str, Any]) -> tuple[dict[str, str], bool]:
    pal = {r: fields.get(f"visual.color.{r}") for r in ("ink", "paper", "accent", "muted")}
    if all(isinstance(pal[r], str) and re.match(r"^#[0-9a-fA-F]{6}$", pal[r]) for r in ("ink", "paper")):
        return {r: (v.lower() if isinstance(v, str) else NEUTRAL[r]) for r, v in pal.items()}, False
    return dict(NEUTRAL), True


_FONT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}$")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def font_name(name: Any) -> Optional[str]:
    """A family name safe to place in CSS (letters, digits, space, dot, dash, underscore); anything else is not styled."""
    return name.strip() if isinstance(name, str) and _FONT_NAME.match(name.strip()) else None


def _stack(name: Any, generic: str) -> str:
    safe = font_name(name)
    return f"'{safe}', {generic}" if safe else generic


def css(fields: dict[str, Any], width: int, height: int) -> str:
    pal, _ = palette_for(fields)
    display = _stack(fields.get("visual.typography.display"), "sans-serif")
    body = _stack(fields.get("visual.typography.body"), "sans-serif")
    return (
        f"@page{{size:{width}px {height}px;margin:0}}"
        f"html,body{{margin:0;background:#808080;}}"  # gutter between pages on screen; not printed
        f".page{{box-sizing:border-box;position:relative;width:{width}px;height:{height}px;margin:0 auto 24px;"
        f"padding:{HEAD}px {PAD}px {FOOT}px;background:{pal['paper']};color:{pal['ink']};font-family:{body};font-size:15px;"
        f"line-height:1.5;page-break-after:always;break-after:page}}"
        f".ph{{position:absolute;top:20px;left:{PAD}px;right:{PAD}px;display:flex;gap:12px;font-size:12px;letter-spacing:.04em}}"
        f".pf{{position:absolute;bottom:14px;left:{PAD}px;right:{PAD}px;display:flex;justify-content:space-between;font-size:11px}}"
        f".body{{position:relative;height:100%;display:flex;flex-direction:column;gap:10px}}"
        f"h1,.title{{font-family:{display};font-size:48px;line-height:1.1;margin:0}}"
        f".subtitle{{font-family:{display};font-size:26px;margin:0}}.meta{{font-size:13px;margin:0}}"
        f".lbl{{font-size:12px;font-weight:700;margin:6px 0 0}}.item{{margin:0 0 0 16px}}.text{{margin:0}}"
        f".note{{font-size:12px;margin:0}}.status,.gap{{font-size:13px;margin:0;padding:4px 8px;border:1px solid {pal['ink']}}}"
        f".gap{{border-style:dashed}}.deco{{height:6px;width:96px;background:{pal['accent']}}}"
        f".group{{display:flex;flex-wrap:wrap;gap:16px;align-items:flex-end}}"
        f".fig{{display:flex;flex-direction:column;gap:4px;font-size:12px}}"
        f".sw{{width:120px;font-size:12px}}.sw div{{height:72px;border:1px solid {pal['ink']}}}"
        f"table{{border-collapse:collapse;font-size:12px;width:100%}}th,td{{border:1px solid {pal['ink']};padding:3px 6px;"
        f"text-align:left;vertical-align:top;overflow-wrap:anywhere}}"
        f".wm{{font-family:{display};font-size:44px;margin:0}}.spec{{font-size:34px;margin:0}}"
        f".reverse{{background:{pal['ink']};padding:12px}}.busy{{padding:12px;background:repeating-linear-gradient(45deg,"
        f"{pal['accent']} 0 8px,{pal['paper']} 8px 16px)}}"
        f".no-deco .deco{{display:none}}.no-optional .optional{{display:none}}"
        f"@media print{{html,body{{background:none}}.page{{margin:0}}}}"
    )


# --------------------------------------------------------------------------- estimation and pagination


def _lines(text: str, size: float, width: float) -> int:
    return max(1, math.ceil(len(text) * size * 0.56 / max(width, 1)))


def estimate(block: dict[str, Any], width: float) -> float:
    t = block["t"]
    if t == "copy":
        size = {"title": 48, "subtitle": 26, "wordmark": 44, "meta": 13}.get(block["role"], 15)
        return _lines(block["text"], size, width - (16 if block["role"] == "item" else 0)) * size * 1.5 + 4
    if t in ("note", "status", "gap", "asset_meta", "asset_missing", "handoff", "example"):
        return _lines(block["text"], 13, width) * 20 + 12
    if t == "label":
        return 26
    if t == "deco":
        return 16
    if t == "table":
        cols = max(1, len(block["columns"]))
        cell = width / cols
        rows = [max(_lines(str(c), 12, cell - 12) for c in row) * 18 + 8 for row in block["rows"]]
        return 26 + sum(rows)
    if t == "legend":
        return 22 * len(block["items"])
    if t == "lockup":
        return 140
    if t == "specimen":
        return 60
    return 0.0


def _group_key(block: dict[str, Any]) -> Optional[str]:
    return block["t"] if block["t"] in ("asset", "swatch", "misuse") else None


def _units(blocks: tuple[dict[str, Any], ...], width: float) -> list[tuple[list[dict[str, Any]], float]]:
    """Blocks grouped into layout units: a run of figures is one wrapping row group."""
    units: list[tuple[list[dict[str, Any]], float]] = []
    i = 0
    while i < len(blocks):
        key = _group_key(blocks[i])
        if key is None:
            units.append(([blocks[i]], estimate(blocks[i], width)))
            i += 1
            continue
        run = []
        while i < len(blocks) and _group_key(blocks[i]) == key:
            run.append(blocks[i])
            i += 1
        if key == "asset":
            row_w, row_h, height = 0.0, 0.0, 0.0
            for b in run:
                w = b["size"] + 16
                if row_w + w > width and row_w:
                    height += row_h + 16
                    row_w, row_h = 0.0, 0.0
                row_w += w
                row_h = max(row_h, b["size"] + 24 + (24 if b["variant"] in ("clearspace", "reverse") else 0))
            height += row_h
        else:
            per = max(1, int(width // (136 if key == "swatch" else 196)))
            height = math.ceil(len(run) / per) * (124 if key == "swatch" else 196)
        units.append((run, height))
    return units


def paginate(page: PagePackage, width: int, height: int, *, capacity: float = 1.0) -> list[list[dict[str, Any]]]:
    """Split a page's blocks into parts whose estimated height fits; tables split by rows. Nothing is dropped."""
    avail = (height - HEAD - FOOT) * capacity
    inner = width - 2 * PAD
    parts: list[list[dict[str, Any]]] = [[]]
    used = 0.0
    for unit, h in _units(page.blocks, inner):
        if len(unit) == 1 and unit[0]["t"] == "table" and h > avail - used:
            table = unit[0]
            rows = list(table["rows"])
            while rows:
                chunk: list[list[str]] = []
                while rows:
                    trial = {**table, "rows": chunk + [rows[0]]}
                    if chunk and estimate(trial, inner) > avail - used:
                        break
                    chunk.append(rows.pop(0))
                parts[-1].append({**table, "rows": chunk})
                used += estimate({**table, "rows": chunk}, inner) + 10
                if rows:
                    parts.append([])
                    used = 0.0
            continue
        if used + h > avail and parts[-1]:
            parts.append([])
            used = 0.0
        parts[-1].extend(unit)
        used += h + 10
    return parts


# --------------------------------------------------------------------------- HTML


def _img(mark: MarkAsset, size: int, *, alt: str, style: str = "", attrs: str = "") -> str:
    return (f'<img class="mark" data-sha="{mark.sha256}" src="{mark.data_uri}" width="{size}" height="{size}" '
            f'alt="{escape(alt, quote=True)}" style="{style}"{attrs}>')


_MISUSE_STYLE = {"stretch": "transform:scaleX(1.5) scaleY(.7);margin:0 28px", "rotate": "transform:rotate(18deg)",
                 "recolor": "filter:hue-rotate(140deg) saturate(3)", "effect": "filter:drop-shadow(6px 6px 4px rgba(0,0,0,.6)) blur(.6px)",
                 "busy": "", "crowd": ""}


def _clearspace(value: Any) -> Optional[str]:
    """A CSS padding for the approved clear space, only when the value is a number of px or of mark heights."""
    if not isinstance(value, str):
        return None
    m = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*px\s*", value)
    if m:
        return f"{float(m.group(1)):g}px"
    m = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*[x×]\s*(?:the\s+)?mark\s+height\s*", value, re.I)
    if m:
        return f"calc({float(m.group(1)):g} * var(--mh))"
    return None


def block_html(b: dict[str, Any], mark: MarkAsset, brand_name: str, fields: dict[str, Any]) -> str:
    t = b["t"]
    if t == "copy":
        cls = {"title": "title", "subtitle": "subtitle", "meta": "meta", "item": "item", "wordmark": "wm", "caption": "note"}.get(b["role"], "text")
        tag = "h1" if b["role"] == "title" else "p"
        flag = ' data-proposed="true"' if b["proposed"] else ""
        return f'<{tag} class="{cls}" data-copy="{b["copy_id"]}"{flag}>{escape(b["text"])}</{tag}>'
    if t == "label":
        return f'<p class="lbl">{escape(b["text"])}</p>'
    if t == "note":
        return f'<p class="note{" optional" if b["optional"] else ""}">{escape(b["text"])}</p>'
    if t in ("status", "asset_meta", "handoff", "asset_missing"):
        return f'<p class="status" data-status="{escape(b.get("status", t))}">{escape(b["text"])}</p>'
    if t == "gap":
        return f'<p class="gap" data-gap="{escape(b["path"])}">{escape(b["text"])}</p>'
    if t == "example":
        return f'<p class="status" data-example="{escape(b["kind"])}">{escape(b["text"])}</p>'
    if t == "deco":
        return '<div class="deco" aria-hidden="true"></div>'
    if t == "wordmark":
        return ""  # its copy block carries the text
    if t == "legend":
        return "<dl>" + "".join(f"<dt>{escape(k)}</dt><dd>{escape(v)}</dd>" for k, v in b["items"]) + "</dl>"
    if t == "table":
        head = "".join(f"<th scope='col'>{escape(c)}</th>" for c in b["columns"])
        rows = "".join("<tr>" + "".join(f"<td>{escape(str(c))}</td>" for c in row) + "</tr>" for row in b["rows"])
        return f"<table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>"
    if t == "specimen":
        safe = font_name(b["family"])
        style = f' style="font-family:\'{safe}\', sans-serif"' if safe else ""
        return (f'<div class="fig"><p class="spec"{style}>Aa Bb Cc 0123456789 &amp; ?!</p>'
                f'<span>{escape(b["role"])}: {escape(b["family"])}{"" if b["approved"] else " (proposed)"}</span></div>')
    if t == "swatch":
        if not _HEX.match(b["value"]):
            return f'<p class="status" data-status="INVALID">{escape(b["role"])}: {escape(b["value"])} is not a #rrggbb colour</p>'
        return (f'<div class="sw"><div style="background:{b["value"]}"></div><b>{escape(b["role"])}</b> '
                f'<span>{escape(b["value"])}</span>{"" if b["approved"] else " (proposed)"}</div>')
    if t == "lockup":
        word = escape(str(fields.get("visual.logo.wordmark") or brand_name))
        if mark.data_uri is None:
            return '<p class="status" data-status="MISSING">Lockup not drawn: no approved master.</p>'
        flow = "row" if b["arrangement"] == "horizontal" else "column"
        return (f'<div class="fig" style="flex-direction:{flow};align-items:center;gap:16px">'
                f'{_img(mark, 96, alt=b["arrangement"] + " lockup mark")}<span class="wm" style="font-size:32px">{word}</span>'
                f'<span class="note">{escape(b["arrangement"])} lockup</span></div>')
    if t == "asset":
        if mark.data_uri is None:
            return '<p class="status" data-status="MISSING">Master mark not approved.</p>'
        size, variant = int(b["size"]), b["variant"]
        cap = escape(b.get("caption") or "")
        if variant == "silhouette":
            inner = _img(mark, size, alt="one-colour silhouette of the master", style="filter:brightness(0)")
        elif variant == "reverse":
            inner = f'<div class="reverse">{_img(mark, size, alt="reverse silhouette of the master", style="filter:brightness(0) invert(1)")}</div>'
        elif variant == "construction":
            inner = (f'<div style="position:relative;width:{size}px;height:{size}px;outline:1px dashed currentColor">'
                     f'{_img(mark, size, alt="master with canvas boundary and centre axes")}'
                     f'<div style="position:absolute;left:50%;top:0;bottom:0;border-left:1px dotted currentColor"></div>'
                     f'<div style="position:absolute;top:50%;left:0;right:0;border-top:1px dotted currentColor"></div></div>')
        elif variant == "clearspace":
            pad = _clearspace(fields.get("visual.logo.clear_space"))
            if pad is None:
                inner = _img(mark, size, alt="master mark") + '<span class="note">Clear-space diagram not drawn: the approved rule is not a number of px or mark heights.</span>'
            else:
                inner = (f'<div style="--mh:{size}px;padding:{pad};outline:1px dashed currentColor;display:inline-block">'
                         f'{_img(mark, size, alt="master with approved clear space")}</div>')
        else:
            inner = _img(mark, size, alt="master mark" + ((" at " + cap) if cap else ""))
        return f'<figure class="fig" style="margin:0">{inner}<figcaption>{cap}</figcaption></figure>'
    if t == "misuse":
        style = _MISUSE_STYLE[b["transform"]]
        img = _img(mark, 96, alt="incorrect use: " + b["transform"], style=style, attrs=' data-misuse="true"')
        if b["transform"] == "busy":
            img = f'<div class="busy">{img}</div>'
        if b["transform"] == "crowd":
            img = f'<div style="position:relative">{img}<span style="position:absolute;left:24px;right:0;top:28px;font-size:14px;line-height:1.2">{escape(brand_name)}</span></div>'
        return (f'<figure class="fig" data-misuse-figure="{b["transform"]}" style="margin:0;width:180px">{img}'
                f'<figcaption data-copy="{b["copy_id"]}">{escape(b["text"])}</figcaption></figure>')
    return ""


def _body(blocks: list[dict[str, Any]], mark: MarkAsset, brand_name: str, fields: dict[str, Any]) -> str:
    out, i = [], 0
    while i < len(blocks):
        key = _group_key(blocks[i])
        if key is None:
            out.append(block_html(blocks[i], mark, brand_name, fields))
            i += 1
            continue
        run = []
        while i < len(blocks) and _group_key(blocks[i]) == key:
            run.append(block_html(blocks[i], mark, brand_name, fields))
            i += 1
        out.append(f'<div class="group" data-group="{key}">{"".join(run)}</div>')
    return "".join(out)


def page_html(page: PagePackage, *, mark: MarkAsset, brand_name: str, fields: dict[str, Any], width: int, height: int,
              total: int, step: int = 0, capacity: float = 1.0) -> list[tuple[str, str]]:
    """[(part_key, section_html)] for one page. ``step`` 1 hides decoration, 2 also optional annotations."""
    parts = paginate(page, width, height, capacity=capacity)
    out = []
    classes = "page" + (" no-deco" if step >= 1 else "") + (" no-optional" if step >= 2 else "")
    for n, blocks in enumerate(parts, start=1):
        key = page.page_id if n == 1 else f"{page.page_id}-{n}"
        cont = f" (continued {n}/{len(parts)})" if len(parts) > 1 else ""
        out.append((key, f'<section class="{classes}" data-page="{key}" data-order="{page.order}" data-status="{page.status}">'
                         f'<header class="ph"><span>{page.order:02d}</span><span>{escape(page.title)}{cont}</span></header>'
                         f'<div class="body">{_body(blocks, mark, brand_name, fields)}</div>'
                         f'<footer class="pf"><span>{escape(brand_name)}</span><span>Page {page.order:02d} of {total:02d}{cont}</span>'
                         f'<span>Status: {escape(page.status)}</span></footer></section>'))
    return out


def book_html(sections: list[str], *, title: str, style: str) -> str:
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>{escape(title)}</title>"
            f"<style>{style}</style></head><body>{''.join(sections)}</body></html>")


def page_key_hash(section: str, style: str) -> str:
    return canonical_hash({"renderer": RENDERER_VERSION, "section": section, "style": style})


__all__ = ["DEFAULT_FORMAT", "MIN_FONT_PX", "PAGE_FORMATS", "RENDERER_VERSION", "book_html", "css", "estimate", "page_format",
           "page_html", "page_key_hash", "paginate", "palette_for", "style_values"]
