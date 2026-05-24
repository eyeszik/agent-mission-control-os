from fastapi import APIRouter

router = APIRouter()

@router.get("")
def list_pending_approvals():
    # Scaffold: list approvals waiting for human intervention
    return {"data": []}

@router.post("/{approval_id}/resolve")
def resolve_approval(approval_id: str, payload: dict):
    # Scaffold: Resume execution from a blocked node
    return {"status": "resolved", "action": payload.get("action")}
