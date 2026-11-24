"""Brand OS 4.0 SOPs (``/brand-os``): read the 60-SOP index and adopt a newly written draft in a project.

Reads need an authenticated principal. Project routes resolve the project first and authorize the
server-derived principal against its recorded tenant (client input never names the tenant). A request
to adopt needs an operator role and an ``Idempotency-Key`` (replay returns the first response; a
different body is a 409). The decision itself is made only on ``/approvals/{id}/decide`` by an approver
who is not the requester; these routes never decide, release, publish, send or spend.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Path

from services.langgraph.agency.sop import brand_os_service as service
from services.langgraph.agency.sop.brand_os_contracts import AdoptionStatus, SopDetail, SopListItem
from services.langgraph.api.routes._project_common import authorize_project_access, domain_errors, storage_adapter
from services.langgraph.core.errors import AMCError
from services.langgraph.persistence.idempotency import (
    complete_idempotency,
    fail_idempotency,
    hash_payload,
    reserve_idempotency,
)
from services.langgraph.security.auth import Principal, get_principal

router = APIRouter()
OPERATOR_ROLES = {"admin", "operator", "owner", "approver"}
IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60
SOP_PATH = Path(..., pattern=r"^F(0[1-9]|[1-5][0-9]|60)$")


def _found(fn):
    try:
        return fn()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _operator(principal: Principal) -> None:
    if principal.role.strip().lower() not in OPERATOR_ROLES:
        raise HTTPException(status_code=403, detail="Requesting SOP adoption requires an operator role")


def _idempotent(principal: Principal, operation: str, key: str, body: dict, run) -> dict:
    scope = f"{principal.tenant_id}:{principal.user_id}:{operation}"
    reservation = reserve_idempotency(scope, key, hash_payload(body), IDEMPOTENCY_TTL_SECONDS)
    if reservation["state"] == "replay":
        return reservation["record"]["result"]
    if reservation["state"] == "in_progress":
        raise AMCError("Equivalent request is already executing", code="IDEMPOTENCY_IN_PROGRESS", status=409)
    if reservation["state"] == "conflict":
        raise AMCError("Idempotency-Key was reused with a different request", code="IDEMPOTENCY_CONFLICT", status=409)
    try:
        result = run()
    except Exception as exc:
        fail_idempotency(scope, key, type(exc).__name__)
        raise
    complete_idempotency(scope, key, result)
    return result


@router.get("/sops", response_model=list[SopListItem])
@domain_errors
def list_sops(principal: Principal = Depends(get_principal)):
    return _found(service.list_sops)


@router.get("/sops/{sop_id}", response_model=SopDetail)
@domain_errors
def get_sop(sop_id: str = SOP_PATH, principal: Principal = Depends(get_principal)):
    return _found(lambda: service.sop_detail(sop_id))


@router.get("/projects/{project_id}/sops/{sop_id}/adoption", response_model=AdoptionStatus)
@domain_errors
def get_adoption(project_id: str, sop_id: str = SOP_PATH, principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    return _found(lambda: service.adoption_status(principal, project_id, sop_id))


@router.post("/projects/{project_id}/sops/{sop_id}/adoption", response_model=AdoptionStatus, status_code=202)
@domain_errors
def request_adoption(project_id: str, sop_id: str = SOP_PATH, idempotency_key: str = Header(..., alias="Idempotency-Key"),
                     principal: Principal = Depends(get_principal)):
    """Stage the exact pinned draft and open its adoption approval (202: a decision is still required)."""
    authorize_project_access(principal, project_id)
    _operator(principal)
    body = {"project_id": project_id, "sop_id": sop_id}
    return _idempotent(principal, f"brand-os.adoption:{project_id}:{sop_id}", idempotency_key, body,
                       lambda: _found(lambda: service.request_adoption(principal, project_id, sop_id, storage_adapter())).model_dump(mode="json"))
