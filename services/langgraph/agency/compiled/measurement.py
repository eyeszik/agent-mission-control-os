"""T22 — measurement and process mining over *actual* run telemetry.

Inputs are rows from ``persistence/events.py`` (``event_type``, ``node_id``,
``observed_at``/``completed_at``, ``safe_payload``). Every metric without
evidence is reported ``NOT_MEASURED`` — never estimated, never a marketing
multiplier.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Mapping

NOT_MEASURED = "NOT_MEASURED"

# Live LangGraph stage → the N1 artifact the compiled plan calls it.
STAGE_ARTIFACT: dict[str, str] = {
    "brand_strategy": "positioning_statement",
    "creative_concepting": "creative_concept",
    "copywriting": "copy_variant",
    "design_brief": "design_brief",
    "campaign_assembly": "campaign_package",
    "brand_safety_qa": "qa_report",
    "delivery": "release_record",
}


def _ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _seconds(start: Any, end: Any) -> float | None:
    a, b = _ts(start), _ts(end)
    return (b - a).total_seconds() if a and b else None


def conformance(planned_order: Iterable[str], observed_order: Iterable[str]) -> dict[str, Any]:
    """Plan-vs-actual routing. Fitness = observed steps that were planned and in planned order."""
    plan = [p for p in planned_order]
    observed = [o for o in observed_order]
    if not observed:
        return {"fitness": NOT_MEASURED, "unplanned": [], "skipped": [], "out_of_order": []}
    position = {p: i for i, p in enumerate(plan)}
    unplanned = [o for o in observed if o not in position]
    in_plan = [o for o in observed if o in position]
    out_of_order = [b for a, b in zip(in_plan, in_plan[1:]) if position[b] < position[a]]
    skipped = [p for p in plan if p not in observed]
    fitting = len(in_plan) - len(out_of_order)
    return {
        "fitness": round(fitting / len(observed), 6),
        "unplanned": unplanned,
        "skipped": skipped,
        "out_of_order": out_of_order,
    }


def measure_run(events: Iterable[Mapping[str, Any]], *, planned_artifacts: Iterable[str] = ()) -> dict[str, Any]:
    rows = sorted(events, key=lambda e: (e.get("sequence") or 0))
    completes = [e for e in rows if e.get("event_type") == "node_complete"]
    errors = [e for e in rows if e.get("event_type") == "node_error"]
    requested = [e for e in rows if e.get("event_type") == "approval_requested"]
    decided = [e for e in rows if e.get("event_type") == "approval_decided"]
    generated = [e for e in rows if e.get("event_type") == "artifact_generated"]

    durations = {
        str(e.get("node_id")): d
        for e in completes
        if (d := _seconds(e.get("started_at"), e.get("completed_at"))) is not None
    }
    approval_latency: Any = NOT_MEASURED
    if requested and decided:
        approval_latency = _seconds(requested[0].get("observed_at"), decided[-1].get("observed_at"))
    production_latency: Any = NOT_MEASURED
    if completes:
        first = rows[0].get("observed_at")
        gate = requested[0].get("observed_at") if requested else completes[-1].get("observed_at")
        production_latency = _seconds(first, gate)

    observed_artifacts = [STAGE_ARTIFACT[str(e.get("node_id"))] for e in completes if str(e.get("node_id")) in STAGE_ARTIFACT]
    planned = list(planned_artifacts)
    decisions = [(e.get("safe_payload") or {}).get("decision") for e in decided]
    return {
        "events": len(rows),
        "node_durations_seconds": durations or NOT_MEASURED,
        "node_errors": len(errors) if rows else NOT_MEASURED,
        "retry_rate": NOT_MEASURED if not completes else round(len(errors) / (len(completes) + len(errors)), 6),
        "client_decision_latency_seconds": approval_latency if approval_latency is not None else NOT_MEASURED,
        "production_latency_seconds": production_latency if production_latency is not None else NOT_MEASURED,
        "artifacts_generated": len(generated) if rows else NOT_MEASURED,
        "accept_reject": decisions or NOT_MEASURED,
        "plan_conformance": conformance(planned, observed_artifacts) if planned else NOT_MEASURED,
        "cost_schedule_variance": NOT_MEASURED,
        "release_result": NOT_MEASURED,
    }


def plan_metrics(plan) -> dict[str, Any]:
    """Structural facts of a compiled plan (planned, not observed)."""
    return {
        "planned_work_nodes": len(plan.work_orders),
        "activated_specialists": len(plan.activated_specialists),
        "dormant_specialists": plan.dormant_specialist_count,
        "shared_context_refs_hoisted": len(plan.shared_genome_refs),
        "dedup_hits": plan.graph.dedup_hits,
        "held_cells": len(plan.waves.held),
    }
