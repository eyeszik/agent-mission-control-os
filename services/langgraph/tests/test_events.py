import json
from uuid import uuid4

from fastapi.testclient import TestClient

from services.langgraph.app.main import app
from services.langgraph.persistence.events import list_events_for_run, record_event

client = TestClient(app)


def test_record_and_list_events_are_ordered_by_sequence():
    run_id = "run-events-test-1"
    record_event(run_id, "brief_intake", "node_start")
    record_event(run_id, "brief_intake", "node_complete")
    record_event(run_id, "brand_strategy", "node_start")

    events = list_events_for_run(run_id)
    assert [e["node_id"] for e in events] == ["brief_intake", "brief_intake", "brand_strategy"]
    assert [e["type"] for e in events] == ["node_start", "node_complete", "node_start"]
    assert [e["sequence"] for e in events] == [0, 1, 2]


def test_list_events_for_unknown_run_is_empty():
    assert list_events_for_run("run-that-does-not-exist") == []


def _parse_sse_events(body: str) -> list:
    events = []
    for line in body.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
    return events


def test_events_endpoint_replays_real_agency_pipeline_events_not_the_old_mock():
    payload = {
        "tenant_id": "tenant-events-test",
        "project_id": "proj-events-test",
        "brief": {"brand_name": "Acme", "target_audience": "Developers"},
    }
    create_resp = client.post(
        "/agency/runs",
        json=payload,
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert create_resp.status_code == 201
    run_id = create_resp.json()["run_id"]

    sse_resp = client.get(f"/runs/{run_id}/events")
    assert sse_resp.status_code == 200
    events = _parse_sse_events(sse_resp.text)

    node_ids = [e["node_id"] for e in events]
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
    assert "ingest" not in node_ids
    assert "planner" not in node_ids
    assert events[0]["type"] == "node_start"
    assert events[1]["type"] == "node_complete"
    assert all(e["run_id"] == run_id for e in events)


def test_events_endpoint_for_unknown_run_returns_empty_stream():
    resp = client.get("/runs/some-run-id-that-was-never-created/events")
    assert resp.status_code == 200
    assert _parse_sse_events(resp.text) == []
