"""Lighting/material coupling and physics/VFX causality.

Lighting is compiled as SOURCE x ANGLE x SURFACE -> RESPONSE, so only visible
material responses appear (no unrelated adjective lists). Physics is compiled as
TRIGGER -> PRIMARY CONSEQUENCE -> SECONDARY RESPONSE -> SETTLE, kept strictly in
visual-production language; nothing here describes how to construct a real,
dangerous physical effect.
"""

from __future__ import annotations

from typing import Any

from .schemas import PhysicsEvent


def compile_lighting(light: dict[str, Any], materials: dict[str, Any]) -> str:
    """Return a visible SOURCE x ANGLE x SURFACE -> RESPONSE phrase, or ''.

    Only material responses that are actually lit are described.
    """

    source = _get(light, "source")
    angle = _get(light, "angle")
    if not source:
        return ""

    lead = source if not angle else f"{source} from {angle}"
    responses: list[str] = []
    for surface, response in (materials or {}).items():
        if response:
            responses.append(f"{surface} reads as {response}")
    if not responses:
        quality = _get(light, "quality")
        return f"{lead}{f', {quality}' if quality else ''}".strip()
    return f"{lead}, so {'; '.join(responses)}"


def compile_physics(event: PhysicsEvent) -> str:
    """Return a causal TRIGGER -> PRIMARY -> SECONDARY -> SETTLE phrase."""

    chain = [event.trigger, event.primary_consequence]
    if event.secondary_response:
        chain.append(event.secondary_response)
    if event.settle:
        chain.append(event.settle)
    return " -> ".join(part for part in chain if part)


def _get(mapping: dict[str, Any], key: str) -> str:
    value = (mapping or {}).get(key)
    return "" if value is None else str(value)
