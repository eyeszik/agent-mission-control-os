from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from services.langgraph.agency.reliability import IdempotencyStatus, PolicyEffect
from services.langgraph.agency.reliability.models import OutboxStatus, RecoveryStatus
from services.langgraph.agency.reliability.outbox import OutboxDispatcher
from services.langgraph.app.in_memory_queue import DuplicateOperationError, QueueFullError
from services.langgraph.app.runtime_support import role_os_registry, runtime_queue, trust_kernel
from services.langgraph.persistence.agency_kernel import create_or_revise_protected_run_artifact, record_artifact_revision
from services.langgraph.persistence.approvals import bind_approval_subject, create_approval_request, get_approvals_for_run
from services.langgraph.persistence.database import database_backend
from services.langgraph.persistence.events import record_event
from services.langgraph.persistence.idempotency import complete_idempotency, fail_idempotency, hash_payload, reserve_idempotency
from services.langgraph.persistence.invalidation import (
    discharge_run_obligations,
    list_project_invalidation_obligations,
    record_run_invalidation_bindings,
    run_compile_gate,
)
from services.langgraph.persistence.lineage import list_project_lineage_remediations, resolve_lineage_remediation_for_run
from services.langgraph.persistence.runs import get_run_record, update_run_status
from services.langgraph.security.auth import Principal, authorize_project, authorize_resource, get_principal

router = APIRouter()
IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60


class RuntimeIngressRequest(BaseModel):
    operation_id: str = Field(min_length=1, max_length=200)
    mission_id: str = Field(min_length=1, max_length=200)
    project_id: str = Field(min_length=1, max_length=200)
    payload: dict = Field(default_factory=dict)


class RecoveryResolveRequest(BaseModel):
    status: str = Field(pattern="^(RECONCILED|COMPENSATED|ESCALATED)$")
    run_id: str | None = None


class OutboxReplayRequest(BaseModel):
    run_id: str | None = None


class RunRetryRequest(BaseModel):
    recovery_id: str = Field(min_length=1)


class RunCompensationRequest(BaseModel):
    recovery_id: str = Field(min_length=1)


class RegenerateApprovalRequest(BaseModel):
    approval_id: str | None = None


class ProtectedArtifactRevisionRequest(BaseModel):
    content_hash: str = Field(min_length=32, max_length=128)


def _operator_scope(principal: Principal, project_id: str, target: str) -> str:
    return f"{principal.tenant_id}:{principal.user_id}:{target}:{project_id}"


def _run_operator_scope(principal: Principal, run_id: str, target: str) -> str:
    return f"{principal.tenant_id}:{principal.user_id}:{target}:{run_id}"


def _authorized_run(principal: Principal, run_id: str) -> dict:
    record = get_run_record(run_id)
    if not record:
        raise HTTPException(status_code=404, detail="Run not found")
    authorize_resource(principal, record["tenant_id"], record["project_id"])
    return record


def _latest_approval_for_run(run_id: str) -> dict | None:
    approvals = get_approvals_for_run(run_id)
    return approvals[0] if approvals else None


def _recovery_for_run(*, run_id: str, recovery_id: str, tenant_id: str, project_id: str):
    kernel = trust_kernel()
    recovery = kernel.store.state.recovery.get(recovery_id)
    if recovery is None:
        raise HTTPException(status_code=404, detail="Recovery case not found")
    if recovery.tenant_id != tenant_id or recovery.project_id != project_id:
        raise HTTPException(status_code=403, detail="Recovery case is outside the authorized project scope")
    refs = {ref for ref in (recovery.execution_ref, recovery.observation_ref, recovery.operation_id) if ref}
    if run_id not in refs and f":{run_id}" not in recovery.operation_id:
        raise HTTPException(status_code=409, detail="Recovery case does not belong to the requested run")
    return kernel, recovery


def _record_recovery_event(run_id: str, tenant_id: str, project_id: str, recovery) -> None:
    record_event(
        run_id,
        tenant_id,
        project_id,
        "trust",
        "recovery_case_updated",
        safe_payload={
            "recovery_id": recovery.recovery_id,
            "status": recovery.status.value,
            "reason": recovery.reason,
            "operation_id": recovery.operation_id,
        },
    )


def _record_remediation_event(run_id: str, tenant_id: str, project_id: str, *, action: str, payload: dict) -> None:
    record_event(
        run_id,
        tenant_id,
        project_id,
        "trust",
        "run_remediation_updated",
        safe_payload={"action": action, **payload},
    )


