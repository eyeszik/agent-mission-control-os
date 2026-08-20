import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from services.langgraph.persistence.sqlite_db import DB_PATH, init_db

init_db()


def hash_payload(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def generate_idempotency_key(project_id: str, node_id: str, input_dict: dict, attempt: int = 1) -> str:
    """Deterministic helper retained for internal non-HTTP callers/tests."""
    input_hash = hash_payload(input_dict)
    raw_key = f"{project_id}:{node_id}:{input_hash}:{attempt}"
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _record_to_result(row: sqlite3.Row) -> dict:
    return {
        "scope": row["scope"],
        "key": row["key"],
        "request_hash": row["request_hash"],
        "status": row["status"],
        "result": json.loads(row["result"]) if row["result"] else None,
        "error": row["error"],
        "attempt_count": row["attempt_count"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "expires_at": row["expires_at"],
    }


def reserve_idempotency(
    scope: str,
    key: str,
    request_hash: str,
    ttl_seconds: int = 86400,
) -> dict:
    """
    Atomically reserve a guarded mutation.

    Returns state=new|replay|in_progress|conflict. Failed reservations are
    retryable with the same logical key and increment attempt_count.
    """

    if not key.strip():
        raise ValueError("idempotency key must be non-empty")
    if ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be positive")

    now = _utcnow()
    expires_at = now + timedelta(seconds=ttl_seconds)
    now_s = now.isoformat()
    expires_s = expires_at.isoformat()

    with sqlite3.connect(DB_PATH, isolation_level=None) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM idempotency_records WHERE scope = ? AND key = ?",
            (scope, key),
        ).fetchone()

        if row is not None:
            try:
                expired = datetime.fromisoformat(row["expires_at"]) <= now
            except (TypeError, ValueError):
                expired = True
            if expired:
                conn.execute(
                    "DELETE FROM idempotency_records WHERE scope = ? AND key = ?",
                    (scope, key),
                )
                row = None

        if row is not None:
            record = _record_to_result(row)
            if row["request_hash"] != request_hash:
                conn.commit()
                return {"state": "conflict", "record": record}
            if row["status"] == "completed":
                conn.commit()
                return {"state": "replay", "record": record}
            if row["status"] == "executing":
                conn.commit()
                return {"state": "in_progress", "record": record}

            conn.execute(
                """
                UPDATE idempotency_records
                   SET status = 'executing', result = NULL, error = NULL,
                       attempt_count = attempt_count + 1,
                       updated_at = ?, expires_at = ?
                 WHERE scope = ? AND key = ? AND status = 'failed'
                """,
                (now_s, expires_s, scope, key),
            )
            row = conn.execute(
                "SELECT * FROM idempotency_records WHERE scope = ? AND key = ?",
                (scope, key),
            ).fetchone()
            conn.commit()
            return {"state": "new", "record": _record_to_result(row)}

        conn.execute(
            """
            INSERT INTO idempotency_records
                (scope, key, request_hash, status, result, error, attempt_count,
                 created_at, updated_at, expires_at)
            VALUES (?, ?, ?, 'executing', NULL, NULL, 1, ?, ?, ?)
            """,
            (scope, key, request_hash, now_s, now_s, expires_s),
        )
        row = conn.execute(
            "SELECT * FROM idempotency_records WHERE scope = ? AND key = ?",
            (scope, key),
        ).fetchone()
        conn.commit()
        return {"state": "new", "record": _record_to_result(row)}


def complete_idempotency(scope: str, key: str, result: dict) -> bool:
    now_s = _utcnow().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            """
            UPDATE idempotency_records
               SET status = 'completed', result = ?, error = NULL, updated_at = ?
             WHERE scope = ? AND key = ? AND status = 'executing'
            """,
            (json.dumps(result), now_s, scope, key),
        )
        return cursor.rowcount == 1


def fail_idempotency(scope: str, key: str, error: str) -> bool:
    now_s = _utcnow().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            """
            UPDATE idempotency_records
               SET status = 'failed', error = ?, updated_at = ?
             WHERE scope = ? AND key = ? AND status = 'executing'
            """,
            (error[:500], now_s, scope, key),
        )
        return cursor.rowcount == 1


def get_idempotency_record(scope: str, key: str) -> Optional[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM idempotency_records WHERE scope = ? AND key = ?",
            (scope, key),
        ).fetchone()
        return _record_to_result(row) if row else None
