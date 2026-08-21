from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from services.langgraph.app.main import app
from services.langgraph.persistence.database import table, transaction

client = TestClient(app)


def _idem() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid4())}


def _event_names(run_id: str) -> list[str]:
    with transaction() as db:
        rows = db.execute(
            f"SELECT event_name FROM {table('analytics_events')} WHERE run_id = ? ORDER BY occurred_at ASC",
            (run_id,),
        ).fetchall()
    return [row["event_name"] for row in rows]


def test_agency_and_external_action_boundaries_emit_first_party_lifecycle_analytics():
    project_id = f"proj-lifecycle-{uuid4()}"
    created = client.post(
        "/agency/runs",
        json={
            "project_id": project_id,
            "brief": {
                "brand_name": "Lifecycle Test Brand",
                "target_audience": "Operations teams",
            },
        },
        headers=_idem(),
    )
    assert created.status_code == 201
    payload = created.json()
    run_id = payload["run_id"]
    approval_id = payload["pending_approval"]["approval_id"]

    names = _event_names(run_id)
    assert "agency_run_created" in names
    assert "agency_run_needs_approval" in names

    publication = client.post(
        "/operations/publications/preview",
        json={
            "run_id": run_id,
            "provider": "test-provider",
            "payload": {"asset_id": "safe-test-asset"},
        },
        headers=_idem(),
    )
    assert publication.status_code == 201
    assert publication.json()["status"] in {"blocked", "validated"}

    spend = client.post(
        "/operations/spend/authorizations",
        json={
            "project_id": project_id,
            "run_id": run_id,
            "provider": "test-provider",
            "amount_minor": 1000,
            "currency": "usd",
            "reason": "Lifecycle analytics test only",
        },
    )
    assert spend.status_code == 201
    assert spend.json()["status"] == "pending"

    decision = client.post(
        f"/approvals/{approval_id}/decide",
        json={"decision": "reject"},
        headers=_idem(),
    )
    assert decision.status_code == 200

    names = _event_names(run_id)
    for required in [
        "publication_previewed",
        "spend_authorization_requested",
        "agency_approval_decided",
        "agency_run_rejected",
    ]:
        assert required in names