def _project_trust_details(project_id: str, tenant_id: str) -> dict:
    kernel = trust_kernel()
    kernel.bind_project(tenant_id=tenant_id, project_id=project_id)
    snapshot = kernel.snapshot(tenant_id=tenant_id, project_id=project_id)
    state = kernel.store.state

    policy_decisions = [
        decision.model_dump(mode="json")
        for decision in state.policy_decisions.values()
        if decision.tenant_id == tenant_id and decision.project_id == project_id
    ]
    policy_decisions.sort(key=lambda item: (item["decided_at"], item["decision_id"]), reverse=True)

    outbox_messages = [
        message.model_dump(mode="json")
        for message in state.outbox.values()
        if message.tenant_id == tenant_id and message.project_id == project_id
    ]
    outbox_messages.sort(key=lambda item: (item["created_at"], item["message_id"]), reverse=True)

    recovery_cases = [
        case.model_dump(mode="json")
        for case in state.recovery.values()
        if case.tenant_id == tenant_id and case.project_id == project_id
    ]
    recovery_cases.sort(key=lambda item: (item["created_at"], item["recovery_id"]), reverse=True)
    lineage_remediations = list_project_lineage_remediations(project_id, tenant_id, limit=12)
    obligations = list_project_invalidation_obligations(project_id, tenant_id, limit=20)

    audit_events = [
        audit.model_dump(mode="json")
        for audit in state.audits
        if audit.tenant_id == tenant_id and audit.project_id == project_id
    ]
    audit_events.sort(key=lambda item: item["seq"], reverse=True)

    return {
        **snapshot.model_dump(mode="json"),
        "database_backend": database_backend(),
        "persistence_mode": "canonical_database",
        "compile_blocked": bool(
            any(item["state"] in {"OPEN", "HOOK_GAP"} and item["demanded"] for item in obligations)
            or any(item["status"] == "OPEN" for item in lineage_remediations)
        ),
        "open_invalidation_obligations": sum(1 for item in obligations if item["state"] == "OPEN"),
        "hook_gap_count": sum(1 for item in obligations if item["state"] == "HOOK_GAP"),
        "delivered_outbox": sum(1 for item in outbox_messages if item["status"] == OutboxStatus.DELIVERED.value),
        "failed_outbox": sum(1 for item in outbox_messages if item["status"] == OutboxStatus.FAILED.value),
        "resolved_recovery_cases": sum(1 for item in recovery_cases if item["status"] != RecoveryStatus.OPEN.value),
        "open_lineage_remediations": sum(1 for item in lineage_remediations if item["status"] == "OPEN"),
        "resolved_lineage_remediations": sum(1 for item in lineage_remediations if item["status"] != "OPEN"),
        "recent_invalidation_obligations": obligations[:8],
        "recent_policy_decisions": policy_decisions[:5],
        "recent_outbox_messages": outbox_messages[:5],
        "recent_recovery_cases": recovery_cases[:5],
        "recent_lineage_remediations": lineage_remediations[:6],
        "recent_audit_events": audit_events[:8],
    }


@router.get("/role-os")
def get_role_os_manifest(principal: Principal = Depends(get_principal)):
    registry = role_os_registry()
    return {
        "tenant_id": principal.tenant_id,
        "registry_hash": registry.registry_hash,
        "role_count": len(registry.roles),
        "phase_count": len(registry.phases),
    }


@router.post("/ingest", status_code=202)
async def enqueue_runtime_work(request: Request):
    body = RuntimeIngressRequest.model_validate(await request.json())
    queue = runtime_queue()
    try:
        envelope = queue.put_nowait(operation_id=body.operation_id, payload=body.model_dump())
    except DuplicateOperationError:
        raise HTTPException(status_code=409, detail="operation_id already queued") from None
    except QueueFullError:
        raise HTTPException(status_code=503, detail="runtime ingress queue is full") from None
    return {
        "accepted": True,
        "operation_id": envelope.operation_id,
        "queue_depth": queue.qsize(),
        "durable": False,
        "process_local": True,
    }


@router.get("/ingest/queue")
def get_queue_snapshot(principal: Principal = Depends(get_principal)):
    snapshot = runtime_queue().snapshot()
    return {
        "tenant_id": principal.tenant_id,
        "depth": snapshot.depth,
        "capacity": snapshot.capacity,
        "dedupe_entries": snapshot.dedupe_entries,
        "durable": snapshot.durable,
        "process_local": snapshot.process_local,
    }


