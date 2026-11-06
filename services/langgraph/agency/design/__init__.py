"""Reusable design-style library: catalog, compatibility, composition, prompts.

Styles combine *by dimension* (layout, lighting, typography, ...), never by
concatenating whole prompts. The package compiles text only; it never invokes a
media provider or writes an asset.
"""

from __future__ import annotations

from .compatibility import analyze_style_compatibility
from .prompt_compiler import compile_design_prompt, compile_negative_prompt
from .style_composer import (
    ComposedStyle,
    DesignStyleDirection,
    DesignStyleSelection,
    InvalidSelectionError,
    StyleSelection,
    compose_style_selection,
    direction_from_selection,
)
from .style_registry import (
    STYLE_DIMENSIONS,
    StyleDefinition,
    StyleLibrary,
    UnknownStyleError,
    get_style,
    load_style_library,
    load_style_registry,
    pending_references,
    style_catalog_snapshot,
)

__all__ = [
    "STYLE_DIMENSIONS",
    "ComposedStyle",
    "DesignStyleDirection",
    "DesignStyleSelection",
    "InvalidSelectionError",
    "StyleDefinition",
    "StyleLibrary",
    "StyleSelection",
    "UnknownStyleError",
    "analyze_style_compatibility",
    "compile_design_prompt",
    "compile_negative_prompt",
    "compose_style_selection",
    "direction_from_selection",
    "get_style",
    "load_style_library",
    "load_style_registry",
    "pending_references",
    "style_catalog_snapshot",
]
