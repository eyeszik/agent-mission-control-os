"""ACE x AVIC API: brief -> verified native SVG, edits, recovery, approval request and local release. Never publishes.

Every route requires an authenticated principal and resolves the project's recorded tenant. The brand
is the server's projection (``profiles.psem_brand``); a request cannot carry brand, approval or tenant
authority (extra fields are rejected). Writes need an operator role and an ``Idempotency-Key``. An
edit must name the SVG it was made against (``base_svg_sha256``); a stale base is ``409``. Approval
is decided only via ``/approvals/{id}/decide``. Stored SVG is served with a CSP that forbids every
fetch and script, so it is safe to open directly; the UI shows it through ``<img>`` anyway.
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field

from services.langgraph.agency.avic import capabilities as caps
from services.langgraph.agency.avic import profiles, render, service
from services.langgraph.agency.prompt_compiler import AssetRequirement
from services.langgraph.api.routes._project_common import authorize_project_access, domain_errors, storage_adapter
from services.langgraph.persistence.idempotency import complete_idempotency, fail_idempotency, hash_payload, reserve_idempotency
from services.langgraph.security.auth import Principal, get_principal

router = APIRouter()
OPERATOR_ROLES = {"admin", "operator", "owner", "approver"}
SVG_HEADERS = {"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
               "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"}


class CompileRequest(BaseModel):
    requirement: AssetRequirement
    style_profile: str = Field(min_length=1, max_length=80)
    seed: int = Field(default=0, ge=0, le=2**31 - 1)

    model_config = {"extra": "forbid"}


class EditRequest(BaseModel):
    op: Literal["recolor", "change_text", "set_geometry"]
    args: dict[str, Any]
    base_svg_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    model_config = {"extra": "forbid"}


class ReleaseRequest(BaseModel):
    approval_id: Optional[str] = Field(default=None, max_length=200)

    model_config = {"extra": "forbid"}


def _operator(principal: Principal) -> None:
    if principal.role.strip().lower() not in OPERATOR_ROLES:
        raise HTTPException(status_code=403, detail="Changing a visual asset requires an operator role")


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Asset not found in this project")


def _idempotent(principal: Principal, project_id: str, action: str, key: str, payload: dict, run) -> dict:
    scope = f"{principal.tenant_id}:{principal.user_id}:avic.{action}:{project_id}"
    reservation = reserve_idempotency(scope, key, hash_payload(payload))
    if reservation["state"] == "replay":
        return reservation["record"]["result"]
    if reservation["state"] in {"in_progress", "conflict"}:
        raise HTTPException(status_code=409, detail="Idempotency-Key is in use or was reused with different input")
    try:
        result = run()
    except Exception as exc:
        fail_idempotency(scope, key, type(exc).__name__)
        raise
    if result.get("status") == "CONFLICT":  # not recorded: the caller reloads and retries with a new base
        fail_idempotency(scope, key, "CONFLICT")
        raise HTTPException(status_code=409, detail={"status": "CONFLICT", "reasons": result.get("reasons", [])})
    complete_idempotency(scope, key, result)
    return result


@router.get("/capabilities")
def capabilities(principal: Principal = Depends(get_principal)) -> dict:
    state, blockers, _ = render.renderer_state()
    return {"capabilities": [c._asdict() for c in caps.CAPABILITIES], "style_profiles": profiles.catalogue(),
            "renderer": {"name": render.RENDERER, "state": state.value, "blockers": blockers,
                         "concurrency": render.RENDER_SLOTS},
            "brand": {"source": "foundry.psem.PALETTE", "palette": dict(profiles.psem_brand().palette)}}


@router.get("/projects/{project_id}/assets")
@domain_errors
def assets(project_id: str, principal: Principal = Depends(get_principal)) -> dict:
    authorize_project_access(principal, project_id)
    return {"assets": service.list_assets(project_id)}


@router.post("/projects/{project_id}/assets", status_code=201)
@domain_errors
def compile_asset(project_id: str, req: CompileRequest, idempotency_key: str = Header(..., alias="Idempotency-Key"),
                  principal: Principal = Depends(get_principal)) -> dict:
    authorize_project_access(principal, project_id)
    _operator(principal)

    def run() -> dict:
        with tempfile.TemporaryDirectory(prefix="avic-") as work:
            out = service.compile_asset(principal, project_id, req.requirement, brand=profiles.psem_brand(),
                                        style_profile=req.style_profile, adapter=storage_adapter(), work_dir=Path(work),
                                        seed=req.seed)
        return {"asset_id": req.requirement.asset_id, **out}
    return _idempotent(principal, project_id, "compile", idempotency_key, req.model_dump(mode="json"), run)


@router.get("/projects/{project_id}/assets/{asset_id}")
@domain_errors
def inspect(project_id: str, asset_id: str, principal: Principal = Depends(get_principal)) -> dict:
    authorize_project_access(principal, project_id)
    try:
        return service.inspect_asset(principal, project_id, asset_id, adapter=storage_adapter())
    except LookupError:
        raise _not_found() from None


def _bytes(principal: Principal, project_id: str, asset_id: str, stage: str) -> bytes:
    authorize_project_access(principal, project_id)
    try:
        return service.read_stage_bytes(principal, project_id, asset_id, stage, adapter=storage_adapter())
    except LookupError:
        raise _not_found() from None


@router.get("/projects/{project_id}/assets/{asset_id}/master.svg")
@domain_errors
def master_svg(project_id: str, asset_id: str, principal: Principal = Depends(get_principal)) -> Response:
    data = _bytes(principal, project_id, asset_id, "svg")
    return Response(data, media_type="image/svg+xml",
                    headers={**SVG_HEADERS, "X-AMC-Content-SHA256": hashlib.sha256(data).hexdigest()})


@router.get("/projects/{project_id}/assets/{asset_id}/preview.png")
@domain_errors
def preview_png(project_id: str, asset_id: str, principal: Principal = Depends(get_principal)) -> Response:
    data = _bytes(principal, project_id, asset_id, "preview")
    return Response(data, media_type="image/png", headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store",
                                                           "X-AMC-Content-SHA256": hashlib.sha256(data).hexdigest()})


@router.post("/projects/{project_id}/assets/{asset_id}/edits")
@domain_errors
def edit(project_id: str, asset_id: str, req: EditRequest, idempotency_key: str = Header(..., alias="Idempotency-Key"),
         principal: Principal = Depends(get_principal)) -> dict:
    authorize_project_access(principal, project_id)
    _operator(principal)

    def run() -> dict:
        with tempfile.TemporaryDirectory(prefix="avic-") as work:
            try:
                return service.edit_asset(principal, project_id, asset_id, op=req.op, args=req.args, adapter=storage_adapter(),
                                          work_dir=Path(work), base_svg_sha256=req.base_svg_sha256)
            except LookupError:
                raise _not_found() from None
            except KeyError as exc:
                raise HTTPException(status_code=422, detail=f"missing edit argument {exc}") from None
    return _idempotent(principal, project_id, f"edit.{asset_id}", idempotency_key, req.model_dump(mode="json"), run)


@router.post("/projects/{project_id}/assets/{asset_id}/recompile")
@domain_errors
def recompile(project_id: str, asset_id: str, idempotency_key: str = Header(..., alias="Idempotency-Key"),
              principal: Principal = Depends(get_principal)) -> dict:
    """Re-derive svg, preview, evaluation and provenance from the stored scene (recovery after a crash or conflict)."""
    authorize_project_access(principal, project_id)
    _operator(principal)

    def run() -> dict:
        with tempfile.TemporaryDirectory(prefix="avic-") as work:
            try:
                return service.recompile_asset(principal, project_id, asset_id, adapter=storage_adapter(), work_dir=Path(work))
            except LookupError:
                raise _not_found() from None
    return _idempotent(principal, project_id, f"recompile.{asset_id}", idempotency_key, {"asset_id": asset_id}, run)


@router.post("/projects/{project_id}/assets/{asset_id}/approval")
@domain_errors
def request_approval(project_id: str, asset_id: str, principal: Principal = Depends(get_principal)) -> dict:
    """Open (or reuse) the pending approval bound to the current SVG hash. Decided only via /approvals/{id}/decide."""
    authorize_project_access(principal, project_id)
    _operator(principal)
    try:
        return service.request_approval(principal, project_id, asset_id, adapter=storage_adapter())
    except LookupError:
        raise _not_found() from None


@router.post("/projects/{project_id}/assets/{asset_id}/release")
@domain_errors
def release(project_id: str, asset_id: str, req: ReleaseRequest, principal: Principal = Depends(get_principal)) -> dict:
    """Seal a local release record. No external effect; blocked unless verified, current and approved."""
    authorize_project_access(principal, project_id)
    _operator(principal)
    try:
        return service.release_local(principal, project_id, asset_id, approval_id=req.approval_id, adapter=storage_adapter())
    except LookupError:
        raise _not_found() from None


__all__ = ["router"]
