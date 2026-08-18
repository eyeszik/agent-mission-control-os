from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from services.langgraph.persistence.approvals import list_pending_approvals, resolve_approval

router = APIRouter()

class ApprovalDecision(BaseModel):
    reviewer: str
    decision: str  # "approve" | "reject"

@router.get("")
def get_pending_approvals(tenant_id: Optional[str] = None):
    return list_pending_approvals(tenant_id)

@router.post("/{approval_id}/decide")
def decide_approval(approval_id: str, body: ApprovalDecision):
    if body.decision not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="decision must be 'approve' or 'reject'")
    return resolve_approval(approval_id, body.reviewer, body.decision)
