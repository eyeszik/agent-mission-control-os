"""Load, validate, and query the canonical design-style catalog.

The catalog at ``packages/shared/style-library/design-styles.json`` is the single
source of truth; these models mirror ``packages/shared/src/schemas/styleLibrary.ts``.
References to styles that are not yet in the catalog are allowed (they name
styles still awaiting migration) but must be well-formed ids, and are reported
by :func:`pending_references` rather than silently resolved.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

STYLE_LIBRARY_VERSION = "style-library-v1"

CATALOG_PATH = (
    Path(__file__).resolve().parents[4] / "packages/shared/style-library/design-styles.json"
)

STYLE_DIMENSIONS: tuple[str, ...] = (
    "layout",
    "typography",
    "palette",
    "lighting",
    "texture",
    "surface",
    "composition",
    "motion",
    "imagery",
    "geometry",
    "depth",
    "material",
)

STYLE_CATEGORIES: tuple[str, ...] = (
    "classical",
    "modernist",
    "experimental",
    "cyber",
    "lifestyle",
    "editorial",
    "illustrative",
    "material",
    "interface",
    "motion",
)

STYLE_ID_PATTERN = re.compile(r"^[A-Z]{3}-\d{2}$")

StyleDimension = Literal[
    "layout",
    "typography",
    "palette",
    "lighting",
    "texture",
    "surface",
    "composition",
    "motion",
    "imagery",
    "geometry",
    "depth",
    "material",
]


def _check_id(value: str) -> str:
    if not STYLE_ID_PATTERN.match(value):
        raise ValueError(f"style id must look like ABC-01, got {value!r}")
    return value


class StylePhysics(BaseModel):
    lighting: list[str] = Field(default_factory=list)
    spatial: list[str] = Field(default_factory=list)
    material: list[str] = Field(default_factory=list)
    composition: list[str] = Field(default_factory=list)
    motion: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class StylePalette(BaseModel):
    colors: list[str] = Field(min_length=1)
    semantic_roles: dict[str, str] = Field(default_factory=dict)
    contrast_notes: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class StyleTypography(BaseModel):
    families: list[str] = Field(default_factory=list)
    category: str
    weights: list[str] = Field(default_factory=list)
    tracking: str | None = None
    hierarchy: str | None = None

    model_config = {"extra": "forbid"}


class StyleDefinition(BaseModel):
    id: str
    name: str = Field(min_length=1)
    category: Literal[
        "classical",
        "modernist",
        "experimental",
        "cyber",
        "lifestyle",
        "editorial",
        "illustrative",
        "material",
        "interface",
        "motion",
    ]
    description: str = Field(min_length=1)
    design_dimensions: list[StyleDimension] = Field(min_length=1)
    physics: StylePhysics
    palette: StylePalette
    typography: StyleTypography
    prompt_tokens: list[str] = Field(min_length=1)
    negative_tokens: list[str] = Field(default_factory=list)
    compatible_with: list[str] = Field(default_factory=list)
    incompatible_with: list[str] = Field(default_factory=list)
    recommended_strength: float = Field(ge=0.0, le=1.0)
    suitable_for: list[str] = Field(default_factory=list)
    unsuitable_for: list[str] = Field(default_factory=list)
    motion_behavior: list[str] = Field(default_factory=list)
    production_notes: list[str] = Field(default_factory=list)
    source_version: str = Field(min_length=1)
    status: Literal["active", "experimental", "deprecated", "disabled"]

    model_config = {"extra": "forbid"}

    @field_validator("id")
    @classmethod
    def _valid_id(cls, value: str) -> str:
        return _check_id(value)

    @field_validator("compatible_with", "incompatible_with")
    @classmethod
    def _valid_refs(cls, values: list[str]) -> list[str]:
        return [_check_id(value) for value in values]

    @model_validator(mode="after")
    def _consistent_relations(self) -> "StyleDefinition":
        overlap = sorted(set(self.compatible_with) & set(self.incompatible_with))
        if overlap:
            raise ValueError(f"{self.id} is both compatible and incompatible with {overlap}")
        if self.id in self.compatible_with or self.id in self.incompatible_with:
            raise ValueError(f"{self.id} references itself")
        return self


class StyleLibrary(BaseModel):
    version: str = Field(min_length=1)
    styles: list[StyleDefinition] = Field(min_length=1)

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _unique_ids(self) -> "StyleLibrary":
        seen: set[str] = set()
        duplicates: set[str] = set()
        for style in self.styles:
            if style.id in seen:
                duplicates.add(style.id)
            seen.add(style.id)
        if duplicates:
            raise ValueError(f"duplicate style id(s): {sorted(duplicates)}")
        return self


class UnknownStyleError(KeyError):
    """Raised for a style id that is not in the catalog."""


def load_style_library(path: str | Path | None = None) -> StyleLibrary:
    """Parse and validate a catalog file. Uncached; use for explicit paths."""
    target = Path(path) if path is not None else CATALOG_PATH
    return StyleLibrary.model_validate(json.loads(target.read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def load_style_registry() -> StyleLibrary:
    """The validated canonical catalog, loaded once per process."""
    return load_style_library()


def get_style(style_id: str, library: StyleLibrary | None = None) -> StyleDefinition:
    library = library or load_style_registry()
    for style in library.styles:
        if style.id == style_id:
            return style
    raise UnknownStyleError(style_id)


def pending_references(library: StyleLibrary | None = None) -> list[str]:
    """Referenced style ids that are not in the catalog yet (awaiting migration)."""
    library = library or load_style_registry()
    known = {style.id for style in library.styles}
    referenced = {
        ref
        for style in library.styles
        for ref in (*style.compatible_with, *style.incompatible_with)
    }
    return sorted(referenced - known)


def style_catalog_snapshot(library: StyleLibrary | None = None) -> dict[str, Any]:
    """JSON-safe catalog payload for the API, including pending references."""
    library = library or load_style_registry()
    return {
        "version": library.version,
        "styles": [style.model_dump(mode="json") for style in library.styles],
        "pending_references": pending_references(library),
    }
