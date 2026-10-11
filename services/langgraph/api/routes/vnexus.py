"""VNEXUS API: brand genome versions, resolution, approval binding and audit.

Every route requires an authenticated principal. Tenant and project authority
come from the server-side principal and the project's recorded tenant, never
from the request body. Approval decisions are not made here: submitting opens
an approval on the existing ``/approvals/{id}/decide`` route, and ``settle``
applies a decision that a different, authorized human already made.
"""

from __future__ import annotations

import functools
import inspect
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from services.langgraph.agency.vnexus import service
from services.langgraph.agency.vnexus.genome import GenomeDocument, GenomeTransitionError, Scope
from services.langgraph.api.routes._project_common import domain_errors
from services.langgraph.persistence.idempotency import complete_idempotency, fail_idempotency, hash_payload, reserve_idempotency
from services.langgraph.persistence.vnexus import VnexusConflict, VnexusNotFound
from services.langgraph.security.auth import Principal, get_principal

router = APIRouter()

_VNEXUS_ERRORS: tuple[tuple[type[BaseException], int], ...] = (
    (VnexusNotFound, 404),
    (VnexusConflict, 409),
    (GenomeTransitionError, 409),
    (service.GenomeIntegrityError, 409),
)


def vnexus_errors(handler: Callable[..., Any]) -> Callable[..., Any]:
    """VNEXUS domain errors first (several subclass ValueError), then the shared project-OS mapping."""

    @functools.wraps(handler)
    def mapped(*args: Any, **kwargs: Any) -> Any:
        try:
            return handler(*args, **kwargs)
        except service.GenomeBlocked as exc:
            raise HTTPException(status_code=409, detail={"message": str(exc), "readiness": exc.report}) from exc
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 - re-raised unless mapped
            for error_type, status in _VNEXUS_ERRORS:
                if isinstance(exc, error_type):
                    raise HTTPException(status_code=status, detail=str(exc) or error_type.__name__) from exc
            raise

    mapped.__signature__ = inspect.signature(handler)  # type: ignore[attr-defined]
    return domain_errors(mapped)


def idempotent(principal: Principal, operation: str, key: str, payload: dict, run: Callable[[], dict]) -> dict:
    scope = f"{principal.tenant_id}:{principal.user_id}:vnexus.{operation}"
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
    complete_idempotency(scope, key, result)
    return result


class BrandCreate(BaseModel):
    brand_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")
    display_name: str = Field(min_length=1, max_length=120)
    owner_project_id: str = Field(min_length=1, max_length=120)

    model_config = {"extra": "forbid"}


class VersionCreate(BaseModel):
    scope: Scope
    scope_ref: str = Field(min_length=1, max_length=300)
    document: GenomeDocument
    experimental: bool = False

    model_config = {"extra": "forbid"}


class VersionEdit(BaseModel):
    expected_revision: int = Field(ge=1)
    document: GenomeDocument

    model_config = {"extra": "forbid"}


def _public(row: dict) -> dict:
    return {k: row.get(k) for k in ("version_id", "brand_id", "scope", "scope_ref", "project_id", "version", "parent_version_id",
                                    "status", "document", "content_hash", "revision", "origin", "origin_ref", "created_by",
                                    "created_at", "updated_at", "submitted_by", "submitted_at", "approval_id", "decided_by",
                                    "decided_at")}


@router.post("/brands", status_code=201)
@vnexus_errors
def create_brand(req: BrandCreate, idempotency_key: str = Header(..., alias="Idempotency-Key"),
                 principal: Principal = Depends(get_principal)) -> dict:
    return idempotent(principal, "brand.create", idempotency_key, req.model_dump(),
                      lambda: {"brand": service.create_brand(principal, **req.model_dump())})


@router.get("/brands")
@vnexus_errors
def list_brands(principal: Principal = Depends(get_principal)) -> dict:
    return {"brands": service.list_brands(principal)}


@router.get("/brands/{brand_id}")
@vnexus_errors
def get_brand(brand_id: str, principal: Principal = Depends(get_principal)) -> dict:
    brand = service.brand_for(principal, brand_id)
    service.authorize(principal, brand["owner_project_id"])
    return {"brand": brand}


