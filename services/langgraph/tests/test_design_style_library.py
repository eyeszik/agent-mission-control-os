from __future__ import annotations

from typing import Any


def compile_design_prompt(brief: dict[str, Any], composed: dict[str, Any]) -> str:
    """Compile a human-readable prompt for design generation from the selected style mix."""
    objective = brief.get('objective', 'Create a premium visual concept')
    audience = brief.get('audience', 'target audience')
    output_format = brief.get('format', 'campaign visuals')
    tokens = [item.get('value', '') for item in composed.get('resolved_tokens', [])][:12]
    prompt = (
        f"Objective: {objective}. Audience: {audience}. Output format: {output_format}. "
        f"Style system: {', '.join(tokens) if tokens else 'coherent premium design system'}. "
        "Maintain a disciplined hierarchy, strong readability, premium production polish, and brand-safe execution. "
        "Avoid decorative noise, unreadable typography, and low-contrast composition."
    )
    if composed.get('conflicts'):
        prompt += ' Resolve all style conflicts before output generation.'
    return prompt


__all__ = ['compile_design_prompt']
