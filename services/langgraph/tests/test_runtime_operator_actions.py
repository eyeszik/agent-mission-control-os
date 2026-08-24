from uuid import uuid4

from fastapi.testclient import TestClient

from services.langgraph.app.main import app
from services.langgraph.app.runtime_support import trust_kernel
from services.langgraph.persistence.events import list_events_for_run
from services.langgraph.persistence.runs import create_run_record

client = TestClient(app)


def test_operator_can_resolve_recovery_case_and_emit_event():
    run_id = f"run-recovery-{uuid4()}"
    project_id = f"proj-recovery-{uuid4()}"
    create_run_record(run_id, "tenant-events-test", project_id, "branding_marketing_agency", "failed", {})
    kernel = trust_kernel()
    kernel.bind_project(tenant_id="tenant-events-test", project_id=project_id)
    recovery = kernel.open_recovery_case(
        tenant_id="tenant-events-test",
        project_id=project_id,
        operation_id=f"agency.resume:{run_id}",
        reason="EXECUTION_WITHOUT_OBSERVATION",
        execution_ref=run_id,
    )

    response = client.post(
        f"/runtime/projects/{project_id}/trust/recovery/{recovery.recovery_id}/resolve",
        json={"status": "RECONCILED", "run_id": run_id},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["recovery_id"] == recovery.recovery_id
    assert payload["status"] == "RECONCILED"

    trust = client.get(f"/runtime/projects/{project_id}/trust")
    assert trust.status_code == 200
    body = trust.json()
    assert body["open_recovery_cases"] == 0
    assert body["resolved_recovery_cases"] >= 1

    events = list_events_for_run(run_id)
    assert any(event["event_type"] == "recovery_case_updated" for event in events)


def test_operator_can_replay_failed_outbox_and_emit_event():
    run_id = f"run-outbox-{uuid4()}"
    project_id = f"proj-outbox-{uuid4()}"
    create_run_record(run_id, "tenant-events-test", project_id, "branding_marketing_agency", "completed", {})
    kernel = trust_kernel()
    kernel.bind_project(tenant_id="tenant-events-test", project_id=project_id)
    message = kernel.enqueue_outbox(
        tenant_id="tenant-events-test",
        project_id=project_id,
        message_id=f"outbox-{uuid4()}",
        topic="agency.delivery.completed",
        payload={"run_id": run_id, "status": "completed"},
        payload_ref=run_id,
        idempotency_key=str(uuid4()),
    )
    kernel.mark_outbox_failed(message_id=message.message_id, error="SyntheticError")

    response = client.post(
        f"/runtime/projects/{project_id}/trust/outbox/{message.message_id}/replay",
        json={"run_id": run_id},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["message_id"] == message.message_id
    assert payload["status"] == "DELIVERED"

    trust = client.get(f"/runtime/projects/{project_id}/trust")
    assert trust.status_code == 200
    body = trust.json()
    assert body["delivered_outbox"] >= 1
    assert any(item["message_id"] == message.message_id and item["status"] == "DELIVERED" for item in body["recent_outbox_messages"])

    events = list_events_for_run(run_id)
    assert any(event["event_type"] == "outbox_updated" for event in events)
