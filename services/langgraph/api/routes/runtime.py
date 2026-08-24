from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from services.langgraph.agency.reliability.models import OutboxStatus, RecoveryStatus
from services.langgraph.app.runtime_support import role_os_registry, runtime_queue, trust_kernel
from services.langgraph.app.in_memory_queue import DuplicateOperationError, QueueFullError
from services.langgraph.persistence.database import database_backend
from services.langgraph.security.auth import Principal, authorize_project, get_principal

router = APIRouter()


class RuntimeIngressRequest(BaseModel):
    operation_id: str = Field(min_length=1, max_length=200)
    mission_id: str = Field(min_length=1, max_length=200)
    project_id: str = Field(min_length=1, max_length=200)
    payload: dict = Field(default_factory=dict)


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
