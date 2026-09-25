from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StyleDefinition:
    id: str
    name: str
    category: str
    description: str
    design_dimensions: list[str]
    prompt_tokens: list[str]
    negative_tokens: list[str]
    palette: dict[str, Any]
    typography: dict[str, Any]
    compatible_with: list[str]
    incompatible_with: list[str]
    recommended_strength: float
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'name': self.name,
            'category': self.category,
            'description': self.description,
            'design_dimensions': self.design_dimensions,
            'prompt_tokens': self.prompt_tokens,
            'negative_tokens': self.negative_tokens,
            'palette': self.palette,
            'typography': self.typography,
            'compatible_with': self.compatible_with,
            'incompatible_with': self.incompatible_with,
            'recommended_strength': self.recommended_strength,
            'status': self.status,
        }


def _catalog_path() -> Path:
    return Path(__file__).resolve().parents[4] / 'packages' / 'shared' / 'style-library' / 'design-styles.json'


def load_style_catalog() -> list[dict[str, Any]]:
    path = _catalog_path()
    payload = json.loads(path.read_text(encoding='utf-8'))
    styles = payload.get('styles', [])
    if not isinstance(styles, list):
        raise ValueError('style catalog is malformed')
    return styles


def load_style_registry() -> dict[str, StyleDefinition]:
    registry: dict[str, StyleDefinition] = {}
    for item in load_style_catalog():
        definition = StyleDefinition(
            id=item['id'],
            name=item['name'],
            category=item['category'],
            description=item['description'],
            design_dimensions=item.get('design_dimensions', []),
            prompt_tokens=item.get('prompt_tokens', []),
            negative_tokens=item.get('negative_tokens', []),
            palette=item.get('palette', {}),
            typography=item.get('typography', {}),
            compatible_with=item.get('compatible_with', []),
            incompatible_with=item.get('incompatible_with', []),
            recommended_strength=float(item.get('recommended_strength', 0.5)),
            status=item.get('status', 'active'),
        )
        registry[definition.id] = definition
    return registry


def get_style(style_id: str) -> StyleDefinition:
    style = load_style_registry().get(style_id)
    if style is None:
        raise KeyError(f"Unknown style '{style_id}'")
    return style


def style_catalog_snapshot() -> dict[str, Any]:
    return {
        'version': 'style-library-v1',
        'styles': [style.to_dict() for style in load_style_registry().values()],
    }


__all__ = ['StyleDefinition', 'get_style', 'load_style_catalog', 'load_style_registry', 'style_catalog_snapshot']
