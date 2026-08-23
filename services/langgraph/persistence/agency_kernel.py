from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from typing import Any, Optional

from services.langgraph.persistence.database import (
    decode_json,
    json_param,
    normalize_record,
    table,
    transaction,
)

_JSON_FIELDS = {
    "engagements": ("constraints", "permissions", "metadata"),
    "workstreams": ("dependencies", "acceptance_criteria", "permissions", "metadata"),
    "agency_evidence": ("payload", "metadata"),
    "agency_decisions": ("alternatives", "selected_option", "evidence_ids", "assumptions", "affected_artifact_ids", "confidence"),
    "agency_artifacts": ("assumptions", "validation", "approval", "metadata"),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_record(row: Any, entity: str) -> dict:
    record = normalize_record(row)
    for field in _JSON_FIELDS.get(entity, ()):
        if field in record:
            default = [] if field in {"dependencies", "acceptance_criteria", "permissions", "alternatives", "evidence_ids", "assumptions", "affected_artifact_ids"} else {}
            record[field] = decode_json(record.get(field), default)
    return record


def _get(entity: str, id_column: str, value: str) -> Optional[dict]:
    with transaction() as db:
        row = db.execute(f"SELECT * FROM {table(entity)} WHERE {id_column} = ?", (value,)).fetchone()
    return _row_to_record(row, entity) if row else None


def create_engagement(
    engagement_id: str,
    tenant_id: str,
    project_id: str,
    objective: str,
    desired_outcome: str,
    *,
    status: str = "intake",
    constraints: Optional[dict] = None,
    permissions: Optional[dict] = None,
    metadata: Optional[dict] = None,
) -> dict:
    now = _now()
    with transaction(write=True) as db:
        db.execute(
            f"""
            INSERT INTO {table('engagements')}
            (engagement_id, tenant_id, project_id, objective, desired_outcome, status, constraints, permissions, metadata, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                engagement_id,
                tenant_id,
                project_id,
                objective,
                desired_outcome,
                status,
                json_param(constraints or {}),
                json_param(permissions or {}),
                json_param(metadata or {}),
                now,
                now,
            ),
        )
    record = get_engagement(engagement_id)
    if record is None:
        raise RuntimeError("Engagement insert succeeded but record could not be read back")
    return record


def get_engagement(engagement_id: str) -> Optional[dict]:
    return _get("engagements", "engagement_id", engagement_id)


def list_engagements(tenant_id: str, project_id: Optional[str] = None, limit: int = 100) -> list[dict]:
    query = f"SELECT * FROM {table('engagements')} WHERE tenant_id = ?"
    params: list[Any] = [tenant_id]
    if project_id is not None:
        query += " AND project_id = ?"
        params.append(project_id)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(max(1, min(limit, 500)))
    with transaction() as db:
        rows = db.execute(query, params).fetchall()
    return [_row_to_record(row, "engagements") for row in rows]


def create_workstream(
    workstream_id: str,
    engagement_id: str,
    tenant_id: str,
    project_id: str,
    department: str,
    objective: str,
    *,
    status: str = "ready",
    dependencies: Optional[list[str]] = None,
    acceptance_criteria: Optional[list[str]] = None,
    permissions: Optional[list[str]] = None,
    metadata: Optional[dict] = None,
) -> dict:
    _assert_engagement_scope(engagement_id, tenant_id, project_id)
    now = _now()
    with transaction(write=True) as db:
        db.execute(
            f"""
            INSERT INTO {table('workstreams')}
            (workstream_id, engagement_id, tenant_id, project_id, department, objective, status, dependencies, acceptance_criteria, permissions, metadata, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                workstream_id,
                engagement_id,
                tenant_id,
                project_id,
                department,
                objective,
                status,
                json_param(dependencies or []),
                json_param(acceptance_criteria or []),
                json_param(permissions or []),
                json_param(metadata or {}),
                now,
                now,
            ),
        )
    record = get_workstream(workstream_id)
    if record is None:
        raise RuntimeError("Workstream insert succeeded but record could not be read back")
    return record


def get_workstream(workstream_id: str) -> Optional[dict]:
    return _get("workstreams", "workstream_id", workstream_id)


def create_evidence(
    evidence_id: str,
    engagement_id: str,
    tenant_id: str,
    project_id: str,
    evidence_type: str,
    claim: str,
    epistemic_status: str,
    confidence: float,
    *,
    source_ref: Optional[str] = None,
    collected_at: Optional[str] = None,
    freshness_seconds: Optional[int] = None,
    payload: Optional[dict] = None,
    metadata: Optional[dict] = None,
) -> dict:
    _assert_engagement_scope(engagement_id, tenant_id, project_id)
    collected_at = collected_at or _now()
    with transaction(write=True) as db:
        db.execute(
            f"""
            INSERT INTO {table('agency_evidence')}
            (evidence_id, engagement_id, tenant_id, project_id, evidence_type, source_ref, claim, epistemic_status, confidence, collected_at, freshness_seconds, payload, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evidence_id,
                engagement_id,
                tenant_id,
                project_id,
                evidence_type,
                source_ref,
                claim,
                epistemic_status,
                confidence,
                collected_at,
                freshness_seconds,
                json_param(payload or {}),
                json_param(metadata or {}),
            ),
        )
    record = get_evidence(evidence_id)
    if record is None:
        raise RuntimeError("Evidence insert succeeded but record could not be read back")
    return record


def get_evidence(evidence_id: str) -> Optional[dict]:
    return _get("agency_evidence", "evidence_id", evidence_id)


def create_decision(
    decision_id: str,
    engagement_id: str,
    tenant_id: str,
    project_id: str,
    question: str,
    confidence: dict,
    *,
    alternatives: Optional[list] = None,
    selected_option: Any = None,
    evidence_ids: Optional[list[str]] = None,
    assumptions: Optional[list[str]] = None,
    affected_artifact_ids: Optional[list[str]] = None,
    status: str = "proposed",
    approver: Optional[str] = None,
) -> dict:
    _assert_engagement_scope(engagement_id, tenant_id, project_id)
    now = _now()
    with transaction(write=True) as db:
        db.execute(
            f"""
            INSERT INTO {table('agency_decisions')}
            (decision_id, engagement_id, tenant_id, project_id, question, alternatives, selected_option, evidence_ids, assumptions, affected_artifact_ids, confidence, status, approver, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision_id,
                engagement_id,
                tenant_id,
                project_id,
                question,
                json_param(alternatives or []),
                json_param(selected_option),
                json_param(evidence_ids or []),
                json_param(assumptions or []),
                json_param(affected_artifact_ids or []),
                json_param(confidence),
                status,
                approver,
                now,
                now,
            ),
        )
    record = get_decision(decision_id)
    if record is None:
        raise RuntimeError("Decision insert succeeded but record could not be read back")
    return record


def get_decision(decision_id: str) -> Optional[dict]:
    return _get("agency_decisions", "decision_id", decision_id)


def create_artifact(
    artifact_id: str,
    engagement_id: str,
    tenant_id: str,
    project_id: str,
    artifact_type: str,
    owner_department: str,
    *,
    workstream_id: Optional[str] = None,
    subtype: Optional[str] = None,
    version: int = 1,
    status: str = "draft",
    content_location: Optional[str] = None,
    content_hash: Optional[str] = None,
    semantic_fingerprint: Optional[str] = None,
    assumptions: Optional[list[str]] = None,
    validation: Optional[dict] = None,
    approval: Optional[dict] = None,
    metadata: Optional[dict] = None,
) -> dict:
    _assert_engagement_scope(engagement_id, tenant_id, project_id)
    if workstream_id is not None:
        workstream = get_workstream(workstream_id)
        if not workstream or workstream["engagement_id"] != engagement_id:
            raise ValueError("workstream_id must belong to the artifact engagement")
    now = _now()
    with transaction(write=True) as db:
        db.execute(
            f"""
            INSERT INTO {table('agency_artifacts')}
            (artifact_id, engagement_id, tenant_id, project_id, workstream_id, artifact_type, subtype, owner_department, version, status, content_location, content_hash, semantic_fingerprint, assumptions, validation, approval, metadata, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact_id,
                engagement_id,
                tenant_id,
                project_id,
                workstream_id,
                artifact_type,
                subtype,
                owner_department,
                version,
                status,
                content_location,
                content_hash,
                semantic_fingerprint,
                json_param(assumptions or []),
                json_param(validation or {}),
                json_param(approval or {}),
                json_param(metadata or {}),
                now,
                now,
            ),
        )
    record = get_artifact(artifact_id)
    if record is None:
        raise RuntimeError("Artifact insert succeeded but record could not be read back")
    return record


def get_artifact(artifact_id: str) -> Optional[dict]:
    return _get("agency_artifacts", "artifact_id", artifact_id)


def _dependency_would_cycle(artifact_id: str, depends_on_artifact_id: str) -> bool:
    queue: deque[str] = deque([depends_on_artifact_id])
    visited: set[str] = set()
    with transaction() as db:
        while queue:
            current = queue.popleft()
            if current == artifact_id:
                return True
            if current in visited:
                continue
            visited.add(current)
            rows = db.execute(
                f"SELECT depends_on_artifact_id FROM {table('artifact_dependencies')} WHERE artifact_id = ? ORDER BY depends_on_artifact_id",
                (current,),
            ).fetchall()
            queue.extend(row["depends_on_artifact_id"] for row in rows)
    return False


def add_artifact_dependency(artifact_id: str, depends_on_artifact_id: str, relationship: str = "hard") -> dict:
    if artifact_id == depends_on_artifact_id:
        raise ValueError("An artifact cannot depend on itself")
    artifact = get_artifact(artifact_id)
    upstream = get_artifact(depends_on_artifact_id)
    if not artifact or not upstream:
        raise ValueError("Both artifacts must exist before a dependency can be added")
    if artifact["engagement_id"] != upstream["engagement_id"]:
        raise ValueError("Artifact dependencies cannot cross engagement boundaries")
    if relationship not in {"hard", "soft"}:
        raise ValueError("relationship must be 'hard' or 'soft'")
    if _dependency_would_cycle(artifact_id, depends_on_artifact_id):
        raise ValueError("Artifact dependency would create a cycle")
    with transaction(write=True) as db:
        db.execute(
            f"INSERT INTO {table('artifact_dependencies')} (artifact_id, depends_on_artifact_id, relationship, created_at) VALUES (?, ?, ?, ?)",
            (artifact_id, depends_on_artifact_id, relationship, _now()),
        )
    return {
        "artifact_id": artifact_id,
        "depends_on_artifact_id": depends_on_artifact_id,
        "relationship": relationship,
    }


def artifact_dependency_graph(engagement_id: str) -> dict:
    with transaction() as db:
        nodes = db.execute(
            f"SELECT artifact_id, artifact_type, version, status FROM {table('agency_artifacts')} WHERE engagement_id = ? ORDER BY artifact_id",
            (engagement_id,),
        ).fetchall()
        edges = db.execute(
            f"""
            SELECT d.artifact_id, d.depends_on_artifact_id, d.relationship
            FROM {table('artifact_dependencies')} d
            JOIN {table('agency_artifacts')} a ON a.artifact_id = d.artifact_id
            WHERE a.engagement_id = ?
            ORDER BY d.depends_on_artifact_id, d.artifact_id
            """,
            (engagement_id,),
        ).fetchall()
    return {
        "engagement_id": engagement_id,
        "nodes": [normalize_record(row) for row in nodes],
        "edges": [normalize_record(row) for row in edges],
    }


def propagate_artifact_change(artifact_id: str) -> list[dict]:
    source = get_artifact(artifact_id)
    if not source:
        raise ValueError("Artifact not found")

    severity: dict[str, str] = {}
    queue: deque[tuple[str, str]] = deque([(artifact_id, "invalidated")])
    visited_states: set[tuple[str, str]] = set()

    with transaction() as db:
        while queue:
            current_id, current_severity = queue.popleft()
            state_key = (current_id, current_severity)
            if state_key in visited_states:
                continue
            visited_states.add(state_key)
            rows = db.execute(
                f"SELECT artifact_id, relationship FROM {table('artifact_dependencies')} WHERE depends_on_artifact_id = ? ORDER BY artifact_id",
                (current_id,),
            ).fetchall()
            for row in rows:
                dependent_id = row["artifact_id"]
                relationship = row["relationship"]
                next_severity = "invalidated" if current_severity == "invalidated" and relationship == "hard" else "review_required"
                prior = severity.get(dependent_id)
                if prior == "invalidated" or prior == next_severity:
                    continue
                if prior == "review_required" and next_severity == "invalidated":
                    severity[dependent_id] = "invalidated"
                elif prior is None:
                    severity[dependent_id] = next_severity
                queue.append((dependent_id, severity[dependent_id]))

    now = _now()
    with transaction(write=True) as db:
        for dependent_id in sorted(severity):
            db.execute(
                f"UPDATE {table('agency_artifacts')} SET status = ?, updated_at = ? WHERE artifact_id = ? AND engagement_id = ?",
                (severity[dependent_id], now, dependent_id, source["engagement_id"]),
            )

    return [
        {"artifact_id": dependent_id, "status": severity[dependent_id]}
        for dependent_id in sorted(severity)
    ]


def _assert_engagement_scope(engagement_id: str, tenant_id: str, project_id: str) -> None:
    engagement = get_engagement(engagement_id)
    if not engagement:
        raise ValueError("Engagement not found")
    if engagement["tenant_id"] != tenant_id or engagement["project_id"] != project_id:
        raise ValueError("Engagement tenant/project scope mismatch")
