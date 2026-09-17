from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from services.langgraph.agency.execution.models import (
    CompletionEvaluation,
    DispatchPermit,
    ExecutionReceipt,
    FailureFingerprint,
    ObservationReceipt,
)
from services.langgraph.persistence.database import decode_json, json_param, normalize_record, table, transaction


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decode_payload(row) -> dict[str, Any]:
    record = normalize_record(row)
    record["payload"] = decode_json(record.get("payload"), {})
    return record


def put_execution_receipt(run_id: str, tenant_id: str, project_id: str, receipt: ExecutionReceipt) -> dict[str, Any]:
    with transaction(write=True) as db:
        db.execute(
            f"""
            INSERT INTO {table('execution_receipts')}
            (operation_id, run_id, tenant_id, project_id, work_order_id, payload, started_at, ended_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (operation_id) DO UPDATE SET
                payload = excluded.payload,
                started_at = excluded.started_at,
                ended_at = excluded.ended_at
            """,
            (
                receipt.operation_id,
                run_id,
                tenant_id,
                project_id,
                receipt.work_order_id,
                json_param(receipt.model_dump(mode="json")),
                receipt.started_at.isoformat(),
                receipt.ended_at.isoformat(),
            ),
        )
    return {
        "run_id": run_id,
        "tenant_id": tenant_id,
        "project_id": project_id,
        **receipt.model_dump(mode="json"),
    }


def put_observation_receipt(run_id: str, tenant_id: str, project_id: str, receipt: ObservationReceipt) -> dict[str, Any]:
    with transaction(write=True) as db:
        db.execute(
            f"""
            INSERT INTO {table('observation_receipts')}
            (operation_id, run_id, tenant_id, project_id, payload, observed_at, matches)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (operation_id) DO UPDATE SET
                payload = excluded.payload,
                observed_at = excluded.observed_at,
                matches = excluded.matches
            """,
            (
                receipt.operation_id,
                run_id,
                tenant_id,
                project_id,
                json_param(receipt.model_dump(mode="json")),
                receipt.observed_at.isoformat(),
                1 if receipt.matches else 0,
            ),
        )
    return {
        "run_id": run_id,
        "tenant_id": tenant_id,
        "project_id": project_id,
        **receipt.model_dump(mode="json"),
    }


def put_dispatch_permit(run_id: str, tenant_id: str, project_id: str, permit: DispatchPermit) -> dict[str, Any]:
    with transaction(write=True) as db:
        db.execute(
            f"""
            INSERT INTO {table('dispatch_permits')}
            (permit_id, run_id, tenant_id, project_id, work_order_id, payload, issued_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (permit_id) DO UPDATE SET
                payload = excluded.payload,
                issued_at = excluded.issued_at
            """,
            (
                permit.permit_id,
                run_id,
                tenant_id,
                project_id,
                permit.work_order_id,
                json_param(permit.model_dump(mode="json")),
                permit.issued_at.isoformat(),
            ),
        )
    return {
        "run_id": run_id,
        "tenant_id": tenant_id,
        "project_id": project_id,
        **permit.model_dump(mode="json"),
    }


def put_failure_fingerprint(
    run_id: str,
    tenant_id: str,
    project_id: str,
    operation_id: str,
    fingerprint: FailureFingerprint,
) -> dict[str, Any]:
    with transaction(write=True) as db:
        db.execute(
            f"""
            INSERT INTO {table('failure_fingerprints')}
            (fingerprint, run_id, tenant_id, project_id, operation_id, payload)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (fingerprint) DO UPDATE SET
                run_id = excluded.run_id,
                tenant_id = excluded.tenant_id,
                project_id = excluded.project_id,
                payload = excluded.payload,
                operation_id = excluded.operation_id
            """,
            (
                fingerprint.fingerprint,
                run_id,
                tenant_id,
                project_id,
                operation_id,
                json_param(fingerprint.model_dump(mode="json")),
            ),
        )
    return {
        "run_id": run_id,
        "tenant_id": tenant_id,
        "project_id": project_id,
        "operation_id": operation_id,
        **fingerprint.model_dump(mode="json"),
    }


