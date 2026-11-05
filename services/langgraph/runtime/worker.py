from __future__ import annotations

import threading
import time
from typing import Optional

from services.langgraph.graph.agency.build import build_agency_workflow
from services.langgraph.graph.models import AgentRun
from services.langgraph.persistence.analytics import emit_lifecycle_event
from services.langgraph.persistence.approvals import get_approvals_for_run
from services.langgraph.persistence.events import record_event
from services.langgraph.persistence.idempotency import complete_idempotency, fail_idempotency
from services.langgraph.persistence.jobs import (
    claim_job,
    complete_job,
    expire_stale_leases,
    fail_job,
    get_job,
    renew_job_lease,
    request_job_cancellation,
)
from services.langgraph.persistence.runs import (
    compare_and_set_run_status,
    create_run_record,
    get_run_record,
    update_run_status,
)
from services.langgraph.runtime.execution import (
    ANALYTICS_REPORTED_BLOCKS,
    DELIVERY_BLOCK_DETAIL,
    agency_payload,
    delivery_context,
    now_iso,
    run_and_record_events,
    run_config,
)

AGENCY_PIPELINE_NAME = "branding_marketing_agency"


class _LeaseHeartbeat:
    """Renews the worker's job lease in a daemon thread while work is executing,
    so a legitimately long pipeline is not stolen by lease expiry."""

    def __init__(self, job_id: str, claim_token: str, interval_seconds: float) -> None:
        self._job_id = job_id
        self._token = claim_token
        self._interval = interval_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                renew_job_lease(self._job_id, self._token)
            except Exception:
                continue

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)


def _record_run_failure(job: dict, phase: str, exc: Exception, idempotent: bool = True) -> None:
    run_id = str(job["run_id"])
    error_class = type(exc).__name__
    update_run_status(run_id, "failed", {"error": error_class})
    record_event(run_id, job["tenant_id"], job["project_id"], phase, "node_error", safe_payload={"error_class": error_class})
    emit_lifecycle_event(
        job["tenant_id"],
        job["project_id"],
        "agency_run_failed",
        {"pipeline": AGENCY_PIPELINE_NAME, "phase": phase, "error_class": error_class},
        run_id,
    )
    if idempotent:
        scope = (job["payload"] or {}).get("idempotency_scope")
        key = (job["payload"] or {}).get("idempotency_key")
        if scope and key:
            fail_idempotency(scope, key, error_class)


def _ensure_run_running(job: dict, metadata: dict) -> Optional[dict]:
    """Move the run record to 'running' (created as 'queued' at submit time), or
    revive a failed retry attempt. Returns the run record, or None if cancelled."""

    run_id = str(job["run_id"])
    record = get_run_record(run_id)
    if record is None:
        record = create_run_record(
            run_id, job["tenant_id"], job["project_id"], AGENCY_PIPELINE_NAME, "queued", metadata
        )
    status = record["status"]
    if status == "cancelled":
        return None
    if status != "running":
        if not compare_and_set_run_status(run_id, status, "running"):
            current = get_run_record(run_id)
            if current is None or current["status"] != "running":
                raise RuntimeError(f"Run {run_id} could not be moved to running")
    return get_run_record(run_id)


def _run_model_from_record(record: dict, metadata: dict) -> AgentRun:
    from datetime import datetime

    return AgentRun(
        id=str(record["run_id"]),
        tenant_id=record["tenant_id"],
        project_id=record["project_id"],
        status=record["status"],
        created_at=datetime.fromisoformat(record["created_at"]),
        updated_at=datetime.fromisoformat(record["updated_at"]),
        metadata=metadata,
    )


def _execute_create_job(job: dict) -> dict:
    payload = job["payload"]
    run_id = str(job["run_id"])
    run_record = _ensure_run_running(job, {"input_data": {"brief": payload["brief"]}})
    if run_record is None:
        return {"run_id": run_id, "status": "cancelled"}

    graph = build_agency_workflow()
    config = run_config(run_id)
    run = _run_model_from_record(run_record, {"input_data": {"brief": payload["brief"]}})
    initial_state = {
        "run": run,
        "current_node": "start",
        "messages": [],
        "extracted_data": {},
        "validation_status": "pending",
    }
    state = run_and_record_events(graph, initial_state, config, run)
    agency_data = agency_payload(state)
    record = update_run_status(run_id, "needs_approval", {"agency": agency_data})
    run_approvals = get_approvals_for_run(run_id)
    release_blocked = bool((agency_data.get("qa_report") or {}).get("release_blocked"))
    emit_lifecycle_event(
        job["tenant_id"],
        job["project_id"],
        "agency_run_needs_approval",
        {
            "pipeline": AGENCY_PIPELINE_NAME,
            "status": record["status"],
            "degraded": bool(agency_data.get("degraded")),
            "release_blocked": release_blocked,
        },
        run_id,
    )
    response = {
        "run_id": run_id,
        "status": record["status"],
        "pipeline": AGENCY_PIPELINE_NAME,
        "campaign_package": agency_data.get("campaign_package"),
        "qa_report": agency_data.get("qa_report"),
        "pending_approval": run_approvals[0] if run_approvals else None,
        "degraded": bool(agency_data.get("degraded")),
        "generation_provenance": agency_data.get("generation_provenance", []),
    }
    scope = payload.get("idempotency_scope")
    key = payload.get("idempotency_key")
    if scope and key:
        complete_idempotency(scope, key, response)
    return response


