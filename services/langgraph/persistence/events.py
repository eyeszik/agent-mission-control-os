import json
import sqlite3
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from services.langgraph.persistence.sqlite_db import DB_PATH, init_db

init_db()

EVENT_SCHEMA_VERSION = "run-event-v2"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_event(row: sqlite3.Row) -> dict:
    event = dict(row)
    event["safe_payload"] = json.loads(event["safe_payload"]) if event["safe_payload"] else {}
    event["redactions_applied"] = json.loads(event["redactions_applied"]) if event["redactions_applied"] else []
    return event


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
    """Persist one causally honest, cursor-addressable event envelope."""

    event_id = str(uuid4())
    observed = observed_at or _now()
    persisted = _now()
    with sqlite3.connect(DB_PATH, isolation_level=None) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("BEGIN IMMEDIATE")
        sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), -1) + 1 FROM run_events_v2 WHERE run_id = ?",
            (run_id,),
        ).fetchone()[0]
        conn.execute(
            """
            INSERT INTO run_events_v2 (
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
                json.dumps(safe_payload or {}),
                json.dumps(redactions_applied or []),
            ),
        )
        row = conn.execute("SELECT * FROM run_events_v2 WHERE event_id = ?", (event_id,)).fetchone()
        conn.commit()
        return _row_to_event(row)


def list_events_for_run(run_id: str, after_sequence: int = -1, limit: int = 1000) -> list:
    bounded_limit = max(1, min(limit, 5000))
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT * FROM run_events_v2
             WHERE run_id = ? AND sequence > ?
             ORDER BY sequence ASC
             LIMIT ?
            """,
            (run_id, after_sequence, bounded_limit),
        ).fetchall()
        return [_row_to_event(row) for row in rows]


def latest_sequence(run_id: str) -> int:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(sequence), -1) FROM run_events_v2 WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        return int(row[0])
