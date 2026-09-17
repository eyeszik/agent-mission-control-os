from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from services.langgraph.persistence.database import decode_json, json_param, normalize_record, table, transaction


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_record(row) -> Optional[dict]:
    if not row:
        return None
    record = normalize_record(row)
    record["payload"] = decode_json(record.get("payload"), {})
    return record


def create_lineage_remediation(
    *,
    tenant_id: str,
    project_id: str,
    run_id: str,
    approval_id: str | None,
    artifact_id: str,
    artifact_version_ref: str,
    changed_artifact_id: str,
    changed_version_ref: str,
    reason: str,
    payload: dict,
) -> dict:
    with transaction(write=True) as db:
        existing = db.execute(
            f"""
            SELECT * FROM {table('lineage_remediation_queue')}
            WHERE run_id = ? AND artifact_version_ref = ? AND changed_version_ref = ? AND status = 'OPEN'
            ORDER BY created_at DESC LIMIT 1
            """,
            (run_id, artifact_version_ref, changed_version_ref),
        ).fetchone()
        if existing:
            record = _row_to_record(existing)
            if record is None:
                raise RuntimeError("Lineage remediation lookup returned no record")
            return record

        remediation_id = str(uuid4())
        created_at = _now()
        db.execute(
            f"""
            INSERT INTO {table('lineage_remediation_queue')}
            (remediation_id, tenant_id, project_id, run_id, approval_id, artifact_id, artifact_version_ref, changed_artifact_id, changed_version_ref, reason, status, payload, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?)
            """,
            (
                remediation_id,
                tenant_id,
                project_id,
                run_id,
                approval_id,
                artifact_id,
                artifact_version_ref,
                changed_artifact_id,
                changed_version_ref,
                reason,
                json_param(payload),
                created_at,
            ),
        )
        row = db.execute(
            f"SELECT * FROM {table('lineage_remediation_queue')} WHERE remediation_id = ?",
            (remediation_id,),
        ).fetchone()
    record = _row_to_record(row)
    if record is None:
        raise RuntimeError("Lineage remediation insert succeeded but record could not be read back")
    return record


def list_project_lineage_remediations(project_id: str, tenant_id: str, limit: int = 20) -> list[dict]:
    with transaction() as db:
        rows = db.execute(
            f"""
            SELECT * FROM {table('lineage_remediation_queue')}
            WHERE tenant_id = ? AND project_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (tenant_id, project_id, max(1, min(limit, 200))),
        ).fetchall()
    return [_row_to_record(row) for row in rows if row]


def resolve_lineage_remediation(remediation_id: str, status: str) -> Optional[dict]:
    if status not in {"REGENERATED", "RETRIED", "RESOLVED"}:
        raise ValueError("status must be REGENERATED, RETRIED, or RESOLVED")
    with transaction(write=True) as db:
        db.execute(
            f"""
            UPDATE {table('lineage_remediation_queue')}
            SET status = ?, resolved_at = ?
            WHERE remediation_id = ? AND status = 'OPEN'
            """,
            (status, _now(), remediation_id),
        )
        row = db.execute(
            f"SELECT * FROM {table('lineage_remediation_queue')} WHERE remediation_id = ?",
            (remediation_id,),
        ).fetchone()
    return _row_to_record(row)


def resolve_lineage_remediation_for_run(
    run_id: str,
    *,
    approval_id: str | None = None,
    status: str,
) -> list[dict]:
    query = f"SELECT remediation_id FROM {table('lineage_remediation_queue')} WHERE run_id = ? AND status = 'OPEN'"
    params: list[str] = [run_id]
    if approval_id:
        query += " AND (approval_id = ? OR approval_id IS NULL)"
        params.append(approval_id)
    with transaction() as db:
        rows = db.execute(query, params).fetchall()
    resolved: list[dict] = []
    for row in rows:
        item = resolve_lineage_remediation(row["remediation_id"], status)
        if item:
            resolved.append(item)
    return resolved
