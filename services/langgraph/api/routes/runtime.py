from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from services.langgraph.agency.reliability.outbox import OutboxDispatcher
from services.langgraph.agency.reliability.models import OutboxStatus, RecoveryStatus
from services.langgraph.app.runtime_support import role_os_registry, runtime_queue, trust_kernel
from services.langgraph.app.in_memory_queue import DuplicateOperationError, QueueFullError
from services.langgraph.persistence.database import database_backend
from services.langgraph.persistence.events import record_event
from services.langgraph.persistence.idempotency import complete_idempotency, fail_idempotency, hash_payload, reserve_idempotency
from services.langgraph.security.auth import Principal, authorize_project, get_principal

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


def _operator_scope(principal: Principal, project_id: str, target: str) -> str:
    return f"{principal.tenant_id}:{principal.user_id}:{target}:{project_id}"


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
        "delivered_outbox": sum(1 for item in outbox_messages if item["status"] == OutboxStatus.DELIVERED.value),
        "failed_outbox": sum(1 for item in outbox_messages if item["status"] == OutboxStatus.FAILED.value),
        "resolved_recovery_cases": sum(1 for item in recovery_cases if item["status"] != RecoveryStatus.OPEN.value),
        "recent_policy_decisions": policy_decisions[:5],
        "recent_outbox_messages": outbox_messages[:5],
        "recent_recovery_cases": recovery_cases[:5],
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
            evidence_refs=((f"operator:{principal.user_id}"),),
        )
    except Exception as exc:
        fail_idempotency(scope, idempotency_key, type(exc).__name__)
        raise HTTPException(status_code=409, detail=f"Recovery resolution failed: {type(exc).__name__}") from exc

    run_id = body.run_id or updated.execution_ref or updated.observation_ref or updated.operation_id
    record_event(
        str(run_id),
        principal.tenant_id,
        project_id,
        "trust",
        "recovery_case_updated",
        safe_payload={
            "recovery_id": updated.recovery_id,
            "status": updated.status.value,
            "reason": updated.reason,
            "operation_id": updated.operation_id,
        },
    )
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

    state = kernel.store.state
    message = state.outbox.get(message_id)
    run_id = body.run_id or (message.payload_ref if message else None) or message_id
    record_event(
        str(run_id),
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
