from services.langgraph.persistence.approvals import create_approval_request, list_pending_approvals, resolve_approval

def test_approval_lifecycle():
    req = create_approval_request("run-1", "tenant-1", "proj-1", "confidence below 0.65", 0.42)
    assert req["status"] == "pending"

    pending = list_pending_approvals(tenant_id="tenant-1")
    assert any(a["approval_id"] == req["approval_id"] for a in pending)

    result = resolve_approval(req["approval_id"], reviewer="isaac", decision="approve")
    assert result["decision"] == "approve"

    pending_after = list_pending_approvals(tenant_id="tenant-1")
    assert not any(a["approval_id"] == req["approval_id"] for a in pending_after)
