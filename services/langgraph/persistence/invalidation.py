from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from services.langgraph.persistence.approvals import get_approvals_for_run
from services.langgraph.persistence.database import decode_json, json_param, normalize_record, table, transaction
from services.langgraph.persistence.idempotency import hash_payload

EVENT_CLASSES: tuple[str, ...] = (
    "SPEC_CHANGE",
    "MODEL_PARAM_CHANGE",
    "TOOL_RESULT_CHANGE",
    "SCHEMA_CHANGE",
    "ACL_SECRET_CHANGE",
    "MEMORY_WRITE",
    "CLOCK_WINDOW_ADVANCE",
    "HOOK_GAP",
)
OPEN_STATES = {"OPEN", "HOOK_GAP"}
DISCHARGED_STATES = {"DISCHARGED_RECOMPUTE", "DISCHARGED_CUTOFF"}
STATE_VALUES = OPEN_STATES | DISCHARGED_STATES
PROTECTED_BRANCH_PREFIX = "art-protected-"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_record(row) -> Optional[dict]:
    if not row:
        return None
    record = normalize_record(row)
    record["payload"] = decode_json(record.get("payload"), {})
    return record


def _project_binding_hash(tenant_id: str, project_id: str) -> str:
    with transaction() as db:
        row = db.execute(
            f"SELECT binding_hash FROM {table('tenant_project_bindings')} WHERE tenant_id = ? AND project_id = ?",
            (tenant_id, project_id),
        ).fetchone()
    binding_hash = row["binding_hash"] if row else "unbound"
    return hash_payload({"tenant_id": tenant_id, "project_id": project_id, "binding_hash": binding_hash})


def _generation_provenance(result: Optional[dict]) -> list[dict]:
    agency = (result or {}).get("agency")
    if not isinstance(agency, dict):
        return []
    provenance = agency.get("generation_provenance") or []
    items = [item for item in provenance if isinstance(item, dict)]
    items.sort(key=lambda item: (str(item.get("task") or ""), str(item.get("completed_at") or "")))
    return items


def derive_event_bindings(*, tenant_id: str, project_id: str, result: Optional[dict]) -> dict[str, dict]:
    agency = (result or {}).get("agency") if isinstance(result, dict) else {}
    agency = agency if isinstance(agency, dict) else {}
    provenance = _generation_provenance(result)

    spec_snapshot = [
        {
            "task": item.get("task"),
            "prompt_version": item.get("prompt_version"),
            "prompt_hash": item.get("prompt_hash"),
        }
        for item in provenance
    ]
    model_snapshot = [
        {
            "task": item.get("task"),
            "provider": item.get("provider"),
            "model": item.get("model"),
            "mode": item.get("mode"),
            "attempts": item.get("attempts"),
            "fallback_used": item.get("fallback_used"),
        }
        for item in provenance
    ]
    schema_snapshot = [
        {
            "task": item.get("task"),
            "schema_version": item.get("schema_version"),
        }
        for item in provenance
    ]
    tool_snapshot = {
        "campaign_package": agency.get("campaign_package"),
        "qa_report": agency.get("qa_report"),
        "delivery": agency.get("delivery"),
        "degraded": bool(agency.get("degraded")),
    }

    return {
        "SPEC_CHANGE": {
            "cause_k": hash_payload({"spec": spec_snapshot}),
            "payload": {"spec_snapshot": spec_snapshot},
            "status": "BOUND",
        },
        "MODEL_PARAM_CHANGE": {
            "cause_k": hash_payload({"model_params": model_snapshot}),
            "payload": {"model_snapshot": model_snapshot},
            "status": "BOUND",
        },
        "TOOL_RESULT_CHANGE": {
            "cause_k": hash_payload({"tool_result": tool_snapshot}),
            "payload": {"tool_snapshot": tool_snapshot},
            "status": "BOUND",
        },
        "SCHEMA_CHANGE": {
            "cause_k": hash_payload({"schema": schema_snapshot}),
            "payload": {"schema_snapshot": schema_snapshot},
            "status": "BOUND",
        },
        "ACL_SECRET_CHANGE": {
            "cause_k": _project_binding_hash(tenant_id, project_id),
            "payload": {"authz_scope": {"tenant_id": tenant_id, "project_id": project_id}},
            "status": "BOUND",
        },
        "MEMORY_WRITE": {
            "cause_k": hash_payload({"memory_support": "not_present"}),
            "payload": {"memory_support": "not_present"},
            "status": "NOOP",
        },
        "CLOCK_WINDOW_ADVANCE": {
            "cause_k": hash_payload({"window_lease": None}),
            "payload": {"window_lease": None},
            "status": "NOOP",
        },
    }


