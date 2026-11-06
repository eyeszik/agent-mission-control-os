import json
from uuid import uuid4

from fastapi.testclient import TestClient

from services.langgraph.app.main import app
from services.langgraph.persistence.approvals import create_approval_request, get_approval, resolve_approval
from services.langgraph.persistence.runs import create_run_record, get_run_record
from services.langgraph.security.preprocess import sanitize_deep

client = TestClient(app)


def _idem() -> dict:
    return {"Idempotency-Key": str(uuid4())}


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
        headers=_idem(),
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
        headers=_idem(),
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
    run_id = f"run-cas-{uuid4()}"
    create_run_record(run_id, "tenant-events-test", "proj-security", "branding_marketing_agency", "needs_approval", {})
    approval = create_approval_request(run_id, "tenant-events-test", "proj-security", "review", 0.5)
    first = resolve_approval(approval["approval_id"], "first-reviewer", "approve")
    second = resolve_approval(approval["approval_id"], "second-reviewer", "reject")
    persisted = get_approval(approval["approval_id"])
    assert first is not None
    assert second is None
    assert persisted["decision"] == "approve"
    assert persisted["reviewer"] == "first-reviewer"


def test_invalid_approval_id_returns_404():
    response = client.post(
        f"/approvals/{uuid4()}/decide",
        json={"decision": "approve"},
        headers=_idem(),
    )
    assert response.status_code == 404


def test_rejection_uses_server_reviewer_and_terminal_run_state():
    create_response = client.post(
        "/agency/runs",
        json={
            "project_id": "proj-security",
            "brief": {"brand_name": "Acme", "target_audience": "Developers"},
        },
        headers=_idem(),
    )
    assert create_response.status_code == 201
    body = create_response.json()
    approval_id = body["pending_approval"]["approval_id"]

    decision = client.post(
        f"/approvals/{approval_id}/decide",
        json={"decision": "reject"},
        headers=_idem(),
    )
    assert decision.status_code == 200
    assert decision.json()["reviewer"] == "test-operator"

    record = get_run_record(body["run_id"])
    assert record["status"] == "rejected"


def _foreign_recovery_case():
    """A recovery case owned by another tenant, plus a project the caller owns."""
    from services.langgraph.app.runtime_support import trust_kernel

    victim_run = f"run-victim-{uuid4()}"
    victim_project = f"proj-victim-{uuid4()}"
    create_run_record(victim_run, "tenant-victim", victim_project, "branding_marketing_agency", "failed", {})
    kernel = trust_kernel()
    kernel.bind_project(tenant_id="tenant-victim", project_id=victim_project)
    case = kernel.open_recovery_case(
        tenant_id="tenant-victim",
        project_id=victim_project,
        operation_id=f"agency.resume:{victim_run}",
        reason="EXECUTION_WITHOUT_OBSERVATION",
        execution_ref=victim_run,
    )
    own_project = f"proj-own-{uuid4()}"
    # Reading the trust view binds the caller's own project, as the UI does.
    assert client.get(f"/runtime/projects/{own_project}/trust").status_code == 200
    return kernel, case, victim_run, own_project


def test_foreign_recovery_case_cannot_be_resolved_from_own_project():
    from services.langgraph.agency.reliability.models import RecoveryStatus
    from services.langgraph.persistence.events import list_events_for_run

    kernel, case, victim_run, own_project = _foreign_recovery_case()

    response = client.post(
        f"/runtime/projects/{own_project}/trust/recovery/{case.recovery_id}/resolve",
        json={"status": "RECONCILED"},
        headers=_idem(),
    )

    assert response.status_code == 404
    assert kernel.store.state.recovery[case.recovery_id].status == RecoveryStatus.OPEN
    assert list_events_for_run(victim_run) == []


def test_foreign_run_id_cannot_receive_operator_events():
    from services.langgraph.agency.reliability.models import RecoveryStatus
    from services.langgraph.persistence.events import list_events_for_run

    kernel, case, victim_run, own_project = _foreign_recovery_case()
    own_run = f"run-own-{uuid4()}"
    create_run_record(own_run, "tenant-events-test", own_project, "branding_marketing_agency", "failed", {})
    own_case = kernel.open_recovery_case(
        tenant_id="tenant-events-test",
        project_id=own_project,
        operation_id=f"agency.resume:{own_run}",
        reason="EXECUTION_WITHOUT_OBSERVATION",
        execution_ref=own_run,
    )

    response = client.post(
        f"/runtime/projects/{own_project}/trust/recovery/{own_case.recovery_id}/resolve",
        json={"status": "RECONCILED", "run_id": victim_run},
        headers=_idem(),
    )

    assert response.status_code == 404
    assert kernel.store.state.recovery[own_case.recovery_id].status == RecoveryStatus.OPEN
    assert list_events_for_run(victim_run) == []


def test_foreign_outbox_message_cannot_be_replayed_or_signalled():
    from services.langgraph.persistence.events import list_events_for_run

    kernel, _case, victim_run, own_project = _foreign_recovery_case()
    message = kernel.enqueue_outbox(
        tenant_id="tenant-victim",
        project_id=kernel.store.state.recovery[_case.recovery_id].project_id,
        message_id=f"outbox-{uuid4()}",
        topic="agency.delivery.completed",
        payload={"run_id": victim_run},
        payload_ref=victim_run,
        idempotency_key=str(uuid4()),
    )

    replay = client.post(
        f"/runtime/projects/{own_project}/trust/outbox/{message.message_id}/replay",
        json={},
        headers=_idem(),
    )
    assert replay.status_code == 404

    own_message = kernel.enqueue_outbox(
        tenant_id="tenant-events-test",
        project_id=own_project,
        message_id=f"outbox-{uuid4()}",
        topic="agency.delivery.completed",
        payload={},
        payload_ref="not-a-run",
        idempotency_key=str(uuid4()),
    )
    injected = client.post(
        f"/runtime/projects/{own_project}/trust/outbox/{own_message.message_id}/replay",
        json={"run_id": victim_run},
        headers=_idem(),
    )
    assert injected.status_code == 404
    assert list_events_for_run(victim_run) == []


def test_project_registered_to_another_tenant_cannot_be_written_into():
    from services.langgraph.persistence.tenancy import ProjectOwnershipError

    project_id = f"proj-owned-{uuid4()}"
    create_run_record(f"run-{uuid4()}", "tenant-owner", project_id, "branding_marketing_agency", "running", {})

    import pytest

    with pytest.raises(ProjectOwnershipError):
        create_run_record(f"run-{uuid4()}", "tenant-events-test", project_id, "branding_marketing_agency", "running", {})

    # Through the API the same squatting attempt is a 403, not a 500 or a bind.
    response = client.get(f"/runtime/projects/{project_id}/trust")
    assert response.status_code == 403