def _execute_resume_job(job: dict) -> dict:
    payload = job["payload"]
    run_id = str(job["run_id"])
    record = get_run_record(run_id)
    if record is None:
        raise RuntimeError(f"Run {run_id} not found for resume job")

    status = record["status"]
    if status == "completed":
        agency_data = (record.get("result") or {}).get("agency", {})
        return {"run_id": run_id, "status": "completed", "delivery": agency_data.get("delivery")}
    if status == "cancelled":
        return {"run_id": run_id, "status": "cancelled"}
    if status == "failed":
        raise RuntimeError(f"Run {run_id} is failed and cannot be resumed by a resume job")

    stored_agency = (record.get("result") or {}).get("agency", {})
    latest = (get_approvals_for_run(run_id) or [None])[0]

    scope = payload.get("idempotency_scope")
    key = payload.get("idempotency_key")

    def _complete_with(result: dict) -> dict:
        if scope and key:
            complete_idempotency(scope, key, result)
        return result

    if status == "delivering":
        # Crash recovery: a previous attempt expired its lease mid-delivery.
        # Delivery was already authorized, so continue without re-running the
        # release guards.
        pass
    else:
        from services.langgraph.agency.kernel.lifecycle import release_guard_failures

        failures = release_guard_failures(delivery_context(stored_agency, latest))
        if failures:
            blocker = failures[0]
            if blocker.code in ANALYTICS_REPORTED_BLOCKS:
                emit_lifecycle_event(
                    record["tenant_id"],
                    record["project_id"],
                    "agency_run_delivery_blocked",
                    {"pipeline": record["pipeline"], "reason": blocker.code},
                    run_id,
                )
            return _complete_with(
                {
                    "run_id": run_id,
                    "status": "needs_approval",
                    "blocked": blocker.code,
                    "detail": DELIVERY_BLOCK_DETAIL[blocker.code](latest),
                }
            )
        if not compare_and_set_run_status(run_id, "needs_approval", "delivering"):
            current = get_run_record(run_id)
            current_status = current["status"] if current else "unknown"
            if current_status == "completed":
                delivery = (current or {}).get("result", {}).get("agency", {}).get("delivery")
                return {"run_id": run_id, "status": "completed", "delivery": delivery}
            raise RuntimeError(f"Run {run_id} status race: {current_status}")

    emit_lifecycle_event(
        record["tenant_id"],
        record["project_id"],
        "agency_run_delivery_started",
        {"pipeline": record["pipeline"], "status": "delivering"},
        run_id,
    )
    try:
        graph = build_agency_workflow()
        config = run_config(run_id)
        run = _run_model_from_record(record, record.get("metadata") or {})
        state = run_and_record_events(graph, None, config, run)
        agency_data = agency_payload(state)
        update_run_status(run_id, "completed", {"agency": agency_data})
        emit_lifecycle_event(
            record["tenant_id"],
            record["project_id"],
            "agency_run_completed",
            {"pipeline": record["pipeline"], "status": "completed"},
            run_id,
        )
        response = {"run_id": run_id, "status": "completed", "delivery": agency_data.get("delivery")}
        return _complete_with(response)
    except Exception:
        _record_run_failure(job, "delivery", Exception("delivery failed"))
        raise


def handle_job(job: dict) -> str:
    """Execute one claimed job under its lease. Returns the terminal outcome."""

    outcome = "unknown"
    from services.langgraph.persistence.jobs import default_lease_seconds

    lease_seconds = default_lease_seconds()
    heartbeat = _LeaseHeartbeat(job["job_id"], job["claim_token"], max(5.0, lease_seconds / 3))
    try:
        # Cancellation fence: the job may have been cancelled between claim and
        # execution start; only the live lease holder may honor it.
        current = get_job(job["job_id"])
        if current is None or current["status"] != "running":
            return "skipped"
        if job["kind"] == "agency.create":
            result = _execute_create_job(current)
            outcome = "completed"
        elif job["kind"] == "agency.resume":
            result = _execute_resume_job(current)
            outcome = "completed"
        else:
            outcome = fail_job(job["job_id"], job["claim_token"], f"unsupported kind {job['kind']}")
            return outcome
        complete_job(job["job_id"], job["claim_token"], result)
        return outcome
    except Exception as exc:
        failure_outcome = fail_job(job["job_id"], job["claim_token"], f"{type(exc).__name__}: {exc}")
        if failure_outcome == "dead_letter" and job["run_id"]:
            emit_lifecycle_event(
                job["tenant_id"],
                job["project_id"],
                "agency_job_dead_lettered",
                {"kind": job["kind"], "run_id": str(job["run_id"]), "attempt": job.get("attempt_count")},
                str(job["run_id"]) if job.get("run_id") else None,
            )
        return failure_outcome
    finally:
        heartbeat.stop()


def poll_once(kind: Optional[str] = None) -> int:
    """Release expired leases, then execute every claimable job until the queue
    is empty or a claim race is lost. Returns the number of jobs attempted."""

    expire_stale_leases()
    attempted = 0
    while True:
        job = claim_job(kind=kind)
        if job is None:
            break
        attempted += 1
        handle_job(job)
    return attempted


def run_worker_loop(poll_interval: float = 2.0, max_jobs: Optional[int] = None) -> None:
    """Long-running worker loop. Cancellation: NOT graceful shutdown-safe, the
    lease expiry recovery guarantees correctness after abrupt termination."""

    processed = 0
    while max_jobs is None or processed < max_jobs:
        attempted = poll_once()
        processed += attempted
        if attempted == 0:
            time.sleep(poll_interval)


def cancel_job(job_id: str) -> bool:
    return request_job_cancellation(job_id)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="AMC durable execution worker")
    parser.add_argument("--once", action="store_true", help="drain the queue then exit")
    parser.add_argument("--max-jobs", type=int, default=None)
    parser.add_argument("--poll-interval", type=float, default=2.0)
    args = parser.parse_args()
    if args.once:
        print(f"drained {poll_once()} jobs")
    else:
        run_worker_loop(poll_interval=args.poll_interval, max_jobs=args.max_jobs)
