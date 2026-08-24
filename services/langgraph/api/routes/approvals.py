from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from services.langgraph.agency.reliability import IdempotencyStatus, PolicyEffect
from services.langgraph.app.runtime_support import trust_kernel
from services.langgraph.persistence.analytics import emit_lifecycle_event
from services.langgraph.persistence.approvals import get_approval, list_pending_approvals, resolve_approval
from services.langgraph.persistence.events import record_event
from services.langgraph.persistence.idempotency import (
    complete_idempotency,
    fail_idempotency,
    hash_payload,
    reserve_idempotency,
)
from services.langgraph.persistence.runs import compare_and_set_run_status, get_run_record
from services.langgraph.security.auth import Principal, authorize_resource, get_principal

router = APIRouter()
IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60


class ApprovalDecision(BaseModel):
    decision: str  # "approve" | "reject"


def _scope(principal: Principal, approval_id: str) -> str:
    return f"{principal.tenant_id}:{principal.user_id}:approval.decide:{approval_id}"


@router.get("")
def get_pending_approvals(
    tenant_id: Optional[str] = None,
    principal: Principal = Depends(get_principal),
):
    if tenant_id is not None and tenant_id != principal.tenant_id:
        raise HTTPException(status_code=403, detail="tenant_id does not match authenticated principal")
    return list_pending_approvals(principal.tenant_id)


@router.post("/{approval_id}/decide")
def decide_approval(
    approval_id: str,
    body: ApprovalDecision,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    principal: Principal = Depends(get_principal),
):
    if body.decision not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="decision must be 'approve' or 'reject'")

    approval = get_approval(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    authorize_resource(principal, approval["tenant_id"], approval["project_id"])

    scope = _scope(principal, approval_id)
    reservation = reserve_idempotency(
        scope,
        idempotency_key,
        hash_payload({"approval_id": approval_id, "decision": body.decision}),
        IDEMPOTENCY_TTL_SECONDS,
    )
    if reservation["state"] == "replay":
        return reservation["record"]["result"]
    if reservation["state"] == "in_progress":
        raise HTTPException(status_code=409, detail="Approval decision is already executing")
    if reservation["state"] == "conflict":
        raise HTTPException(status_code=409, detail="Idempotency-Key was reused with a different decision")
    trust = trust_kernel()
    trust.bind_project(tenant_id=approval["tenant_id"], project_id=approval["project_id"])
    trust.record_policy_decision(
        tenant_id=approval["tenant_id"],
        project_id=approval["project_id"],
        decision_id=f"policy-approval-decide-{approval_id}-{idempotency_key}",
        subject_ref=approval_id,
        action="approval.decide",
        target=body.decision,
        policy_version="amc-trust/v1",
        policy_input={"approval_id": approval_id, "decision": body.decision},
        effect=PolicyEffect.ALLOW,
    )
    trust.claim_idempotency(
        tenant_id=approval["tenant_id"],
        project_id=approval["project_id"],
        idempotency_key=idempotency_key,
        operation_id=f"approval.decide:{approval_id}",
        request={"approval_id": approval_id, "decision": body.decision},
    )

    run = get_run_record(approval["run_id"])
    if not run:
        fail_idempotency(scope, idempotency_key, "run_missing")
        trust.complete_idempotency(idempotency_key=idempotency_key, result_ref=None, status=IdempotencyStatus.FAILED)
        raise HTTPException(status_code=409, detail="Approval references a missing run")
    authorize_resource(principal, run["tenant_id"], run["project_id"])
    if run["status"] != "needs_approval":
        fail_idempotency(scope, idempotency_key, f"invalid_run_status:{run['status']}")
        trust.complete_idempotency(idempotency_key=idempotency_key, result_ref=None, status=IdempotencyStatus.FAILED)
        raise HTTPException(status_code=409, detail=f"Run is not awaiting approval (status={run['status']})")
    if approval["status"] == "stale":
        fail_idempotency(scope, idempotency_key, "approval_stale")
        trust.complete_idempotency(idempotency_key=idempotency_key, result_ref=None, status=IdempotencyStatus.FAILED)
        raise HTTPException(status_code=409, detail="Approval is stale and must be regenerated")

    resolved = resolve_approval(
        approval_id,
        reviewer=principal.user_id,
        decision=body.decision,
    )
    if not resolved:
        fail_idempotency(scope, idempotency_key, "approval_terminal")
        trust.complete_idempotency(idempotency_key=idempotency_key, result_ref=None, status=IdempotencyStatus.FAILED)
        raise HTTPException(status_code=409, detail="Approval already has a terminal decision")

    if body.decision == "reject":
        changed = compare_and_set_run_status(
            approval["run_id"],
            "needs_approval",
            "rejected",
            {"approval_id": approval_id, "decision": "reject"},
        )
        if not changed:
            fail_idempotency(scope, idempotency_key, "run_state_race")
            trust.complete_idempotency(idempotency_key=idempotency_key, result_ref=None, status=IdempotencyStatus.FAILED)
            raise HTTPException(status_code=409, detail="Run state changed while rejection was being recorded")
        emit_lifecycle_event(
            approval["tenant_id"],
            approval["project_id"],
            "agency_run_rejected",
            {"approval_id": approval_id, "decision": "reject"},
            approval["run_id"],
        )

    emit_lifecycle_event(
        approval["tenant_id"],
        approval["project_id"],
        "agency_approval_decided",
        {"approval_id": approval_id, "decision": body.decision},
        approval["run_id"],
    )
    record_event(
        approval["run_id"],
        approval["tenant_id"],
        approval["project_id"],
        "hitl_gate",
        "approval_decided",
        safe_payload={
            "approval_id": resolved["approval_id"],
            "decision": resolved["decision"],
            "status": resolved["status"],
            "reviewer": resolved["reviewer"],
        },
    )

    response = {
        "approval_id": resolved["approval_id"],
        "status": resolved["status"],
        "decision": resolved["decision"],
        "reviewer": resolved["reviewer"],
        "decided_at": resolved["decided_at"],
    }
    if not complete_idempotency(scope, idempotency_key, response):
        raise HTTPException(status_code=500, detail="Failed to finalize idempotency record")
    trust.complete_idempotency(idempotency_key=idempotency_key, result_ref=approval_id)
    return response
