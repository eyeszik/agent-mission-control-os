"""Font discovery.

FreeVideoForge ships no font files. It finds one of the free faces that are
already on almost every Linux, macOS and Windows box, and degrades to Pillow's
built-in bitmap face if it genuinely finds nothing - so a render never fails
because of typography.
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

from PIL import ImageFont

#: Preferred faces per role, best first. All are libre fonts.
FACE_CANDIDATES: dict[str, tuple[str, ...]] = {
    "display_bold": (
        "DejaVuSerif-Bold.ttf", "LiberationSerif-Bold.ttf", "NotoSerif-Bold.ttf",
        "FreeSerifBold.ttf", "Georgia Bold.ttf", "Georgia.ttf",
        "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "arialbd.ttf",
    ),
    "sans_bold": (
        "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "NotoSans-Bold.ttf",
        "FreeSansBold.ttf", "Helvetica.ttc", "arialbd.ttf", "Arial Bold.ttf",
    ),
    "sans_regular": (
        "DejaVuSans.ttf", "LiberationSans-Regular.ttf", "NotoSans-Regular.ttf",
        "FreeSans.ttf", "Helvetica.ttc", "arial.ttf", "Arial.ttf",
    ),
    "mono": (
        "DejaVuSansMono.ttf", "LiberationMono-Regular.ttf", "NotoSansMono-Regular.ttf",
        "FreeMono.ttf", "Menlo.ttc", "consola.ttf",
    ),
}

_DEFAULT_DIRS: tuple[str, ...] = (
    "/usr/share/fonts",
    "/usr/local/share/fonts",
    "/usr/share/fonts/truetype",
    str(Path.home() / ".fonts"),
    str(Path.home() / ".local/share/fonts"),
    "/Library/Fonts",
    "/System/Library/Fonts",
    str(Path.home() / "Library/Fonts"),
    "C:\\Windows\\Fonts",
)


def search_dirs(extra: Iterable[str] = ()) -> list[Path]:
    dirs: list[Path] = []
    env = os.environ.get("FVF_FONT_DIRS", "")
    for raw in [*extra, *(p for p in env.split(os.pathsep) if p), *_DEFAULT_DIRS]:
        path = Path(raw)
        if path.is_dir() and path not in dirs:
            dirs.append(path)
    return dirs


@lru_cache(maxsize=8)
def _index(extra_key: tuple[str, ...] = ()) -> dict[str, str]:
    """Map lowercase font filename -> absolute path, once per process."""
    table: dict[str, str] = {}
    for directory in search_dirs(extra_key):
        try:
            for path in directory.rglob("*"):
                if path.suffix.lower() in {".ttf", ".otf", ".ttc"} and path.is_file():
                    table.setdefault(path.name.lower(), str(path))
        except (OSError, PermissionError):
            continue
    return table


def find_face(role: str, extra_dirs: tuple[str, ...] = ()) -> Optional[str]:
    """Return a font file path for ``role``, or None if nothing was found."""
    table = _index(tuple(extra_dirs))
    for candidate in FACE_CANDIDATES.get(role, ()):
        hit = table.get(candidate.lower())
        if hit:
            return hit
    # Last resort within the role: any face whose name hints at the right shape.
    hint = {"display_bold": "serif", "sans_bold": "sans", "sans_regular": "sans",
            "mono": "mono"}.get(role, "")
    if hint:
        for name, path in sorted(table.items()):
            if hint in name and "bold" in name and role.endswith("bold"):
                return path
    return next(iter(sorted(table.values())), None)


class FontBook:
    """Cached, size-indexed font loader.

    Loading a TrueType face is expensive relative to a frame, so every
    (role, size) pair is loaded once and reused for the whole render.
    """

    def __init__(self, extra_dirs: Iterable[str] = ()) -> None:
        self.extra_dirs = tuple(extra_dirs)
        self._paths: dict[str, Optional[str]] = {}
        self._cache: dict[tuple[str, int], ImageFont.ImageFont] = {}
        self.degraded = False

    def path(self, role: str) -> Optional[str]:
        if role not in self._paths:
            self._paths[role] = find_face(role, self.extra_dirs)
        return self._paths[role]

    def get(self, role: str, size: int) -> ImageFont.ImageFont:
        size = max(6, int(size))
        key = (role, size)
        if key in self._cache:
            return self._cache[key]
        path = self.path(role)
        font: ImageFont.ImageFont
        if path:
            try:
                font = ImageFont.truetype(path, size)
            except (OSError, ValueError):
                self.degraded = True
                font = self._default(size)
        else:
            self.degraded = True
            font = self._default(size)
        self._cache[key] = font
        return font

    @staticmethod
    def _default(size: int) -> ImageFont.ImageFont:
        try:
            return ImageFont.load_default(size=size)  # Pillow >= 10.1
        except TypeError:  # pragma: no cover - very old Pillow
            return ImageFont.load_default()

    def report(self) -> dict[str, Optional[str]]:
        return {role: self.path(role) for role in FACE_CANDIDATES}