def put_completion_evaluation(
    run_id: str,
    tenant_id: str,
    project_id: str,
    evaluation: CompletionEvaluation,
) -> dict[str, Any]:
    evaluation_id = str(uuid4())
    created_at = _now()
    with transaction(write=True) as db:
        db.execute(
            f"""
            INSERT INTO {table('completion_evaluations')}
            (evaluation_id, run_id, tenant_id, project_id, terminal_candidate, proof_coverage, confidence, payload, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evaluation_id,
                run_id,
                tenant_id,
                project_id,
                evaluation.terminal_candidate,
                evaluation.proof_coverage,
                evaluation.confidence,
                json_param(evaluation.model_dump(mode="json")),
                created_at,
            ),
        )
    return {
        "evaluation_id": evaluation_id,
        "run_id": run_id,
        "tenant_id": tenant_id,
        "project_id": project_id,
        "created_at": created_at,
        **evaluation.model_dump(mode="json"),
    }


def list_execution_receipts(run_id: str) -> list[dict[str, Any]]:
    with transaction() as db:
        rows = db.execute(
            f"SELECT run_id, tenant_id, project_id, payload FROM {table('execution_receipts')} WHERE run_id = ? ORDER BY started_at ASC",
            (run_id,),
        ).fetchall()
    return [{**normalize_record(row), **decode_json(row["payload"], {})} for row in rows]


def list_observation_receipts(run_id: str) -> list[dict[str, Any]]:
    with transaction() as db:
        rows = db.execute(
            f"SELECT run_id, tenant_id, project_id, payload FROM {table('observation_receipts')} WHERE run_id = ? ORDER BY observed_at ASC",
            (run_id,),
        ).fetchall()
    return [{**normalize_record(row), **decode_json(row["payload"], {})} for row in rows]


def list_dispatch_permits(run_id: str) -> list[dict[str, Any]]:
    with transaction() as db:
        rows = db.execute(
            f"SELECT run_id, tenant_id, project_id, payload FROM {table('dispatch_permits')} WHERE run_id = ? ORDER BY issued_at ASC",
            (run_id,),
        ).fetchall()
    return [{**normalize_record(row), **decode_json(row["payload"], {})} for row in rows]


def list_failure_fingerprints(run_id: str) -> list[dict[str, Any]]:
    with transaction() as db:
        rows = db.execute(
            f"SELECT run_id, tenant_id, project_id, operation_id, payload FROM {table('failure_fingerprints')} WHERE run_id = ? ORDER BY operation_id ASC",
            (run_id,),
        ).fetchall()
    return [{**normalize_record(row), **decode_json(row["payload"], {})} for row in rows]


def get_latest_completion_evaluation(run_id: str) -> dict[str, Any] | None:
    with transaction() as db:
        row = db.execute(
            f"SELECT * FROM {table('completion_evaluations')} WHERE run_id = ? ORDER BY created_at DESC LIMIT 1",
            (run_id,),
        ).fetchone()
    return _decode_payload(row) if row else None


def get_run_proof_bundle(run_id: str) -> dict[str, Any]:
    executions = list_execution_receipts(run_id)
    observations = list_observation_receipts(run_id)
    permits = list_dispatch_permits(run_id)
    failures = list_failure_fingerprints(run_id)
    completion = get_latest_completion_evaluation(run_id)
    matched_observations = sum(1 for receipt in observations if receipt.get("matches") is True)
    return {
        "dispatch_permits": permits,
        "execution_receipts": executions,
        "observation_receipts": observations,
        "failure_fingerprints": failures,
        "completion_evaluation": completion["payload"] if completion else None,
        "summary": {
            "dispatch_count": len(permits),
            "execution_count": len(executions),
            "observation_count": len(observations),
            "matched_observation_count": matched_observations,
            "failure_count": len(failures),
            "latest_terminal_candidate": (completion or {}).get("terminal_candidate"),
            "latest_confidence": (completion or {}).get("confidence"),
        },
    }
