from services.langgraph.persistence.approvals import (
    bind_approval_subject,
    create_approval_request,
    get_approval,
    list_pending_approvals,
    mark_approval_stale,
    resolve_approval,
)

def test_approval_lifecycle():
    req = create_approval_request("run-1", "tenant-1", "proj-1", "confidence below 0.65", 0.42)
    assert req["status"] == "pending"

    pending = list_pending_approvals(tenant_id="tenant-1")
    assert any(a["approval_id"] == req["approval_id"] for a in pending)

    result = resolve_approval(req["approval_id"], reviewer="isaac", decision="approve")
    assert result["decision"] == "approve"

    pending_after = list_pending_approvals(tenant_id="tenant-1")
    assert not any(a["approval_id"] == req["approval_id"] for a in pending_after)


def test_approval_subject_binding_and_stale_marking():
    req = create_approval_request("run-2", "tenant-1", "proj-1", "review payload hash", None)
    bound = bind_approval_subject(
        req["approval_id"],
        subject_hash="a" * 64,
        subject_ref="run-2",
        subject_version_ref="run-2",
        authority_ref="human-review",
        policy_version="amc-approval/v1",
    )
    assert bound["subject_hash"] == "a" * 64
    assert bound["authority_ref"] == "human-review"

    stale = mark_approval_stale(req["approval_id"], "content changed")
    assert stale["status"] == "stale"
    assert stale["stale_reason"] == "content changed"
    assert get_approval(req["approval_id"])["status"] == "stale"

    assert resolve_approval(req["approval_id"], reviewer="isaac", decision="approve") is None
