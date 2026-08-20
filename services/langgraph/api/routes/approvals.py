from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from services.langgraph.persistence.approvals import get_approval, list_pending_approvals, resolve_approval
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

    run = get_run_record(approval["run_id"])
    if not run:
        fail_idempotency(scope, idempotency_key, "run_missing")
        raise HTTPException(status_code=409, detail="Approval references a missing run")
    authorize_resource(principal, run["tenant_id"], run["project_id"])
    if run["status"] != "needs_approval":
        fail_idempotency(scope, idempotency_key, f"invalid_run_status:{run['status']}")
        raise HTTPException(status_code=409, detail=f"Run is not awaiting approval (status={run['status']})")

    resolved = resolve_approval(
        approval_id,
        reviewer=principal.user_id,
        decision=body.decision,
    )
    if not resolved:
        fail_idempotency(scope, idempotency_key, "approval_terminal")
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
            raise HTTPException(status_code=409, detail="Run state changed while rejection was being recorded")

    response = {
        "approval_id": resolved["approval_id"],
        "status": resolved["status"],
        "decision": resolved["decision"],
        "reviewer": resolved["reviewer"],
        "decided_at": resolved["decided_at"],
    }
    if not complete_idempotency(scope, idempotency_key, response):
        raise HTTPException(status_code=500, detail="Failed to finalize idempotency record")
    return response
