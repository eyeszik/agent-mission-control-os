"""Compose style selections into one resolved design direction, by dimension.

Each selection is a layer: a style, a strength (0..1), the dimensions it claims
(empty means the style's own ``design_dimensions``), and whether it locks them.
Every dimension resolves to exactly one style:

  * a locked layer beats unlocked layers; two locks on one dimension is a
    blocking conflict;
  * otherwise the strongest layer wins, the primary style breaks ties, then
    selection order.

Tokens are drawn from the winning style's material for *that dimension only*
(its lighting physics for ``lighting``, its typography spec for ``typography``,
...), with layer strength controlling how much of it is used. Exactly one style —
the imagery owner, else the primary — contributes whole-style identity tokens,
so the result is a composed system rather than concatenated style prompts.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Iterable, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .compatibility import analyze_style_compatibility
from .prompt_compiler import compile_design_prompt, compile_negative_prompt
from .style_registry import (
    STYLE_DIMENSIONS,
    STYLE_LIBRARY_VERSION,
    StyleDefinition,
    StyleDimension,
    StyleLibrary,
    _check_id,
    get_style,
    load_style_registry,
)

COMPOSER_VERSION = "style-composer/v1"
MAX_SELECTIONS = 8


class StyleSelection(BaseModel):
    style_id: str
    role: Literal["primary", "secondary"] = "secondary"
    strength: float = Field(default=0.5, ge=0.0, le=1.0)
    dimensions: list[StyleDimension] = Field(default_factory=list)
    locked: bool = False

    model_config = {"extra": "forbid"}

    @field_validator("style_id")
    @classmethod
    def _valid_id(cls, value: str) -> str:
        return _check_id(value)


class DesignStyleSelection(BaseModel):
    """What a run carries in: the selection composed in Design Mode."""

    selections: list[StyleSelection] = Field(min_length=1, max_length=MAX_SELECTIONS)
    rationale: str = ""
    catalog_version: str = STYLE_LIBRARY_VERSION

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _well_formed(self) -> "DesignStyleSelection":
        _check_selection_set(self.selections)
        return self


class ResolvedStyleToken(BaseModel):
    token: str
    value: str
    dimension: StyleDimension
    strength: float = Field(ge=0.0, le=1.0)

    model_config = {"extra": "forbid"}


class ComposedStyle(BaseModel):
    composition_id: str
    catalog_version: str
    selections: list[StyleSelection]
    resolved_dimensions: dict[StyleDimension, str] = Field(default_factory=dict)
    resolved_tokens: list[ResolvedStyleToken] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    blocking: bool
    prompt: str
    negative_prompt: str = ""
    version: str = COMPOSER_VERSION

    model_config = {"extra": "forbid"}


class DesignStyleDirection(BaseModel):
    """What a run persists on its DesignBrief (artifact lineage)."""

    composition_id: str
    catalog_version: str
    selections: list[StyleSelection]
    resolved_dimensions: dict[StyleDimension, str] = Field(default_factory=dict)
    prompt: str
    negative_prompt: str = ""
    conflicts: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    blocking: bool
    applied: bool
    rationale: str = ""

    model_config = {"extra": "forbid"}


class InvalidSelectionError(ValueError):
    """The selection set itself is malformed (duplicate style, >1 primary, ...)."""


def _check_selection_set(selections: list[StyleSelection]) -> None:
    if not selections:
        raise InvalidSelectionError("at least one style selection is required")
    if len(selections) > MAX_SELECTIONS:
        raise InvalidSelectionError(f"at most {MAX_SELECTIONS} style selections are allowed")
    if sum(1 for s in selections if s.role == "primary") > 1:
        raise InvalidSelectionError("at most one primary style is allowed")
    ids = [s.style_id for s in selections]
    if len(set(ids)) != len(ids):
        raise InvalidSelectionError("a style may appear only once per composition")


def _normalize(selections: Iterable[StyleSelection | dict[str, Any]]) -> list[StyleSelection]:
    normalized = [
        s if isinstance(s, StyleSelection) else StyleSelection.model_validate(s) for s in selections
    ]
    _check_selection_set(normalized)
    return normalized


def _dimension_material(style: StyleDefinition, dimension: str) -> list[str]:
    """The strings a style contributes to one dimension."""
    physics = style.physics
    typo = style.typography
    if dimension == "lighting":
        return list(physics.lighting)
    if dimension in {"layout", "depth"}:
        return list(physics.spatial)
    if dimension in {"composition", "geometry"}:
        return list(physics.composition)
    if dimension in {"texture", "material", "surface"}:
        return list(physics.material)
    if dimension == "motion":
        return list(dict.fromkeys([*physics.motion, *style.motion_behavior]))
    if dimension == "palette":
        roles = [f"{role} {value}" for role, value in style.palette.semantic_roles.items()]
        return [*(roles or style.palette.colors), *style.palette.contrast_notes]
    if dimension == "typography":
        parts = [typo.category, *typo.families]
        if typo.tracking:
            parts.append(f"{typo.tracking} tracking")
        if typo.hierarchy:
            parts.append(typo.hierarchy)
        return parts
    if dimension == "imagery":
        return list(style.prompt_tokens)
    return []


def _take(values: list[str], strength: float) -> list[str]:
    """Layer strength controls how much of a style's material is used."""
    if not values:
        return []
    return values[: max(1, math.ceil(strength * len(values)))]