@router.get("/projects/{project_id}/trust")
def get_project_trust(project_id: str, principal: Principal = Depends(get_principal)):
    authorize_project(principal, project_id)
    try:
        return _project_trust_details(project_id, principal.tenant_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"trust projection unavailable: {type(exc).__name__}") from exc


@router.get("/projects/{project_id}/trust/outbox")
def get_project_outbox(project_id: str, principal: Principal = Depends(get_principal)):
    authorize_project(principal, project_id)
    try:
        return _project_trust_details(project_id, principal.tenant_id)["recent_outbox_messages"]
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"trust outbox unavailable: {type(exc).__name__}") from exc


@router.get("/projects/{project_id}/trust/recovery")
def get_project_recovery(project_id: str, principal: Principal = Depends(get_principal)):
    authorize_project(principal, project_id)
    try:
        return _project_trust_details(project_id, principal.tenant_id)["recent_recovery_cases"]
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"trust recovery unavailable: {type(exc).__name__}") from exc


@router.post("/runs/{run_id}/artifacts/protected/revise")
def revise_protected_run_artifact(
    run_id: str,
    body: ProtectedArtifactRevisionRequest,
    principal: Principal = Depends(get_principal),
):
    record = _authorized_run(principal, run_id)
    approvals = get_approvals_for_run(run_id)
    approval = approvals[0] if approvals else None
    result = create_or_revise_protected_run_artifact(
        run_id=run_id,
        tenant_id=record["tenant_id"],
        project_id=record["project_id"],
        approval_id=approval["approval_id"] if approval else None,
        content_hash=body.content_hash,
        synthetic=True,
    )
    artifact_id = result["artifact"]["artifact_id"]
    if result["created"]:
        result = record_artifact_revision(artifact_id, content_hash=body.content_hash)
    record_run_invalidation_bindings(
        tenant_id=record["tenant_id"],
        project_id=record["project_id"],
        run_id=run_id,
        artifact_branch=artifact_id,
        result=record.get("result"),
    )
    record_event(
        run_id,
        record["tenant_id"],
        record["project_id"],
        "artifact",
        "artifact_generated",
        safe_payload={
            "artifact_id": artifact_id,
            "changed_version_ref": result["changed_version_ref"],
            "approval_id": approval["approval_id"] if approval else None,
        },
    )
    return {
        "artifact": result["artifact"],
        "changed_version_ref": result["changed_version_ref"],
        "affected": result["affected"],
        "trust": _project_trust_details(record["project_id"], record["tenant_id"]),
    }


@router.post("/projects/{project_id}/trust/recovery/{recovery_id}/resolve")
def resolve_project_recovery(
    project_id: str,
    recovery_id: str,
    body: RecoveryResolveRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    principal: Principal = Depends(get_principal),
):
    authorize_project(principal, project_id)
    scope = _operator_scope(principal, project_id, f"recovery.resolve:{recovery_id}")
    request_hash = hash_payload({"recovery_id": recovery_id, "status": body.status, "run_id": body.run_id})
    reservation = reserve_idempotency(scope, idempotency_key, request_hash, IDEMPOTENCY_TTL_SECONDS)
    if reservation["state"] == "replay":
        return reservation["record"]["result"]
    if reservation["state"] == "in_progress":
        raise HTTPException(status_code=409, detail="Recovery action is already executing")
    if reservation["state"] == "conflict":
        raise HTTPException(status_code=409, detail="Idempotency-Key was reused with different recovery input")

    kernel = trust_kernel()
    try:
        kernel.assert_scope(tenant_id=principal.tenant_id, project_id=project_id)
        updated = kernel.resolve_recovery(
            recovery_id=recovery_id,
            status=RecoveryStatus(body.status),
            evidence_refs=(f"operator:{principal.user_id}",),
        )
    except Exception as exc:
        fail_idempotency(scope, idempotency_key, type(exc).__name__)
        raise HTTPException(status_code=409, detail=f"Recovery resolution failed: {type(exc).__name__}") from exc

    run_id = str(body.run_id or updated.execution_ref or updated.observation_ref or updated.operation_id)
    _record_recovery_event(run_id, principal.tenant_id, project_id, updated)
    response = updated.model_dump(mode="json")
    if not complete_idempotency(scope, idempotency_key, response):
        raise HTTPException(status_code=500, detail="Failed to finalize recovery idempotency record")
    return response


