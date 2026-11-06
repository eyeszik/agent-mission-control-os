"""Deterministic selector for expert guidance.

The router uses typed metadata first. No LLM call is required for routing, so
identical inputs and registry versions yield identical selections.
"""

from __future__ import annotations

import re
from typing import Any

from .models import GuidanceActivation, GuidanceOverride, GuidancePack, GuidanceSelection
from .registry import GuidanceRegistry, REGISTRY_VERSION, stable_guidance_hash

ROUTER_VERSION = "amc-guidance-router/v1"
_SELECTION_THRESHOLD = 0.25
_WEIGHTS = {
    "family": 0.30,
    "asset_type": 0.25,
    "channel": 0.15,
    "brand_domains": 0.10,
    "capabilities": 0.10,
    "task_tags": 0.10,
}
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _norm(value: Any) -> str:
    raw = getattr(value, "value", value)
    return " ".join(_TOKEN_RE.findall(str(raw).lower()))


def _tokens(value: Any) -> set[str]:
    return set(_TOKEN_RE.findall(str(value).lower()))


def _list_values(values: list[Any]) -> set[str]:
    return {_norm(item) for item in values}


def _overlap_fraction(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left)


def _text_match(candidate: str, allowed: list[str]) -> float:
    if not allowed:
        return 0.0
    normalized = _norm(candidate)
    allowed_norm = {_norm(item) for item in allowed}
    if normalized in allowed_norm:
        return 1.0
    candidate_tokens = _tokens(candidate)
    best = 0.0
    for item in allowed:
        item_tokens = _tokens(item)
        if not item_tokens:
            continue
        best = max(best, len(candidate_tokens & item_tokens) / len(item_tokens))
    return best


def _activation_score(requirement: Any, activation: GuidanceActivation) -> tuple[float, list[str]]:
    components: list[tuple[str, float, float]] = []
    reasons: list[str] = []

    if activation.asset_families:
        value = 1.0 if _norm(requirement.family) in _list_values(activation.asset_families) else 0.0
        components.append(("family", _WEIGHTS["family"], value))
    if activation.asset_types:
        value = _text_match(requirement.asset_type, activation.asset_types)
        components.append(("asset_type", _WEIGHTS["asset_type"], value))
    if activation.channels:
        value = _text_match(requirement.channel, activation.channels)
        components.append(("channel", _WEIGHTS["channel"], value))
    if activation.brand_domains:
        value = _overlap_fraction(
            _list_values(activation.brand_domains),
            _list_values(list(requirement.required_brand_domains)),
        )
        components.append(("brand_domains", _WEIGHTS["brand_domains"], value))
    if activation.capabilities:
        value = _overlap_fraction(
            _list_values(activation.capabilities),
            _list_values(list(requirement.required_capabilities)),
        )
        components.append(("capabilities", _WEIGHTS["capabilities"], value))
    if activation.task_tags:
        haystack = " ".join(
            [
                requirement.objective,
                requirement.business_reason or "",
                *list(requirement.content_requirements),
                *list(requirement.quality_constraints),
            ]
        )
        value = _overlap_fraction(_list_values(activation.task_tags), _tokens(haystack))
        components.append(("task_tags", _WEIGHTS["task_tags"], value))

    if not components:
        return 0.0, reasons

    denominator = sum(weight for _, weight, _ in components)
    score = sum(weight * value for _, weight, value in components) / denominator
    for name, _, value in components:
        if value > 0:
            reasons.append(f"{name}={value:.3f}")
    return round(max(0.0, min(1.0, score)), 6), reasons


def _excluded(requirement: Any, excludes: GuidanceActivation) -> str | None:
    checks = [
        ("family", _norm(requirement.family), excludes.asset_families),
        ("asset_type", requirement.asset_type, excludes.asset_types),
        ("channel", requirement.channel, excludes.channels),
    ]
    for label, value, rules in checks:
        if rules and _text_match(str(value), rules) >= 1.0:
            return f"{label} explicitly excluded"
    return None


def _section_matches(section: Any, requirement: Any) -> bool:
    predicate = section.activate_when
    if not predicate.any and not predicate.all:
        return True
    haystack = " ".join(
        [
            requirement.asset_type,
            requirement.objective,
            requirement.channel,
            requirement.business_reason or "",
            *list(requirement.content_requirements),
            *list(requirement.quality_constraints),
        ]
    ).lower()
    if predicate.all and not all(term.lower() in haystack for term in predicate.all):
        return False
    if predicate.any and not any(term.lower() in haystack for term in predicate.any):
        return False
    return True


