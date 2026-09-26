"""Derive a tiered DTCG token system for a UI spec and check its contrast.

Authority split (see docs/ui-ux-design-compiler.md):
* WCAG 2.2 is the normative accessibility target. Pass/fail uses its contrast
  ratio and nothing else.
* APCA Lc is computed as *advisory* perceptual analysis. It is reported beside
  the WCAG ratio, never substituted for it, never merged into one score.
* DTCG 2025.10 governs token structure only; compilation goes through the one
  repository compiler in agency/design_tokens.py.
"""

from __future__ import annotations

import re
from typing import Any

from services.langgraph.agency.design_tokens import compile_css, hex_to_color

from .models import (
    A11yVerification,
    BrandContext,
    ContrastCheck,
    DesignGenome,
    SourceKind,
    TokenSystemSpec,
    WCAGRequirement,
)

CSS_PREFIX = "ui"
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

_WCAG_THRESHOLDS = {
    WCAGRequirement.aaa_normal: 7.0,
    WCAGRequirement.aaa_large: 4.5,
    WCAGRequirement.aa_normal: 4.5,
    WCAGRequirement.aa_large: 3.0,
    WCAGRequirement.non_text: 3.0,
}

# Neutral ramp: the AMC Zinc baseline. Used for structure; brand color is layered
# on top as accent, never used for body text unless it passes WCAG.
_NEUTRAL = {
    "50": "#fafafa", "100": "#f4f4f5", "200": "#e4e4e7", "300": "#d4d4d8", "400": "#a1a1aa",
    "500": "#71717a", "600": "#52525b", "700": "#3f3f46", "800": "#27272a", "900": "#18181b",
    "950": "#09090b",
}
_STATUS = {
    "dark": {"success": "#34d399", "warning": "#fbbf24", "danger": "#f87171", "info": "#38bdf8"},
    "light": {"success": "#047857", "warning": "#b45309", "danger": "#b91c1c", "info": "#0369a1"},
}
_FALLBACK_ACCENT = {"dark": "#10b981", "light": "#047857"}
_SCHEME_ROLES = {
    "dark": {
        "background": "950", "surface": "900", "surface-raised": "800", "border": "800",
        "border-strong": "500", "foreground": "300", "foreground-strong": "50", "foreground-muted": "400",
    },
    "light": {
        "background": "50", "surface": "100", "surface-raised": "200", "border": "200",
        "border-strong": "500", "foreground": "700", "foreground-strong": "950", "foreground-muted": "600",
    },
}


# --------------------------------------------------------------------------- #
# Contrast math
# --------------------------------------------------------------------------- #


def _channels(hex_value: str) -> tuple[float, float, float]:
    h = hex_value.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def relative_luminance(hex_value: str) -> float:
    """WCAG 2.2 relative luminance (sRGB)."""

    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(c) for c in _channels(hex_value))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def wcag_contrast_ratio(foreground: str, background: str) -> float:
    a, b = relative_luminance(foreground), relative_luminance(background)
    lighter, darker = max(a, b), min(a, b)
    return round((lighter + 0.05) / (darker + 0.05), 2)


def apca_lc(text: str, background: str) -> float:
    """APCA-W3 0.0.98G-4g Lc. ADVISORY ONLY -- not a WCAG 2.2 conformance measure."""

    def y(hex_value: str) -> float:
        r, g, b = _channels(hex_value)
        value = 0.2126729 * r ** 2.4 + 0.7151522 * g ** 2.4 + 0.0721750 * b ** 2.4
        return value if value > 0.022 else value + (0.022 - value) ** 1.414

    txt, bg = y(text), y(background)
    if abs(bg - txt) < 0.0005:
        return 0.0
    if bg > txt:
        sapc = (bg ** 0.56 - txt ** 0.57) * 1.14
        out = 0.0 if sapc < 0.1 else sapc - 0.027
    else:
        sapc = (bg ** 0.65 - txt ** 0.62) * 1.14
        out = 0.0 if sapc > -0.1 else sapc + 0.027
    return round(out * 100, 1)


