import sqlite3
from datetime import datetime
from uuid import uuid4
from services.langgraph.persistence.sqlite_db import DB_PATH, init_db

init_db()

def init_approvals_table():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''
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
        ''')

init_approvals_table()

def create_approval_request(run_id: str, tenant_id: str, project_id: str, reason: str, confidence: float) -> dict:
    approval_id = str(uuid4())
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO approvals (approval_id, run_id, tenant_id, project_id, reason, confidence) VALUES (?, ?, ?, ?, ?, ?)",
            (approval_id, run_id, tenant_id, project_id, reason, confidence)
        )
    return {"approval_id": approval_id, "status": "pending"}

def list_pending_approvals(tenant_id: str = None) -> list:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        if tenant_id:
            rows = conn.execute("SELECT * FROM approvals WHERE status = 'pending' AND tenant_id = ?", (tenant_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM approvals WHERE status = 'pending'").fetchall()
        return [dict(r) for r in rows]

def resolve_approval(approval_id: str, reviewer: str, decision: str) -> dict:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE approvals SET status = ?, reviewer = ?, decision = ?, decided_at = ? WHERE approval_id = ?",
            ('resolved', reviewer, decision, datetime.utcnow().isoformat(), approval_id)
        )
    return {"approval_id": approval_id, "status": "resolved", "decision": decision}

def get_approvals_for_run(run_id: str) -> list:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM approvals WHERE run_id = ? ORDER BY created_at DESC", (run_id,)
        ).fetchall()
        return [dict(r) for r in rows]
