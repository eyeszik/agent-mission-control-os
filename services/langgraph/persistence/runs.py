import sqlite3
import json
from datetime import datetime
from typing import Optional

from services.langgraph.persistence.sqlite_db import DB_PATH, init_db

init_db()


def init_runs_table():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                pipeline TEXT NOT NULL,
                status TEXT NOT NULL,
                metadata TEXT,
                result TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


init_runs_table()


def _row_to_record(row: sqlite3.Row) -> dict:
    record = dict(row)
    record["metadata"] = json.loads(record["metadata"]) if record["metadata"] else {}
    record["result"] = json.loads(record["result"]) if record["result"] else None
    return record


def create_run_record(run_id: str, tenant_id: str, project_id: str, pipeline: str, status: str, metadata: dict) -> dict:
    now = datetime.utcnow().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO runs (run_id, tenant_id, project_id, pipeline, status, metadata, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, tenant_id, project_id, pipeline, status, json.dumps(metadata), now, now),
        )
    return get_run_record(run_id)


def get_run_record(run_id: str) -> Optional[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return _row_to_record(row) if row else None


def update_run_status(run_id: str, status: str, result: Optional[dict] = None) -> Optional[dict]:
    now = datetime.utcnow().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        if result is not None:
            conn.execute(
                "UPDATE runs SET status = ?, result = ?, updated_at = ? WHERE run_id = ?",
                (status, json.dumps(result), now, run_id),
            )
        else:
            conn.execute(
                "UPDATE runs SET status = ?, updated_at = ? WHERE run_id = ?",
                (status, now, run_id),
            )
    return get_run_record(run_id)


def list_runs(tenant_id: Optional[str] = None, pipeline: Optional[str] = None) -> list:
    query = "SELECT * FROM runs"
    clauses = []
    params: list = []
    if tenant_id:
        clauses.append("tenant_id = ?")
        params.append(tenant_id)
    if pipeline:
        clauses.append("pipeline = ?")
        params.append(pipeline)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY created_at DESC"
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query, params).fetchall()
        return [_row_to_record(r) for r in rows]