def contrast_check(fg_path: str, bg_path: str, fg: str, bg: str, requirement: WCAGRequirement) -> ContrastCheck:
    ratio = wcag_contrast_ratio(fg, bg)
    return ContrastCheck(
        foreground=fg_path,
        background=bg_path,
        foreground_value=fg,
        background_value=bg,
        wcag_requirement=requirement,
        wcag_ratio=ratio,
        passes=ratio >= _WCAG_THRESHOLDS[requirement],
        verification=A11yVerification.verified_static,
        apca_lc_advisory=apca_lc(fg, bg),
    )


# --------------------------------------------------------------------------- #
# Token document
# --------------------------------------------------------------------------- #


def _valid_palette(brand: BrandContext | None) -> list[str]:
    if brand is None:
        return []
    return [value.lower() for value in brand.palette_hex if isinstance(value, str) and _HEX.match(value)]


def choose_scheme(palette: list[str]) -> str:
    """Light when the brand declares a near-white surface color, otherwise dark."""
    if palette and max(relative_luminance(value) for value in palette) > 0.85:
        return "light"
    return "dark"


def _spacing(density: str) -> dict[str, int]:
    base = {"LOW": 6, "MEDIUM": 4, "HIGH": 3}[density]
    return {"1": base, "2": base * 2, "3": base * 3, "4": base * 4, "6": base * 6}


def build_token_document(
    brand: BrandContext | None,
    genome: DesignGenome,
    *,
    include_ai: bool,
    include_data: bool,
) -> tuple[dict[str, Any], str, list[str]]:
    """Return (dtcg_document, scheme, palette_notes)."""
    palette = _valid_palette(brand)
    scheme = choose_scheme(palette)
    roles = _SCHEME_ROLES[scheme]
    background = _NEUTRAL[roles["background"]]
    notes: list[str] = []

    accent_hex = next(
        (value for value in palette if wcag_contrast_ratio(value, background) >= 3.0), None
    )
    if accent_hex is None:
        accent_hex = _FALLBACK_ACCENT[scheme]
        notes.append(
            "No brand palette color reaches 3:1 non-text contrast against the background; "
            "baseline accent used pending design_token_set review."
            if palette else
            "Brand palette unresolved (no reference hex); baseline accent used as a placeholder."
        )
    on_accent = max(("#fafafa", "#09090b"), key=lambda value: wcag_contrast_ratio(value, accent_hex))

    def color(hex_value: str) -> dict[str, Any]:
        return {"$value": hex_to_color(hex_value)}

    primitive_color: dict[str, Any] = {
        "$type": "color",
        "neutral": {key: color(value) for key, value in _NEUTRAL.items()},
        "status": {key: color(value) for key, value in _STATUS[scheme].items()},
        "accent": {"base": color(accent_hex), "on": color(on_accent)},
    }
    if palette:
        primitive_color["brand"] = {str(index + 1): color(value) for index, value in enumerate(palette)}

    semantic_color: dict[str, Any] = {"$type": "color"}
    for role, step in roles.items():
        semantic_color[role] = {"$value": f"{{primitive.color.neutral.{step}}}"}
    semantic_color["accent"] = {"$value": "{primitive.color.accent.base}"}
    semantic_color["on-accent"] = {"$value": "{primitive.color.accent.on}"}
    semantic_color["focus-ring"] = {"$value": "{primitive.color.accent.base}"}
    semantic_color["status"] = {
        key: {"$value": f"{{primitive.color.status.{key}}}"} for key in _STATUS[scheme]
    }

    spacing = _spacing(genome.density)
    component: dict[str, Any] = {
        "button": {
            "primary": {
                "$type": "color",
                "background": {"$value": "{semantic.color.accent}"},
                "foreground": {"$value": "{semantic.color.on-accent}"},
            },
            "radius": {"$type": "dimension", "$value": "{semantic.radius.control}"},
        },
        "focus": {"$type": "color", "ring": {"$value": "{semantic.color.focus-ring}"}},
    }
    if include_ai:
        component["ai-trust"] = {
            "$type": "color",
            "border": {"$value": "{semantic.color.border-strong}"},
            "label": {"$value": "{semantic.color.foreground-strong}"},
            "degraded": {"$value": "{semantic.color.status.warning}"},
            "unavailable": {"$value": "{semantic.color.status.danger}"},
        }
    if include_data:
        component["metric"] = {
            "$type": "color",
            "value": {"$value": "{semantic.color.foreground-strong}"},
            "truth-label": {"$value": "{semantic.color.foreground}"},
        }

    document: dict[str, Any] = {
        "primitive": {
            "color": primitive_color,
            "space": {
                "$type": "dimension",
                **{key: {"$value": {"value": value, "unit": "px"}} for key, value in spacing.items()},
            },
            "radius": {
                "$type": "dimension",
                "sm": {"$value": {"value": 4, "unit": "px"}},
                "md": {"$value": {"value": 6, "unit": "px"}},
                "lg": {"$value": {"value": 10, "unit": "px"}},
            },
            "duration": {
                "$type": "duration",
                "fast": {"$value": {"value": 120, "unit": "ms"}},
                "base": {"$value": {"value": 200, "unit": "ms"}},
            },
        },
        "semantic": {
            "color": semantic_color,
            "space": {
                "$type": "dimension",
                "inline": {"$value": "{primitive.space.2}"},
                "stack": {"$value": "{primitive.space.3}"},
                "panel": {"$value": "{primitive.space.4}"},
                "section": {"$value": "{primitive.space.6}"},
            },
            "radius": {
                "$type": "dimension",
                "control": {"$value": "{primitive.radius.md}"},
                "panel": {"$value": "{primitive.radius.lg}"},
            },
            "motion": {"$type": "duration", "feedback": {"$value": "{primitive.duration.fast}"}},
        },
        "component": component,
    }
    return document, scheme, notes


