"""Compatibility analysis for a set of selected styles.

Blocking conflicts (a composition carrying one must not be applied):
  * two selected styles declare each other incompatible (either direction);
  * a selected style is ``disabled``.

Warnings (surfaced, not blocking):
  * a selected style is ``deprecated`` or ``experimental``;
  * two styles both declare the same dimension without a declared compatibility
    between them — an untested pairing, resolved by dimension assignment;
  * the brief matches a style's ``unsuitable_for`` metadata.
"""

from __future__ import annotations

from typing import Any

from .style_registry import StyleLibrary, get_style, load_style_registry


def analyze_style_compatibility(
    style_ids: list[str],
    *,
    brief_text: str = "",
    dimension_overlap: bool = True,
    library: StyleLibrary | None = None,
) -> dict[str, Any]:
    """``dimension_overlap=False`` skips declared-dimension overlap warnings; the
    composer passes it because it reports contention from actual assignments."""
    library = library or load_style_registry()
    styles = [get_style(style_id, library) for style_id in style_ids]

    conflicts: list[str] = []
    warnings: list[str] = []

    for style in styles:
        if style.status == "disabled":
            conflicts.append(f"'{style.name}' ({style.id}) is disabled and cannot be composed")
        elif style.status in {"deprecated", "experimental"}:
            warnings.append(f"'{style.name}' ({style.id}) is {style.status}")

    seen_pairs: set[tuple[str, str]] = set()
    for index, left in enumerate(styles):
        for right in styles[index + 1 :]:
            pair = tuple(sorted((left.id, right.id)))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            if right.id in left.incompatible_with or left.id in right.incompatible_with:
                conflicts.append(f"'{left.name}' ({left.id}) is incompatible with '{right.name}' ({right.id})")
                continue
            if not dimension_overlap:
                continue
            declared = right.id in left.compatible_with or left.id in right.compatible_with
            shared = sorted(set(left.design_dimensions) & set(right.design_dimensions))
            if shared and not declared:
                warnings.append(
                    f"'{left.name}' and '{right.name}' both shape {', '.join(shared)} without a declared "
                    "compatibility; assign those dimensions explicitly"
                )

    lowered = brief_text.lower()
    if lowered.strip():
        for style in styles:
            for phrase in style.unsuitable_for:
                if phrase and phrase.lower() in lowered:
                    warnings.append(f"'{style.name}' is marked unsuitable for '{phrase}'")

    return {
        "conflicts": conflicts,
        "warnings": warnings,
        "blocking": bool(conflicts),
    }


__all__ = ["analyze_style_compatibility"]
