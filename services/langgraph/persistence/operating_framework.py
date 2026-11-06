"""Persistence for agency framework plans and task instances
(SQLite migration 20 / 20261024_amc_agency_framework_v1.sql).

``instantiate_plan`` is idempotent per (project, catalog version): the plan and
its 295 instance rows are written once, in one transaction, and a repeat call
returns the existing plan without touching any row, so reimporting can never
overwrite accepted work. ``update_task`` is the only writer of instance rows: it
compares and sets on ``version``, accepts an allowlisted column set and appends
the audit event to ``project_events`` in the same transaction.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.project_os.vocabulary import ActivityType
from services.langgraph.persistence.database import (
    decode_json,
    json_param,
    normalize_record,
    table,
    transaction,
)
from services.langgraph.persistence.projects import _append_event
from services.langgraph.persistence.tenancy import ensure_tenant_project

TASK_COLUMNS = frozenset({
    "applicability", "applicability_reason", "applicability_by", "state", "blocked_from", "status_reason",
    "evidence_refs", "artifact_refs", "decision_refs", "submitted_by", "verification", "approval_ref",
})
_JSON_COLUMNS = ("evidence_refs", "artifact_refs", "decision_refs", "verification")


class StaleTaskVersion(Exception):
    def __init__(self, task_id: str, expected: int, actual: int | None):
        super().__init__(f"{task_id} is at version {actual}, not {expected}")
        self.task_id = task_id
        self.expected = expected
        self.actual = actual


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def plan_id_for(project_id: str, catalog_version: str) -> str:
    return "afp-" + canonical_hash({"project_id": project_id, "catalog_version": catalog_version})[:24]


def _task(row: Any) -> dict:
    record = normalize_record(row)
    for key in _JSON_COLUMNS:
        record[key] = decode_json(record.get(key), [] if key != "verification" else None)
    return record


def get_plan(plan_id: str) -> dict | None:
    with transaction() as db:
        row = db.execute(f"SELECT * FROM {table('agency_framework_plans')} WHERE plan_id = ?", (plan_id,)).fetchone()
    return normalize_record(row) if row else None


def plans_for_project(project_id: str) -> list[dict]:
    with transaction() as db:
        rows = db.execute(
            f"SELECT * FROM {table('agency_framework_plans')} WHERE project_id = ? ORDER BY created_at", (project_id,),
        ).fetchall()
    return [normalize_record(r) for r in rows]


def instantiate_plan(*, tenant_id: str, project_id: str, catalog: Any, archetype: str, engagement_scope: str,
                     actor: str, assignee_roles: dict[str, str]) -> tuple[dict, bool]:
    """Return (plan, created). Never modifies an existing plan or its tasks."""
    plan_id = plan_id_for(project_id, catalog.catalog_version)
    existing = get_plan(plan_id)
    if existing is not None:
        return existing, False
    now = _now()
    with transaction(write=True) as db:
        ensure_tenant_project(db, tenant_id, project_id)
        row = db.execute(f"SELECT plan_id FROM {table('agency_framework_plans')} WHERE plan_id = ?", (plan_id,)).fetchone()
        if row is not None:  # another request won the race inside its own transaction
            return get_plan(plan_id), False  # type: ignore[return-value]
        db.execute(
            f"""INSERT INTO {table('agency_framework_plans')} (plan_id, tenant_id, project_id, catalog_id, catalog_version,
                catalog_sha256, archetype, engagement_scope, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (plan_id, tenant_id, project_id, catalog.catalog_id, catalog.catalog_version, catalog.sha256, archetype,
             engagement_scope, actor, now),
        )
        for task in catalog.tasks:
            db.execute(
                f"""INSERT INTO {table('agency_task_instances')} (plan_id, task_id, tenant_id, project_id, module_id, stage_gate,
                    applicability, state, assignee_role, evidence_refs, artifact_refs, decision_refs, version, updated_by,
                    created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'UNASSESSED', 'BACKLOG', ?, ?, ?, ?, 0, ?, ?, ?)""",
                (plan_id, task.task_id, tenant_id, project_id, task.module_id, task.stage_gate,
                 assignee_roles[task.module_id], json_param([]), json_param([]), json_param([]), actor, now, now),
            )
        _append_event(db, tenant_id=tenant_id, project_id=project_id, event_type=ActivityType.WORK_STARTED, actor=actor,
                      subject_ref=f"agency-plan:{plan_id}",
                      payload={"kind": "agency_framework.plan_instantiated", "plan_id": plan_id,
                               "catalog_version": catalog.catalog_version, "catalog_sha256": catalog.sha256,
                               "task_count": len(catalog.tasks), "archetype": archetype})
    return get_plan(plan_id), True  # type: ignore[return-value]


