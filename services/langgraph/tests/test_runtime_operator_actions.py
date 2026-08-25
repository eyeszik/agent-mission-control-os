from uuid import uuid4

from fastapi.testclient import TestClient

from services.langgraph.app.main import app
from services.langgraph.app.runtime_support import trust_kernel
from services.langgraph.persistence.approvals import create_approval_request, mark_approval_stale, resolve_approval
from services.langgraph.persistence.events import list_events_for_run
from services.langgraph.persistence.lineage import list_project_lineage_remediations
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


def test_operator_can_retry_failed_run_from_recovery(monkeypatch):
    run_id = f"run-retry-{uuid4()}"
    project_id = f"proj-retry-{uuid4()}"
    create_run_record(
        run_id,
        "tenant-events-test",
        project_id,
        "branding_marketing_agency",
        "failed",
        {"agency": {"qa_report": {"brand_safety_passed": True}}},
    )
    approval = create_approval_request(run_id, "tenant-events-test", project_id, "retry delivery", 0.8)
    resolve_approval(approval["approval_id"], reviewer="qa-bot", decision="approve")
    kernel = trust_kernel()
    kernel.bind_project(tenant_id="tenant-events-test", project_id=project_id)
    recovery = kernel.open_recovery_case(
        tenant_id="tenant-events-test",
        project_id=project_id,
        operation_id=f"agency.resume:{run_id}",
        reason="EXECUTION_WITHOUT_OBSERVATION",
        execution_ref=run_id,
    )

    def fake_resume(*_args, **_kwargs):
        return {
            "run_id": run_id,
            "project_id": project_id,
            "status": "completed",
            "approvals": [],
            "proof": {"summary": {"dispatch_count": 2, "execution_count": 2, "observation_count": 2, "matched_observation_count": 2, "failure_count": 0, "latest_terminal_candidate": "COMPLETE", "latest_confidence": 0.96}},
            "delivery": {"format": "json_bundle_v1", "approval_id": approval["approval_id"], "campaign_package": {}, "delivered_at": "2026-08-24T00:00:00+00:00"},
        }

    monkeypatch.setattr("services.langgraph.api.routes.agency.resume_agency_run", fake_resume)

    response = client.post(
        f"/runtime/runs/{run_id}/remediation/retry",
        json={"recovery_id": recovery.recovery_id},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "retry_blocked_execution"
    assert payload["run"]["status"] == "completed"
    assert payload["recovery_case"]["status"] == "RECONCILED"

    events = list_events_for_run(run_id)
    assert any(event["event_type"] == "run_remediation_updated" for event in events)
    assert any(event["event_type"] == "recovery_case_updated" for event in events)


def test_operator_can_compensate_ambiguous_recovery_case():
    run_id = f"run-compensate-{uuid4()}"
    project_id = f"proj-compensate-{uuid4()}"
    create_run_record(run_id, "tenant-events-test", project_id, "branding_marketing_agency", "failed", {})
    kernel = trust_kernel()
    kernel.bind_project(tenant_id="tenant-events-test", project_id=project_id)
    recovery = kernel.open_recovery_case(
        tenant_id="tenant-events-test",
        project_id=project_id,
        operation_id=f"agency.resume:{run_id}",
        reason="AMBIGUOUS_EXTERNAL_RESULT",
        execution_ref=run_id,
    )

    response = client.post(
        f"/runtime/runs/{run_id}/remediation/compensate",
        json={"recovery_id": recovery.recovery_id},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "compensate_ambiguous_result"
    assert payload["recovery_case"]["status"] == "COMPENSATED"

    events = list_events_for_run(run_id)
    assert any(event["event_type"] == "run_remediation_updated" for event in events)
    assert any(event["event_type"] == "recovery_case_updated" for event in events)


def test_operator_can_regenerate_stale_approval_chain():
    run_id = f"run-approval-{uuid4()}"
    project_id = f"proj-approval-{uuid4()}"
    create_run_record(
        run_id,
        "tenant-events-test",
        project_id,
        "branding_marketing_agency",
        "needs_approval",
        {"agency": {"campaign_package": {"brief": {"brand_name": "Northwind"}}, "qa_report": {"brand_safety_passed": True}, "generation_provenance": [], "degraded": False}},
    )
    approval = create_approval_request(run_id, "tenant-events-test", project_id, "review payload hash", 0.5)
    mark_approval_stale(approval["approval_id"], "content changed")

    response = client.post(
        f"/runtime/runs/{run_id}/remediation/regenerate-approval",
        json={"approval_id": approval["approval_id"]},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "regenerate_approval"
    assert payload["pending_approval"]["status"] == "pending"
    assert payload["pending_approval"]["approval_id"] != approval["approval_id"]

    events = list_events_for_run(run_id)
    assert any(event["event_type"] == "approval_requested" for event in events)
    assert any(event["event_type"] == "run_remediation_updated" for event in events)


def test_artifact_revision_trust_projection_opens_lineage_remediation():
    run_id = f"run-lineage-{uuid4()}"
    project_id = f"proj-lineage-{uuid4()}"
    create_run_record(
        run_id,
        "tenant-events-test",
        project_id,
        "branding_marketing_agency",
        "needs_approval",
        {"agency": {"campaign_package": {"brief": {"brand_name": "Northwind"}}, "qa_report": {"brand_safety_passed": True}, "generation_provenance": [], "degraded": False}},
    )
    create_approval_request(run_id, "tenant-events-test", project_id, "review artifact", 0.7)

    response = client.post(
        f"/runtime/runs/{run_id}/artifacts/protected/revise",
        json={"content_hash": "c" * 64},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["changed_version_ref"].endswith(":v2")
    trust = payload["trust"]
    assert trust["open_lineage_remediations"] >= 1
    assert trust["recent_lineage_remediations"][0]["run_id"] == run_id

    queue = list_project_lineage_remediations(project_id, "tenant-events-test")
    assert queue[0]["run_id"] == run_id
    assert queue[0]["status"] == "OPEN"


def test_resume_delivery_blocks_on_hook_gap_and_trust_projection_matches():
    run_id = f"run-delivery-gap-{uuid4()}"
    project_id = f"proj-delivery-gap-{uuid4()}"
    kernel = trust_kernel()
    kernel.bind_project(tenant_id="tenant-events-test", project_id=project_id)
    create_run_record(run_id, "tenant-events-test", project_id, "branding_marketing_agency", "running", {})
    from services.langgraph.persistence.runs import update_run_status
    update_run_status(
        run_id,
        "needs_approval",
        {
            "agency": {
                "campaign_package": {"brief": {"brand_name": "Northwind"}},
                "qa_report": {"brand_safety_passed": True},
                "generation_provenance": [],
                "degraded": False,
            }
        },
    )
    approval = create_approval_request(run_id, "tenant-events-test", project_id, "release review", 0.8)
    resolve_approval(approval["approval_id"], reviewer="qa-bot", decision="approve")

    response = client.post(
        f"/agency/runs/{run_id}/resume",
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 409
    assert "blocked" in response.json()["detail"].lower()

    trust = client.get(f"/runtime/projects/{project_id}/trust")
    assert trust.status_code == 200
    payload = trust.json()
    assert payload["compile_blocked"] is True
    assert payload["hook_gap_count"] >= 1
    assert any(item["run_id"] == run_id and item["state"] == "HOOK_GAP" for item in payload["recent_invalidation_obligations"])
