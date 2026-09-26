from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from services.langgraph.persistence.idempotency import hash_payload
from services.langgraph.persistence.invalidation import (
    AGENCY_PIPELINE_DEMANDED_EVENT_CLASSES,
    record_run_invalidation_bindings,
)
from services.langgraph.persistence.database import (
    decode_json,
    is_postgres,
    json_param,
    normalize_record,
    table,
    transaction,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_runs_table() -> None:
    if is_postgres():
        return
    with transaction(write=True) as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                pipeline TEXT NOT NULL,
                status TEXT NOT NULL,
                metadata TEXT,
                result TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_runs_tenant_project ON runs (tenant_id, project_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_runs_status_updated ON runs (status, updated_at DESC)")


init_runs_table()


def _row_to_record(row) -> dict:
    record = normalize_record(row)
    record["metadata"] = decode_json(record.get("metadata"), {})
    record["result"] = decode_json(record.get("result"), None)
    return record


def _agency_subject_hash(result: Optional[dict]) -> Optional[str]:
    agency = (result or {}).get("agency")
    if not isinstance(agency, dict) or not agency.get("campaign_package"):
        return None
    return hash_payload(
        {
            "campaign_package": agency.get("campaign_package"),
            "qa_report": agency.get("qa_report"),
            "generation_provenance": agency.get("generation_provenance", []),
            "degraded": bool(agency.get("degraded")),
        }
    )


def _sync_protected_run_artifact(run_id: str, tenant_id: str, project_id: str, result: Optional[dict]) -> None:
    subject_hash = _agency_subject_hash(result)
    if subject_hash is None:
        return

    from services.langgraph.persistence.agency_kernel import create_or_revise_protected_run_artifact
    from services.langgraph.persistence.approvals import get_approvals_for_run

    approvals = get_approvals_for_run(run_id)
    approval = approvals[0] if approvals else None
    revision = create_or_revise_protected_run_artifact(
        run_id=run_id,
        tenant_id=tenant_id,
        project_id=project_id,
        approval_id=approval["approval_id"] if approval else None,
        content_hash=subject_hash,
    )
    if not revision["changed"]:
        return

    record_run_invalidation_bindings(
        tenant_id=tenant_id,
        project_id=project_id,
        run_id=run_id,
        artifact_branch=revision["artifact"]["artifact_id"],
        result=result,
        demanded_event_classes=AGENCY_PIPELINE_DEMANDED_EVENT_CLASSES,
    )


def create_run_record(run_id: str, tenant_id: str, project_id: str, pipeline: str, status: str, metadata: dict) -> dict:
    now = _now()
    with transaction(write=True) as db:
        db.execute(
            f"INSERT INTO {table('runs')} (run_id, tenant_id, project_id, pipeline, status, metadata, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, tenant_id, project_id, pipeline, status, json_param(metadata), now, now),
        )
    record = get_run_record(run_id)
    if record is None:
        raise RuntimeError("Run insert succeeded but record could not be read back")
    return record


def get_run_record(run_id: str) -> Optional[dict]:
    with transaction() as db:
        row = db.execute(f"SELECT * FROM {table('runs')} WHERE run_id = ?", (run_id,)).fetchone()
        return _row_to_record(row) if row else None


def update_run_status(run_id: str, status: str, result: Optional[dict] = None) -> Optional[dict]:
    now = _now()
    tenant_id: Optional[str] = None
    project_id: Optional[str] = None
    with transaction(write=True) as db:
        if result is not None:
            current = db.execute(
                f"SELECT tenant_id, project_id FROM {table('runs')} WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if current:
                tenant_id = current["tenant_id"]
                project_id = current["project_id"]
            db.execute(
                f"UPDATE {table('runs')} SET status = ?, result = ?, updated_at = ? WHERE run_id = ?",
                (status, json_param(result), now, run_id),
            )
        else:
            db.execute(
                f"UPDATE {table('runs')} SET status = ?, updated_at = ? WHERE run_id = ?",
                (status, now, run_id),
            )
    record = get_run_record(run_id)
    if result is not None and tenant_id and project_id:
        _sync_protected_run_artifact(run_id, tenant_id, project_id, result)
        record = get_run_record(run_id)
    return record


def compare_and_set_run_status(run_id: str, expected_status: str, new_status: str, result: Optional[dict] = None) -> bool:
    now = _now()
    tenant_id: Optional[str] = None
    project_id: Optional[str] = None
    with transaction(write=True) as db:
        if result is None:
            cursor = db.execute(
                f"UPDATE {table('runs')} SET status = ?, updated_at = ? WHERE run_id = ? AND status = ?",
                (new_status, now, run_id, expected_status),
            )
        else:
            current = db.execute(
                f"SELECT tenant_id, project_id FROM {table('runs')} WHERE run_id = ? AND status = ?",
                (run_id, expected_status),
            ).fetchone()
            if current:
                tenant_id = current["tenant_id"]
                project_id = current["project_id"]
            cursor = db.execute(
                f"UPDATE {table('runs')} SET status = ?, result = ?, updated_at = ? WHERE run_id = ? AND status = ?",
                (new_status, json_param(result), now, run_id, expected_status),
            )
        changed = cursor.rowcount == 1
    if changed and result is not None and tenant_id and project_id:
        _sync_protected_run_artifact(run_id, tenant_id, project_id, result)
    return changed


def list_runs(tenant_id: Optional[str] = None, pipeline: Optional[str] = None, limit: int = 200) -> list:
    query = f"SELECT * FROM {table('runs')}"
    clauses: list[str] = []
    params: list = []
    if tenant_id:
        clauses.append("tenant_id = ?")
        params.append(tenant_id)
    if pipeline:
        clauses.append("pipeline = ?")
        params.append(pipeline)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(max(1, min(limit, 1000)))
    with transaction() as db:
        rows = db.execute(query, params).fetchall()
        return [_row_to_record(row) for row in rows]
