import json
from uuid import uuid4

from fastapi.testclient import TestClient

from services.langgraph.app.main import app
from services.langgraph.persistence.events import list_events_for_run, record_event
from services.langgraph.persistence.runs import create_run_record

client = TestClient(app)


def _parse_sse_events(body: str) -> list:
    events = []
    for line in body.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
    return events


def test_record_and_list_events_are_ordered_by_sequence():
    run_id = f"run-events-{uuid4()}"
    record_event(run_id, "tenant-events-test", "proj-events-test", "brief_intake", "node_complete")
    record_event(run_id, "tenant-events-test", "proj-events-test", "brand_strategy", "node_complete")
    events = list_events_for_run(run_id)
    assert [event["sequence"] for event in events] == [0, 1]
    assert [event["node_id"] for event in events] == ["brief_intake", "brand_strategy"]
    assert all(event["schema_version"] == "run-event-v2" for event in events)


def test_cursor_returns_only_events_after_acknowledged_sequence():
    run_id = f"run-cursor-{uuid4()}"
    create_run_record(run_id, "tenant-events-test", "proj-events-test", "branding_marketing_agency", "completed", {})
    for node in ["brief_intake", "brand_strategy", "copywriting"]:
        record_event(run_id, "tenant-events-test", "proj-events-test", node, "node_complete")

    response = client.get(f"/runs/{run_id}/events?cursor=0")
    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    assert [event["sequence"] for event in events] == [1, 2]


def test_last_event_id_resumes_after_header_cursor():
    run_id = f"run-header-{uuid4()}"
    create_run_record(run_id, "tenant-events-test", "proj-events-test", "branding_marketing_agency", "completed", {})
    for node in ["brief_intake", "brand_strategy", "copywriting"]:
        record_event(run_id, "tenant-events-test", "proj-events-test", node, "node_complete")

    response = client.get(f"/runs/{run_id}/events", headers={"Last-Event-ID": "1"})
    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    assert [event["sequence"] for event in events] == [2]


def test_events_endpoint_replays_completed_agency_stage_observations():
    create_resp = client.post(
        "/agency/runs",
        json={
            "tenant_id": "tenant-events-test",
            "project_id": "proj-events-test",
            "brief": {"brand_name": "Acme", "target_audience": "Developers"},
        },
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert create_resp.status_code == 201
    run_id = create_resp.json()["run_id"]

    response = client.get(f"/runs/{run_id}/events")
    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    node_ids = [event["node_id"] for event in events]
    for stage in [
        "brief_intake",
        "brand_strategy",
        "creative_concepting",
        "copywriting",
        "design_brief",
        "campaign_assembly",
        "brand_safety_qa",
        "hitl_gate",
    ]:
        assert stage in node_ids
    assert "delivery" not in node_ids
    assert all(event["event_type"] == "node_complete" for event in events)
    assert all(event["started_at"] is None for event in events)
    assert all(event["completed_at"] is not None for event in events)


def test_unknown_run_event_stream_returns_404():
    response = client.get(f"/runs/{uuid4()}/events")
    assert response.status_code == 404


def test_foreign_tenant_event_stream_is_denied():
    run_id = f"run-foreign-{uuid4()}"
    create_run_record(run_id, "tenant-other", "proj-other", "branding_marketing_agency", "completed", {})
    response = client.get(f"/runs/{run_id}/events")
    assert response.status_code == 403
