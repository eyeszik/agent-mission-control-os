"""UI/UX adapter: headless DOM validation and a design-system spec.

"Headless" here means the DOM is parsed and checked without a browser (stdlib
``html.parser``): WCAG 2.2 contrast for inline colour pairs, viewport and
language declarations, image alternatives, declared target sizes and
fixed-width layout. It does not lay out or render pages; checks that need
computed styles (cascade, media queries) are reported as not verified rather
than passed.

Contrast uses ``agency.ui_ux.tokens.wcag_contrast_ratio`` (WCAG 2.2 is
normative; APCA is not consulted).
"""

from __future__ import annotations

import json
import re
from typing import Any

from services.langgraph.agency.ui_ux.tokens import wcag_contrast_ratio

from ..capsules import BrandContextCapsule
from ..verifiers import Verdict, parse_dom

AA_NORMAL = 4.5
TARGET_MIN_PX = 24  # WCAG 2.2 SC 2.5.8 Target Size (Minimum)
MAX_FIXED_WIDTH_PX = 360
_STYLE = re.compile(r"\s*([a-z-]+)\s*:\s*([^;]+)")
_PX = re.compile(r"^(\d+(?:\.\d+)?)px$")
_HEX6 = re.compile(r"^#[0-9a-fA-F]{6}$")


def _styles(attrs: dict[str, str]) -> dict[str, str]:
    return {m.group(1).lower(): m.group(2).strip() for m in _STYLE.finditer(attrs.get("style", ""))}


def dom_audit(html: str) -> dict[str, Any]:
    dom = parse_dom(html)
    findings: list[dict[str, str]] = []
    not_verified = ["computed-style cascade", "media-query reflow", "focus order", "keyboard operability"]

    html_el = next((a for t, a in dom.elements if t == "html"), None)
    if html_el is None or not html_el.get("lang"):
        findings.append({"rule": "html-lang", "severity": "error", "detail": "<html> lacks a lang attribute (SC 3.1.1)"})
    viewport = [a for t, a in dom.elements if t == "meta" and a.get("name", "").lower() == "viewport"]
    if not viewport or "width=device-width" not in viewport[0].get("content", "").replace(" ", ""):
        findings.append({"rule": "viewport", "severity": "error", "detail": "no responsive viewport meta"})

    pairs = []
    for tag, attrs, text in dom.text_by_tag:
        st = _styles(attrs)
        fg, bg = st.get("color"), st.get("background-color") or st.get("background")
        if fg and bg and _HEX6.match(fg) and _HEX6.match(bg) and text:
            ratio = wcag_contrast_ratio(fg, bg)
            pairs.append({"tag": tag, "fg": fg.lower(), "bg": bg.lower(), "ratio": ratio})
            if ratio < AA_NORMAL:
                findings.append({"rule": "contrast-aa", "severity": "error",
                                 "detail": f"<{tag}> {fg} on {bg} is {ratio}:1 (< {AA_NORMAL}:1, SC 1.4.3)"})
    for tag, attrs in dom.elements:
        st = _styles(attrs)
        if tag == "img" and "alt" not in attrs:
            findings.append({"rule": "img-alt", "severity": "error", "detail": "<img> without alt (SC 1.1.1)"})
        if tag in {"button", "a"}:
            for prop in ("min-height", "height"):
                m = _PX.match(st.get(prop, ""))
                if m and float(m.group(1)) < TARGET_MIN_PX:
                    findings.append({"rule": "target-size", "severity": "error",
                                     "detail": f"<{tag}> {prop} {m.group(1)}px < {TARGET_MIN_PX}px (SC 2.5.8)"})
        m = _PX.match(st.get("width", ""))
        if m and float(m.group(1)) > MAX_FIXED_WIDTH_PX:
            findings.append({"rule": "fixed-width", "severity": "error",
                             "detail": f"<{tag}> fixed width {m.group(1)}px breaks reflow at 320 CSS px (SC 1.4.10)"})
    return {
        "findings": sorted(findings, key=lambda f: (f["rule"], f["detail"])),
        "contrast_pairs": pairs,
        "not_verified": not_verified,
        "passed": not any(f["severity"] == "error" for f in findings),
    }


def _preview_html(capsule: BrandContextCapsule) -> str:
    p = capsule.palette
    return (
        f'<!doctype html><html lang="{capsule.locale}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{capsule.brand_name} design system preview</title></head>"
        f'<body style="color:{p["text"]};background-color:{p["surface"]}">'
        f'<main><h1 style="color:{p["text"]};background-color:{p["surface"]}">{capsule.brand_name}</h1>'
        f'<p style="color:{p["text"]};background-color:{p["surface"]}">Body copy on the surface colour.</p>'
        f'<button style="color:{p["surface"]};background-color:{p["primary"]};min-height:44px">Primary action</button>'
        f'<a href="#top" style="color:{p["primary"]};background-color:{p["surface"]};min-height:24px">Text link</a>'
        "</main></body></html>"
    )


def design_system_spec(payload: dict[str, Any]) -> dict[str, Any]:
    capsule = BrandContextCapsule.model_validate(payload["brand"])
    p = capsule.palette
    pairs = [
        {"usage": "body-text", "fg": p["text"], "bg": p["surface"]},
        {"usage": "primary-button", "fg": p["surface"], "bg": p["primary"]},
        {"usage": "text-link", "fg": p["primary"], "bg": p["surface"]},
    ]
    for pair in pairs:
        pair["ratio"] = wcag_contrast_ratio(pair["fg"], pair["bg"])
        pair["aa_normal_text"] = pair["ratio"] >= AA_NORMAL
    preview = _preview_html(capsule)
    spec = {
        "standard": "WCAG 2.2 (normative); APCA not consulted",
        "color_pairs": pairs,
        "typography": {"heading": capsule.heading_font, "body": capsule.body_font},
        "target_size_min_px": TARGET_MIN_PX,
        "preview_html": preview,
        "dom_audit": dom_audit(preview),
    }
    return {"content": json.dumps(spec, sort_keys=True, indent=2), "mime_type": "application/json", "subtype": "design_system_spec"}


def uiux_dom_audit(payload: dict[str, Any]) -> dict[str, Any]:
    html = payload.get("inputs", {}).get("html")
    if not isinstance(html, str) or not html.strip():
        raise ValueError("inputs.html is required")
    report = {"kind": "uiux_dom_audit", **dom_audit(html)}
    return {"content": json.dumps(report, sort_keys=True, indent=2), "mime_type": "application/json", "subtype": "uiux_audit"}


def validate_contrast(output: dict[str, Any], payload: dict[str, Any]) -> Verdict:
    spec = json.loads(output["content"])
    failing = [p["usage"] for p in spec.get("color_pairs", []) if not p.get("aa_normal_text")]
    if failing or not spec.get("dom_audit", {}).get("passed", False):
        return Verdict("wcag_contrast_aa", False, f"WCAG 2.2 AA failures: pairs={failing}, dom={spec.get('dom_audit', {}).get('findings')}")
    return Verdict("wcag_contrast_aa", True, "all declared colour pairs meet WCAG 2.2 AA (4.5:1) and the preview DOM audit passed")


def validate_report(output: dict[str, Any], payload: dict[str, Any]) -> Verdict:
    try:
        report = json.loads(output["content"])
    except ValueError:
        return Verdict("report_wellformed", False, "report is not JSON")
    ok = isinstance(report.get("findings"), list) and isinstance(report.get("passed"), bool)
    return Verdict("report_wellformed", ok, "report carries findings and a verdict" if ok else "report is missing findings/verdict")
