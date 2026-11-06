"""Cost × quality routing over provider capability profiles.

Priority (cheapest-to-justify first)::

    reuse approved asset → deterministic transform → local/free execution
    → cheap draft → evaluate → premium final (only when justified)
    → post-process before regenerate

The objective is COST_PER_APPROVED_ARTIFACT = cost per unit / acceptance rate,
not raw generation cost: a cheap model whose output is usually rejected is
expensive. Both inputs must be OBSERVED (with an evidence ref); otherwise the
objective is UNKNOWN and the router says so instead of ranking on a guess.

Routing is advice. It never activates a provider: a DISABLED profile is never
chosen, and executing a LIVE cloud provider still goes through its own gates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from .models import ObservedMetric, ProviderCapabilityProfile
from .vocabulary import UNKNOWN, ProviderMode


@dataclass(frozen=True)
class RouteRequest:
    task: str
    output_format: str
    reusable_approved_asset_ref: Optional[str] = None
    deterministic_transform: bool = False
    premium_justification: Optional[str] = None
    max_failure_rate: float = 0.25


def _observed(metric: ObservedMetric) -> Optional[float]:
    if metric.status == "OBSERVED" and metric.value is not None and metric.evidence_ref:
        return float(metric.value)
    return None


def cost_per_approved_artifact(profile: ProviderCapabilityProfile) -> float | str:
    cost = _observed(profile.cost_per_unit)
    acceptance = _observed(profile.acceptance_rate)
    if cost is None or acceptance is None or acceptance <= 0:
        return UNKNOWN
    return round(cost / acceptance, 6)


def _eligible(profile: ProviderCapabilityProfile, request: RouteRequest) -> Optional[str]:
    if profile.mode is ProviderMode.DISABLED:
        return "PROVIDER_DISABLED"
    if profile.task != request.task:
        return "TASK_MISMATCH"
    if request.output_format not in profile.formats:
        return "FORMAT_UNSUPPORTED"
    failure = _observed(profile.failure_rate)
    if failure is not None and failure > request.max_failure_rate:
        return "FAILURE_RATE_ABOVE_LIMIT"
    return None


def route(request: RouteRequest, profiles: Iterable[ProviderCapabilityProfile]) -> dict[str, object]:
    if request.reusable_approved_asset_ref:
        return {"tier": "reuse_approved_asset", "asset_ref": request.reusable_approved_asset_ref, "profile_id": None,
                "objective": 0.0, "rationale": "an approved asset already satisfies the request"}
    if request.deterministic_transform:
        return {"tier": "deterministic_transform", "profile_id": None, "objective": 0.0,
                "rationale": "a deterministic transform (crop, resize, template) is sufficient"}
    considered = []
    rejected: dict[str, str] = {}
    for profile in profiles:
        reason = _eligible(profile, request)
        if reason:
            rejected[profile.profile_id] = reason
            continue
        considered.append(profile)
    local = [p for p in considered if p.locality == "local"]
    cloud = [p for p in considered if p.locality == "cloud"]

    def rank(items: list[ProviderCapabilityProfile]) -> list[ProviderCapabilityProfile]:
        known = [p for p in items if cost_per_approved_artifact(p) != UNKNOWN]
        unknown = [p for p in items if cost_per_approved_artifact(p) == UNKNOWN]
        known.sort(key=lambda p: (cost_per_approved_artifact(p), p.profile_id))
        unknown.sort(key=lambda p: p.profile_id)
        return known + unknown

    if local:
        choice = rank(local)[0]
        tier = "local_free_execution"
    elif cloud:
        ranked = rank(cloud)
        choice = ranked[0]
        tier = "premium_final" if request.premium_justification else "cheap_draft"
    else:
        return {"tier": None, "profile_id": None, "objective": UNKNOWN, "rejected": rejected,
                "rationale": "no eligible provider profile; nothing is routed"}
    return {
        "tier": tier,
        "profile_id": choice.profile_id,
        "provider": choice.provider,
        "model": choice.model,
        "objective": cost_per_approved_artifact(choice),
        "objective_name": "COST_PER_APPROVED_ARTIFACT",
        "then": ["evaluate", "post_process"] if tier != "premium_final" else ["evaluate"],
        "rejected": rejected,
        "rationale": (
            "local execution preferred" if tier == "local_free_execution"
            else "premium tier requires a recorded justification" if tier == "premium_final"
            else "cheapest observed cost per approved artifact; unknown costs ranked last"
        ),
    }
