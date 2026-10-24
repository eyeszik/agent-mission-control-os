"""Authenticated rendering resources; GETs never execute or resume jobs."""
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field
from fastapi import APIRouter, Depends, Header, HTTPException
from services.langgraph.agency.exporter import resolve_export_root
from services.langgraph.agency.rendering.contracts import RenderRequest, RenderEngineId
from services.langgraph.agency.rendering.runtime import inventory
from services.langgraph.agency.rendering import service
from services.langgraph.api.routes._project_common import domain_errors
from services.langgraph.persistence.idempotency import reserve_idempotency, complete_idempotency, fail_idempotency, hash_payload
from services.langgraph.security.auth import Principal, get_principal

router = APIRouter()


@router.get('/render-capabilities')
def capabilities(principal: Principal = Depends(get_principal)):
    return {'engines': inventory(), 'external_effects': 'none'}


@router.post('/projects/{project_id}/renders', status_code=202)
@domain_errors
def dispatch(project_id: str, request: RenderRequest, principal: Principal = Depends(get_principal),
             idempotency_key: str = Header(..., alias='Idempotency-Key')):
    service._scope(principal, project_id)
    scope = f'{principal.tenant_id}:{principal.user_id}:render:{project_id}'
    reservation = reserve_idempotency(scope, idempotency_key, hash_payload(request.model_dump(mode='json')))
    if reservation['state'] == 'replay':
        return reservation['record']['result']
    if reservation['state'] != 'new':
        raise HTTPException(409, 'Idempotency key is in progress or conflicts')
    try:
        result = service.submit(principal, project_id, request, Path(resolve_export_root()))
        complete_idempotency(scope, idempotency_key, result)
        return result
    except Exception as exc:
        fail_idempotency(scope, idempotency_key, type(exc).__name__)
        raise


@router.get('/projects/{project_id}/renders/{job_id}')
@domain_errors
def get_job(project_id: str, job_id: str, principal: Principal = Depends(get_principal)):
    try:
        return service.inspect(principal, project_id, job_id)
    except LookupError:
        raise HTTPException(404, 'Render job not found') from None


@router.post('/projects/{project_id}/renders/{job_id}/cancel')
@domain_errors
def cancel(project_id: str, job_id: str, principal: Principal = Depends(get_principal)):
    try:
        return service.cancel(principal, project_id, job_id)
    except LookupError:
        raise HTTPException(404, 'Render job not found') from None


class QuarantineRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    engine: RenderEngineId
    quarantined: bool
    reason: str = Field(min_length=10, max_length=500)


@router.post('/projects/{project_id}/render-quarantine')
@domain_errors
def set_quarantine(project_id: str, body: QuarantineRequest, principal: Principal = Depends(get_principal)):
    return service.quarantine(principal, project_id, body.engine, body.quarantined, body.reason)


@router.post('/projects/{project_id}/renders/{job_id}/resume')
@domain_errors
def resume(project_id: str, job_id: str, principal: Principal = Depends(get_principal)):
    try:
        return service.resume(principal, project_id, job_id)
    except LookupError:
        raise HTTPException(404, 'Render job not found') from None
