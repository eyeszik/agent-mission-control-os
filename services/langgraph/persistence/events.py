import sqlite3
import json
from datetime import datetime
from uuid import uuid4

from services.langgraph.persistence.sqlite_db import DB_PATH, init_db

init_db()


def init_events_table():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS run_events (
                event_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                node_id TEXT NOT NULL,
                type TEXT NOT NULL,
                payload TEXT,
                sequence INTEGER NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


init_events_table()


def record_event(run_id: str, node_id: str, event_type: str, payload: dict = None) -> dict:
    """
    Appends one real event for a run, e.g. after a LangGraph node actually
    executes (see graph.stream(..., stream_mode="updates") in api/routes/agency.py).
    Sequence is per-run monotonic so the SSE endpoint can replay events in order.
    """
    event_id = str(uuid4())
    now = datetime.utcnow().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        seq = conn.execute(
            "SELECT COALESCE(MAX(sequence), -1) + 1 FROM run_events WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO run_events (event_id, run_id, node_id, type, payload, sequence, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (event_id, run_id, node_id, event_type, json.dumps(payload or {}), seq, now),
        )
    return {
        "event_id": event_id,
        "run_id": run_id,
        "node_id": node_id,
        "type": event_type,
        "payload": payload or {},
        "sequence": seq,
        "timestamp": now,
    }


def list_events_for_run(run_id: str) -> list:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM run_events WHERE run_id = ? ORDER BY sequence ASC", (run_id,)
        ).fetchall()
        events = []
        for row in rows:
            event = dict(row)
            event["payload"] = json.loads(event["payload"]) if event["payload"] else {}
            events.append(event)
        return events
