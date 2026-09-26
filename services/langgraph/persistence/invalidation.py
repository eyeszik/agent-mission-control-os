from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from services.langgraph.persistence.approvals import get_approvals_for_run
from services.langgraph.persistence.database import decode_json, json_param, normalize_record, table, transaction
from services.langgraph.persistence.idempotency import hash_payload
from services.langgraph.persistence.lineage import list_project_lineage_remediations

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

# The live branding/marketing pipeline currently depends on generation spec,
# model parameters, tool results, schemas, and tenant/project authorization.
# Mutable memory and clock-window leases remain visible as HOOK_GAP evidence,
# but are not release-blocking until a pipeline explicitly declares them.
AGENCY_PIPELINE_DEMANDED_EVENT_CLASSES = frozenset({
    "SPEC_CHANGE",
    "MODEL_PARAM_CHANGE",
    "TOOL_RESULT_CHANGE",
    "SCHEMA_CHANGE",
    "ACL_SECRET_CHANGE",
})


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
    if not row or not row["binding_hash"]:
        return ""
    binding_hash = row["binding_hash"]
    return hash_payload({"tenant_id": tenant_id, "project_id": project_id, "binding_hash": binding_hash})


def _generation_provenance(result: Optional[dict]) -> list[dict]:
    agency = (result or {}).get("agency")
    if not isinstance(agency, dict):
        return []
    provenance = agency.get("generation_provenance") or []
    items = [item for item in provenance if isinstance(item, dict)]
    items.sort(key=lambda item: (str(item.get("task") or ""), str(item.get("completed_at") or "")))
    return items


