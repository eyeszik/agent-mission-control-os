from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from services.langgraph.persistence.approvals import get_approval, list_pending_approvals, resolve_approval
from services.langgraph.persistence.runs import get_run_record, update_run_status
from services.langgraph.security.auth import Principal, authorize_resource, get_principal

router = APIRouter()


class ApprovalDecision(BaseModel):
    decision: str  # "approve" | "reject"


@router.get("")
def get_pending_approvals(
    tenant_id: Optional[str] = None,
    principal: Principal = Depends(get_principal),
):
    # tenant_id is accepted only as a compatibility check; it is never the
    # authority source. The authenticated server principal defines the scope.
    if tenant_id is not None and tenant_id != principal.tenant_id:
        raise HTTPException(status_code=403, detail="tenant_id does not match authenticated principal")
    return list_pending_approvals(principal.tenant_id)


@router.post("/{approval_id}/decide")
def decide_approval(
    approval_id: str,
    body: ApprovalDecision,
    principal: Principal = Depends(get_principal),
):
    if body.decision not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="decision must be 'approve' or 'reject'")

    approval = get_approval(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    authorize_resource(principal, approval["tenant_id"], approval["project_id"])

    resolved = resolve_approval(
        approval_id,
        reviewer=principal.user_id,
        decision=body.decision,
    )
    if not resolved:
        raise HTTPException(status_code=409, detail="Approval already has a terminal decision")

    # Couple the rejection decision to a deterministic terminal run state.
    if body.decision == "reject":
        run = get_run_record(approval["run_id"])
        if run:
            authorize_resource(principal, run["tenant_id"], run["project_id"])
            update_run_status(approval["run_id"], "rejected", {"approval_id": approval_id})

    return {
        "approval_id": resolved["approval_id"],
        "status": resolved["status"],
        "decision": resolved["decision"],
        "reviewer": resolved["reviewer"],
        "decided_at": resolved["decided_at"],
    }