def create_invalidation_obligation(
    *,
    tenant_id: str,
    project_id: str,
    run_id: str,
    artifact_branch: str,
    node_id: str,
    event_class: str,
    state: str,
    demanded: bool,
    cause_k: str,
    payload: dict,
) -> dict:
    if event_class not in EVENT_CLASSES:
        raise ValueError(f"Unsupported event_class={event_class}")
    if state not in STATE_VALUES:
        raise ValueError(f"Unsupported invalidation obligation state={state}")
    obligation_id = str(uuid4())
    now = _now()
    with transaction(write=True) as db:
        db.execute(
            f"""
            INSERT INTO {table('invalidation_obligations')}
            (obligation_id, tenant_id, project_id, run_id, artifact_branch, node_id, event_class, state, demanded, cause_k, payload, created_at, updated_at, discharged_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                obligation_id,
                tenant_id,
                project_id,
                run_id,
                artifact_branch,
                node_id,
                event_class,
                state,
                1 if demanded else 0,
                cause_k,
                json_param(payload),
                now,
                now,
                now if state in DISCHARGED_STATES else None,
            ),
        )
        row = db.execute(
            f"SELECT * FROM {table('invalidation_obligations')} WHERE obligation_id = ?",
            (obligation_id,),
        ).fetchone()
    record = _row_to_record(row)
    if record is None:
        raise RuntimeError("Invalidation obligation insert succeeded but record could not be read back")
    return record


def latest_branch_obligations(run_id: str, artifact_branch: str) -> dict[str, dict]:
    with transaction() as db:
        rows = db.execute(
            f"""
            SELECT io.*
            FROM {table('invalidation_obligations')} io
            JOIN (
                SELECT event_class, MAX(updated_at) AS updated_at
                FROM {table('invalidation_obligations')}
                WHERE run_id = ? AND artifact_branch = ?
                GROUP BY event_class
            ) latest
              ON latest.event_class = io.event_class AND latest.updated_at = io.updated_at
            WHERE io.run_id = ? AND io.artifact_branch = ?
            ORDER BY io.event_class
            """,
            (run_id, artifact_branch, run_id, artifact_branch),
        ).fetchall()
    latest: dict[str, dict] = {}
    for row in rows:
        record = _row_to_record(row)
        if record:
            latest[record["event_class"]] = record
    return latest


def record_run_invalidation_bindings(
    *,
    tenant_id: str,
    project_id: str,
    run_id: str,
    artifact_branch: str,
    result: Optional[dict],
    node_id: str = "delivery",
    demanded: bool = True,
) -> list[dict]:
    current = latest_branch_obligations(run_id, artifact_branch)
    bindings = derive_event_bindings(tenant_id=tenant_id, project_id=project_id, result=result)
    created: list[dict] = []
    for event_class in EVENT_CLASSES:
        if event_class == "HOOK_GAP":
            continue
        binding = bindings[event_class]
        previous = current.get(event_class)
        cause_k = binding["cause_k"]
        payload = {
            **binding["payload"],
            "artifact_branch": artifact_branch,
            "run_id": run_id,
            "binding_status": binding["status"],
        }
        if previous is None:
            created.append(
                create_invalidation_obligation(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    run_id=run_id,
                    artifact_branch=artifact_branch,
                    node_id=node_id,
                    event_class=event_class,
                    state="DISCHARGED_RECOMPUTE" if binding["status"] == "BOUND" else "DISCHARGED_CUTOFF",
                    demanded=demanded,
                    cause_k=cause_k,
                    payload=payload,
                )
            )
            continue
        if previous["cause_k"] == cause_k:
            continue
        created.append(
            create_invalidation_obligation(
                tenant_id=tenant_id,
                project_id=project_id,
                run_id=run_id,
                artifact_branch=artifact_branch,
                node_id=node_id,
                event_class=event_class,
                state="OPEN",
                demanded=demanded,
                cause_k=cause_k,
                payload={**payload, "previous_cause_k": previous["cause_k"]},
            )
        )
    return created


def discharge_run_obligations(
    *,
    run_id: str,
    artifact_branch: Optional[str] = None,
    status: str = "DISCHARGED_RECOMPUTE",
) -> list[dict]:
    if status not in DISCHARGED_STATES:
        raise ValueError(f"Unsupported discharge status={status}")
    query = f"""
        SELECT obligation_id FROM {table('invalidation_obligations')}
        WHERE run_id = ? AND state IN ('OPEN', 'HOOK_GAP')
    """
    params: list[object] = [run_id]
    if artifact_branch:
        query += " AND artifact_branch = ?"
        params.append(artifact_branch)
    with transaction() as db:
        rows = db.execute(query, params).fetchall()
    updated: list[dict] = []
    for row in rows:
        item = resolve_invalidation_obligation(row["obligation_id"], status)
        if item:
            updated.append(item)
    return updated


def resolve_invalidation_obligation(obligation_id: str, status: str) -> Optional[dict]:
    if status not in DISCHARGED_STATES:
        raise ValueError(f"Unsupported discharge status={status}")
    now = _now()
    with transaction(write=True) as db:
        db.execute(
            f"""
            UPDATE {table('invalidation_obligations')}
            SET state = ?, updated_at = ?, discharged_at = ?
            WHERE obligation_id = ? AND state IN ('OPEN', 'HOOK_GAP')
            """,
            (status, now, now, obligation_id),
        )
        row = db.execute(
            f"SELECT * FROM {table('invalidation_obligations')} WHERE obligation_id = ?",
            (obligation_id,),
        ).fetchone()
    return _row_to_record(row)


def list_project_invalidation_obligations(
    project_id: str,
    tenant_id: str,
    *,
    run_id: str | None = None,
    limit: int = 30,
) -> list[dict]:
    query = f"""
        SELECT * FROM {table('invalidation_obligations')}
        WHERE tenant_id = ? AND project_id = ?
    """
    params: list[object] = [tenant_id, project_id]
    if run_id:
        query += " AND run_id = ?"
        params.append(run_id)
    query += " ORDER BY updated_at DESC LIMIT ?"
    params.append(max(1, min(limit, 200)))
    with transaction() as db:
        rows = db.execute(query, params).fetchall()
    return [_row_to_record(row) for row in rows if row]


def open_demanded_obligations(
    *,
    run_id: str,
    artifact_branch: Optional[str] = None,
) -> list[dict]:
    query = f"""
        SELECT * FROM {table('invalidation_obligations')}
        WHERE run_id = ? AND demanded = 1 AND state IN ('OPEN', 'HOOK_GAP')
    """
    params: list[object] = [run_id]
    if artifact_branch:
        query += " AND artifact_branch = ?"
        params.append(artifact_branch)
    query += " ORDER BY updated_at DESC"
    with transaction() as db:
        rows = db.execute(query, params).fetchall()
    return [_row_to_record(row) for row in rows if row]


def run_compile_gate(run_id: str) -> dict:
    artifact_branch = f"{PROTECTED_BRANCH_PREFIX}{run_id}"
    obligations = open_demanded_obligations(run_id=run_id, artifact_branch=artifact_branch)
    approvals = get_approvals_for_run(run_id)
    stale_approvals = [approval for approval in approvals if approval.get("status") == "stale"]
    return {
        "artifact_branch": artifact_branch,
        "compile_blocked": bool(obligations or stale_approvals),
        "open_obligations": obligations,
        "stale_approvals": stale_approvals,
    }


def project_snapshot_fold(*, tenant_id: str, project_id: str, run_id: str | None = None) -> str:
    obligations = list_project_invalidation_obligations(project_id, tenant_id, run_id=run_id, limit=200)
    approvals: list[dict] = []
    with transaction() as db:
        query = f"SELECT * FROM {table('approvals')} WHERE tenant_id = ? AND project_id = ? AND status = 'stale' ORDER BY approval_id"
        params: list[object] = [tenant_id, project_id]
        if run_id:
            query = f"SELECT * FROM {table('approvals')} WHERE tenant_id = ? AND project_id = ? AND run_id = ? AND status = 'stale' ORDER BY approval_id"
            params.append(run_id)
        rows = db.execute(query, params).fetchall()
        approvals = [normalize_record(row) for row in rows]
    return hash_payload({"obligations": obligations, "stale_approvals": approvals})
