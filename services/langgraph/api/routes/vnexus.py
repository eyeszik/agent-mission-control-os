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

from services.langgraph.agency.vnexus import creative_service, fabric_service, media_fabric, production, service
from services.langgraph.agency.vnexus.art_director import ArtDirectionRequest
from services.langgraph.agency.vnexus.experience import ExperienceRequest
from services.langgraph.agency.vnexus.video import VideoBrief
from services.langgraph.agency.vnexus.genome import GenomeDocument, GenomeTransitionError, Scope
from services.langgraph.agency.vnexus.graph import EdgeKind, GraphError, NodeKind
from services.langgraph.agency.vnexus.multiverse import BranchTransitionError, ChangeSet
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
    (GraphError, 409),
    (BranchTransitionError, 409),
    (LookupError, 404),
)


def vnexus_errors(handler: Callable[..., Any]) -> Callable[..., Any]:
    """VNEXUS domain errors first (several subclass ValueError), then the shared project-OS mapping."""

    @functools.wraps(handler)
    def mapped(*args: Any, **kwargs: Any) -> Any:
        try:
            return handler(*args, **kwargs)
        except service.GenomeBlocked as exc:
            raise HTTPException(status_code=409, detail={"message": str(exc), "readiness": exc.report}) from exc
        except fabric_service.RateLimited as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        except creative_service.MergeConflict as exc:
            raise HTTPException(status_code=409, detail={"message": str(exc), "report": exc.report}) from exc
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


# --------------------------------------------------------------------------- knowledge graph


class NodeCreate(BaseModel):
    kind: NodeKind
    label: str = Field(min_length=1, max_length=200)
    attributes: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}


class EdgeCreate(BaseModel):
    kind: EdgeKind
    src_node_id: str = Field(min_length=1, max_length=80)
    dst_node_id: str = Field(min_length=1, max_length=80)
    provenance: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}


class NodeSupersede(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    attributes: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}


class ImpactRequest(BaseModel):
    node_ids: list[str] = Field(min_length=1, max_length=50)
    as_of: Optional[str] = None

    model_config = {"extra": "forbid"}


@router.get("/brands/{brand_id}/graph")
@vnexus_errors
def graph_view(brand_id: str, as_of: Optional[str] = None, principal: Principal = Depends(get_principal)) -> dict:
    return creative_service.graph_view(principal, brand_id, as_of=as_of)


@router.post("/brands/{brand_id}/graph/nodes", status_code=201)
@vnexus_errors
def add_node(brand_id: str, req: NodeCreate, principal: Principal = Depends(get_principal)) -> dict:
    return {"node": creative_service.add_node(principal, brand_id, kind=req.kind, label=req.label, attributes=req.attributes)}


@router.post("/brands/{brand_id}/graph/edges", status_code=201)
@vnexus_errors
def add_edge(brand_id: str, req: EdgeCreate, principal: Principal = Depends(get_principal)) -> dict:
    return {"edge": creative_service.add_edge(principal, brand_id, kind=req.kind, src=req.src_node_id, dst=req.dst_node_id,
                                              provenance=req.provenance)}


@router.delete("/brands/{brand_id}/graph/edges/{edge_id}")
@vnexus_errors
def retire_edge(brand_id: str, edge_id: str, principal: Principal = Depends(get_principal)) -> dict:
    creative_service.retire_edge(principal, brand_id, edge_id)
    return {"retired": edge_id}


@router.post("/graph/nodes/{node_id}/supersede", status_code=201)
@vnexus_errors
def supersede_node(node_id: str, req: NodeSupersede, principal: Principal = Depends(get_principal)) -> dict:
    return {"node": creative_service.supersede_node(principal, node_id, label=req.label, attributes=req.attributes)}


@router.get("/graph/nodes/{node_id}/evidence")
@vnexus_errors
def node_evidence(node_id: str, as_of: Optional[str] = None, principal: Principal = Depends(get_principal)) -> dict:
    return creative_service.evidence(principal, node_id, as_of=as_of)


