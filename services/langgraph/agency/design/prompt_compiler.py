from __future__ import annotations

from typing import Any

from services.langgraph.agency.design.compatibility import analyze_style_compatibility
from services.langgraph.agency.design.style_registry import get_style


def compose_style_selection(selections: list[dict[str, Any]]) -> dict[str, Any]:
    """Compose multiple style selections into a design recipe without mutating the catalog."""
    resolved_tokens: list[dict[str, Any]] = []
    style_ids: list[str] = []

    for selection in selections:
        style_id = selection['style_id']
        style = get_style(style_id)
        style_ids.append(style_id)

        strength = float(selection.get('strength', style.recommended_strength))
        for token in style.prompt_tokens:
            resolved_tokens.append({
                'token': token,
                'value': token,
                'dimension': 'prompt',
                'strength': strength,
            })

        for dimension in style.design_dimensions:
            resolved_tokens.append({
                'token': style.name,
                'value': f'{dimension}:{style.name}',
                'dimension': dimension,
                'strength': strength,
            })

    compatibility = analyze_style_compatibility(style_ids)
    return {
        'composition_id': 'style-composition-1',
        'selections': selections,
        'resolved_tokens': resolved_tokens,
        'conflicts': compatibility['conflicts'],
        'warnings': compatibility['warnings'],
        'blocking': compatibility['blocking'],
    }


__all__ = ['compose_style_selection']