def list_tasks(plan_id: str, *, module_id: str | None = None) -> list[dict]:
    query = f"SELECT * FROM {table('agency_task_instances')} WHERE plan_id = ?"
    params: list[Any] = [plan_id]
    if module_id:
        query += " AND module_id = ?"
        params.append(module_id)
    query += " ORDER BY task_id"
    with transaction() as db:
        rows = db.execute(query, params).fetchall()
    return [_task(r) for r in rows]


def get_task(plan_id: str, task_id: str) -> dict | None:
    with transaction() as db:
        row = db.execute(
            f"SELECT * FROM {table('agency_task_instances')} WHERE plan_id = ? AND task_id = ?", (plan_id, task_id),
        ).fetchone()
    return _task(row) if row else None


def update_task(plan_id: str, task_id: str, *, expected_version: int, actor: str, changes: dict[str, Any],
                event_type: ActivityType, event_payload: dict[str, Any]) -> dict:
    """Compare-and-set one instance row and append its audit event atomically."""
    bad = set(changes) - TASK_COLUMNS
    if bad:
        raise ValueError(f"columns not writable: {sorted(bad)}")
    values = {k: (json_param(v) if k in _JSON_COLUMNS and v is not None else v) for k, v in changes.items()}
    assignments = ", ".join(f"{k} = ?" for k in values)
    with transaction(write=True) as db:
        cursor = db.execute(
            f"""UPDATE {table('agency_task_instances')} SET {assignments}{', ' if assignments else ''}version = version + 1,
                updated_by = ?, updated_at = ? WHERE plan_id = ? AND task_id = ? AND version = ?""",
            (*values.values(), actor, _now(), plan_id, task_id, expected_version),
        )
        if cursor.rowcount != 1:
            row = db.execute(
                f"SELECT version FROM {table('agency_task_instances')} WHERE plan_id = ? AND task_id = ?", (plan_id, task_id),
            ).fetchone()
            raise StaleTaskVersion(task_id, expected_version, int(row["version"]) if row else None)
        row = db.execute(
            f"SELECT * FROM {table('agency_task_instances')} WHERE plan_id = ? AND task_id = ?", (plan_id, task_id),
        ).fetchone()
        task = _task(row)
        _append_event(db, tenant_id=task["tenant_id"], project_id=task["project_id"], event_type=event_type, actor=actor,
                      subject_ref=f"agency-task:{plan_id}:{task_id}:v{task['version']}",
                      payload={"plan_id": plan_id, "task_id": task_id, "version": task["version"], **event_payload})
    return task


def framework_events(project_id: str, plan_id: str, *, limit: int = 200) -> list[dict]:
    """Audit trail of this plan, read from the existing project event stream."""
    with transaction() as db:
        rows = db.execute(
            f"""SELECT * FROM {table('project_events')} WHERE project_id = ? AND (subject_ref LIKE ? OR subject_ref = ?)
                ORDER BY sequence DESC LIMIT ?""",
            (project_id, f"agency-task:{plan_id}:%", f"agency-plan:{plan_id}", max(1, min(limit, 1000))),
        ).fetchall()
    out = []
    for row in rows:
        record = normalize_record(row)
        record["payload"] = decode_json(record.get("payload"), {})
        out.append(record)
    return out


def task_ids_by_state(plan_id: str, states: Iterable[str]) -> list[str]:
    wanted = list(states)
    with transaction() as db:
        rows = db.execute(
            f"SELECT task_id FROM {table('agency_task_instances')} WHERE plan_id = ? AND state IN ({', '.join('?' * len(wanted))})",
            (plan_id, *wanted),
        ).fetchall()
    return [r["task_id"] for r in rows]


__all__ = [
    "TASK_COLUMNS",
    "StaleTaskVersion",
    "framework_events",
    "get_plan",
    "get_task",
    "instantiate_plan",
    "list_tasks",
    "plan_id_for",
    "plans_for_project",
    "task_ids_by_state",
    "update_task",
]
