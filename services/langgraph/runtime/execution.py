"""Shared agency execution core.

Both the synchronous inline route (apps calling POST /agency/runs) and the
durable background worker (runtime/worker.py) execute the pipeline through this
module, so inline and background execution cannot drift into different
semantics. This extraction is behavior-preserving relative to the original
route implementation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from services.langgraph.agency.kernel.lifecycle import TransitionContext
from services.langgraph.graph.models import AgentRun


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_config(run_id: str) -> dict:
    return {"configurable": {"thread_id": run_id}}


def agency_payload(state: dict) -> dict:
    return (state.get("extracted_data") or {}).get("agency", {}) if state else {}


def run_and_record_events(graph, input_state, config: dict, run: AgentRun) -> dict:
    """
    Execute synchronously and persist causally honest completion observations.

    The current execution API does not expose a pre-node callback from this
    wrapper, so we intentionally do NOT fabricate node_start timestamps. Each
    event records the point at which a completed node update was observed.
    """

    from services.langgraph.persistence.events import record_event

    for step in graph.stream(input_state, config=config, stream_mode="updates"):
        for node_id, _delta in step.items():
            if node_id == "__interrupt__":
                continue
            completed_at = now_iso()
            record_event(
                str(run.id),
                run.tenant_id,
                run.project_id,
                node_id,
                "node_complete",
                observed_at=completed_at,
                completed_at=completed_at,
            )

    snapshot = graph.get_state(config)
    return dict(snapshot.values) if snapshot and snapshot.values else {}


def delivery_context(stored_agency: dict, approval: Optional[dict]) -> TransitionContext:
    """Build the N2 guard context from the run's persisted facts.

    ``brand_safety_advisory`` is True because this route's established policy is
    that the HITL gate is the authority: a reviewer may approve a campaign whose
    brand-safety heuristic flagged terms. Degraded provider output is *not*
    discharged that way and remains a hard block.
    """

    qa_report = stored_agency.get("qa_report") or {}
    return TransitionContext(
        generation_mode="FALLBACK_DEGRADED" if qa_report.get("release_blocked") else "PROVIDER_SUCCESS",
        approval_exists=approval is not None,
        approval_resolved=bool(approval and approval.get("status") == "resolved"),
        approval_decision=(approval or {}).get("decision"),
        brand_safety_passed=bool(qa_report.get("brand_safety_passed")),
        brand_safety_advisory=True,
    )


# Guard codes that represent a substantive release block worth recording in
# lifecycle analytics, as opposed to a run simply awaiting its approval
# decision. Matches the pre-refactor emission behavior.
ANALYTICS_REPORTED_BLOCKS = frozenset({"degraded_release_block", "brand_safety_failed", "spend_unauthorized"})

DELIVERY_BLOCK_DETAIL = {
    "degraded_release_block": lambda _approval: (
        "Run contains degraded provider output and cannot be delivered; "
        "rerun with a configured provider"
    ),
    "approval_missing": lambda _approval: "No approval found for this run",
    "approval_pending": lambda _approval: "Run still has an unresolved approval",
    "approval_not_approved": lambda approval: (
        f"Run was not approved (decision={(approval or {}).get('decision')})"
    ),
    "brand_safety_failed": lambda _approval: (
        "Run failed brand-safety review and cannot be delivered"
    ),
    "spend_unauthorized": lambda _approval: (
        "Delivery requires an explicit spend/publication authorization"
    ),
}