def _composition_id(catalog_version: str, selections: list[StyleSelection]) -> str:
    canonical = json.dumps(
        {
            "catalog_version": catalog_version,
            "selections": [s.model_dump(mode="json") for s in selections],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "cmp-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def compose_style_selection(
    selections: Iterable[StyleSelection | dict[str, Any]],
    brief: dict[str, Any] | None = None,
    *,
    library: StyleLibrary | None = None,
) -> ComposedStyle:
    library = library or load_style_registry()
    brief = brief or {}
    layers = _normalize(selections)
    styles = {layer.style_id: get_style(layer.style_id, library) for layer in layers}

    brief_text = " ".join(str(brief.get(key, "")) for key in ("objective", "audience", "format"))
    compatibility = analyze_style_compatibility(
        [layer.style_id for layer in layers],
        brief_text=brief_text,
        dimension_overlap=False,
        library=library,
    )
    conflicts = list(compatibility["conflicts"])
    warnings = list(compatibility["warnings"])

    order = {layer.style_id: index for index, layer in enumerate(layers)}
    claims: dict[str, list[StyleSelection]] = {}
    for layer in layers:
        style = styles[layer.style_id]
        claimed = layer.dimensions or list(style.design_dimensions)
        for dimension in claimed:
            if dimension not in style.design_dimensions:
                warnings.append(
                    f"'{style.name}' is assigned to {dimension}, which it does not declare; "
                    "its contribution there may be thin"
                )
            claims.setdefault(dimension, []).append(layer)

    resolved: dict[str, str] = {}
    for dimension in STYLE_DIMENSIONS:
        candidates = claims.get(dimension)
        if not candidates:
            continue
        locked = [layer for layer in candidates if layer.locked]
        if len(locked) > 1:
            names = ", ".join(styles[layer.style_id].name for layer in locked)
            conflicts.append(f"{dimension} is locked by more than one style: {names}")
        pool = locked or candidates
        winner = max(
            pool,
            key=lambda layer: (layer.strength, layer.role == "primary", -order[layer.style_id]),
        )
        resolved[dimension] = winner.style_id
        winning_style = styles[winner.style_id]
        for other in candidates:
            if other is winner:
                continue
            other_style = styles[other.style_id]
            declared = (
                other.style_id in winning_style.compatible_with
                or winner.style_id in other_style.compatible_with
            )
            if not declared:
                warnings.append(
                    f"{dimension}: '{winning_style.name}' takes precedence over "
                    f"'{other_style.name}' (no declared compatibility between them)"
                )

    strength_of = {layer.style_id: layer.strength for layer in layers}
    tokens: list[ResolvedStyleToken] = []
    for dimension, style_id in resolved.items():
        style = styles[style_id]
        for value in _take(_dimension_material(style, dimension), strength_of[style_id]):
            tokens.append(
                ResolvedStyleToken(
                    token=style.name,
                    value=value,
                    dimension=dimension,
                    strength=strength_of[style_id],
                )
            )

    # Exactly one style supplies whole-style identity tokens.
    if "imagery" not in resolved:
        primary = next((layer for layer in layers if layer.role == "primary"), None)
        identity = primary or max(layers, key=lambda layer: (layer.strength, -order[layer.style_id]))
        style = styles[identity.style_id]
        for value in _take(list(style.prompt_tokens), identity.strength):
            tokens.append(
                ResolvedStyleToken(
                    token=style.name, value=value, dimension="imagery", strength=identity.strength
                )
            )

    owners = list(dict.fromkeys(resolved.values()))
    negatives = list(
        dict.fromkeys(token for style_id in owners for token in styles[style_id].negative_tokens)
    )

    blocking = bool(conflicts)
    composed_payload = {
        "resolved_tokens": [token.model_dump() for token in tokens],
        "resolved_dimensions": resolved,
        "conflicts": conflicts,
        "production_notes": list(
            dict.fromkeys(note for style_id in owners for note in styles[style_id].production_notes)
        ),
    }
    return ComposedStyle(
        composition_id=_composition_id(library.version, layers),
        catalog_version=library.version,
        selections=layers,
        resolved_dimensions=resolved,
        resolved_tokens=tokens,
        conflicts=conflicts,
        warnings=list(dict.fromkeys(warnings)),
        blocking=blocking,
        prompt=compile_design_prompt(brief, composed_payload),
        negative_prompt=compile_negative_prompt(negatives),
    )


def direction_from_selection(
    selection: DesignStyleSelection | dict[str, Any],
    brief: dict[str, Any] | None = None,
    *,
    library: StyleLibrary | None = None,
) -> DesignStyleDirection:
    """Compose a run's style selection into the direction persisted on its DesignBrief.

    A blocking direction is recorded (for lineage and human review) but marked
    ``applied=False`` so it never steers generation.
    """
    chosen = (
        selection
        if isinstance(selection, DesignStyleSelection)
        else DesignStyleSelection.model_validate(selection)
    )
    composed = compose_style_selection(chosen.selections, brief, library=library)
    return DesignStyleDirection(
        composition_id=composed.composition_id,
        catalog_version=composed.catalog_version,
        selections=composed.selections,
        resolved_dimensions=composed.resolved_dimensions,
        prompt=composed.prompt,
        negative_prompt=composed.negative_prompt,
        conflicts=composed.conflicts,
        warnings=composed.warnings,
        blocking=composed.blocking,
        applied=not composed.blocking,
        rationale=chosen.rationale,
    )


__all__ = [
    "COMPOSER_VERSION",
    "ComposedStyle",
    "DesignStyleDirection",
    "DesignStyleSelection",
    "InvalidSelectionError",
    "ResolvedStyleToken",
    "StyleSelection",
    "compose_style_selection",
    "direction_from_selection",
]