@router.post("/brands/{brand_id}/graph/impact")
@vnexus_errors
def graph_impact(brand_id: str, req: ImpactRequest, principal: Principal = Depends(get_principal)) -> dict:
    return creative_service.impact(principal, brand_id, req.node_ids, as_of=req.as_of)


@router.get("/brands/{brand_id}/graph/diff")
@vnexus_errors
def graph_diff(brand_id: str, from_ts: str = Query(..., alias="from"), to_ts: Optional[str] = Query(None, alias="to"),
               principal: Principal = Depends(get_principal)) -> dict:
    return creative_service.snapshot_diff(principal, brand_id, from_ts=from_ts, to_ts=to_ts)


# --------------------------------------------------------------------------- creative multiverse


class BranchCreate(BaseModel):
    base_version_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    hypothesis: str = Field(default="", max_length=1000)
    changes: ChangeSet
    parent_branch_id: Optional[str] = None

    model_config = {"extra": "forbid"}


class BranchEdit(BaseModel):
    expected_revision: int = Field(ge=1)
    changes: ChangeSet

    model_config = {"extra": "forbid"}


class BranchFeedback(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    decision: Optional[str] = None

    model_config = {"extra": "forbid"}


class BranchMerge(BaseModel):
    other_branch_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)

    model_config = {"extra": "forbid"}


@router.get("/brands/{brand_id}/branches")
@vnexus_errors
def list_branches(brand_id: str, principal: Principal = Depends(get_principal)) -> dict:
    return {"branches": creative_service.list_branches(principal, brand_id)}


@router.post("/brands/{brand_id}/branches", status_code=201)
@vnexus_errors
def fork_branch(brand_id: str, req: BranchCreate, idempotency_key: str = Header(..., alias="Idempotency-Key"),
                principal: Principal = Depends(get_principal)) -> dict:
    payload = {"brand_id": brand_id, **req.model_dump(mode="json")}
    return idempotent(principal, "branch.fork", idempotency_key, payload, lambda: {"branch": creative_service.fork(
        principal, brand_id, base_version_id=req.base_version_id, name=req.name, hypothesis=req.hypothesis, changes=req.changes,
        parent_branch_id=req.parent_branch_id)})


@router.get("/branches/{branch_id}")
@vnexus_errors
def get_branch(branch_id: str, principal: Principal = Depends(get_principal)) -> dict:
    return {"branch": creative_service.get_branch(principal, branch_id)}


@router.put("/branches/{branch_id}")
@vnexus_errors
def edit_branch(branch_id: str, req: BranchEdit, principal: Principal = Depends(get_principal)) -> dict:
    return {"branch": creative_service.edit(principal, branch_id, expected_revision=req.expected_revision, changes=req.changes)}


@router.get("/branches/{branch_id}/compare")
@vnexus_errors
def compare_branch(branch_id: str, principal: Principal = Depends(get_principal)) -> dict:
    return {"comparison": creative_service.compare(principal, branch_id)}


@router.get("/branches/{branch_id}/compare/{other_id}")
@vnexus_errors
def compare_two_branches(branch_id: str, other_id: str, principal: Principal = Depends(get_principal)) -> dict:
    return {"comparison": creative_service.compare_two(principal, branch_id, other_id)}


@router.post("/branches/{branch_id}/evaluations", status_code=201)
@vnexus_errors
def evaluate_branch(branch_id: str, principal: Principal = Depends(get_principal)) -> dict:
    return {"evaluation": creative_service.evaluate(principal, branch_id)}


@router.post("/branches/{branch_id}/feedback", status_code=201)
@vnexus_errors
def branch_feedback(branch_id: str, req: BranchFeedback, principal: Principal = Depends(get_principal)) -> dict:
    return {"evaluation": creative_service.record_feedback(principal, branch_id, text=req.text, decision=req.decision)}


