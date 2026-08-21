from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from services.langgraph.persistence.database import (
    decode_json,
    is_postgres,
    json_param,
    normalize_record,
    table,
    transaction,
)

EVENT_SCHEMA_VERSION = "run-event-v2"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_event(row) -> dict:
    event = normalize_record(row)
    event["safe_payload"] = decode_json(event.get("safe_payload"), {})
    event["redactions_applied"] = decode_json(event.get("redactions_applied"), [])
    return event


def _next_sequence(db, run_id: str) -> int:
    if is_postgres():
        db.execute(
            f"INSERT INTO {table('run_event_counters')} (run_id, next_sequence) VALUES (?, 0) ON CONFLICT (run_id) DO NOTHING",
            (run_id,),
        )
        row = db.execute(
            f"UPDATE {table('run_event_counters')} SET next_sequence = next_sequence + 1 WHERE run_id = ? RETURNING next_sequence - 1 AS sequence",
            (run_id,),
        ).fetchone()
        return int(row["sequence"])
    row = db.execute(
        f"SELECT COALESCE(MAX(sequence), -1) + 1 AS sequence FROM {table('run_events')} WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    return int(row["sequence"])


def record_event(
    run_id: str,
    tenant_id: str,
    project_id: str,
    node_id: Optional[str],
    event_type: str,
    safe_payload: Optional[dict] = None,
    *,
    observed_at: Optional[str] = None,
    started_at: Optional[str] = None,
    completed_at: Optional[str] = None,
    checkpoint_ref: Optional[str] = None,
    redactions_applied: Optional[list[str]] = None,
) -> dict:
    event_id = str(uuid4())
    observed = observed_at or _now()
    persisted = _now()
    with transaction(write=True) as db:
        sequence = _next_sequence(db, run_id)
        db.execute(
            f"""
            INSERT INTO {table('run_events')} (
                event_id, run_id, tenant_id, project_id, sequence, schema_version,
                event_type, node_id, observed_at, started_at, completed_at,
                persisted_at, checkpoint_ref, safe_payload, redactions_applied
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                run_id,
                tenant_id,
                project_id,
                sequence,
                EVENT_SCHEMA_VERSION,
                event_type,
                node_id,
                observed,
                started_at,
                completed_at,
                persisted,
                checkpoint_ref,
                json_param(safe_payload or {}),
                json_param(redactions_applied or []),
            ),
        )
        row = db.execute(f"SELECT * FROM {table('run_events')} WHERE event_id = ?", (event_id,)).fetchone()
        return _row_to_event(row)


def list_events_for_run(run_id: str, after_sequence: int = -1, limit: int = 1000) -> list:
    bounded_limit = max(1, min(limit, 5000))
    with transaction() as db:
        rows = db.execute(
            f"SELECT * FROM {table('run_events')} WHERE run_id = ? AND sequence > ? ORDER BY sequence ASC LIMIT ?",
            (run_id, after_sequence, bounded_limit),
        ).fetchall()
        return [_row_to_event(row) for row in rows]


def latest_sequence(run_id: str) -> int:
    with transaction() as db:
        row = db.execute(
            f"SELECT COALESCE(MAX(sequence), -1) AS sequence FROM {table('run_events')} WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        return int(row["sequence"])