@router.post("/projects/{project_id}/trust/outbox/{message_id}/replay")
def replay_project_outbox(
    project_id: str,
    message_id: str,
    body: OutboxReplayRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    principal: Principal = Depends(get_principal),
):
    authorize_project(principal, project_id)
    scope = _operator_scope(principal, project_id, f"outbox.replay:{message_id}")
    request_hash = hash_payload({"message_id": message_id, "run_id": body.run_id})
    reservation = reserve_idempotency(scope, idempotency_key, request_hash, IDEMPOTENCY_TTL_SECONDS)
    if reservation["state"] == "replay":
        return reservation["record"]["result"]
    if reservation["state"] == "in_progress":
        raise HTTPException(status_code=409, detail="Outbox replay is already executing")
    if reservation["state"] == "conflict":
        raise HTTPException(status_code=409, detail="Idempotency-Key was reused with different outbox input")

    kernel = trust_kernel()
    dispatcher = OutboxDispatcher(
        kernel,
        authorize_delivery=lambda message: message.tenant_id == principal.tenant_id and message.project_id == project_id,
    )
    dispatcher.register("agency.delivery.completed", lambda message: message.payload_ref)

    try:
        result = dispatcher.dispatch_one(message_id=message_id, worker_id=f"operator:{principal.user_id}")
    except Exception as exc:
        fail_idempotency(scope, idempotency_key, type(exc).__name__)
        raise HTTPException(status_code=409, detail=f"Outbox replay failed: {type(exc).__name__}") from exc

    message = kernel.store.state.outbox.get(message_id)
    run_id = str(body.run_id or (message.payload_ref if message else None) or message_id)
    record_event(
        run_id,
        principal.tenant_id,
        project_id,
        "trust",
        "outbox_updated",
        safe_payload={
            "message_id": message_id,
            "status": result.status,
            "result_ref": result.result_ref,
            "error": result.error,
        },
    )
    response = {
        "message_id": result.message_id,
        "status": result.status,
        "result_ref": result.result_ref,
        "error": result.error,
    }
    if not complete_idempotency(scope, idempotency_key, response):
        raise HTTPException(status_code=500, detail="Failed to finalize outbox idempotency record")
    return response