@router.post("/branches/{branch_id}/merge", status_code=201)
@vnexus_errors
def merge_branches(branch_id: str, req: BranchMerge, idempotency_key: str = Header(..., alias="Idempotency-Key"),
                   principal: Principal = Depends(get_principal)) -> dict:
    payload = {"branch_id": branch_id, **req.model_dump()}
    return idempotent(principal, "branch.merge", idempotency_key, payload,
                      lambda: creative_service.merge(principal, branch_id, req.other_branch_id, name=req.name))


@router.post("/branches/{branch_id}/rebase")
@vnexus_errors
def rebase_branch(branch_id: str, principal: Principal = Depends(get_principal)) -> dict:
    return creative_service.rebase_branch(principal, branch_id)


@router.post("/branches/{branch_id}/submit")
@vnexus_errors
def submit_branch(branch_id: str, idempotency_key: str = Header(..., alias="Idempotency-Key"),
                  principal: Principal = Depends(get_principal)) -> dict:
    return idempotent(principal, "branch.submit", idempotency_key, {"branch_id": branch_id},
                      lambda: _jsonable(creative_service.submit(principal, branch_id)))


@router.post("/branches/{branch_id}/settle")
@vnexus_errors
def settle_branch(branch_id: str, principal: Principal = Depends(get_principal)) -> dict:
    return {"branch": creative_service.settle(principal, branch_id)}


@router.post("/branches/{branch_id}/archive")
@vnexus_errors
def archive_branch(branch_id: str, principal: Principal = Depends(get_principal)) -> dict:
    return {"branch": creative_service.archive(principal, branch_id)}


def _jsonable(result: dict) -> dict:
    return {"branch": result["branch"], "proposal": _public(result["proposal"])}


# --------------------------------------------------------------------------- media fabric


class MediaJobCreate(BaseModel):
    provider_id: str = Field(min_length=1, max_length=80)
    request: media_fabric.MediaRequest
    budget_ceiling_minor: int = Field(default=0, ge=0, le=10_000_000)
    run: bool = True

    model_config = {"extra": "forbid"}


@router.get("/fabric/providers")
@vnexus_errors
def providers(principal: Principal = Depends(get_principal)) -> dict:
    return {"providers": media_fabric.discover(), "fabric_version": media_fabric.FABRIC_VERSION,
            "hosted_generation": "DISABLED: no hosted adapter is implemented or authorized"}


@router.post("/projects/{project_id}/media-jobs", status_code=201)
@vnexus_errors
def create_media_job(project_id: str, req: MediaJobCreate, idempotency_key: str = Header(..., alias="Idempotency-Key"),
                     principal: Principal = Depends(get_principal)) -> dict:
    if req.run:
        row = fabric_service.execute(principal, project_id, provider_id=req.provider_id, request=req.request,
                                     idempotency_key=idempotency_key, budget_ceiling_minor=req.budget_ceiling_minor)
    else:
        row = fabric_service.plan(principal, project_id, provider_id=req.provider_id, request=req.request,
                                  idempotency_key=idempotency_key, budget_ceiling_minor=req.budget_ceiling_minor)
        row = fabric_service.validate(principal, row["job_id"])
    return {"job": fabric_service.public(row)}


@router.get("/projects/{project_id}/media-jobs")
@vnexus_errors
def list_media_jobs(project_id: str, principal: Principal = Depends(get_principal)) -> dict:
    return {"jobs": fabric_service.list_jobs(principal, project_id)}


@router.get("/media-jobs/{job_id}")
@vnexus_errors
def get_media_job(job_id: str, principal: Principal = Depends(get_principal)) -> dict:
    return {"job": fabric_service.get_job(principal, job_id)}


@router.post("/media-jobs/{job_id}/authorize")
@vnexus_errors
def authorize_media_job(job_id: str, principal: Principal = Depends(get_principal)) -> dict:
    return {"job": fabric_service.public(fabric_service.authorize(principal, job_id))}


