"""Compile a composed style direction into generation-ready prompt text.

The prompt is assembled per resolved dimension ("Lighting (Tenebrism): ...;
Layout (Bauhaus): ..."), so each dimension is described by exactly one style.
This module only produces text: it never invokes a media provider or writes an
asset, consistent with the repository's PROMPT_PACKAGE_READY firewall.
"""

from __future__ import annotations

from typing import Any

from .style_registry import STYLE_DIMENSIONS

_BASELINE = (
    "Maintain a disciplined hierarchy, strong readability, and brand-safe execution; "
    "avoid decorative noise, unreadable typography, and low-contrast composition."
)


def _brief_line(brief: dict[str, Any]) -> str:
    objective = brief.get("objective") or "Create a premium visual concept"
    audience = brief.get("audience") or "the target audience"
    output_format = brief.get("format") or "campaign visuals"
    return f"Objective: {objective}. Audience: {audience}. Output format: {output_format}."


def _dimension_sections(tokens: list[dict[str, Any]]) -> list[str]:
    grouped: dict[str, dict[str, list[str]]] = {}
    for token in tokens:
        dimension = token.get("dimension") or "style"
        owner = token.get("token") or ""
        value = token.get("value", "")
        if not value:
            continue
        grouped.setdefault(dimension, {}).setdefault(owner, [])
        if value not in grouped[dimension][owner]:
            grouped[dimension][owner].append(value)

    ordered = [d for d in (*STYLE_DIMENSIONS, "style") if d in grouped]
    ordered += sorted(d for d in grouped if d not in ordered)

    sections: list[str] = []
    for dimension in ordered:
        label = "Identity" if dimension == "imagery" else dimension.capitalize()
        for owner, values in grouped[dimension].items():
            prefix = f"{label} ({owner})" if owner else label
            sections.append(f"{prefix}: {', '.join(values)}")
    return sections


def compile_design_prompt(brief: dict[str, Any], composed: dict[str, Any]) -> str:
    """Brief + per-dimension style system + production notes -> prompt text."""
    sections = _dimension_sections(list(composed.get("resolved_tokens", [])))
    parts = [_brief_line(brief or {})]
    parts.append(
        "Style system — " + "; ".join(sections) + "."
        if sections
        else "Style system: a coherent premium design system."
    )
    notes = [note for note in composed.get("production_notes", []) if note]
    if notes:
        parts.append("Production: " + "; ".join(notes) + ".")
    parts.append(_BASELINE)
    conflicts = [c for c in composed.get("conflicts", []) if c]
    if conflicts:
        parts.append("BLOCKED — resolve style conflicts before generation: " + "; ".join(conflicts) + ".")
    return " ".join(parts)


def compile_negative_prompt(negative_tokens: list[str]) -> str:
    return ", ".join(dict.fromkeys(token for token in negative_tokens if token))


__all__ = ["compile_design_prompt", "compile_negative_prompt"]
