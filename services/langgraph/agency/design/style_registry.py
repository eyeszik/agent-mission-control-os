from __future__ import annotations

from collections import defaultdict
from typing import Any

from services.langgraph.agency.design.style_registry import get_style


def analyze_style_compatibility(style_ids: list[str]) -> dict[str, Any]:
    """Check whether a style selection conflicts by dimension or incompatibility list."""
    style_objects = [get_style(style_id) for style_id in style_ids]
    conflicts: list[str] = []
    warnings: list[str] = []
    dimension_map: dict[str, list[str]] = defaultdict(list)

    for style in style_objects:
        for dimension in style.design_dimensions:
            dimension_map[dimension].append(style.id)

    for dimension, owners in sorted(dimension_map.items()):
        if len(owners) > 1:
            warnings.append(f"Multiple styles target the same dimension '{dimension}': {', '.join(owners)}")

    for style in style_objects:
        for other_id in style.incompatible_with:
            if other_id in style_ids:
                conflicts.append(f"'{style.id}' is incompatible with '{other_id}'")

    return {
        'conflicts': conflicts,
        'warnings': warnings,
        'dimension_map': {key: values for key, values in sorted(dimension_map.items())},
        'blocking': bool(conflicts),
    }


__all__ = ['analyze_style_compatibility']
