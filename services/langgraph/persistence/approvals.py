from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from services.langgraph.persistence.database import is_postgres, normalize_record, table, transaction


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_approvals_table() -> None:
    if is_postgres():
        return
    with transaction(write=True) as db:
        db.execute(
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
                created_at TEXT NOT NULL,
                decided_at TEXT
            )
            """
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_approvals_tenant_status ON approvals (tenant_id, status)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_approvals_run_created ON approvals (run_id, created_at DESC)")


init_approvals_table()


def _row_to_dict(row) -> Optional[dict]:
    return normalize_record(row) if row else None


def create_approval_request(run_id: str, tenant_id: str, project_id: str, reason: str, confidence: Optional[float]) -> dict:
    approval_id = str(uuid4())
    with transaction(write=True) as db:
        db.execute(
            f"INSERT INTO {table('approvals')} (approval_id, run_id, tenant_id, project_id, reason, confidence, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (approval_id, run_id, tenant_id, project_id, reason, confidence, _now()),
        )
    return {"approval_id": approval_id, "status": "pending"}


def get_approval(approval_id: str) -> Optional[dict]:
    with transaction() as db:
        row = db.execute(f"SELECT * FROM {table('approvals')} WHERE approval_id = ?", (approval_id,)).fetchone()
        return _row_to_dict(row)


def list_pending_approvals(tenant_id: str) -> list:
    with transaction() as db:
        rows = db.execute(
            f"SELECT * FROM {table('approvals')} WHERE status = 'pending' AND tenant_id = ? ORDER BY created_at ASC",
            (tenant_id,),
        ).fetchall()
        return [normalize_record(row) for row in rows]


def resolve_approval(approval_id: str, reviewer: str, decision: str) -> Optional[dict]:
    if decision not in ("approve", "reject"):
        raise ValueError("decision must be 'approve' or 'reject'")
    decided_at = _now()
    with transaction(write=True) as db:
        cursor = db.execute(
            f"UPDATE {table('approvals')} SET status = 'resolved', reviewer = ?, decision = ?, decided_at = ? WHERE approval_id = ? AND status = 'pending'",
            (reviewer, decision, decided_at, approval_id),
        )
        if cursor.rowcount != 1:
            return None
        row = db.execute(f"SELECT * FROM {table('approvals')} WHERE approval_id = ?", (approval_id,)).fetchone()
        return _row_to_dict(row)


def get_approvals_for_run(run_id: str) -> list:
    with transaction() as db:
        rows = db.execute(
            f"SELECT * FROM {table('approvals')} WHERE run_id = ? ORDER BY created_at DESC",
            (run_id,),
        ).fetchall()
        return [normalize_record(row) for row in rows]