@router.post("/media-jobs/{job_id}/run")
@vnexus_errors
def run_media_job(job_id: str, principal: Principal = Depends(get_principal)) -> dict:
    return {"job": fabric_service.public(fabric_service.run(principal, job_id))}


@router.post("/media-jobs/{job_id}/retry")
@vnexus_errors
def retry_media_job(job_id: str, principal: Principal = Depends(get_principal)) -> dict:
    return {"job": fabric_service.public(fabric_service.retry(principal, job_id))}


@router.post("/media-jobs/{job_id}/cancel")
@vnexus_errors
def cancel_media_job(job_id: str, principal: Principal = Depends(get_principal)) -> dict:
    return {"job": fabric_service.public(fabric_service.cancel(principal, job_id))}


# --------------------------------------------------------------------------- production from an approved genome


class ProductionTarget(BaseModel):
    scope: Scope
    scope_ref: str = Field(min_length=1, max_length=300)
    project_id: str = Field(min_length=1, max_length=120)

    model_config = {"extra": "forbid"}


class IdentityProduction(ProductionTarget):
    deliverables: list[str] = Field(min_length=1, max_length=11)
    copy_text: dict[str, str] = Field(default_factory=dict)


class ExperienceProduction(ProductionTarget):
    request: ExperienceRequest


class ArtDirectionProduction(ProductionTarget):
    request: ArtDirectionRequest


class VideoProduction(ProductionTarget):
    brief: VideoBrief


@router.post("/brands/{brand_id}/production/identity")
@vnexus_errors
def produce_identity(brand_id: str, req: IdentityProduction, idempotency_key: str = Header(..., alias="Idempotency-Key"),
                     principal: Principal = Depends(get_principal)) -> dict:
    payload = {"brand_id": brand_id, **req.model_dump(mode="json")}
    return idempotent(principal, "production.identity", idempotency_key, payload, lambda: production.produce_identity(
        principal, brand_id, scope=req.scope, scope_ref=req.scope_ref, project_id=req.project_id, deliverables=tuple(req.deliverables),
        copy={k: v[:200] for k, v in req.copy_text.items()}, run_key=f"identity:{idempotency_key}"))


@router.post("/brands/{brand_id}/production/experience")
@vnexus_errors
def produce_experience(brand_id: str, req: ExperienceProduction, idempotency_key: str = Header(..., alias="Idempotency-Key"),
                       principal: Principal = Depends(get_principal)) -> dict:
    payload = {"brand_id": brand_id, **req.model_dump(mode="json")}
    return idempotent(principal, "production.experience", idempotency_key, payload, lambda: production.produce_experience(
        principal, brand_id, scope=req.scope, scope_ref=req.scope_ref, project_id=req.project_id, request=req.request))


@router.post("/brands/{brand_id}/production/art-direction")
@vnexus_errors
def produce_art_direction(brand_id: str, req: ArtDirectionProduction, idempotency_key: str = Header(..., alias="Idempotency-Key"),
                          principal: Principal = Depends(get_principal)) -> dict:
    payload = {"brand_id": brand_id, **req.model_dump(mode="json")}
    return idempotent(principal, "production.art_direction", idempotency_key, payload, lambda: production.art_direction(
        principal, brand_id, scope=req.scope, scope_ref=req.scope_ref, project_id=req.project_id, request=req.request))


@router.post("/brands/{brand_id}/production/video")
@vnexus_errors
def produce_video(brand_id: str, req: VideoProduction, idempotency_key: str = Header(..., alias="Idempotency-Key"),
                  principal: Principal = Depends(get_principal)) -> dict:
    payload = {"brand_id": brand_id, **req.model_dump(mode="json")}
    return idempotent(principal, "production.video", idempotency_key, payload, lambda: production.produce_video(
        principal, brand_id, scope=req.scope, scope_ref=req.scope_ref, project_id=req.project_id, brief=req.brief,
        run_key=f"video:{idempotency_key}"))