@router.post("/brands/{brand_id}/versions", status_code=201)
@vnexus_errors
def create_version(brand_id: str, req: VersionCreate, idempotency_key: str = Header(..., alias="Idempotency-Key"),
                   principal: Principal = Depends(get_principal)) -> dict:
    payload = {"brand_id": brand_id, **req.model_dump(mode="json")}
    return idempotent(principal, "genome.create", idempotency_key, payload, lambda: {"version": _public(service.create_draft(
        principal, brand_id, scope=req.scope, scope_ref=req.scope_ref, document=req.document, experimental=req.experimental))})


@router.get("/brands/{brand_id}/versions")
@vnexus_errors
def list_versions(brand_id: str, scope: Optional[Scope] = None, scope_ref: Optional[str] = None,
                  principal: Principal = Depends(get_principal)) -> dict:
    return {"versions": [_public(r) for r in service.list_versions(principal, brand_id, scope=scope, scope_ref=scope_ref)]}


@router.get("/brands/{brand_id}/resolve")
@vnexus_errors
def resolve_scope(brand_id: str, scope: Scope, scope_ref: str, preview_version_id: Optional[str] = None,
                  principal: Principal = Depends(get_principal)) -> dict:
    resolution, layers = service.resolve_scope(principal, brand_id, scope=scope, scope_ref=scope_ref,
                                               preview_version_id=preview_version_id)
    return {"resolution": resolution.model_dump(mode="json"), "resolution_hash": resolution.resolution_hash,
            "layers": [{"scope": layer.scope.value, "scope_ref": layer.scope_ref, "status": layer.status.value, "version_id": layer.version_id,
                        "version": layer.version, "content_hash": layer.document.content_hash} for layer in layers]}


@router.get("/brands/{brand_id}/audit")
@vnexus_errors
def audit(brand_id: str, subject_id: Optional[str] = None, principal: Principal = Depends(get_principal)) -> dict:
    return service.audit_trail(principal, brand_id, subject_id=subject_id)


@router.get("/versions/{version_id}")
@vnexus_errors
def get_version(version_id: str, principal: Principal = Depends(get_principal)) -> dict:
    return {"version": _public(service.get_version(principal, version_id))}


@router.put("/versions/{version_id}")
@vnexus_errors
def edit_version(version_id: str, req: VersionEdit, principal: Principal = Depends(get_principal)) -> dict:
    return {"version": _public(service.edit_draft(principal, version_id, expected_revision=req.expected_revision,
                                                  document=req.document))}


@router.get("/versions/{version_id}/readiness")
@vnexus_errors
def readiness(version_id: str, principal: Principal = Depends(get_principal)) -> dict:
    return {"readiness": service.readiness(service.get_version(principal, version_id, settle=False))}


@router.post("/versions/{version_id}/submit")
@vnexus_errors
def submit(version_id: str, idempotency_key: str = Header(..., alias="Idempotency-Key"),
           principal: Principal = Depends(get_principal)) -> dict:
    return idempotent(principal, "genome.submit", idempotency_key, {"version_id": version_id},
                      lambda: {"version": _public(service.submit_version(principal, version_id))})


@router.post("/versions/{version_id}/withdraw")
@vnexus_errors
def withdraw(version_id: str, principal: Principal = Depends(get_principal)) -> dict:
    return {"version": _public(service.withdraw_version(principal, version_id))}


@router.post("/versions/{version_id}/settle")
@vnexus_errors
def settle(version_id: str, principal: Principal = Depends(get_principal)) -> dict:
    return {"version": _public(service.settle_version(principal, version_id))}


@router.post("/versions/{version_id}/revert", status_code=201)
@vnexus_errors
def revert(version_id: str, idempotency_key: str = Header(..., alias="Idempotency-Key"),
           principal: Principal = Depends(get_principal)) -> dict:
    return idempotent(principal, "genome.revert", idempotency_key, {"version_id": version_id},
                      lambda: {"version": _public(service.revert_to(principal, version_id))})


@router.get("/compare")
@vnexus_errors
def compare(from_version: str = Query(..., alias="from"), to_version: str = Query(..., alias="to"),
            principal: Principal = Depends(get_principal)) -> dict:
    return service.compare_versions(principal, from_version, to_version)
