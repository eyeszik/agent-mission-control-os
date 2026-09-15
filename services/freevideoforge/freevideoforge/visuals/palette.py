"""Colour helpers.

Everything is plain tuples so the renderer never depends on a colour library.
"""

from __future__ import annotations

RGB = tuple[int, int, int]
RGBA = tuple[int, int, int, int]


def hex_to_rgb(value: str) -> RGB:
    text = value.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        raise ValueError(f"Not a hex colour: {value!r}")
    return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))


def rgba(colour: RGB | str, alpha: int = 255) -> RGBA:
    base = hex_to_rgb(colour) if isinstance(colour, str) else colour
    return (base[0], base[1], base[2], max(0, min(255, int(alpha))))


def lerp(a: RGB, b: RGB, t: float) -> RGB:
    t = max(0.0, min(1.0, t))
    return (
        int(round(a[0] + (b[0] - a[0]) * t)),
        int(round(a[1] + (b[1] - a[1]) * t)),
        int(round(a[2] + (b[2] - a[2]) * t)),
    )


def mix(colour: RGB, other: RGB, amount: float) -> RGB:
    return lerp(colour, other, amount)


def relative_luminance(colour: RGB) -> float:
    """WCAG relative luminance, used to pick legible ink automatically."""

    def channel(value: int) -> float:
        srgb = value / 255.0
        return srgb / 12.92 if srgb <= 0.04045 else ((srgb + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in colour)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: RGB, b: RGB) -> float:
    la, lb = relative_luminance(a), relative_luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def readable_ink(background: RGB, candidates: list[RGB]) -> RGB:
    """Pick the candidate with the best contrast against ``background``.

    This is what keeps captions legible after a palette change, instead of
    hardcoding white text and hoping.
    """
    pool = candidates or [(255, 255, 255), (0, 0, 0)]
    return max(pool, key=lambda c: contrast_ratio(c, background))


class Palette:
    """A resolved five-role palette: two background stops, accent, ink, muted."""

    __slots__ = ("bg_a", "bg_b", "accent", "ink", "muted", "raw")

    def __init__(self, colours: list[str]) -> None:
        if len(colours) < 5:
            raise ValueError("A palette needs 5 colours: bg_a, bg_b, accent, ink, muted")
        self.raw = list(colours[:5])
        self.bg_a = hex_to_rgb(colours[0])
        self.bg_b = hex_to_rgb(colours[1])
        self.accent = hex_to_rgb(colours[2])
        self.ink = hex_to_rgb(colours[3])
        self.muted = hex_to_rgb(colours[4])

    @property
    def is_dark(self) -> bool:
        return relative_luminance(self.bg_a) < 0.35

    @property
    def caption_ink(self) -> RGB:
        return readable_ink(self.caption_plate, [self.ink, (255, 255, 255), (12, 14, 20)])

    @property
    def caption_plate(self) -> RGB:
        """Background plate behind burned-in captions."""
        return mix(self.bg_a, (0, 0, 0) if self.is_dark else (255, 255, 255), 0.55)

    def as_dict(self) -> dict[str, str]:
        return dict(
            zip(("bg_a", "bg_b", "accent", "ink", "muted"), self.raw)
        )