@router.post("/runs/{run_id}/remediation/retry")
def retry_run_from_recovery(
    run_id: str,
    body: RunRetryRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    principal: Principal = Depends(get_principal),
):
    record = _authorized_run(principal, run_id)
    scope = _run_operator_scope(principal, run_id, f"run.retry:{body.recovery_id}")
    request_hash = hash_payload({"run_id": run_id, "recovery_id": body.recovery_id})
    reservation = reserve_idempotency(scope, idempotency_key, request_hash, IDEMPOTENCY_TTL_SECONDS)
    if reservation["state"] == "replay":
        return reservation["record"]["result"]
    if reservation["state"] == "in_progress":
        raise HTTPException(status_code=409, detail="Run retry is already executing")
    if reservation["state"] == "conflict":
        raise HTTPException(status_code=409, detail="Idempotency-Key was reused with different retry input")

    kernel, recovery = _recovery_for_run(
        run_id=run_id,
        recovery_id=body.recovery_id,
        tenant_id=record["tenant_id"],
        project_id=record["project_id"],
    )
    if recovery.status != RecoveryStatus.OPEN:
        fail_idempotency(scope, idempotency_key, "recovery_not_open")
        raise HTTPException(status_code=409, detail="Recovery case is not open")
    if recovery.reason == "AMBIGUOUS_EXTERNAL_RESULT":
        fail_idempotency(scope, idempotency_key, "ambiguous_requires_compensation")
        raise HTTPException(status_code=409, detail="Ambiguous external results must be compensated or escalated")

    latest_approval = _latest_approval_for_run(run_id)
    if not latest_approval or latest_approval.get("status") != "resolved" or latest_approval.get("decision") != "approve":
        fail_idempotency(scope, idempotency_key, "approval_not_retryable")
        raise HTTPException(status_code=409, detail="Retry requires an approved, resolved human approval")

    from services.langgraph.api.routes import agency as agency_routes

    started_at = agency_routes.datetime.now(agency_routes.timezone.utc)
    agency_routes._issue_dispatch_permit(
        run_id=run_id,
        tenant_id=record["tenant_id"],
        project_id=record["project_id"],
        phase="run_remediation_retry",
        subject_hash=hash_payload({"run_id": run_id, "recovery_id": body.recovery_id}),
        approval_refs=(latest_approval["approval_id"],),
        authority_refs=(f"operator:{principal.user_id}",),
    )
    kernel.record_policy_decision(
        tenant_id=record["tenant_id"],
        project_id=record["project_id"],
        decision_id=f"policy-run-retry-{run_id}-{idempotency_key}",
        subject_ref=run_id,
        action="run.retry",
        target=recovery.reason,
        policy_version="amc-trust/v1",
        policy_input={"run_id": run_id, "recovery_id": body.recovery_id},
        effect=PolicyEffect.ALLOW,
        required_authority_refs=(f"operator:{principal.user_id}",),
        evidence_refs=(body.recovery_id, latest_approval["approval_id"]),
    )
    kernel.claim_idempotency(
        tenant_id=record["tenant_id"],
        project_id=record["project_id"],
        idempotency_key=idempotency_key,
        operation_id=f"run.retry:{run_id}",
        request={"run_id": run_id, "recovery_id": body.recovery_id},
    )

    if record["status"] == "failed":
        update_run_status(run_id, "needs_approval", record.get("result"))
    elif record["status"] != "needs_approval":
        fail_idempotency(scope, idempotency_key, f"invalid_run_status:{record['status']}")
        kernel.complete_idempotency(idempotency_key=idempotency_key, result_ref=run_id, status=IdempotencyStatus.FAILED)
        raise HTTPException(status_code=409, detail=f"Run is not retryable from status={record['status']}")

    try:
        run_response = agency_routes.resume_agency_run(
            run_id,
            idempotency_key=hash_payload({"parent_idempotency_key": idempotency_key, "operation": "run.retry"}),
            principal=principal,
        )
    except HTTPException as exc:
        ended_at = agency_routes.datetime.now(agency_routes.timezone.utc)
        agency_routes._record_execution_phase(
            run_id=run_id,
            tenant_id=record["tenant_id"],
            project_id=record["project_id"],
            operation_id=f"run.retry:{run_id}:{body.recovery_id}",
            actor_role_id="operator-remediation",
            args_payload={"run_id": run_id, "recovery_id": body.recovery_id},
            started_at=started_at,
            ended_at=ended_at,
            returned_state="FAILED",
            result_ref=None,
        )
        agency_routes._record_failure(
            run_id=run_id,
            tenant_id=record["tenant_id"],
            project_id=record["project_id"],
            operation_id=f"run.retry:{run_id}:{body.recovery_id}",
            args_payload={"run_id": run_id, "recovery_id": body.recovery_id},
            error_class=f"HTTP_{exc.status_code}",
        )
        fail_idempotency(scope, idempotency_key, f"http_{exc.status_code}")
        kernel.complete_idempotency(idempotency_key=idempotency_key, result_ref=run_id, status=IdempotencyStatus.FAILED)
        raise

    updated_recovery = kernel.resolve_recovery(
        recovery_id=body.recovery_id,
        status=RecoveryStatus.RECONCILED,
        evidence_refs=(f"operator:{principal.user_id}", run_id),
    )
    ended_at = agency_routes.datetime.now(agency_routes.timezone.utc)
    agency_routes._record_execution_phase(
        run_id=run_id,
        tenant_id=record["tenant_id"],
        project_id=record["project_id"],
        operation_id=f"run.retry:{run_id}:{body.recovery_id}",
        actor_role_id="operator-remediation",
        args_payload={"run_id": run_id, "recovery_id": body.recovery_id},
        started_at=started_at,
        ended_at=ended_at,
        returned_state=run_response["status"].upper(),
        result_ref=run_id,
    )
    agency_routes._record_observation_phase(
        run_id=run_id,
        tenant_id=record["tenant_id"],
        project_id=record["project_id"],
        operation_id=f"run.retry:{run_id}:{body.recovery_id}",
        expected_postcondition={"recovery_status": "RECONCILED", "run_status": run_response["status"]},
        observed_postcondition={"recovery_status": updated_recovery.status.value, "run_status": run_response["status"]},
        evidence_refs=(body.recovery_id,),
    )
    agency_routes._record_completion(
        run_id=run_id,
        tenant_id=record["tenant_id"],
        project_id=record["project_id"],
        terminal_candidate=("COMPLETE" if run_response["status"] == "completed" else "BLOCKED"),
        proof_coverage=(1.0 if run_response["status"] == "completed" else 0.8),
        confidence=0.9,
        criteria=(
            agency_routes.CompletionCriterionResult(
                criterion_ref="remediation_retry",
                status=agency_routes.CriterionStatus.SATISFIED,
            ),
            agency_routes.CompletionCriterionResult(
                criterion_ref="recovery_case",
                status=agency_routes.CriterionStatus.SATISFIED,
            ),
        ),
    )
    _record_recovery_event(run_id, record["tenant_id"], record["project_id"], updated_recovery)
    _record_remediation_event(
        run_id,
        record["tenant_id"],
        record["project_id"],
        action="retry_blocked_execution",
        payload={
            "recovery_id": body.recovery_id,
            "recovery_status": updated_recovery.status.value,
            "status": run_response["status"],
        },
    )
    resolve_lineage_remediation_for_run(run_id, status="RETRIED")
    discharge_run_obligations(run_id=run_id, artifact_branch=f"art-protected-{run_id}")
    response = {
        "action": "retry_blocked_execution",
        "run": run_response,
        "recovery_case": updated_recovery.model_dump(mode="json"),
        "pending_approval": run_response.get("pending_approval"),
    }
    if not complete_idempotency(scope, idempotency_key, response):
        raise HTTPException(status_code=500, detail="Failed to finalize remediation idempotency record")
    kernel.complete_idempotency(idempotency_key=idempotency_key, result_ref=run_id)
    return response


