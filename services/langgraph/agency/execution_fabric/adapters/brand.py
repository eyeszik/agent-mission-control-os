"""Branding/design adapters: deterministic SVG marks and DTCG token sets.

Both reuse existing compilers instead of adding new ones: the SVG mark is
``agency.assets.render_logo_svg`` and tokens go through
``agency.design_tokens`` (the only DTCG compiler in the repository). Raster or
generative imagery (text-to-image) has no installed provider; that skill is
registered so it can be classified, and the fabric reports PROVIDER_GAP.
"""

from __future__ import annotations

import json
from typing import Any

from services.langgraph.agency.assets import render_logo_svg
from services.langgraph.agency.design_tokens import TokenError, compile_css, hex_to_color

from ..capsules import BrandContextCapsule
from ..verifiers import Verdict, palette_conformance, svg_safety


def _capsule(payload: dict[str, Any]) -> BrandContextCapsule:
    brand = payload.get("brand")
    if not isinstance(brand, dict):
        raise ValueError("payload['brand'] (a BrandContextCapsule) is required")
    return BrandContextCapsule.model_validate(brand)


def brand_logo_svg(payload: dict[str, Any]) -> dict[str, Any]:
    capsule = _capsule(payload)
    p = capsule.palette
    svg = render_logo_svg(brand_name=capsule.brand_name, primary=p["primary"], secondary=p["secondary"], surface=p["surface"])
    return {"content": svg, "mime_type": "image/svg+xml", "subtype": "logo_svg"}


def token_document(capsule: BrandContextCapsule) -> dict[str, Any]:
    """Tiered DTCG source: literal primitives, semantic aliases on top."""
    primitives = {role: {"$type": "color", "$value": hex_to_color(value)} for role, value in capsule.palette.items()}
    return {
        "primitive": {
            "color": primitives,
            "font": {
                "heading": {"$type": "fontFamily", "$value": [capsule.heading_font, "sans-serif"]},
                "body": {"$type": "fontFamily", "$value": [capsule.body_font, "sans-serif"]},
            },
        },
        "semantic": {
            "color": {
                "action": {"$type": "color", "$value": "{primitive.color.primary}"},
                "accent": {"$type": "color", "$value": "{primitive.color.secondary}"},
                "background": {"$type": "color", "$value": "{primitive.color.surface}"},
                "foreground": {"$type": "color", "$value": "{primitive.color.text}"},
            },
            "font": {
                "heading": {"$type": "fontFamily", "$value": "{primitive.font.heading}"},
                "body": {"$type": "fontFamily", "$value": "{primitive.font.body}"},
            },
        },
    }


def dtcg_token_compile(payload: dict[str, Any]) -> dict[str, Any]:
    capsule = _capsule(payload)
    document = token_document(capsule)
    graph, css = compile_css(document, prefix="brand", tiered=True, source_label=f"brand-capsule:{capsule.capsule_hash[:16]}")
    body = {"format": "DTCG 2025.10", "source_hash": graph.source_hash, "document": document, "css": css}
    return {"content": json.dumps(body, sort_keys=True, indent=2), "mime_type": "application/json", "subtype": "dtcg_token_set"}


def text_to_image(payload: dict[str, Any]) -> dict[str, Any]:  # pragma: no cover - never dispatched
    raise RuntimeError("no text-to-image provider is installed")


# ---------------------------------------------------------------- validators

def validate_svg(output: dict[str, Any], payload: dict[str, Any]) -> Verdict:
    return svg_safety(output["content"])


def validate_palette(output: dict[str, Any], payload: dict[str, Any]) -> Verdict:
    return palette_conformance(output["content"], _capsule(payload).palette.values())


def validate_dtcg(output: dict[str, Any], payload: dict[str, Any]) -> Verdict:
    """Recompile the emitted DTCG document; the CSS must reproduce byte for byte."""
    try:
        body = json.loads(output["content"])
        _, css = compile_css(body["document"], prefix="brand", tiered=True,
                             source_label=f"brand-capsule:{_capsule(payload).capsule_hash[:16]}")
    except (ValueError, KeyError, TokenError) as exc:
        return Verdict("dtcg_recompile", False, f"token document does not compile: {exc}")
    if css != body.get("css"):
        return Verdict("dtcg_recompile", False, "recompiled CSS differs from the emitted CSS")
    return Verdict("dtcg_recompile", True, "DTCG document recompiles to identical CSS")