def _provenance_witness(
    provenance: list[dict],
    *,
    required_fields: tuple[str, ...],
    event_class: str,
) -> dict[str, object]:
    if not provenance:
        return {
            "status": "HOOK_GAP",
            "cause_k": hash_payload({"event_class": event_class, "reason": "missing_generation_provenance"}),
            "payload": {
                "reason": "missing_generation_provenance",
                "required_fields": list(required_fields),
                "provenance_items": 0,
            },
        }

    missing: list[dict[str, object]] = []
    for item in provenance:
        absent = [
            field
            for field in required_fields
            if field not in item
            or item[field] is None
            or (isinstance(item[field], str) and not item[field].strip())
        ]
        if absent:
            missing.append(
                {
                    "task": item.get("task"),
                    "missing_fields": absent,
                }
            )
    if missing:
        return {
            "status": "HOOK_GAP",
            "cause_k": hash_payload({"event_class": event_class, "reason": "incomplete_generation_provenance", "missing": missing}),
            "payload": {
                "reason": "incomplete_generation_provenance",
                "required_fields": list(required_fields),
                "missing": missing,
                "provenance_items": len(provenance),
            },
        }

    return {
        "status": "BOUND",
        "cause_k": "",
        "payload": {
            "required_fields": list(required_fields),
            "provenance_items": len(provenance),
        },
    }


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
    spec_witness = _provenance_witness(
        provenance,
        required_fields=("task", "prompt_version", "prompt_hash"),
        event_class="SPEC_CHANGE",
    )
    model_witness = _provenance_witness(
        provenance,
        required_fields=("task", "provider", "model", "mode", "attempts", "fallback_used"),
        event_class="MODEL_PARAM_CHANGE",
    )
    schema_witness = _provenance_witness(
        provenance,
        required_fields=("task", "schema_version"),
        event_class="SCHEMA_CHANGE",
    )
    binding_hash = _project_binding_hash(tenant_id, project_id)
    acl_status = "BOUND" if binding_hash else "HOOK_GAP"

    return {
        "SPEC_CHANGE": {
            "cause_k": hash_payload({"spec": spec_snapshot}) if spec_witness["status"] == "BOUND" else spec_witness["cause_k"],
            "payload": {"spec_snapshot": spec_snapshot, **spec_witness["payload"]},
            "status": spec_witness["status"],
        },
        "MODEL_PARAM_CHANGE": {
            "cause_k": hash_payload({"model_params": model_snapshot}) if model_witness["status"] == "BOUND" else model_witness["cause_k"],
            "payload": {"model_snapshot": model_snapshot, **model_witness["payload"]},
            "status": model_witness["status"],
        },
        "TOOL_RESULT_CHANGE": {
            "cause_k": hash_payload({"tool_result": tool_snapshot}),
            "payload": {"tool_snapshot": tool_snapshot},
            "status": "BOUND",
        },
        "SCHEMA_CHANGE": {
            "cause_k": hash_payload({"schema": schema_snapshot}) if schema_witness["status"] == "BOUND" else schema_witness["cause_k"],
            "payload": {"schema_snapshot": schema_snapshot, **schema_witness["payload"]},
            "status": schema_witness["status"],
        },
        "ACL_SECRET_CHANGE": {
            "cause_k": binding_hash if binding_hash else hash_payload({"event_class": "ACL_SECRET_CHANGE", "reason": "missing_tenant_project_binding"}),
            "payload": {
                "authz_scope": {"tenant_id": tenant_id, "project_id": project_id},
                "reason": None if acl_status == "BOUND" else "missing_tenant_project_binding",
            },
            "status": acl_status,
        },
        "MEMORY_WRITE": {
            "cause_k": hash_payload({"event_class": "MEMORY_WRITE", "reason": "no_persisted_memory_source"}),
            "payload": {"reason": "no_persisted_memory_source"},
            "status": "HOOK_GAP",
        },
        "CLOCK_WINDOW_ADVANCE": {
            "cause_k": hash_payload({"event_class": "CLOCK_WINDOW_ADVANCE", "reason": "missing_window_lease_source"}),
            "payload": {"reason": "missing_window_lease_source", "window_lease": None},
            "status": "HOOK_GAP",
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
    demanded_event_classes: set[str] | frozenset[str] | None = None,
) -> list[dict]:
    current = latest_branch_obligations(run_id, artifact_branch)
    bindings = derive_event_bindings(tenant_id=tenant_id, project_id=project_id, result=result)
    created: list[dict] = []
    for event_class in EVENT_CLASSES:
        if event_class == "HOOK_GAP":
            continue
        binding = bindings[event_class]
        event_demanded = (
            event_class in demanded_event_classes
            if demanded_event_classes is not None
            else demanded
        )
        previous = current.get(event_class)
        cause_k = binding["cause_k"]
        payload = {
            **binding["payload"],
            "artifact_branch": artifact_branch,
            "run_id": run_id,
            "binding_status": binding["status"],
        }
        if previous is None:
            initial_state = (
                "DISCHARGED_RECOMPUTE"
                if binding["status"] == "BOUND"
                else "HOOK_GAP"
                if binding["status"] == "HOOK_GAP"
                else "DISCHARGED_CUTOFF"
            )
            created.append(
                create_invalidation_obligation(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    run_id=run_id,
                    artifact_branch=artifact_branch,
                    node_id=node_id,
                    event_class=event_class,
                    state=initial_state,
                    demanded=event_demanded,
                    cause_k=cause_k,
                    payload=payload,
                )
            )
            continue
        if previous["cause_k"] == cause_k:
            continue
        next_state = "HOOK_GAP" if binding["status"] == "HOOK_GAP" else "OPEN"
        created.append(
            create_invalidation_obligation(
                tenant_id=tenant_id,
                project_id=project_id,
                run_id=run_id,
                artifact_branch=artifact_branch,
                node_id=node_id,
                event_class=event_class,
                state=next_state,
                demanded=event_demanded,
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
    lineage_remediations: list[dict] = []
    with transaction() as db:
        run_row = db.execute(
            f"SELECT tenant_id, project_id FROM {table('runs')} WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    if run_row:
        lineage_remediations = [
            item
            for item in list_project_lineage_remediations(run_row["project_id"], run_row["tenant_id"], limit=200)
            if item["run_id"] == run_id and item["status"] == "OPEN"
        ]
    return {
        "artifact_branch": artifact_branch,
        "compile_blocked": bool(obligations or stale_approvals or lineage_remediations),
        "open_obligations": obligations,
        "stale_approvals": stale_approvals,
        "lineage_remediations": lineage_remediations,
    }


def project_snapshot_state(*, tenant_id: str, project_id: str, run_id: str | None = None) -> dict:
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
    lineage = list_project_lineage_remediations(project_id, tenant_id, limit=200)
    if run_id:
        lineage = [item for item in lineage if item["run_id"] == run_id]
    return {
        "obligations": obligations,
        "stale_approvals": approvals,
        "lineage_remediations": lineage,
        "compile_blocked": bool(
            any(item["state"] in {"OPEN", "HOOK_GAP"} and item["demanded"] for item in obligations)
            or approvals
            or any(item["status"] == "OPEN" for item in lineage)
        ),
    }


def project_snapshot_fold(*, tenant_id: str, project_id: str, run_id: str | None = None) -> str:
    return hash_payload(project_snapshot_state(tenant_id=tenant_id, project_id=project_id, run_id=run_id))
