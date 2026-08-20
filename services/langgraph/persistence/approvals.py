import sqlite3
from datetime import datetime
from typing import Optional
from uuid import uuid4

from services.langgraph.persistence.sqlite_db import DB_PATH, init_db

init_db()


def init_approvals_table():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS approvals (
                approval_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                reason TEXT NOT NULL,
                confidence REAL,
                status TEXT DEFAULT 'pending',
                reviewer TEXT,
                decision TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                decided_at TIMESTAMP
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_approvals_tenant_status ON approvals (tenant_id, status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_approvals_run_created ON approvals (run_id, created_at DESC)")


init_approvals_table()


def _row_to_dict(row: sqlite3.Row | None) -> Optional[dict]:
    return dict(row) if row else None


def create_approval_request(
    run_id: str,
    tenant_id: str,
    project_id: str,
    reason: str,
    confidence: Optional[float],
) -> dict:
    approval_id = str(uuid4())
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO approvals (approval_id, run_id, tenant_id, project_id, reason, confidence) VALUES (?, ?, ?, ?, ?, ?)",
            (approval_id, run_id, tenant_id, project_id, reason, confidence),
        )
    return {"approval_id": approval_id, "status": "pending"}


def get_approval(approval_id: str) -> Optional[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM approvals WHERE approval_id = ?", (approval_id,)).fetchone()
        return _row_to_dict(row)


def list_pending_approvals(tenant_id: str) -> list:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM approvals WHERE status = 'pending' AND tenant_id = ? ORDER BY created_at ASC",
            (tenant_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def resolve_approval(approval_id: str, reviewer: str, decision: str) -> Optional[dict]:
    """Atomically transition PENDING -> one immutable terminal decision."""

    if decision not in ("approve", "reject"):
        raise ValueError("decision must be 'approve' or 'reject'")

    decided_at = datetime.utcnow().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            """
            UPDATE approvals
               SET status = 'resolved', reviewer = ?, decision = ?, decided_at = ?
             WHERE approval_id = ? AND status = 'pending'
            """,
            (reviewer, decision, decided_at, approval_id),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            return None
        row = conn.execute("SELECT * FROM approvals WHERE approval_id = ?", (approval_id,)).fetchone()
        conn.commit()
        return _row_to_dict(row)


def get_approvals_for_run(run_id: str) -> list:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM approvals WHERE run_id = ? ORDER BY created_at DESC", (run_id,)
        ).fetchall()
        return [dict(row) for row in rows]