@router.post("/runs/{run_id}/remediation/compensate")
def compensate_run_recovery(
    run_id: str,
    body: RunCompensationRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    principal: Principal = Depends(get_principal),
):
    record = _authorized_run(principal, run_id)
    scope = _run_operator_scope(principal, run_id, f"run.compensate:{body.recovery_id}")
    request_hash = hash_payload({"run_id": run_id, "recovery_id": body.recovery_id})
    reservation = reserve_idempotency(scope, idempotency_key, request_hash, IDEMPOTENCY_TTL_SECONDS)
    if reservation["state"] == "replay":
        return reservation["record"]["result"]
    if reservation["state"] == "in_progress":
        raise HTTPException(status_code=409, detail="Run compensation is already executing")
    if reservation["state"] == "conflict":
        raise HTTPException(status_code=409, detail="Idempotency-Key was reused with different compensation input")

    kernel, recovery = _recovery_for_run(
        run_id=run_id,
        recovery_id=body.recovery_id,
        tenant_id=record["tenant_id"],
        project_id=record["project_id"],
    )
    if recovery.status != RecoveryStatus.OPEN:
        fail_idempotency(scope, idempotency_key, "recovery_not_open")
        raise HTTPException(status_code=409, detail="Recovery case is not open")
    if recovery.reason != "AMBIGUOUS_EXTERNAL_RESULT":
        fail_idempotency(scope, idempotency_key, "recovery_not_ambiguous")
        raise HTTPException(status_code=409, detail="Only ambiguous external results can be compensated")

    from services.langgraph.api.routes import agency as agency_routes

    started_at = agency_routes.datetime.now(agency_routes.timezone.utc)
    kernel.record_policy_decision(
        tenant_id=record["tenant_id"],
        project_id=record["project_id"],
        decision_id=f"policy-run-compensate-{run_id}-{idempotency_key}",
        subject_ref=run_id,
        action="run.compensate",
        target=recovery.reason,
        policy_version="amc-trust/v1",
        policy_input={"run_id": run_id, "recovery_id": body.recovery_id},
        effect=PolicyEffect.ALLOW,
        required_authority_refs=(f"operator:{principal.user_id}",),
        evidence_refs=(body.recovery_id,),
    )
    kernel.claim_idempotency(
        tenant_id=record["tenant_id"],
        project_id=record["project_id"],
        idempotency_key=idempotency_key,
        operation_id=f"run.compensate:{run_id}",
        request={"run_id": run_id, "recovery_id": body.recovery_id},
    )
    updated_recovery = kernel.resolve_recovery(
        recovery_id=body.recovery_id,
        status=RecoveryStatus.COMPENSATED,
        evidence_refs=(f"operator:{principal.user_id}", run_id),
    )
    ended_at = agency_routes.datetime.now(agency_routes.timezone.utc)
    agency_routes._record_execution_phase(
        run_id=run_id,
        tenant_id=record["tenant_id"],
        project_id=record["project_id"],
        operation_id=f"run.compensate:{run_id}:{body.recovery_id}",
        actor_role_id="operator-remediation",
        args_payload={"run_id": run_id, "recovery_id": body.recovery_id},
        started_at=started_at,
        ended_at=ended_at,
        returned_state="COMPENSATED",
        result_ref=run_id,
    )
    agency_routes._record_observation_phase(
        run_id=run_id,
        tenant_id=record["tenant_id"],
        project_id=record["project_id"],
        operation_id=f"run.compensate:{run_id}:{body.recovery_id}",
        expected_postcondition={"recovery_status": "COMPENSATED"},
        observed_postcondition={"recovery_status": updated_recovery.status.value},
        evidence_refs=(body.recovery_id,),
    )
    agency_routes._record_completion(
        run_id=run_id,
        tenant_id=record["tenant_id"],
        project_id=record["project_id"],
        terminal_candidate="BLOCKED",
        proof_coverage=0.85,
        confidence=0.88,
        criteria=(
            agency_routes.CompletionCriterionResult(
                criterion_ref="remediation_compensation",
                status=agency_routes.CriterionStatus.SATISFIED,
            ),
        ),
    )
    run_payload = agency_routes.get_agency_run(run_id, principal=principal)
    _record_recovery_event(run_id, record["tenant_id"], record["project_id"], updated_recovery)
    _record_remediation_event(
        run_id,
        record["tenant_id"],
        record["project_id"],
        action="compensate_ambiguous_result",
        payload={
            "recovery_id": body.recovery_id,
            "recovery_status": updated_recovery.status.value,
            "status": run_payload["status"],
        },
    )
    response = {
        "action": "compensate_ambiguous_result",
        "run": run_payload,
        "recovery_case": updated_recovery.model_dump(mode="json"),
        "pending_approval": None,
    }
    if not complete_idempotency(scope, idempotency_key, response):
        raise HTTPException(status_code=500, detail="Failed to finalize remediation idempotency record")
    kernel.complete_idempotency(idempotency_key=idempotency_key, result_ref=run_id)
    return response