_CONTRAST_PAIRS = (
    ("semantic.color.foreground", "semantic.color.background", WCAGRequirement.aaa_normal),
    ("semantic.color.foreground-strong", "semantic.color.background", WCAGRequirement.aaa_normal),
    ("semantic.color.foreground", "semantic.color.surface", WCAGRequirement.aa_normal),
    ("semantic.color.foreground-muted", "semantic.color.background", WCAGRequirement.aa_normal),
    ("semantic.color.on-accent", "semantic.color.accent", WCAGRequirement.aa_normal),
    ("semantic.color.focus-ring", "semantic.color.background", WCAGRequirement.non_text),
    ("semantic.color.border-strong", "semantic.color.background", WCAGRequirement.non_text),
    ("semantic.color.status.warning", "semantic.color.surface", WCAGRequirement.aa_normal),
    ("semantic.color.status.danger", "semantic.color.surface", WCAGRequirement.aa_normal),
)


def compile_token_system(
    brand: BrandContext | None,
    genome: DesignGenome,
    *,
    include_ai: bool,
    include_data: bool,
) -> TokenSystemSpec:
    document, scheme, notes = build_token_document(
        brand, genome, include_ai=include_ai, include_data=include_data
    )
    graph, css = compile_css(document, prefix=CSS_PREFIX, tiered=True, source_label="uiux-compiler")
    values = {path: token.css for path, token in graph.tokens.items()}
    contrast = [
        contrast_check(fg, bg, values[fg], values[bg], requirement)
        for fg, bg, requirement in _CONTRAST_PAIRS
    ]
    palette = _valid_palette(brand)
    if palette:
        source = brand.palette_source.value if brand else SourceKind.compiler_default.value
        resolution = f"{scheme} scheme; accent from {source} palette ({len(palette)} valid color(s))"
    else:
        resolution = f"{scheme} scheme; brand palette UNRESOLVED -- structural tokens only"
    if notes:
        resolution += "; " + " ".join(notes)
    return TokenSystemSpec(
        css_prefix=CSS_PREFIX,
        document=document,
        source_hash=graph.source_hash,
        token_count=len(graph.tokens),
        css=css,
        contrast=contrast,
        palette_resolution=resolution,
    )
