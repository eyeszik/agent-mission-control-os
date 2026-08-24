from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

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
    kernel = trust_kernel()
    try:
        kernel.bind_project(tenant_id=principal.tenant_id, project_id=project_id)
        snapshot = kernel.snapshot(tenant_id=principal.tenant_id, project_id=project_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"trust projection unavailable: {type(exc).__name__}") from exc
    return {
        **snapshot.model_dump(mode="json"),
        "database_backend": database_backend(),
        "persistence_mode": "canonical_database",
    }