@router.post("/runs/{run_id}/remediation/regenerate-approval")
def regenerate_run_approval(
    run_id: str,
    body: RegenerateApprovalRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    principal: Principal = Depends(get_principal),
):
    record = _authorized_run(principal, run_id)
    scope = _run_operator_scope(principal, run_id, "approval.regenerate")
    request_hash = hash_payload({"run_id": run_id, "approval_id": body.approval_id})
    reservation = reserve_idempotency(scope, idempotency_key, request_hash, IDEMPOTENCY_TTL_SECONDS)
    if reservation["state"] == "replay":
        return reservation["record"]["result"]
    if reservation["state"] == "in_progress":
        raise HTTPException(status_code=409, detail="Approval regeneration is already executing")
    if reservation["state"] == "conflict":
        raise HTTPException(status_code=409, detail="Idempotency-Key was reused with different approval regeneration input")

    approvals = get_approvals_for_run(run_id)
    target = next((approval for approval in approvals if approval["approval_id"] == body.approval_id), None) if body.approval_id else (approvals[0] if approvals else None)
    if not target:
        fail_idempotency(scope, idempotency_key, "approval_missing")
        raise HTTPException(status_code=404, detail="Approval not found for run")
    if target["status"] != "stale":
        fail_idempotency(scope, idempotency_key, "approval_not_stale")
        raise HTTPException(status_code=409, detail="Only stale approvals can be regenerated")

    from services.langgraph.api.routes import agency as agency_routes

    agency_result = ((record.get("result") or {}).get("agency") or {})
    subject_hash = agency_routes._agency_subject_hash(agency_result)
    started_at = agency_routes.datetime.now(agency_routes.timezone.utc)
    kernel = trust_kernel()
    kernel.bind_project(tenant_id=record["tenant_id"], project_id=record["project_id"])
    kernel.record_policy_decision(
        tenant_id=record["tenant_id"],
        project_id=record["project_id"],
        decision_id=f"policy-approval-regenerate-{run_id}-{idempotency_key}",
        subject_ref=run_id,
        action="approval.regenerate",
        target=target["approval_id"],
        policy_version="amc-trust/v1",
        policy_input={"run_id": run_id, "approval_id": target["approval_id"]},
        effect=PolicyEffect.REQUIRE_APPROVAL,
        required_authority_refs=("human-review", f"operator:{principal.user_id}"),
        evidence_refs=(target["approval_id"],),
    )
    kernel.claim_idempotency(
        tenant_id=record["tenant_id"],
        project_id=record["project_id"],
        idempotency_key=idempotency_key,
        operation_id=f"approval.regenerate:{run_id}",
        request={"run_id": run_id, "approval_id": target["approval_id"]},
    )
    regenerated = create_approval_request(
        run_id,
        record["tenant_id"],
        record["project_id"],
        target["reason"],
        target.get("confidence"),
        subject_type=target.get("subject_type") or "RUN_RESULT",
        subject_ref=target.get("subject_ref") or run_id,
        subject_version_ref=target.get("subject_version_ref") or run_id,
        subject_hash=subject_hash,
        authority_ref=target.get("authority_ref") or "human-review",
        policy_version=target.get("policy_version") or "amc-approval/v1",
    )
    bind_approval_subject(
        regenerated["approval_id"],
        subject_hash=subject_hash,
        subject_ref=target.get("subject_ref") or run_id,
        subject_version_ref=target.get("subject_version_ref") or run_id,
        authority_ref=target.get("authority_ref") or "human-review",
        policy_version=target.get("policy_version") or "amc-approval/v1",
    )
    update_run_status(run_id, "needs_approval", record.get("result"))
    ended_at = agency_routes.datetime.now(agency_routes.timezone.utc)
    agency_routes._record_execution_phase(
        run_id=run_id,
        tenant_id=record["tenant_id"],
        project_id=record["project_id"],
        operation_id=f"approval.regenerate:{run_id}:{regenerated['approval_id']}",
        actor_role_id="operator-remediation",
        args_payload={"run_id": run_id, "stale_approval_id": target["approval_id"]},
        started_at=started_at,
        ended_at=ended_at,
        returned_state="NEEDS_APPROVAL",
        result_ref=regenerated["approval_id"],
    )
    agency_routes._record_observation_phase(
        run_id=run_id,
        tenant_id=record["tenant_id"],
        project_id=record["project_id"],
        operation_id=f"approval.regenerate:{run_id}:{regenerated['approval_id']}",
        expected_postcondition={"status": "needs_approval", "approval_status": "pending"},
        observed_postcondition={"status": "needs_approval", "approval_status": regenerated["status"]},
        evidence_refs=(target["approval_id"], regenerated["approval_id"]),
    )
    agency_routes._record_completion(
        run_id=run_id,
        tenant_id=record["tenant_id"],
        project_id=record["project_id"],
        terminal_candidate="BLOCKED",
        proof_coverage=0.82,
        confidence=0.9,
        criteria=(
            agency_routes.CompletionCriterionResult(
                criterion_ref="approval_regenerated",
                status=agency_routes.CriterionStatus.SATISFIED,
            ),
            agency_routes.CompletionCriterionResult(
                criterion_ref="human_approval",
                status=agency_routes.CriterionStatus.BLOCKED,
            ),
        ),
    )
    record_event(
        run_id,
        record["tenant_id"],
        record["project_id"],
        "hitl_gate",
        "approval_requested",
        safe_payload={
            "approval_id": regenerated["approval_id"],
            "status": regenerated["status"],
            "reason": regenerated["reason"],
            "confidence": regenerated["confidence"],
            "regenerated_from": target["approval_id"],
        },
    )
    _record_remediation_event(
        run_id,
        record["tenant_id"],
        record["project_id"],
        action="regenerate_approval",
        payload={
            "approval_id": regenerated["approval_id"],
            "stale_approval_id": target["approval_id"],
            "status": "needs_approval",
        },
    )
    resolve_lineage_remediation_for_run(run_id, approval_id=target["approval_id"], status="REGENERATED")
    discharge_run_obligations(run_id=run_id, artifact_branch=f"art-protected-{run_id}")
    run_payload = agency_routes.get_agency_run(run_id, principal=principal)
    response = {
        "action": "regenerate_approval",
        "run": run_payload,
        "recovery_case": None,
        "pending_approval": regenerated,
    }
    if not complete_idempotency(scope, idempotency_key, response):
        raise HTTPException(status_code=500, detail="Failed to finalize approval regeneration idempotency record")
    kernel.complete_idempotency(idempotency_key=idempotency_key, result_ref=regenerated["approval_id"])
    return response
