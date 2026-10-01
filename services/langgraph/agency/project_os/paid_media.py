"""Paid-media planning. Planning only: no account, no budget, no mutation.

The future mutation sequence is modelled explicitly so a plan always shows
how far it is from execution::

    PLAN → ACCOUNT_RESOLUTION → EXACT_MUTATION_PREVIEW → BUDGET_AUTHORIZATION
    → HUMAN_APPROVAL → IDEMPOTENT_PROVIDER_WRITE → READBACK → RECONCILIATION
    → RECEIPT → ANALYTICS

Only PLAN runs here. Everything after it reports NOT_AVAILABLE (no reviewed
provider adapter) or, for budget authorization, points at the existing
spend-authorization ledger, which records requests but never executes them.
LLM or planner output never grants spend authority: ``spend_authority_granted``
is a literal ``False`` in every plan.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from .workspace import canonical_json, sha256_bytes

MUTATION_SEQUENCE = (
    "PLAN",
    "ACCOUNT_RESOLUTION",
    "EXACT_MUTATION_PREVIEW",
    "BUDGET_AUTHORIZATION",
    "HUMAN_APPROVAL",
    "IDEMPOTENT_PROVIDER_WRITE",
    "READBACK",
    "RECONCILIATION",
    "RECEIPT",
    "ANALYTICS",
)

# Planning defaults are labelled as such; they are not performance claims.
DEFAULT_FREQUENCY_CAP_PER_WEEK = 3
CREATIVE_FATIGUE_REVIEW_DAYS = 14


@dataclass(frozen=True)
class PaidMediaBrief:
    objective: str
    offer: str
    audiences: tuple[str, ...]
    channels: tuple[str, ...]
    budget_minor: int
    currency: str
    flight_days: int
    creative_refs: tuple[str, ...]
    landing_page_ref: str | None = None
    keywords: tuple[str, ...] = ()


def plan_campaign(brief: PaidMediaBrief, *, paid_media_mode: str = "disabled") -> dict[str, object]:
    if brief.budget_minor < 0 or brief.flight_days <= 0:
        raise ValueError("budget must be non-negative and the flight at least one day")
    if not brief.audiences or not brief.channels:
        raise ValueError("a paid plan needs at least one audience and one channel")
    ad_groups = [
        {"ad_group_id": f"ag-{channel}-{index}", "channel": channel, "audience": audience,
         "keywords_or_context": list(brief.keywords) if channel in {"search", "google_search", "bing"} else []}
        for channel in brief.channels
        for index, audience in enumerate(brief.audiences)
    ]
    creative_matrix = [
        {"ad_group_id": group["ad_group_id"], "creative_ref": creative, "variant": f"{group['ad_group_id']}::{creative}"}
        for group in ad_groups
        for creative in brief.creative_refs
    ]
    daily_minor = math.floor(brief.budget_minor / brief.flight_days)
    per_group_daily = math.floor(daily_minor / max(len(ad_groups), 1))
    experiments = [
        {"experiment": "creative_split", "arms": list(brief.creative_refs[:2]), "metric": brief.objective}
    ] if len(brief.creative_refs) >= 2 else []
    sequence = []
    for step in MUTATION_SEQUENCE:
        if step == "PLAN":
            status = "COMPLETE"
        elif step == "BUDGET_AUTHORIZATION":
            status = "REQUEST_ONLY_VIA_SPEND_LEDGER"
        elif step == "HUMAN_APPROVAL":
            status = "REQUIRED"
        else:
            status = "NOT_AVAILABLE"
        sequence.append({"step": step, "status": status})
    plan = {
        "objective": brief.objective,
        "offer": brief.offer,
        "campaign_architecture": {"campaign": f"{brief.objective}:{brief.offer}", "ad_groups": ad_groups},
        "creative_matrix": creative_matrix,
        "landing_page_ref": brief.landing_page_ref,
        "tracking": {"utm_template": "utm_source={channel}&utm_medium=paid&utm_campaign={campaign}&utm_content={variant}",
                     "conversion_event": brief.objective},
        "budget": {"total_minor": brief.budget_minor, "currency": brief.currency.upper(), "flight_days": brief.flight_days,
                   "daily_minor": daily_minor, "per_ad_group_daily_minor": per_group_daily, "pacing": "EVEN"},
        "frequency": {"cap_per_week": DEFAULT_FREQUENCY_CAP_PER_WEEK, "basis": "PLANNING_DEFAULT"},
        "retargeting": {"enabled": False, "reason": "requires consented first-party audiences"},
        "experiments": experiments,
        "creative_fatigue": {"review_every_days": CREATIVE_FATIGUE_REVIEW_DAYS, "basis": "PLANNING_DEFAULT"},
        "mutation_sequence": sequence,
        "paid_media_mode": paid_media_mode,
        "spend_authority_granted": False,
        "execution_available": False,
    }
    plan["plan_hash"] = sha256_bytes(canonical_json(plan))
    return plan


def analyze_delivery(observations: Iterable[dict]) -> dict[str, object]:
    """Recommendations from *observed* delivery rows only; no row, no claim."""
    rows = list(observations)
    if not rows:
        return {"status": "NO_OBSERVED_DATA", "recommendations": []}
    recommendations = []
    for row in rows:
        impressions, clicks = row.get("impressions"), row.get("clicks")
        if not impressions or clicks is None:
            continue
        ctr = clicks / impressions
        if row.get("frequency") and row["frequency"] > DEFAULT_FREQUENCY_CAP_PER_WEEK and ctr < row.get("baseline_ctr", ctr):
            recommendations.append({"ad_group_id": row.get("ad_group_id"), "action": "REFRESH_CREATIVE", "reason": "fatigue: CTR below baseline at high frequency"})
    return {"status": "OBSERVED", "rows": len(rows), "recommendations": recommendations}
