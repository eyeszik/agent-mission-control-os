from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from services.langgraph.persistence.database import (
    decode_json,
    is_postgres,
    json_param,
    normalize_record,
    table,
    transaction,
)


def hash_payload(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def generate_idempotency_key(project_id: str, node_id: str, input_dict: dict, attempt: int = 1) -> str:
    input_hash = hash_payload(input_dict)
    raw_key = f"{project_id}:{node_id}:{input_hash}:{attempt}"
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _record_to_result(row) -> dict:
    record = normalize_record(row)
    record["result"] = decode_json(record.get("result"), None)
    return record


def reserve_idempotency(scope: str, key: str, request_hash: str, ttl_seconds: int = 86400) -> dict:
    if not key.strip():
        raise ValueError("idempotency key must be non-empty")
    if ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be positive")

    now = _utcnow()
    expires_at = now + timedelta(seconds=ttl_seconds)
    now_s = now.isoformat()
    expires_s = expires_at.isoformat()
    lock_suffix = " FOR UPDATE" if is_postgres() else ""

    with transaction(write=True) as db:
        row = db.execute(
            f"SELECT * FROM {table('idempotency_records')} WHERE scope = ? AND key = ?{lock_suffix}",
            (scope, key),
        ).fetchone()

        if row is not None:
            normalized = _record_to_result(row)
            try:
                expired = datetime.fromisoformat(str(normalized["expires_at"])) <= now
            except (TypeError, ValueError):
                expired = True
            if expired:
                db.execute(
                    f"DELETE FROM {table('idempotency_records')} WHERE scope = ? AND key = ?",
                    (scope, key),
                )
                row = None

        if row is not None:
            record = _record_to_result(row)
            if record["request_hash"] != request_hash:
                return {"state": "conflict", "record": record}
            if record["status"] == "completed":
                return {"state": "replay", "record": record}
            if record["status"] == "executing":
                return {"state": "in_progress", "record": record}
            db.execute(
                f"UPDATE {table('idempotency_records')} SET status = 'executing', result = NULL, error = NULL, attempt_count = attempt_count + 1, updated_at = ?, expires_at = ? WHERE scope = ? AND key = ? AND status = 'failed'",
                (now_s, expires_s, scope, key),
            )
            refreshed = db.execute(
                f"SELECT * FROM {table('idempotency_records')} WHERE scope = ? AND key = ?",
                (scope, key),
            ).fetchone()
            return {"state": "new", "record": _record_to_result(refreshed)}

        db.execute(
            f"INSERT INTO {table('idempotency_records')} (scope, key, request_hash, status, result, error, attempt_count, created_at, updated_at, expires_at) VALUES (?, ?, ?, 'executing', NULL, NULL, 1, ?, ?, ?)",
            (scope, key, request_hash, now_s, now_s, expires_s),
        )
        inserted = db.execute(
            f"SELECT * FROM {table('idempotency_records')} WHERE scope = ? AND key = ?",
            (scope, key),
        ).fetchone()
        return {"state": "new", "record": _record_to_result(inserted)}


def complete_idempotency(scope: str, key: str, result: dict) -> bool:
    with transaction(write=True) as db:
        cursor = db.execute(
            f"UPDATE {table('idempotency_records')} SET status = 'completed', result = ?, error = NULL, updated_at = ? WHERE scope = ? AND key = ? AND status = 'executing'",
            (json_param(result), _utcnow().isoformat(), scope, key),
        )
        return cursor.rowcount == 1


def fail_idempotency(scope: str, key: str, error: str) -> bool:
    with transaction(write=True) as db:
        cursor = db.execute(
            f"UPDATE {table('idempotency_records')} SET status = 'failed', error = ?, updated_at = ? WHERE scope = ? AND key = ? AND status = 'executing'",
            (error[:500], _utcnow().isoformat(), scope, key),
        )
        return cursor.rowcount == 1


def get_idempotency_record(scope: str, key: str) -> Optional[dict]:
    with transaction() as db:
        row = db.execute(
            f"SELECT * FROM {table('idempotency_records')} WHERE scope = ? AND key = ?",
            (scope, key),
        ).fetchone()
        return _record_to_result(row) if row else None
