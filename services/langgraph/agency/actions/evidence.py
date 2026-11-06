"""Read models over the action plane. They read rows and compute views; none of them writes.

* ``evidence`` (Evidence Twin): every claim about an action linked to proof.
  That is the hash-chained transitions (re-verified), the permit, execution and
  observation receipts, approvals, trust-kernel policy decisions and recovery
  cases, the budget reservation and the sandbox provider record.
* ``recovery_workbench``: UNKNOWN / RECONCILING / NEEDS_HUMAN / FAILED actions,
  with retry eligibility and the evidence that decides it.
* ``capability_drift``: declared (catalogue) versus observed (live probe) support.
* ``budget_envelope``: ceilings, committed, reserved and pending exposure.
* ``expiring``: approvals and actions whose window closes soon.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from services.langgraph.persistence import actions as db
from services.langgraph.security.auth import Principal

from . import broker
from .catalog import catalog
from .fsm import MAX_ATTEMPTS, ActionState
from .vocabulary import STATUS_LABELS


def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


def evidence(principal: Principal, action_id: str) -> dict[str, Any]:
    from services.langgraph.app.runtime_support import trust_kernel
    from services.langgraph.persistence.proofs import list_dispatch_permits, list_execution_receipts, list_observation_receipts

    row = broker.visible(principal, db.get_request(action_id))
    chain = db.verify_transition_chain(action_id)
    transitions = db.list_transitions(action_id)
    run_id = row.get("run_id")
    state = trust_kernel().store.state
    decisions = [d.model_dump(mode="json") for d in state.policy_decisions.values()
                 if d.subject_ref == action_id and d.tenant_id == row["tenant_id"]]
    recovery = [r.model_dump(mode="json") for r in state.recovery.values()
                if r.operation_id == action_id and r.tenant_id == row["tenant_id"]]
    approvals = broker._action_approvals(row)
    reservation = db.get_reservation(row["budget_reservation_id"]) if row.get("budget_reservation_id") else None
    from .gateway import _ctx

    sandbox = db.sandbox_get(tenant_id=row["tenant_id"], provider=catalog().get(row["capability_id"]).provider,
                             idempotency_key=_ctx(row).effect_key) if row["environment"] == "SANDBOX" else None
    claims = []
    if row["state"] == ActionState.COMPLETED.value:
        claims.append({"claim": "the effect exists at the provider with the bound payload hash",
                       "proof": [f"observation:{o['operation_id']}" for o in (list_observation_receipts(run_id) if run_id else [])
                                 if o.get("matches")],
                       "label": (row.get("outcome") or {}).get("label")})
    return {
        "action_id": action_id, "state": row["state"], "status_label": STATUS_LABELS.get(row["state"], row["state"]),
        "chain": chain, "transitions": transitions,
        "permits": list_dispatch_permits(run_id) if run_id else [],
        "execution_receipts": list_execution_receipts(run_id) if run_id else [],
        "observation_receipts": list_observation_receipts(run_id) if run_id else [],
        "approvals": [{k: a.get(k) for k in ("approval_id", "subject_type", "status", "decision", "reviewer", "decided_at",
                                             "subject_hash", "stale_reason")} for a in approvals.values()],
        "policy_decisions": decisions, "recovery_cases": recovery, "budget_reservation": reservation,
        "sandbox_record": sandbox, "claims": claims,
        "binding_hash": row["binding_hash"], "live_execution": "DISABLED",
    }


def recovery_workbench(principal: Principal) -> list[dict[str, Any]]:
    states = (ActionState.UNKNOWN.value, ActionState.RECONCILING.value, ActionState.NEEDS_HUMAN.value, ActionState.FAILED.value)
    out = []
    for row in db.list_requests(principal.tenant_id, states=states):
        if not principal.can_access_project(row["project_id"]):
            continue
        state = row["state"]
        if state in {ActionState.UNKNOWN.value, ActionState.NEEDS_HUMAN.value}:
            next_step = "reconcile by read-back (never re-sent)"
        elif state == ActionState.RECONCILING.value:
            next_step = "a reconciliation is in progress"
        elif row["retry_eligible"] and int(row["attempts"]) < MAX_ATTEMPTS:
            next_step = f"retry allowed ({row['attempts']}/{MAX_ATTEMPTS} attempts used; the failure had no effect)"
        else:
            next_step = "not retryable: create a new action if still needed"
        out.append({"action_id": row["action_id"], "project_id": row["project_id"], "capability_id": row["capability_id"],
                    "state": state, "status_label": STATUS_LABELS.get(state, state), "reasons": row["reasons"],
                    "attempts": row["attempts"], "reconcile_attempts": row["reconcile_attempts"],
                    "retry_eligible": row["retry_eligible"], "next_step": next_step, "updated_at": row["updated_at"]})
    return out


def capability_drift() -> dict[str, Any]:
    """Declared support (catalogue, built once per process) vs observed support (probed now)."""
    from services.langgraph.agency.vnexus.media_fabric import REGISTRY

    from .adapters import adapters

    rows = []
    for a in adapters().values():
        probe = a.probe()
        rows.append({"id": a.descriptor.id, "declared": a.descriptor.status.value,
                     "observed": "AVAILABLE" if probe.available else "UNAVAILABLE", "drift": not probe.available,
                     "reasons": list(probe.reasons)})
    for d in catalog().all():
        if d.dispatch_owner != "vnexus.media_fabric":
            continue
        provider = REGISTRY.get(d.provider)
        observed = provider.capabilities().status.value if provider else "MISSING"
        declared_available = d.status.value == "IMPLEMENTED"
        rows.append({"id": d.id, "declared": d.status.value, "observed": observed,
                     "drift": declared_available != (observed == "AVAILABLE"), "reasons": list(d.status_reasons)})
    return {"checked_at": db.now_iso(), "entries": rows, "drifted": sum(1 for r in rows if r["drift"])}


def budget_envelope(principal: Principal, *, now: Optional[datetime] = None) -> dict[str, Any]:
    moment = _now(now)
    policies = db.list_budget_policies(principal.tenant_id)
    reservations = db.list_reservations(principal.tenant_id)
    pending = [r for r in db.list_requests(principal.tenant_id, states=("AWAITING_APPROVAL", "AUTHORIZED"))
               if int((r["binding"] or {}).get("cost_minor") or 0) > 0]
    by_currency: dict[str, dict[str, int]] = {}
    for r in reservations:
        cur = by_currency.setdefault(r["currency"], {"reserved_minor": 0, "committed_minor": 0, "refunded_minor": 0,
                                                     "pending_exposure_minor": 0})
        if r["status"] == "RESERVED":
            cur["reserved_minor"] += int(r["amount_minor"])
        elif r["status"] == "COMMITTED":
            cur["committed_minor"] += int(r["committed_minor"] if r["committed_minor"] is not None else r["amount_minor"])
        elif r["status"] == "REFUNDED":
            cur["refunded_minor"] += int(r["committed_minor"] or 0)
    for a in pending:
        c = a["binding"].get("currency")
        if c:
            by_currency.setdefault(c, {"reserved_minor": 0, "committed_minor": 0, "refunded_minor": 0,
                                       "pending_exposure_minor": 0})["pending_exposure_minor"] += int(a["binding"]["cost_minor"])
    return {"as_of": db.iso(moment), "policies": policies, "currencies": by_currency,
            "note": "Committed amounts come only from observed (sandbox) provider records; nothing here is a real settlement."}


def expiring(principal: Principal, *, within_hours: int = 24, now: Optional[datetime] = None) -> list[dict[str, Any]]:
    moment = _now(now)
    horizon = moment + timedelta(hours=max(1, min(within_hours, 24 * 14)))
    pre = (ActionState.AWAITING_APPROVAL.value, ActionState.AUTHORIZED.value, ActionState.RESERVED.value)
    out = []
    for row in db.expiring_before(principal.tenant_id, horizon, pre):
        if principal.can_access_project(row["project_id"]):
            out.append({"action_id": row["action_id"], "project_id": row["project_id"], "state": row["state"],
                        "expires_at": row["expires_at"], "expired": row["expires_at"] < db.iso(moment),
                        "capability_id": row["capability_id"]})
    return out


__all__ = ["budget_envelope", "capability_drift", "evidence", "expiring", "recovery_workbench"]
