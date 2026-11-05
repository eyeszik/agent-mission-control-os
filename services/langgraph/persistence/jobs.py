from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from services.langgraph.persistence.database import (
    decode_json,
    json_param,
    normalize_record,
    table,
    transaction,
)

_VALID_JOB_KINDS = {"agency.create", "agency.resume"}
_TERMINAL_JOB_STATUSES = {"completed", "failed", "dead_letter", "cancelled"}
_CLAIMABLE_STATUSES = ("queued",)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_max_attempts() -> int:
    raw = (os.environ.get("AMC_JOB_MAX_ATTEMPTS") or "3").strip()
    try:
        value = int(raw)
    except ValueError:
        return 3
    return max(1, min(value, 20))


def default_lease_seconds() -> int:
    raw = (os.environ.get("AMC_JOB_LEASE_SECONDS") or "900").strip()
    try:
        value = int(raw)
    except ValueError:
        return 900
    return max(30, min(value, 24 * 60 * 60))


def _row_to_job(row) -> dict:
    record = normalize_record(row)
    record["payload"] = decode_json(record.get("payload"), {})
    record["result"] = decode_json(record.get("result"), None)
    return record


def enqueue_job(
    kind: str,
    tenant_id: str,
    project_id: str,
    payload: dict,
    *,
    run_id: Optional[str] = None,
    max_attempts: Optional[int] = None,
) -> dict:
    if kind not in _VALID_JOB_KINDS:
        raise ValueError(f"Unsupported job kind: {kind}")
    job_id = f"job_{secrets.token_hex(16)}"
    lease = (max_attempts or default_max_attempts()) if max_attempts else default_max_attempts()
    now = _now_iso()
    with transaction(write=True) as db:
        db.execute(
            f"INSERT INTO {table('amc_jobs')} (job_id, kind, tenant_id, project_id, run_id, status, attempt_count, max_attempts, payload, queued_at, updated_at) VALUES (?, ?, ?, ?, ?, 'queued', 0, ?, ?, ?, ?)",
            (job_id, kind, tenant_id, project_id, run_id, lease, json_param(payload), now, now),
        )
    return get_job(job_id)  # type: ignore[return-value]


def get_job(job_id: str) -> Optional[dict]:
    with transaction() as db:
        row = db.execute(f"SELECT * FROM {table('amc_jobs')} WHERE job_id = ?", (job_id,)).fetchone()
        return _row_to_job(row) if row else None


def list_jobs(tenant_id: Optional[str] = None, status: Optional[str] = None, limit: int = 100) -> list[dict]:
    query = f"SELECT * FROM {table('amc_jobs')}"
    clauses: list[str] = []
    params: list = []
    if tenant_id:
        clauses.append("tenant_id = ?")
        params.append(tenant_id)
    if status:
        clauses.append("status = ?")
        params.append(status)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY queued_at ASC LIMIT ?"
    params.append(max(1, min(limit, 1000)))
    with transaction() as db:
        rows = db.execute(query, params).fetchall()
        return [_row_to_job(row) for row in rows]


def expire_stale_leases() -> list[str]:
    """Release jobs whose worker lease expired back to the retry queue.

    attempt_count is NOT incremented here: the lease was taken by a dead
    worker, not a failed attempt of a live one; the retry budget is charged at
    claim time so recovery cannot be skipped.
    """

    now_str = _now_iso()
    with transaction(write=True) as db:
        stale = db.execute(
            "SELECT job_id FROM amc_jobs WHERE status = 'running' AND lease_expires_at IS NOT NULL AND lease_expires_at < ?",
            (now_str,),
        ).fetchall()
        if not stale:
            return []
        ids = [str(r["job_id"]) for r in stale]
        marks = ",".join("?" for _ in ids)
        db.execute(
            f"UPDATE {table('amc_jobs')} SET status = 'queued', claim_token = NULL, lease_expires_at = NULL, updated_at = ? WHERE job_id IN ({marks})",
            (now_str, *ids),
        )
    return ids


