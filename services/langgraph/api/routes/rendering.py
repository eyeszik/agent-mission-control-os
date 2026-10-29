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
def capabilities(project_id: str | None = None, principal: Principal = Depends(get_principal)):
    if project_id: service._scope(principal, project_id)
    return {'engines': inventory(principal.tenant_id,project_id), 'external_effects': 'none'}


@router.post('/projects/{project_id}/renders', status_code=202)
@domain_errors
def dispatch(project_id: str, request: RenderRequest, principal: Principal = Depends(get_principal),
             idempotency_key: str = Header(..., alias='Idempotency-Key')):
    service._scope(principal, project_id)
    scope = f'{principal.tenant_id}:{principal.user_id}:render:{project_id}'
    payload=request.model_dump(mode='json')
    if request.motion is None:payload.pop('motion')  # Preserve pre-extension retry identities.
    reservation = reserve_idempotency(scope, idempotency_key, hash_payload(payload))
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


class WorkerLease(BaseModel):
    model_config = ConfigDict(extra='forbid')
    fencing_token: int = Field(gt=0, strict=True)

class WorkerOutput(WorkerLease):
    content_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    data_base64: str = Field(min_length=1, max_length=21_333_336)

@router.post('/projects/{project_id}/renders/{job_id}/claim')
@domain_errors
def claim_worker(project_id: str, job_id: str, principal: Principal = Depends(get_principal)):
    from services.langgraph.agency.rendering.remote import claim
    return claim(principal,project_id,job_id)

@router.post('/projects/{project_id}/renders/{job_id}/heartbeat')
@domain_errors
def heartbeat_worker(project_id: str, job_id: str, request: WorkerLease, principal: Principal = Depends(get_principal)):
    from services.langgraph.agency.rendering.remote import heartbeat
    return heartbeat(principal,project_id,job_id,request.fencing_token)

@router.post('/projects/{project_id}/renders/{job_id}/complete')
@domain_errors
def complete_worker(project_id: str, job_id: str, request: WorkerOutput, principal: Principal = Depends(get_principal)):
    from services.langgraph.agency.rendering.remote import complete
    return complete(principal,project_id,job_id,request.fencing_token,request.content_hash,request.data_base64)

class LicenseDecision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    permitted: bool
    basis: str = Field(min_length=10,max_length=1000)
    evidence_refs: tuple[str, ...] = Field(min_length=1,max_length=10)

@router.post('/projects/{project_id}/render-license')
@domain_errors
def license_decision(project_id: str, request: LicenseDecision, principal: Principal = Depends(get_principal)):
    from services.langgraph.agency.rendering.licenses import record
    result=record(principal,project_id,request.permitted,request.basis,request.evidence_refs)
    return {'memory_id':result['memory'].memory_id,'permitted':request.permitted}
