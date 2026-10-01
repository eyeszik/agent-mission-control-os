"""Calendar, scheduling policy and supply forecasting (pure, deterministic).

Scheduler invariant::

    DUE → dependency check → evidence/freshness check → rights check
        → exact approval check → enqueue outbox → adapter → read-back
        → reconciliation → receipt

This module owns the checks and the planning maths. It never calls a provider:
``persistence.project_ops.run_scheduler_tick`` turns a passing gate into an
outbox message, and only the outbox worker reaches an adapter.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping, Optional

from .models import ScheduleCadence
from .vocabulary import (
    APPROVAL_BOUND_CONTENT_STATES,
    CALENDAR_HORIZON_DAYS,
    CONTENT_KIND_ARTIFACT,
    CONTENT_TRANSITIONS,
    UNKNOWN,
    ContentKind,
    ContentState,
    can_transition,
)


class ContentTransitionError(ValueError):
    pass


def parse_ts(value: str | datetime) -> datetime:
    moment = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def assert_content_transition(
    current: ContentState | str,
    target: ContentState | str,
    *,
    version: int,
    approved_version: Optional[int],
    release_blockers: Iterable[str] = (),
) -> None:
    current_state = ContentState(current).value
    target_state = ContentState(target).value
    if not can_transition(CONTENT_TRANSITIONS, current_state, target_state):
        raise ContentTransitionError(f"cannot move content from {current_state} to {target_state}")
    if target_state == "APPROVED":
        # Entering APPROVED is the approval decision itself; it is recorded by
        # the caller with separation of duties enforced.
        return
    if target_state in APPROVAL_BOUND_CONTENT_STATES and approved_version != version:
        raise ContentTransitionError(
            f"{target_state} requires an approval bound to v{version}; approval is "
            f"{'missing' if approved_version is None else f'for v{approved_version}'}"
        )
    blockers = list(release_blockers)
    if target_state in {"READY", "SCHEDULED"} and blockers:
        raise ContentTransitionError(f"release blocked: {', '.join(blockers)}")


def requires_rights(kind: ContentKind | str) -> bool:
    artifact_type, _ = CONTENT_KIND_ARTIFACT[ContentKind(kind).value]
    return artifact_type in {"media_asset", "creative_concept"}


@dataclass(frozen=True)
class GateInput:
    state: str
    version: int
    approved_version: Optional[int]
    approval_ref: Optional[str]
    release_blockers: tuple[str, ...] = ()
    evidence_fresh_until: Optional[str] = None
    dependency_statuses: Mapping[str, str] = field(default_factory=dict)
    rights_required: bool = False
    rights: Optional[Mapping[str, object]] = None


def due_gate(item: GateInput, *, now: datetime) -> list[str]:
    """Return every reason the item may not be published now (empty = clear)."""
    reasons: list[str] = []
    for artifact_id, status in sorted(item.dependency_statuses.items()):
        if status in {"invalidated", "review_required", "archived"}:
            reasons.append(f"DEPENDENCY_{status.upper()}:{artifact_id}")
    if item.evidence_fresh_until and parse_ts(item.evidence_fresh_until) < now:
        reasons.append("EVIDENCE_STALE")
    reasons += [f"RELEASE_BLOCKER:{blocker}" for blocker in item.release_blockers]
    if item.rights_required or item.rights is not None:
        rights = item.rights or {"ok": False, "reason": "RIGHTS_MISSING"}
        if not rights.get("ok"):
            reasons.append(str(rights.get("reason") or "RIGHTS_MISSING"))
    if not item.approval_ref or item.approved_version != item.version:
        reasons.append("APPROVAL_NOT_BOUND_TO_CURRENT_VERSION")
    return reasons


def plan_horizon(
    *,
    start: datetime,
    horizon_days: int,
    cadences: Iterable[ScheduleCadence],
) -> list[dict[str, str]]:
    """Deterministic slot plan for 14 days to 12 months ahead.

    Posts per week are spread over the cadence's weekdays; fractional cadences
    (e.g. 0.5/week) become one slot every other eligible week.
    """
    if horizon_days not in CALENDAR_HORIZON_DAYS:
        raise ValueError(f"horizon_days must be one of {CALENDAR_HORIZON_DAYS}")
    start = parse_ts(start).replace(minute=0, second=0, microsecond=0)
    end = start + timedelta(days=horizon_days)
    slots: list[dict[str, str]] = []
    for cadence in cadences:
        weekdays = sorted(set(cadence.weekdays)) or [0]
        per_week = cadence.posts_per_week
        weeks = math.ceil(horizon_days / 7) + 1
        week_zero = start - timedelta(days=start.weekday())
        accumulator = 0.0
        for week in range(weeks):
            accumulator += per_week
            count = int(accumulator)
            accumulator -= count
            if count <= 0:
                continue
            days = [weekdays[i % len(weekdays)] for i in range(count)]
            for index, weekday in enumerate(days):
                moment = (week_zero + timedelta(weeks=week, days=weekday)).replace(hour=cadence.hour_utc)
                moment += timedelta(minutes=(index // len(weekdays)) * 90)
                if start <= moment < end:
                    slots.append({
                        "channel": cadence.channel,
                        "kind": cadence.kind.value,
                        "scheduled_for": moment.isoformat(),
                    })
    slots.sort(key=lambda slot: (slot["scheduled_for"], slot["channel"], slot["kind"]))
    return slots


def adaptive_reschedule(blocked_at: str, open_slots: Iterable[str], *, now: datetime) -> Optional[str]:
    """AdaptiveCalendar: the earliest open slot after both ``now`` and the
    blocked slot. None when the calendar has no capacity left."""
    floor = max(parse_ts(blocked_at), now)
    candidates = sorted(parse_ts(slot) for slot in open_slots if parse_ts(slot) > floor)
    return candidates[0].isoformat() if candidates else None


# --------------------------------------------------------------------------
# Content supply forecaster
# --------------------------------------------------------------------------

DERIVATIVES_PER_MASTER = 3  # one approved master typically feeds 3 channel cuts


@dataclass(frozen=True)
class ForecastInput:
    horizon_days: int
    cadences: tuple[ScheduleCadence, ...]
    brands: int = 1
    campaigns: int = 1
    approval_batch_size: int = 10
    research_refresh_days: int = 30
    unit_costs: Mapping[str, float] = field(default_factory=dict)  # kind -> observed cost per item


def forecast_supply(spec: ForecastInput) -> dict[str, object]:
    """Required production volume from measurable inputs.

    Costs are only computed from ``unit_costs`` the caller supplies as observed
    evidence. A kind without an observed cost is reported as UNKNOWN, and so is
    the total, rather than inventing a price.
    """
    per_kind: dict[str, int] = {}
    for cadence in spec.cadences:
        slots = plan_horizon(
            start=datetime(2026, 1, 5, tzinfo=timezone.utc),  # a Monday: count is calendar-anchor independent
            horizon_days=spec.horizon_days,
            cadences=[cadence],
        )
        per_kind[cadence.kind.value] = per_kind.get(cadence.kind.value, 0) + len(slots) * spec.brands
    total_items = sum(per_kind.values())
    masters = math.ceil(total_items / DERIVATIVES_PER_MASTER) if total_items else 0
    costs: dict[str, object] = {}
    total_cost: float | str = 0.0
    for kind, count in sorted(per_kind.items()):
        if kind in spec.unit_costs:
            costs[kind] = round(spec.unit_costs[kind] * count, 4)
            if isinstance(total_cost, float):
                total_cost += costs[kind]  # type: ignore[operator]
        else:
            costs[kind] = UNKNOWN
            total_cost = UNKNOWN
    category = {
        "articles": per_kind.get("article", 0),
        "emails": per_kind.get("email", 0) + per_kind.get("newsletter", 0),
        "posts": sum(per_kind.get(k, 0) for k in ("social_post", "thread", "carousel", "story")),
        "videos": sum(per_kind.get(k, 0) for k in ("short_video", "reel", "video_script")),
        "graphics": sum(per_kind.get(k, 0) for k in ("carousel", "story", "paid_creative")),
        "landing_pages": per_kind.get("landing_section", 0),
    }
    return {
        "horizon_days": spec.horizon_days,
        "items_by_kind": dict(sorted(per_kind.items())),
        "by_category": category,
        "required_master_assets": masters,
        "channel_derivatives": max(total_items - masters, 0),
        "approval_batches": math.ceil(total_items / max(spec.approval_batch_size, 1)) if total_items else 0,
        "research_refreshes": math.ceil(spec.horizon_days / max(spec.research_refresh_days, 1)) * spec.brands,
        "estimated_generation_jobs": masters + max(total_items - masters, 0),
        "estimated_cost_by_kind": costs,
        "estimated_total_cost": round(total_cost, 4) if isinstance(total_cost, float) else total_cost,
        "cost_basis": "OBSERVED_UNIT_COSTS" if total_cost != UNKNOWN else "UNKNOWN_WHERE_UNOBSERVED",
    }
