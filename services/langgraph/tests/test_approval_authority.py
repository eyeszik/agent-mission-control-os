from uuid import uuid4

from fastapi.testclient import TestClient

from services.langgraph.app.config import production_config_errors
from services.langgraph.app.main import app
from services.langgraph.persistence.approvals import create_approval_request, get_approval
from services.langgraph.persistence.runs import create_run_record, get_run_record

client = TestClient(app)
TENANT = "tenant-events-test"


def _pending_approval(initiated_by: str | None) -> dict:
    run_id = f"run-authority-{uuid4()}"
    project_id = f"proj-authority-{uuid4()}"
    metadata = {"initiated_by": initiated_by} if initiated_by else {}
    create_run_record(run_id, TENANT, project_id, "branding_marketing_agency", "needs_approval", metadata)
    return create_approval_request(run_id, TENANT, project_id, "review", 0.5)


def _decide(approval_id: str, decision: str = "approve"):
    return client.post(f"/approvals/{approval_id}/decide", json={"decision": decision}, headers={"Idempotency-Key": str(uuid4())})


def _enforced(monkeypatch, *, role: str = "reviewer", user: str = "reviewer-1") -> None:
    monkeypatch.setenv("AMC_LOCAL_ROLE", role)
    monkeypatch.setenv("AMC_LOCAL_USER_ID", user)
    monkeypatch.delenv("AMC_ALLOW_SELF_APPROVAL", raising=False)


def test_operator_role_cannot_decide_approvals(monkeypatch):
    _enforced(monkeypatch, role="operator")
    approval = _pending_approval("someone-else")
    for decision in ("approve", "reject"):
        response = _decide(approval["approval_id"], decision)
        assert response.status_code == 403
        assert "approver role" in response.json()["detail"]
    assert get_approval(approval["approval_id"])["status"] == "pending"


def test_initiator_cannot_approve_their_own_run(monkeypatch):
    _enforced(monkeypatch, user="author-1")
    approval = _pending_approval("author-1")
    response = _decide(approval["approval_id"])
    assert response.status_code == 403
    assert "started a run" in response.json()["detail"]
    assert get_approval(approval["approval_id"])["status"] == "pending"


def test_initiator_may_still_reject_their_own_run(monkeypatch):
    _enforced(monkeypatch, user="author-2")
    approval = _pending_approval("author-2")
    response = _decide(approval["approval_id"], "reject")
    assert response.status_code == 200
    assert get_run_record(approval["run_id"])["status"] == "rejected"


def test_run_without_recorded_initiator_cannot_be_approved(monkeypatch):
    _enforced(monkeypatch)
    approval = _pending_approval(None)
    response = _decide(approval["approval_id"])
    assert response.status_code == 403
    assert "separation of duties" in response.json()["detail"]


def test_different_reviewer_can_approve(monkeypatch):
    _enforced(monkeypatch, user="reviewer-2")
    approval = _pending_approval("author-3")
    response = _decide(approval["approval_id"])
    assert response.status_code == 200
    assert response.json()["reviewer"] == "reviewer-2"


def test_approver_roles_are_configurable(monkeypatch):
    _enforced(monkeypatch, role="brand_lead", user="lead-1")
    approval = _pending_approval("author-4")
    assert _decide(approval["approval_id"]).status_code == 403
    monkeypatch.setenv("AMC_APPROVER_ROLES", "brand_lead")
    assert _decide(approval["approval_id"]).status_code == 200


def test_created_runs_record_their_initiator(monkeypatch):
    monkeypatch.setenv("AMC_LOCAL_USER_ID", "creator-1")
    response = client.post(
        "/agency/runs",
        json={"project_id": f"proj-authority-{uuid4()}", "brief": {"brand_name": "Northwind", "target_audience": "Makers"}},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 201
    assert get_run_record(response.json()["run_id"])["metadata"]["initiated_by"] == "creator-1"


def test_self_approval_switch_is_rejected_in_production(monkeypatch):
    monkeypatch.setenv("AMC_ENV", "production")
    monkeypatch.setenv("AMC_ALLOW_SELF_APPROVAL", "1")
    assert "AMC_ALLOW_SELF_APPROVAL must not be enabled in production" in production_config_errors()


def test_self_approval_switch_has_no_effect_in_production(monkeypatch):
    from services.langgraph.security.approval_authority import self_approval_allowed

    monkeypatch.setenv("AMC_ALLOW_SELF_APPROVAL", "1")
    monkeypatch.setenv("AMC_ENV", "production")
    assert self_approval_allowed() is False
    monkeypatch.setenv("AMC_ENV", "local")
    assert self_approval_allowed() is True
