"""Authenticated, project-scoped UNBOUND simulation and persisted review drafts."""
from fastapi import APIRouter, Depends, Header, Query

from services.langgraph.agency.innovation import service
from services.langgraph.agency.innovation.contracts import InnovationBrief
from services.langgraph.agency.innovation.service import ControlRequest, RunEnvelope, RunListing, TickRequest
from services.langgraph.api.routes._project_common import domain_errors, storage_adapter
from services.langgraph.security.auth import Principal, get_principal

router = APIRouter()


@router.post("/projects/{project_id}/runs", status_code=201, response_model=RunEnvelope)
@domain_errors
def create(project_id: str, req: InnovationBrief,
           idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=128),
           principal: Principal = Depends(get_principal)) -> dict:
    return service.create_run(principal, project_id, req, idempotency_key, storage_adapter())


@router.get("/projects/{project_id}/runs", response_model=RunListing)
@domain_errors
def listing(project_id: str, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0, le=100000),
            principal: Principal = Depends(get_principal)) -> dict:
    return service.list_runs(principal, project_id, storage_adapter(), limit=limit, offset=offset)


@router.get("/projects/{project_id}/runs/{run_id}", response_model=RunEnvelope)
@domain_errors
def get(project_id: str, run_id: str, principal: Principal = Depends(get_principal)) -> dict:
    return service.get_run(principal, project_id, run_id, storage_adapter())


@router.post("/projects/{project_id}/runs/{run_id}/tick", response_model=RunEnvelope)
@domain_errors
def tick(project_id: str, run_id: str, req: TickRequest, principal: Principal = Depends(get_principal)) -> dict:
    return service.tick_run(principal, project_id, run_id, req.expected_version, storage_adapter())


@router.post("/projects/{project_id}/runs/{run_id}/control", response_model=RunEnvelope)
@domain_errors
def control(project_id: str, run_id: str, req: ControlRequest, principal: Principal = Depends(get_principal)) -> dict:
    return service.control_run(principal, project_id, run_id, req, storage_adapter())
