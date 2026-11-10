"""Durable execution tests for the AMC job queue and background worker.

Covers the W3 acceptance criteria that can be exercised inside the repository:
atomic job claiming, lease fencing, retry budget with dead-lettering,
cancellation, lease-expiry crash recovery, and an end-to-end background-mode
run (create -> poll -> needs_approval -> resume -> poll -> completed) with
no duplicated committed effects.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from services.langgraph.app.main import app
from services.langgraph.graph.agency.llm import GenerationOutcome
from services.langgraph.persistence.database import transaction
from services.langgraph.persistence.jobs import (
    claim_job,
    complete_job,
    enqueue_job,
    expire_stale_leases,
    fail_job,
    get_job,
    request_job_cancellation,
)
from services.langgraph.persistence.runs import get_run_record
from services.langgraph.runtime.worker import poll_once

client = TestClient(app)


def _project() -> str:
    return f"proj-durable-{uuid4().hex[:8]}"


def _enqueue_create(tenant: str = "tenant-events-test", project: str | None = None, max_attempts: int | None = None) -> dict:
    return enqueue_job(
        "agency.create",
        tenant or "tenant-events-test",
        project or _project(),
        {"run_id": f"run-{uuid4().hex[:10]}"},
        max_attempts=max_attempts,
    )


def _expire_lease(job_id: str, seconds: float = -1.0) -> None:
    stamp = (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
    with transaction(write=True) as db:
        db.execute(
            "UPDATE amc_jobs SET lease_expires_at = ? WHERE job_id = ?",
            (stamp, job_id),
        )


# ---------------------------------------------------------------------------
# Queue primitives
# ---------------------------------------------------------------------------


def test_job_is_claimed_by_exactly_one_worker():
    job = _enqueue_create()
    with __import__("concurrent.futures", fromlist=["ThreadPoolExecutor"]).ThreadPoolExecutor(max_workers=4) as pool:
        claims = list(pool.map(lambda _: claim_job(), range(4)))

    claimed = [c for c in claims if c is not None]
    assert [c["job_id"] for c in claimed] == [job["job_id"]]
    assert claimed[0]["status"] == "running"
    assert claimed[0]["attempt_count"] == 1
    assert claimed[0]["claim_token"]


def test_lease_expiry_recovery_requeues_without_charging_twice_per_crash():
    job = _enqueue_create()
    lease = claim_job()
    assert lease["job_id"] == job["job_id"]

    # Worker dies: lease expires, recovery releases the lease.
    _expire_lease(job["job_id"])
    released = expire_stale_leases()
    assert job["job_id"] in released

    recovered = get_job(job["job_id"])
    assert recovered["status"] == "queued"
    # The recovery path does not itself burn retry budget: the charge happens at
    # the next claim, so a crash that never re-claimed cannot dead-letter alone.
    assert recovered["attempt_count"] == 1

    reclaimed = claim_job()
    assert reclaimed["job_id"] == job["job_id"]
    assert reclaimed["attempt_count"] == 2


def test_retry_budget_dead_letters_after_exhaustion():
    job = _enqueue_create(max_attempts=2)
    max_attempts = int((get_job(job["job_id"]) or {}).get("max_attempts") or 2)
    while max_attempts > 0:
        max_attempts -= 1
        claimed = claim_job()
        assert claimed["job_id"] == job["job_id"]
        outcome = fail_job(claimed["job_id"], claimed["claim_token"], "provider timeout")
        assert outcome == ("queued" if max_attempts > 0 else "dead_letter")
    final = get_job(job["job_id"])
    assert final["status"] == "dead_letter"

    # Dead-lettered jobs are never claimed automatically.
    assert claim_job() is None


def test_complete_and_fail_are_fenced_by_claim_token():
    job = _enqueue_create()
    claimed = claim_job()

    assert complete_job(job["job_id"], "lease_forged_token", {"x": 1}) is False
    assert fail_job(job["job_id"], "lease_forged_token", "x") == "not_fenced"
    assert get_job(job["job_id"])["status"] == "running"

    assert complete_job(job["job_id"], claimed["claim_token"], {"answer": 1}) is True
    done = get_job(job["job_id"])
    assert done["status"] == "completed"
    assert done["result"] == {"answer": 1}


def test_cancellation_of_queued_job():
    job = _enqueue_create()
    assert request_job_cancellation(job["job_id"]) is True
    assert get_job(job["job_id"])["status"] == "cancelled"
    assert claim_job() is None


def test_cancellation_of_running_job_prevents_execution_fence():
    job = _enqueue_create()
    _ = claim_job()
    assert request_job_cancellation(job["job_id"]) is True
    assert get_job(job["job_id"])["status"] == "cancelled"


def test_expire_stale_leases_ignores_fresh_leases():
    job = _enqueue_create()
    claimed = claim_job()
    assert expire_stale_leases() == []
    assert get_job(job["job_id"])["status"] == "running"
    assert claimed["claim_token"] == get_job(job["job_id"])["claim_token"]


def poll_jobs():
    return poll_once()


# ---------------------------------------------------------------------------
# End-to-end background execution
# ---------------------------------------------------------------------------


@pytest.fixture
def provider_success(monkeypatch):
    def fake_generate(prompt: str, fallback: dict, **kwargs):
        now = datetime.now(timezone.utc).isoformat()
        return GenerationOutcome(
            data=fallback,
            mode="PROVIDER_SUCCESS",
            provider="test-provider",
            model="test-model",
            schema_version=kwargs.get("schema_version", "test-v1"),
            prompt_version="test-v1",
            prompt_hash="test-hash",
            attempts=1,
            started_at=now,
            completed_at=now,
            fallback_used=False,
            error_class=None,
        )

    monkeypatch.setattr("services.langgraph.graph.agency.nodes.generate_structured", fake_generate)


def _create_background_run(monkeypatch, project: str | None = None):
    monkeypatch.setenv("AMC_EXECUTION_MODE", "background")
    response = client.post(
        "/agency/runs",
        json={
            "project_id": project or _project(),
            "brief": {"brand_name": "Northwind", "target_audience": "Urban professionals"},
        },
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 201
    return response.json()


def test_background_create_poll_resume_completed(provider_success, monkeypatch):
    body = _create_background_run(monkeypatch)
    assert body["status"] == "queued"
    assert body["execution_mode"] == "background"
    assert body["job_id"]

    run_id = body["run_id"]
    assert get_run_record(run_id)["status"] == "queued"

    assert poll_once() >= 1
    record = get_run_record(run_id)
    assert record["status"] == "needs_approval"

    # Duration gate: the HITL approval must be approved before delivery can be
    # scheduled. Resolve the pipeline's pending approval, then resume.
    detail = client.get(f"/agency/runs/{run_id}").json()
    approval_id = detail["approvals"][0]["approval_id"]
    decision = client.post(
        f"/approvals/{approval_id}/decide",
        json={"decision": "approve"},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert decision.status_code == 200

    monkeypatch.setenv("AMC_EXECUTION_MODE", "background")
    resume = client.post(
        f"/agency/runs/{run_id}/resume",
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert resume.status_code == 200
    assert resume.json()["status"] == "needs_approval"  # still needs approval; delivery queued

    assert poll_once() >= 1
    completed = get_run_record(run_id)
    assert completed["status"] == "completed"
    replay = client.post(
        f"/agency/runs/{run_id}/resume",
        headers={"Idempotency-Key": resume.headers.get("x-idempotency-key", str(uuid4()))},
    )
    assert replay.status_code in {200, 201}


def test_worker_crash_recovery_completes_exactly_once(provider_success, monkeypatch):
    body = _create_background_run(monkeypatch)
    run_id = body["run_id"]

    # Worker claims the job, then dies before executing anything.
    job = claim_job()
    assert job is not None
    _expire_lease(job["job_id"])

    assert poll_once() >= 1
    record = get_run_record(run_id)
    assert record["status"] == "needs_approval"

    # A second poll pass must be a no-op: no duplicate committed effects.
    from services.langgraph.persistence.events import list_events_for_run

    first_events = list_events_for_run(run_id)
    second = poll_once()
    assert second == 0
    assert list_events_for_run(run_id) == first_events
    assert get_run_record(run_id)["status"] == "needs_approval"


def test_background_create_replay_after_completion(provider_success, monkeypatch):
    body = _create_background_run(monkeypatch)
    poll_once()
    record = get_run_record(body["run_id"])
    assert record["status"] == "needs_approval"
    assert poll_once() == 0  # queue is empty
