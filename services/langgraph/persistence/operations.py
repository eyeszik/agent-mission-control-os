from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from services.langgraph.persistence.database import json_param, normalize_record, table, transaction


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_publication_job(run_id: str, tenant_id: str, project_id: str, provider: str, mode: str, status: str, idempotency_key: str, payload: dict, error: str | None = None) -> dict:
    job_id = str(uuid4())
    now = _now()
    with transaction(write=True) as db:
        db.execute(
            f"INSERT INTO {table('publication_jobs')} (job_id, run_id, tenant_id, project_id, provider, mode, status, idempotency_key, payload, error, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (job_id, run_id, tenant_id, project_id, provider, mode, status, idempotency_key, json_param(payload), error, now, now),
        )
        row = db.execute(f"SELECT * FROM {table('publication_jobs')} WHERE job_id = ?", (job_id,)).fetchone()
        return normalize_record(row)


def request_spend_authorization(run_id: str | None, tenant_id: str, project_id: str, provider: str, amount_minor: int, currency: str, requested_by: str, reason: str) -> dict:
    authorization_id = str(uuid4())
    now = _now()
    with transaction(write=True) as db:
        db.execute(
            f"INSERT INTO {table('spend_authorizations')} (authorization_id, run_id, tenant_id, project_id, provider, amount_minor, currency, status, requested_by, reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)",
            (authorization_id, run_id, tenant_id, project_id, provider, amount_minor, currency.upper(), requested_by, reason, now),
        )
        row = db.execute(f"SELECT * FROM {table('spend_authorizations')} WHERE authorization_id = ?", (authorization_id,)).fetchone()
        return normalize_record(row)