def _section_payload(pack: GuidancePack, section: Any) -> dict[str, Any]:
    return {
        "pack_id": pack.id,
        "pack_version": pack.pack_version,
        "domain": pack.domain.value,
        "authority_class": pack.authority_class.value,
        "section": section.model_dump(mode="json"),
        "pack_hash": pack.content_hash,
    }


def route_guidance(
    requirement: Any,
    registry: GuidanceRegistry,
    override: GuidanceOverride | None = None,
) -> GuidanceSelection:
    override = override or GuidanceOverride()
    include = set(override.include)
    exclude = set(override.exclude)

    ranked: list[tuple[float, str, GuidancePack, list[str]]] = []
    rejected: list[str] = []
    exclusion_reasons: list[str] = []

    for pack in registry.packs:
        if pack.id in exclude:
            rejected.append(pack.id)
            exclusion_reasons.append(f"{pack.id}: explicit override exclusion")
            continue
        exclusion = _excluded(requirement, pack.excludes)
        if exclusion:
            rejected.append(pack.id)
            exclusion_reasons.append(f"{pack.id}: {exclusion}")
            continue

        score, reasons = _activation_score(requirement, pack.activation)
        forced = pack.id in include
        if forced:
            score = 1.0
            reasons = ["explicit_include"]
        if score < _SELECTION_THRESHOLD:
            rejected.append(pack.id)
            exclusion_reasons.append(f"{pack.id}: relevance={score:.3f}")
            continue
        ranked.append((score, pack.id, pack, reasons))

    selected: dict[str, tuple[float, GuidancePack, list[str]]] = {
        pack.id: (score, pack, reasons)
        for score, _, pack, reasons in ranked
    }

    changed = True
    while changed:
        changed = False
        for pack_id in sorted(list(selected)):
            score, pack, reasons = selected[pack_id]
            blocked_dependency = next(
                (dependency for dependency in pack.dependencies if dependency in exclude),
                None,
            )
            if blocked_dependency is not None:
                selected.pop(pack_id, None)
                rejected.append(pack_id)
                exclusion_reasons.append(
                    f"{pack_id}: dependency {blocked_dependency} explicitly excluded"
                )
                changed = True
                continue

            for dependency in pack.dependencies:
                if dependency in selected:
                    dependency_score, dependency_pack, dependency_reasons = selected[dependency]
                    dependency_reason = f"dependency_of={pack_id}"
                    if dependency_reason not in dependency_reasons:
                        selected[dependency] = (
                            dependency_score,
                            dependency_pack,
                            [*dependency_reasons, dependency_reason],
                        )
                    continue
                dependency_pack = registry.get(dependency)
                selected[dependency] = (
                    score,
                    dependency_pack,
                    [f"dependency_of={pack_id}"],
                )
                changed = True

    ranked = [
        (score, pack_id, pack, reasons)
        for pack_id, (score, pack, reasons) in selected.items()
    ]
    ranked.sort(key=lambda item: (-item[0], item[1]))

    selected_pack_ids: list[str] = []
    selected_section_ids: list[str] = []
    activation_reasons: list[str] = []
    guidance_context: dict[str, Any] = {}

    for score, _, pack, reasons in ranked:
        selected_pack_ids.append(pack.id)
        activation_reasons.append(
            f"{pack.id}: relevance={score:.3f}; " + (", ".join(reasons) or "typed match")
        )
        selected = [section for section in pack.sections if _section_matches(section, requirement)]
        selected = selected[: pack.context_budget.max_sections]

        chars = 0
        for section in selected:
            payload = _section_payload(pack, section)
            encoded = str(payload)
            if chars + len(encoded) > pack.context_budget.max_chars:
                exclusion_reasons.append(
                    f"{pack.id}:{section.id}: context budget exceeded"
                )
                continue
            chars += len(encoded)
            key = f"{pack.id}:{section.id}"
            guidance_context[key] = payload
            selected_section_ids.append(key)

    hash_input = {
        "registry_version": REGISTRY_VERSION,
        "registry_hash": registry.registry_hash,
        "router_version": ROUTER_VERSION,
        "selected_pack_ids": selected_pack_ids,
        "selected_section_ids": selected_section_ids,
        "guidance_context": guidance_context,
    }
    return GuidanceSelection(
        registry_version=REGISTRY_VERSION,
        router_version=ROUTER_VERSION,
        selected_pack_ids=selected_pack_ids,
        selected_section_ids=selected_section_ids,
        activation_reasons=activation_reasons,
        rejected_pack_ids=sorted(set(rejected)),
        exclusion_reasons=exclusion_reasons,
        guidance_context=guidance_context,
        guidance_hash=stable_guidance_hash(hash_input),
    )
