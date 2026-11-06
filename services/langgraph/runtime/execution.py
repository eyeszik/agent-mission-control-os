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

from services.langgraph.agency.delivery.release import safe_attributes
from services.langgraph.agency.delivery.workflow import CONTRACT_CHECK_NODE
from services.langgraph.agency.kernel.lifecycle import TransitionContext
from services.langgraph.graph.models import AgentRun


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_config(run_id: str) -> dict:
    return {"configurable": {"thread_id": run_id}}


def agency_payload(state: dict) -> dict:
    return (state.get("extracted_data") or {}).get("agency", {}) if state else {}


def node_event_payload(node_id: str, delta) -> Optional[dict]:
    """Safe, query-free provenance attached to selected node_complete events."""
    if not isinstance(delta, dict):
        return None
    if node_id == CONTRACT_CHECK_NODE:
        evaluation = (((delta.get("extracted_data") or {}).get("agency") or {}).get("contract_evaluation") or {})
        return {
            "contract_check": safe_attributes(
                node_id=node_id,
                contract_hash=evaluation.get("contract_hash"),
                critic_verdict=evaluation.get("dod") or evaluation.get("status"),
                contract_mode=evaluation.get("contract_mode"),
            )
        }
    if node_id != "creative_concepting":
        return None
    agency = ((delta.get("extracted_data") or {}).get("agency") or {})
    corpus = agency.get("design_corpus_provenance")
    return {"design_corpus": corpus} if corpus else None


def run_pin(record: dict):
    """The run's own pinned workflow, verified against the code's current topology.

    Both the inline route and the background worker resolve the pin the same way,
    so a queued run replays through the graph it was created with - or refuses.
    """

    from services.langgraph.agency.delivery.workflow import assert_pin_current, pinned_workflow

    pin = pinned_workflow(record.get("metadata"))
    assert_pin_current(pin)
    return pin


def contract_from_metadata(metadata: dict):
    """Rehydrate the run's pinned delivery contract, or None when it carries none."""

    raw = (metadata or {}).get("delivery_contract")
    if not raw:
        return None
    from services.langgraph.agency.delivery.contract import DeliveryContract

    return DeliveryContract.model_validate(raw)


def initial_extracted_data(pin, contract: "DeliveryContract | None") -> dict:
    if not pin.uses_contract:
        return {}
    return {
        "delivery_contract": contract.model_dump(mode="json") if contract is not None else None,
        "contract_mode": pin.contract_mode,
    }


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
                safe_payload=node_event_payload(node_id, _delta),
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
        # release_blocked is set by brand_safety_qa when any generation stage
        # fell back, so it is the persisted form of degraded provenance.
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