def claim_job(kind: Optional[str] = None, lease_seconds: Optional[int] = None) -> Optional[dict]:
    """Atomically claim the oldest claimable job with a fresh fencing token.

    Claiming is a compare-and-swap on the job status so two workers can never
    hold the same job: the loser of the race sees rowcount 0 and retries on its
    next poll. Each claim charges the retry budget (attempt_count + 1).
    """

    if kind is not None and kind not in _VALID_JOB_KINDS:
        raise ValueError(f"Unsupported job kind: {kind}")
    lease = lease_seconds or default_lease_seconds()
    now = datetime.now(timezone.utc)
    now_s = now.isoformat()
    lease_until = (now + timedelta(seconds=lease)).isoformat()
    token = f"lease_{secrets.token_hex(16)}"

    with transaction(write=True) as db:
        clauses: list[str] = ["status = 'queued'"]
        params: list = []
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        candidate = db.execute(
            f"SELECT job_id FROM {table('amc_jobs')} WHERE {' AND '.join(clauses)} ORDER BY queued_at ASC LIMIT 1",
            tuple(params),
        ).fetchone()
        if candidate is None:
            return None
        job_id = str(candidate["job_id"])
        cursor = db.execute(
            f"UPDATE {table('amc_jobs')} SET status = 'running', claim_token = ?, lease_expires_at = ?, attempt_count = attempt_count + 1, claimed_at = ?, updated_at = ? WHERE job_id = ? AND status = 'queued'",
            (token, lease_until, now_s, now_s, job_id),
        )
        if cursor.rowcount != 1:
            return None
        row = db.execute(f"SELECT * FROM {table('amc_jobs')} WHERE job_id = ?", (job_id,)).fetchone()
        return _row_to_job(row)


def renew_job_lease(job_id: str, claim_token: str, lease_seconds: Optional[int] = None) -> bool:
    lease = lease_seconds or default_lease_seconds()
    lease_until = (datetime.now(timezone.utc) + timedelta(seconds=lease)).isoformat()
    now = _now_iso()
    with transaction(write=True) as db:
        cursor = db.execute(
            f"UPDATE {table('amc_jobs')} SET lease_expires_at = ?, updated_at = ? WHERE job_id = ? AND claim_token = ? AND status = 'running'",
            (lease_until, now, job_id, claim_token),
        )
        return cursor.rowcount == 1


def _fenced_update(db, job_id: str, claim_token: str, set_clause: str, params: tuple):
    return db.execute(
        f"UPDATE {table('amc_jobs')} SET {set_clause}, updated_at = ? WHERE job_id = ? AND claim_token = ? AND status = 'running'",
        (*params, _now_iso(), job_id, claim_token),
    )


def complete_job(job_id: str, claim_token: str, result: dict) -> bool:
    """Finish a claimed job. Fenced by claim token: a zombie worker that lost
    its lease after a network partition can no longer mutate the job."""

    with transaction(write=True) as db:
        cursor = _fenced_update(db, job_id, claim_token, "status = 'completed', lease_expires_at = NULL, result = ?, error = NULL", (json_param(result),))
        return cursor.rowcount == 1


def fail_job(job_id: str, claim_token: str, error: str) -> str:
    """Record an attempt failure. Inside the retry budget the job re-enters the
    queue; past it, the job is dead-lettered and no longer claimed automatically."""

    error_text = (error or "unknown")[:500]
    with transaction(write=True) as db:
        row = db.execute(
            f"SELECT max_attempts, attempt_count FROM {table('amc_jobs')} WHERE job_id = ? AND claim_token = ? AND status = 'running'",
            (job_id, claim_token),
        ).fetchone()
        if row is None:
            return "not_fenced"
        if row["attempt_count"] >= row["max_attempts"]:
            _fenced_update(db, job_id, claim_token, "status = 'dead_letter', lease_expires_at = NULL, error = ?", (error_text,))
            return "dead_letter"
        _fenced_update(db, job_id, claim_token, "status = 'queued', lease_expires_at = NULL, error = ?", (error_text,))
        return "queued"


def request_job_cancellation(job_id: str) -> bool:
    """Mark a job cancelled. Only jobs that have not started affecting the world
    (queued, or running) may transition; a terminal job keeps its record."""

    now = _now_iso()
    with transaction(write=True) as db:
        cursor = db.execute(
            f"UPDATE {table('amc_jobs')} SET status = 'cancelled', lease_expires_at = NULL, updated_at = ? WHERE job_id = ? AND status IN ('queued', 'running')",
            (now, job_id),
        )
        return cursor.rowcount == 1

