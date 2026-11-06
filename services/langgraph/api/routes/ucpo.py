"""Website production line API (UCPO): brief -> verified, approval-gated static site. Never deploys.

Every route requires an authenticated principal and resolves the project's recorded tenant.
Compiling is deterministic and executes nothing. Building runs the generated source only inside
the sandbox, through one explicit durable-job tick (no worker is deployed); an operator role is
required. Approval goes through the existing ``/approvals/{id}/decide``; no route here
publishes, deploys or sends anything.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from services.langgraph.agency.ucpo import service
from services.langgraph.agency.ucpo.capabilities import capability_matrix
from services.langgraph.agency.ucpo.contracts import WebsiteBrief
from services.langgraph.agency.ucpo.framework import framework_bindings
from services.langgraph.api.routes._project_common import authorize_project_access, domain_errors, storage_adapter
from services.langgraph.persistence.idempotency import complete_idempotency, fail_idempotency, hash_payload, reserve_idempotency
from services.langgraph.security.auth import Principal, get_principal

router = APIRouter()
OPERATOR_ROLES = {"admin", "operator", "owner", "approver"}


class SiteRequest(BaseModel):
    site_id: str = Field(pattern=service.SITE_ID)
    brief: WebsiteBrief

    model_config = {"extra": "forbid"}


class ImpactRequest(BaseModel):
    req_ids: list[str] = Field(min_length=1, max_length=50)

    model_config = {"extra": "forbid"}


def _operator(principal: Principal) -> None:
    if principal.role.strip().lower() not in OPERATOR_ROLES:
        raise HTTPException(status_code=403, detail="Building a site requires an operator role")


def _site(project_id: str, site_id: str):
    try:
        return service.linker(project_id, site_id, adapter=storage_adapter())
    except LookupError:
        raise HTTPException(status_code=404, detail="Site not found in this project") from None
    except ValueError:
        raise HTTPException(status_code=404, detail="Site not found in this project") from None


@router.get("/capabilities")
def capabilities(principal: Principal = Depends(get_principal)) -> dict:
    return capability_matrix()


@router.get("/projects/{project_id}/sites")
@domain_errors
def sites(project_id: str, principal: Principal = Depends(get_principal)) -> dict:
    authorize_project_access(principal, project_id)
    return {"sites": service.list_sites(project_id)}


@router.post("/projects/{project_id}/sites", status_code=201)
@domain_errors
def compile_site(project_id: str, req: SiteRequest, idempotency_key: str = Header(..., alias="Idempotency-Key"),
                 principal: Principal = Depends(get_principal)) -> dict:
    authorize_project_access(principal, project_id)
    _operator(principal)
    scope = f"{principal.tenant_id}:{principal.user_id}:ucpo.site:{project_id}"
    reservation = reserve_idempotency(scope, idempotency_key, hash_payload(req.model_dump(mode="json")))
    if reservation["state"] == "replay":
        return reservation["record"]["result"]
    if reservation["state"] in {"in_progress", "conflict"}:
        raise HTTPException(status_code=409, detail="Idempotency-Key is in use or was reused with different input")
    try:
        from services.langgraph.agency.exporter import resolve_export_root

        result = service.compile_site_line(principal, project_id, req.site_id, req.brief, adapter=storage_adapter(),
                                           export_root=resolve_export_root())
    except Exception as exc:
        fail_idempotency(scope, idempotency_key, type(exc).__name__)
        raise
    complete_idempotency(scope, idempotency_key, result)
    return result


@router.get("/projects/{project_id}/sites/{site_id}")
@domain_errors
def inspect(project_id: str, site_id: str, principal: Principal = Depends(get_principal)) -> dict:
    authorize_project_access(principal, project_id)
    try:
        return service.inspect_site(principal, project_id, site_id, adapter=storage_adapter())
    except (LookupError, ValueError):
        raise HTTPException(status_code=404, detail="Site not found in this project") from None


@router.post("/projects/{project_id}/sites/{site_id}/build")
@domain_errors
def build(project_id: str, site_id: str, principal: Principal = Depends(get_principal)) -> dict:
    """Run one durable tick for the site's current source revision (sandboxed build + browser QA)."""
    authorize_project_access(principal, project_id)
    _operator(principal)
    try:
        view = service.inspect_site(principal, project_id, site_id, adapter=storage_adapter())
    except (LookupError, ValueError):
        raise HTTPException(status_code=404, detail="Site not found in this project") from None
    report = service.run_build_tick(view["job"]["job_id"])
    return {"tick": {"outcome": report.outcome, "state": report.final_state, "reasons": report.reasons},
            "site": service.inspect_site(principal, project_id, site_id, adapter=storage_adapter())}


@router.get("/projects/{project_id}/sites/{site_id}/trace/{req_id}")
@domain_errors
def trace(project_id: str, site_id: str, req_id: str, principal: Principal = Depends(get_principal)) -> dict:
    authorize_project_access(principal, project_id)
    try:
        return _site(project_id, site_id).trace(req_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown requirement") from None


@router.get("/projects/{project_id}/sites/{site_id}/inspect/{target:path}")
@domain_errors
def inspect_target(project_id: str, site_id: str, target: str, principal: Principal = Depends(get_principal)) -> dict:
    authorize_project_access(principal, project_id)
    return _site(project_id, site_id).inspect(target)


@router.get("/projects/{project_id}/sites/{site_id}/omissions")
@domain_errors
def omissions(project_id: str, site_id: str, principal: Principal = Depends(get_principal)) -> dict:
    authorize_project_access(principal, project_id)
    return {"omissions": _site(project_id, site_id).find_omissions()}


@router.post("/projects/{project_id}/sites/{site_id}/impact")
@domain_errors
def impact(project_id: str, site_id: str, req: ImpactRequest, principal: Principal = Depends(get_principal)) -> dict:
    authorize_project_access(principal, project_id)
    try:
        return _site(project_id, site_id).impact_analysis(req.req_ids)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown requirement") from None


@router.get("/projects/{project_id}/sites/{site_id}/repair/{req_id}")
@domain_errors
def repair(project_id: str, site_id: str, req_id: str, principal: Principal = Depends(get_principal)) -> dict:
    authorize_project_access(principal, project_id)
    try:
        return _site(project_id, site_id).propose_repair(req_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown requirement") from None


@router.get("/projects/{project_id}/sites/{site_id}/framework-bindings")
@domain_errors
def bindings(project_id: str, site_id: str, principal: Principal = Depends(get_principal)) -> dict:
    """Proposed Agency Operating Framework task refs. Read-only: the framework's ledger is never written here."""
    authorize_project_access(principal, project_id)
    try:
        return framework_bindings(project_id, site_id, adapter=storage_adapter())
    except (LookupError, ValueError):
        raise HTTPException(status_code=404, detail="Site not found in this project") from None


__all__ = ["router"]
