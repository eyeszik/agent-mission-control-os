from __future__ import annotations

import inspect
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException

from .models import OutboxStatus, RecoveryStatus
from .service import ProductionTrustKernel, ReliabilityError


def create_reliability_router(
    *,
    kernel: ProductionTrustKernel,
    resolve_tenant: Callable[[], str | Any],
    authorize_project: Callable[[str, str], bool | Any],
) -> APIRouter:
    """Read-only trust projection router with server-derived tenant context.

    Tenant identity is never accepted from request bodies or query parameters.
    The canonical repository owns authentication and project authorization and
    injects both functions here.
    """

    router = APIRouter(prefix="/api/agency/projects", tags=["agency-trust"])

    async def _tenant() -> str:
        value = resolve_tenant()
        if inspect.isawaitable(value):
            value = await value
        if not value:
            raise HTTPException(status_code=401, detail="Unauthorized")
        return str(value)

    async def _authorize(project_id: str, tenant_id: str = Depends(_tenant)) -> str:
        result = authorize_project(tenant_id, project_id)
        if inspect.isawaitable(result):
            result = await result
        if not result:
            raise HTTPException(status_code=403, detail="Forbidden")
        try:
            kernel.assert_scope(tenant_id=tenant_id, project_id=project_id)
        except ReliabilityError:
            raise HTTPException(status_code=404, detail="Project not found") from None
        return tenant_id

    @router.get("/{project_id}/trust")
    async def get_trust(project_id: str, tenant_id: str = Depends(_authorize)):
        return kernel.snapshot(tenant_id=tenant_id, project_id=project_id).model_dump(mode="json")

    @router.get("/{project_id}/trust/outbox")
    async def list_outbox(project_id: str, tenant_id: str = Depends(_authorize)):
        values = [
            m for m in kernel.store.state.outbox.values()
            if m.tenant_id == tenant_id and m.project_id == project_id
        ]
        values.sort(key=lambda item: (item.created_at, item.message_id))
        return [v.model_dump(mode="json") for v in values]

    @router.get("/{project_id}/trust/recovery")
    async def list_recovery(project_id: str, tenant_id: str = Depends(_authorize)):
        values = [
            r for r in kernel.store.state.recovery.values()
            if r.tenant_id == tenant_id and r.project_id == project_id
        ]
        values.sort(key=lambda item: (item.created_at, item.recovery_id))
        return [v.model_dump(mode="json") for v in values]

    @router.get("/{project_id}/trust/audit")
    async def list_audit(project_id: str, tenant_id: str = Depends(_authorize)):
        values = [
            a for a in kernel.store.state.audits
            if a.tenant_id == tenant_id and a.project_id == project_id
        ]
        return {
            "valid": kernel.verify_audit_chain(),
            "checkpoints": [v.model_dump(mode="json") for v in values],
        }

    return router
