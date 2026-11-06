"""WCAG 2.2 contrast-ratio math -- the real formula, not an approximation.

Relative luminance and contrast ratio as defined by WCAG 2.x/2.2:
sRGB channel -> linear-light value -> luminance-weighted sum, then
contrast = (lighter + 0.05) / (darker + 0.05).

These utilities are for cases where WCAG contrast actually applies -- body
text, UI components, graphical objects (SC 1.4.11). They are deliberately
NOT wired into ``LogoLockup`` validation: WCAG 2.2 SC 1.4.11 explicitly
exempts logotypes ("Text that is part of a logo or brand name has no
minimum contrast requirement"), so enforcing a contrast floor on a logo
lockup would be citing a compliance requirement that does not exist.
"""

from __future__ import annotations

import re

HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _srgb_channel_to_linear(channel_255: int) -> float:
    c = channel_255 / 255.0
    if c <= 0.03928:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color: str) -> float:
    """WCAG relative luminance of a 6-digit hex color, in [0, 1]."""
    if not HEX_COLOR_RE.match(hex_color):
        raise ValueError(f"'{hex_color}' is not a 6-digit hex color (e.g. '#1a2b4c')")
    value = hex_color.lstrip("#")
    r, g, b = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    r_lin, g_lin, b_lin = (_srgb_channel_to_linear(channel) for channel in (r, g, b))
    return 0.2126 * r_lin + 0.7152 * g_lin + 0.0722 * b_lin


def contrast_ratio(hex_a: str, hex_b: str) -> float:
    """WCAG contrast ratio between two hex colors, in [1, 21]. Symmetric."""
    luminance_a = relative_luminance(hex_a)
    luminance_b = relative_luminance(hex_b)
    lighter, darker = max(luminance_a, luminance_b), min(luminance_a, luminance_b)
    return (lighter + 0.05) / (darker + 0.05)


def meets_wcag_aa(ratio: float, *, large_text: bool = False) -> bool:
    """SC 1.4.3: 4.5:1 for normal text, 3:1 for large text (>=18pt or >=14pt bold)."""
    return ratio >= (3.0 if large_text else 4.5)


def meets_wcag_non_text(ratio: float) -> bool:
    """SC 1.4.11: 3:1 for UI components and graphical objects (not logotypes)."""
    return ratio >= 3.0
