"""Durable, tenant-scoped authenticated provenance for ACE v100 decisions.

The database is a write-ahead audit store, not a cryptographic WORM device.
Record digests are content-addressed and HMAC-authenticated by a protected,
caller-supplied key. Verification requires an independently retained keyring.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hmac
from typing import Any, Mapping

from services.langgraph.agency.ace_controls import AuditRecord, seal_record
from services.langgraph.persistence.database import (
    decode_json, is_postgres, json_param, normalize_record, table, transaction
)
from services.langgraph.persistence.tenancy import ensure_tenant_project
from services.langgraph.security.pii import redact_value


def _timestamp(now: datetime) -> str:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("observed_at must be timezone aware")
    return now.astimezone(timezone.utc).isoformat()


def append_provenance(
    *,
    tenant_id: str,
    project_id: str,
    actor: str,
    event_type: str,
    payload: Mapping[str, Any],
    signing_key: bytes,
    key_id: str,
    now: datetime,
) -> dict:
    """Append a signed, redacted event atomically under tenant/project scope.

    A per-project row lock serializes PostgreSQL writers. SQLite uses BEGIN
    IMMEDIATE. Any failure aborts the record instead of issuing a false receipt.
    Caller must already have authorization for this tenant/project.
    """
    if not all((tenant_id, project_id, actor, event_type, key_id)):
        raise ValueError("nonempty scope, actor, event_type and key_id required")
    if not isinstance(signing_key, bytes) or len(signing_key) < 32:
        raise ValueError("minimum 256-bit HMAC key required")
    if not isinstance(payload, Mapping):
        raise ValueError("payload must be a JSON-compatible object")
    stamp = _timestamp(now)
    sanitized = redact_value(dict(payload))
    with transaction(write=True) as db:
        ensure_tenant_project(db, tenant_id, project_id)
        if is_postgres():
            lock = db.execute(
                f"SELECT project_id FROM {table('projects')} WHERE project_id = ? AND tenant_id = ? FOR UPDATE",
                (project_id, tenant_id),
            ).fetchone()
            if lock is None:
                raise PermissionError("project ownership changed")
        prior = db.execute(
            f"""SELECT sequence, record_hash FROM {table('ace_provenance')}
            WHERE tenant_id = ? AND project_id = ?
            ORDER BY sequence DESC LIMIT 1""",
            (tenant_id, project_id),
        ).fetchone()
        sequence = int(prior["sequence"]) + 1 if prior else 1
        previous_hash = prior["record_hash"] if prior else "0" * 64
        record = seal_record(
            sequence=sequence, previous_hash=previous_hash,
            payload=sanitized, signing_key=signing_key,
        )
        db.execute(
            f"""INSERT INTO {table('ace_provenance')}
            (tenant_id, project_id, sequence, key_id, actor, event_type,
             payload, previous_hash, payload_digest, record_hash, signature, observed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (tenant_id, project_id, sequence, key_id, actor, event_type,
             json_param(sanitized), record.previous_hash, record.payload_digest,
             record.record_hash, record.signature, stamp),
        )
    return {
        "sequence": sequence, "tenant_id": tenant_id, "project_id": project_id,
        "key_id": key_id, "record_hash": record.record_hash,
        "payload_digest": record.payload_digest, "signature": record.signature,
    }


def read_project_provenance(*, tenant_id: str, project_id: str) -> tuple[dict, ...]:
    if not tenant_id or not project_id:
        raise ValueError("tenant_id and project_id required")
    with transaction() as db:
        rows = db.execute(
            f"""SELECT * FROM {table('ace_provenance')}
            WHERE tenant_id = ? AND project_id = ? ORDER BY sequence ASC""",
            (tenant_id, project_id),
        ).fetchall()
    records = []
    for row in rows:
        normalized = normalize_record(row)
        normalized["payload"] = decode_json(normalized["payload"])
        records.append(normalized)
    return tuple(records)


def verify_project_provenance(
    *, tenant_id: str, project_id: str, keys: Mapping[str, bytes]
) -> bool:
    if not keys:
        return False
    events = read_project_provenance(tenant_id=tenant_id, project_id=project_id)
    if not events:
        return False
    previous = "0" * 64
    for index, event in enumerate(events, start=1):
        key = keys.get(event["key_id"])
        if not isinstance(key, bytes) or len(key) < 32 or event["sequence"] != index:
            return False
        try:
            expected = seal_record(
                sequence=index, previous_hash=previous,
                payload=event["payload"], signing_key=key,
            )
            actual = AuditRecord.model_validate({
                "sequence": event["sequence"], "previous_hash": event["previous_hash"],
                "payload_digest": event["payload_digest"],
                "record_hash": event["record_hash"], "signature": event["signature"],
            })
        except (ValueError, TypeError):
            return False
        if (actual.previous_hash != expected.previous_hash
                or actual.payload_digest != expected.payload_digest
                or actual.record_hash != expected.record_hash
                or not hmac.compare_digest(actual.signature, expected.signature)):
            return False
        previous = actual.record_hash
    return True
