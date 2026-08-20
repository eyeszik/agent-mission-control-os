import json
from uuid import uuid4

from fastapi.testclient import TestClient

from services.langgraph.app.main import app
from services.langgraph.persistence.approvals import create_approval_request, get_approval, resolve_approval
from services.langgraph.persistence.runs import create_run_record, get_run_record
from services.langgraph.security.preprocess import sanitize_deep

client = TestClient(app)


def test_cross_tenant_run_access_is_denied():
    run_id = str(uuid4())
    create_run_record(run_id, "tenant-other", "proj-other", "branding_marketing_agency", "running", {})
    response = client.get(f"/agency/runs/{run_id}")
    assert response.status_code == 403


def test_client_tenant_substitution_is_denied():
    response = client.post(
        "/agency/runs",
        json={
            "tenant_id": "tenant-other",
            "project_id": "proj-security",
            "brief": {"brand_name": "Acme", "target_audience": "Developers"},
        },
    )
    assert response.status_code == 403


def test_nested_sensitive_canaries_are_redacted_before_persistence():
    canaries = {
        "email": "canary@example.test",
        "phone": "213-555-0199",
        "ssn": "123-45-6789",
        "card": "4111111111111111",
    }
    response = client.post(
        "/agency/runs",
        json={
            "project_id": "proj-security",
            "brief": {
                "brand_name": canaries["email"],
                "target_audience": "Developers",
                "goals": [canaries["phone"], canaries["ssn"], canaries["card"]],
            },
        },
    )
    assert response.status_code == 201
    record = get_run_record(response.json()["run_id"])
    serialized = json.dumps(record["metadata"])
    for raw in canaries.values():
        assert raw not in serialized
    assert "REDACTED_EMAIL" in serialized
    assert "REDACTED_PHONE" in serialized
    assert "REDACTED_SSN" in serialized
    assert "REDACTED_CREDIT_CARD" in serialized


def test_nested_control_language_is_sanitized_recursively():
    control_phrase = "system " + "prompt"
    cleaned = sanitize_deep({"constraints": [control_phrase]})
    assert control_phrase not in cleaned["constraints"][0].lower()
    assert "MALICIOUS_INTENT_REDACTED" in cleaned["constraints"][0]


def test_approval_terminal_decision_cannot_be_overwritten():
    approval = create_approval_request("run-cas", "tenant-events-test", "proj-security", "review", 0.5)
    first = resolve_approval(approval["approval_id"], "first-reviewer", "approve")
    second = resolve_approval(approval["approval_id"], "second-reviewer", "reject")
    persisted = get_approval(approval["approval_id"])
    assert first is not None
    assert second is None
    assert persisted["decision"] == "approve"
    assert persisted["reviewer"] == "first-reviewer"


def test_invalid_approval_id_returns_404():
    response = client.post(f"/approvals/{uuid4()}/decide", json={"decision": "approve"})
    assert response.status_code == 404


def test_rejection_uses_server_reviewer_and_terminal_run_state():
    create_response = client.post(
        "/agency/runs",
        json={
            "project_id": "proj-security",
            "brief": {"brand_name": "Acme", "target_audience": "Developers"},
        },
    )
    assert create_response.status_code == 201
    body = create_response.json()
    approval_id = body["pending_approval"]["approval_id"]

    decision = client.post(f"/approvals/{approval_id}/decide", json={"decision": "reject"})
    assert decision.status_code == 200
    assert decision.json()["reviewer"] == "test-operator"

    record = get_run_record(body["run_id"])
    assert record["status"] == "rejected"
