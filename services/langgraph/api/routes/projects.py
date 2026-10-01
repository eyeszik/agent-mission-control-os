"""Project workspaces, artifact graph v2, DAM, prompts, workstreams, video, brand."""

from __future__ import annotations

import base64
import binascii
import os
from pathlib import Path
from typing import Any, Literal, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from services.langgraph.agency.project_os.brand_drift import BrandFacts, analyze
from services.langgraph.agency.project_os.paid_media import PaidMediaBrief, plan_campaign
from services.langgraph.agency.project_os.video import freevideoforge_capability, plan_video_production
from services.langgraph.agency.project_os.vocabulary import CapabilityStatus, ProjectLifecycle
from services.langgraph.agency.project_os.workspace import tree
from services.langgraph.agency.project_os.workstreams import WORKSTREAMS, plan_workstream
from services.langgraph.api.routes._project_common import (
    authorize_project_access,
    domain_errors,
    storage_adapter,
)
from services.langgraph.persistence.idempotency import complete_idempotency, fail_idempotency, hash_payload, reserve_idempotency
from services.langgraph.persistence.project_media import (
    collect_drift_subjects,
    ingest_video_run,
    rights_expiration_radar,
    upload_media,
)
from services.langgraph.persistence.projects import (
    artifact_history,
    branch_artifact,
    compare_artifact_versions,
    create_project_artifact,
    create_project_workspace,
    list_asset_rights,
    list_edit_requests,
    list_project_artifacts,
    list_project_events,
    list_project_workspaces,
    list_prompts,
    list_storage_objects,
    materialize_prompt_ledger,
    merge_branch,
    project_snapshot,
    reconcile_storage_objects,
    record_prompt,
    register_asset_rights,
    restore_artifact_version,
    revise_project_artifact,
    transition_project,
    workspace_root_for,
)
from services.langgraph.persistence.project_ops import add_artifact_comment, request_artifact_edit
from services.langgraph.security.auth import Principal, get_principal

router = APIRouter()

PROJECT_CREATOR_ROLES = frozenset({"owner", "admin", "operator"})
MAX_UPLOAD_BASE64_CHARS = 21 * 1024 * 1024


class CreateProjectRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=160)
    slug: Optional[str] = Field(default=None, max_length=64)
    project_id: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    description: str = Field(default="", max_length=4000)
    brand_name: Optional[str] = Field(default=None, max_length=160)
    brand_id: Optional[str] = Field(default=None, max_length=128)


class LifecycleRequest(BaseModel):
    target: ProjectLifecycle


class CreateArtifactRequest(BaseModel):
    artifact_key: str = Field(min_length=1, max_length=120)
    artifact_type: str
    content_text: str = Field(max_length=500_000)
    subtype: Optional[str] = Field(default=None, max_length=80)
    v2: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list, max_length=50)


class ReviseArtifactRequest(BaseModel):
    expected_version: int = Field(ge=1)
    content_text: Optional[str] = Field(default=None, max_length=500_000)
    v2_patch: dict[str, Any] = Field(default_factory=dict)


class RestoreRequest(BaseModel):
    version: int = Field(ge=1)
    expected_version: int = Field(ge=1)


class BranchRequest(BaseModel):
    branch_key: str = Field(min_length=1, max_length=120)
    v2: dict[str, Any] = Field(default_factory=dict)
    content_text: Optional[str] = Field(default=None, max_length=500_000)


class MergeRequest(BaseModel):
    branch_id: str
    expected_version: int = Field(ge=1)
    replace_master: bool = False


class CommentRequest(BaseModel):
    version_ref: str
    body: str = Field(min_length=1, max_length=4000)


class EditRequest(BaseModel):
    base_version_ref: str
    instruction: str = Field(min_length=1, max_length=4000)


class RightsRequest(BaseModel):
    license: str = Field(min_length=1, max_length=200)
    territory: str = "UNSPECIFIED"
    usage_scope: str = "UNSPECIFIED"
    attribution: Optional[str] = None
    source_ref: Optional[str] = None
    expires_at: Optional[str] = None


class UploadRequest(BaseModel):
    artifact_key: str = Field(min_length=1, max_length=120)
    content_base64: str = Field(min_length=4, max_length=MAX_UPLOAD_BASE64_CHARS)
    v2: dict[str, Any] = Field(default_factory=dict)


class PromptRequest(BaseModel):
    prompt_id: Optional[str] = None
    department: str
    artifact_target: Optional[str] = None
    family: Optional[str] = None
    campaign_id: Optional[str] = None
    status: Literal["draft", "approved", "retired"] = "draft"
    body: dict[str, Any]


class VideoPlanRequest(BaseModel):
    cinematic_request: dict[str, Any]
    aspect: Literal["9:16", "1:1", "16:9", "4:5"] = "9:16"
    duration: Optional[float] = Field(default=None, ge=3.0, le=600.0)
    seed: Optional[int] = None


class VideoIngestRequest(BaseModel):
    output_dir: str = Field(min_length=1, max_length=1024)
    campaign_id: Optional[str] = None


class BrandFactsRequest(BaseModel):
    palette: list[str] = Field(default_factory=list)
    banned_terms: list[str] = Field(default_factory=list)
    deprecated_names: dict[str, str] = Field(default_factory=dict)
    current_prices: list[str] = Field(default_factory=list)
    brand_core_ref: Optional[str] = None


class PaidPlanRequest(BaseModel):
    objective: str
    offer: str
    audiences: list[str] = Field(min_length=1)
    channels: list[str] = Field(min_length=1)
    budget_minor: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    flight_days: int = Field(ge=1, le=730)
    creative_refs: list[str] = Field(default_factory=list)
    landing_page_ref: Optional[str] = None
    keywords: list[str] = Field(default_factory=list)


def _dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_dump(item) for item in value]
    return value


# --------------------------------------------------------------------------
# Workspaces
# --------------------------------------------------------------------------


@router.get("")
@domain_errors
def list_projects(principal: Principal = Depends(get_principal)):
    allowed = None if "*" in principal.allowed_project_ids else principal.allowed_project_ids
    return {"projects": _dump(list_project_workspaces(principal.tenant_id, project_ids=allowed))}


@router.post("", status_code=201)
@domain_errors
def create_project(
    req: CreateProjectRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    principal: Principal = Depends(get_principal),
):
    if principal.role.strip().lower() not in PROJECT_CREATOR_ROLES:
        raise HTTPException(status_code=403, detail="Creating projects requires an owner, admin or operator role")
    project_id = req.project_id
    if project_id is None and "*" not in principal.allowed_project_ids:
        raise HTTPException(status_code=403, detail="Allocating a new project id requires tenant-wide project scope")
    scope = f"{principal.tenant_id}:{principal.user_id}:project.create"
    request_hash = hash_payload(req.model_dump(mode="json"))
    reservation = reserve_idempotency(scope, idempotency_key, request_hash)
    if reservation["state"] == "replay":
        return reservation["record"]["result"]
    if reservation["state"] == "in_progress":
        raise HTTPException(status_code=409, detail="Equivalent request is already executing")
    if reservation["state"] == "conflict":
        raise HTTPException(status_code=409, detail="Idempotency-Key was reused with different input")
    project_id = project_id or f"prj-{uuid4().hex[:20]}"
    if not principal.can_access_project(project_id):
        fail_idempotency(scope, idempotency_key, "project_out_of_scope")
        raise HTTPException(status_code=403, detail="Project is outside the authenticated principal scope")
    try:
        result = create_project_workspace(
            tenant_id=principal.tenant_id,
            project_id=project_id,
            actor=principal.user_id,
            display_name=req.display_name,
            slug=req.slug,
            description=req.description,
            brand_id=req.brand_id,
            brand_name=req.brand_name,
        )
    except Exception as exc:
        fail_idempotency(scope, idempotency_key, type(exc).__name__)
        raise
    response = {
        "project": _dump(result["workspace"]),
        "created": result["created"],
        "mirror": result["mirror"],
    }
    complete_idempotency(scope, idempotency_key, response)
    return response


@router.get("/{project_id}")
@domain_errors
def get_project(project_id: str, principal: Principal = Depends(get_principal)):
    workspace = authorize_project_access(principal, project_id)
    return {"project": _dump(workspace), "snapshot": _dump(project_snapshot(project_id))}


@router.post("/{project_id}/lifecycle")
@domain_errors
def change_lifecycle(project_id: str, req: LifecycleRequest, principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    return {"project": _dump(transition_project(project_id, req.target.value, principal.user_id))}


@router.get("/{project_id}/events")
@domain_errors
def project_events(
    project_id: str,
    after: int = Query(default=0, ge=0),
    thread_id: Optional[str] = None,
    limit: int = Query(default=200, ge=1, le=1000),
    principal: Principal = Depends(get_principal),
):
    authorize_project_access(principal, project_id)
    return {"events": _dump(list_project_events(project_id, after_sequence=after, limit=limit, thread_id=thread_id))}


@router.get("/{project_id}/workspace")
@domain_errors
def workspace_view(project_id: str, principal: Principal = Depends(get_principal)):
    workspace = authorize_project_access(principal, project_id)
    root = workspace_root_for(workspace.tenant_id, project_id)
    adapter = storage_adapter()
    return {
        "root": str(root),
        "files": tree(root),
        "storage": adapter.status(),
        "objects": _dump(list_storage_objects(project_id)),
        "authority": "relational store is canonical; this tree is a materialized view",
    }


@router.post("/{project_id}/workspace/prompts/materialize")
@domain_errors
def materialize_prompts(project_id: str, principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    return materialize_prompt_ledger(project_id)


@router.post("/{project_id}/storage/reconcile")
@domain_errors
def reconcile_storage(project_id: str, principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    return reconcile_storage_objects(project_id, storage_adapter())


# --------------------------------------------------------------------------
# Artifact graph v2 + DAM
# --------------------------------------------------------------------------


@router.get("/{project_id}/artifacts")
@domain_errors
def list_artifacts(
    project_id: str,
    media_type: Optional[str] = None,
    channel: Optional[str] = None,
    artifact_type: Optional[str] = None,
    q: Optional[str] = Query(default=None, max_length=200),
    principal: Principal = Depends(get_principal),
):
    authorize_project_access(principal, project_id)
    return {"artifacts": _dump(list_project_artifacts(project_id, media_type=media_type, channel=channel, artifact_type=artifact_type, query=q))}


@router.post("/{project_id}/artifacts", status_code=201)
@domain_errors
def create_artifact(project_id: str, req: CreateArtifactRequest, principal: Principal = Depends(get_principal)):
    workspace = authorize_project_access(principal, project_id)
    artifact = create_project_artifact(
        tenant_id=workspace.tenant_id, project_id=project_id, actor=principal.user_id, artifact_key=req.artifact_key,
        artifact_type=req.artifact_type, adapter=storage_adapter(), content_text=req.content_text, subtype=req.subtype,
        v2=req.v2, depends_on=req.depends_on,
    )
    return {"artifact": _dump(artifact)}


@router.post("/{project_id}/artifacts/{artifact_id}/revisions")
@domain_errors
def revise_artifact(project_id: str, artifact_id: str, req: ReviseArtifactRequest, principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    result = revise_project_artifact(
        project_id=project_id, artifact_id=artifact_id, actor=principal.user_id, adapter=storage_adapter(),
        expected_version=req.expected_version, content_text=req.content_text, v2_patch=req.v2_patch,
    )
    return {**result, "artifact": _dump(result["artifact"])}


@router.get("/{project_id}/artifacts/{artifact_id}/history")
@domain_errors
def history(project_id: str, artifact_id: str, principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    return {"versions": _dump(artifact_history(project_id, artifact_id))}


@router.get("/{project_id}/artifacts/{artifact_id}/compare")
@domain_errors
def compare(project_id: str, artifact_id: str, from_version: int = Query(alias="from", ge=1), to_version: int = Query(alias="to", ge=1), principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    return {"diff": _dump(compare_artifact_versions(project_id=project_id, artifact_id=artifact_id, from_version=from_version, to_version=to_version, adapter=storage_adapter()))}


@router.post("/{project_id}/artifacts/{artifact_id}/restore")
@domain_errors
def restore(project_id: str, artifact_id: str, req: RestoreRequest, principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    result = restore_artifact_version(project_id=project_id, artifact_id=artifact_id, version=req.version, actor=principal.user_id,
                                      expected_version=req.expected_version, adapter=storage_adapter())
    return {**result, "artifact": _dump(result["artifact"])}


@router.post("/{project_id}/artifacts/{artifact_id}/branch", status_code=201)
@domain_errors
def branch(project_id: str, artifact_id: str, req: BranchRequest, principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    return {"artifact": _dump(branch_artifact(project_id=project_id, artifact_id=artifact_id, actor=principal.user_id, branch_key=req.branch_key,
                                              adapter=storage_adapter(), v2=req.v2, content_text=req.content_text))}


@router.post("/{project_id}/artifacts/{artifact_id}/merge")
@domain_errors
def merge(project_id: str, artifact_id: str, req: MergeRequest, principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    result = merge_branch(project_id=project_id, branch_id=req.branch_id, into_id=artifact_id, actor=principal.user_id,
                          expected_version=req.expected_version, adapter=storage_adapter(), replace_master=req.replace_master)
    return {**result, "artifact": _dump(result["artifact"])}


@router.post("/{project_id}/artifacts/{artifact_id}/comments", status_code=201)
@domain_errors
def comment(project_id: str, artifact_id: str, req: CommentRequest, principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    return {"comment": add_artifact_comment(project_id=project_id, artifact_id=artifact_id, version_ref=req.version_ref, author=principal.user_id, body=req.body)}


@router.post("/{project_id}/artifacts/{artifact_id}/edit-requests", status_code=201)
@domain_errors
def edit_request(project_id: str, artifact_id: str, req: EditRequest, principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    return {"edit_request": request_artifact_edit(project_id=project_id, artifact_id=artifact_id, base_version_ref=req.base_version_ref,
                                                  instruction=req.instruction, actor=principal.user_id)}


@router.get("/{project_id}/edit-requests")
@domain_errors
def edit_requests(project_id: str, status: Optional[str] = None, principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    return {"edit_requests": list_edit_requests(project_id, status=status)}


@router.post("/{project_id}/artifacts/{artifact_id}/rights", status_code=201)
@domain_errors
def add_rights(project_id: str, artifact_id: str, req: RightsRequest, principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    return {"rights": _dump(register_asset_rights(project_id=project_id, artifact_id=artifact_id, **req.model_dump()))}


@router.get("/{project_id}/rights")
@domain_errors
def rights(project_id: str, within_days: int = Query(default=30, ge=1, le=365), principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    return {"rights": _dump(list_asset_rights(project_id)), "radar": rights_expiration_radar(project_id, within_days=within_days)}


@router.post("/{project_id}/uploads", status_code=201)
@domain_errors
def upload(project_id: str, req: UploadRequest, principal: Principal = Depends(get_principal)):
    workspace = authorize_project_access(principal, project_id)
    try:
        data = base64.b64decode(req.content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=422, detail="content_base64 is not valid base64") from exc
    return {"artifact": _dump(upload_media(tenant_id=workspace.tenant_id, project_id=project_id, actor=principal.user_id,
                                           artifact_key=req.artifact_key, data=data, adapter=storage_adapter(), v2=req.v2))}


# --------------------------------------------------------------------------
# Prompt ledger
# --------------------------------------------------------------------------


@router.get("/{project_id}/prompts")
@domain_errors
def prompts(project_id: str, all_versions: bool = False, principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    return {"prompts": list_prompts(project_id, latest_only=not all_versions)}


@router.post("/{project_id}/prompts", status_code=201)
@domain_errors
def add_prompt(project_id: str, req: PromptRequest, principal: Principal = Depends(get_principal)):
    workspace = authorize_project_access(principal, project_id)
    return record_prompt(tenant_id=workspace.tenant_id, project_id=project_id, actor=principal.user_id, department=req.department,
                         body=req.body, prompt_id=req.prompt_id, artifact_target=req.artifact_target, family=req.family,
                         campaign_id=req.campaign_id, status=req.status)


# --------------------------------------------------------------------------
# Workstreams, video, brand, paid media
# --------------------------------------------------------------------------


@router.get("/{project_id}/workstreams")
@domain_errors
def workstreams(project_id: str, principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    existing = [item.model_dump(mode="json") for item in list_project_artifacts(project_id, limit=1000)]
    return {"workstreams": {kind: plan_workstream(kind, existing) for kind in sorted(WORKSTREAMS)}}


@router.get("/{project_id}/workstreams/{kind}")
@domain_errors
def workstream(project_id: str, kind: str, principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    existing = [item.model_dump(mode="json") for item in list_project_artifacts(project_id, limit=1000)]
    return plan_workstream(kind, existing)


@router.post("/{project_id}/video/plan")
@domain_errors
def video_plan(project_id: str, req: VideoPlanRequest, principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    return plan_video_production(req.cinematic_request, aspect=req.aspect, duration=req.duration, seed=req.seed)


def _video_ingest_root() -> Path:
    from services.langgraph.agency.exporter import resolve_export_root

    configured = (os.environ.get("AMC_VIDEO_INGEST_ROOT") or "").strip()
    return Path(configured) if configured else resolve_export_root() / "freevideoforge"


@router.post("/{project_id}/video/ingest", status_code=201)
@domain_errors
def video_ingest(project_id: str, req: VideoIngestRequest, principal: Principal = Depends(get_principal)):
    workspace = authorize_project_access(principal, project_id)
    root = _video_ingest_root().resolve()
    target = Path(req.output_dir).resolve()
    if target != root and root not in target.parents:
        # Never read an arbitrary server path on a client's say-so.
        raise HTTPException(status_code=400, detail="output_dir must be inside the configured video ingest root")
    return ingest_video_run(tenant_id=workspace.tenant_id, project_id=project_id, actor=principal.user_id, output_dir=target,
                            adapter=storage_adapter(), campaign_id=req.campaign_id)


@router.post("/{project_id}/brand-drift")
@domain_errors
def brand_drift(project_id: str, req: BrandFactsRequest, principal: Principal = Depends(get_principal)):
    workspace = authorize_project_access(principal, project_id)
    facts = BrandFacts(palette=tuple(req.palette), banned_terms=tuple(req.banned_terms), deprecated_names=req.deprecated_names,
                       current_prices=tuple(req.current_prices), brand_core_ref=req.brand_core_ref)
    report = analyze(project_id=project_id, tenant_id=workspace.tenant_id, facts=facts, subjects=collect_drift_subjects(project_id, storage_adapter()))
    return {"report": _dump(report)}


@router.post("/{project_id}/paid-media/plan")
@domain_errors
def paid_media_plan(project_id: str, req: PaidPlanRequest, principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    mode = (os.environ.get("AMC_PAID_MEDIA_MODE") or "disabled").strip().lower()
    brief = PaidMediaBrief(
        objective=req.objective, offer=req.offer, audiences=tuple(req.audiences), channels=tuple(req.channels),
        budget_minor=req.budget_minor, currency=req.currency, flight_days=req.flight_days, creative_refs=tuple(req.creative_refs),
        landing_page_ref=req.landing_page_ref, keywords=tuple(req.keywords),
    )
    return {"plan": plan_campaign(brief, paid_media_mode=mode),
            "status": CapabilityStatus.IMPLEMENTED_FAIL_CLOSED.value}


@router.get("/{project_id}/capabilities")
@domain_errors
def project_capabilities(project_id: str, principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    from services.langgraph.agency.project_os.publishing import provider_capabilities

    adapter = storage_adapter()
    return {
        "object_storage": adapter.status(),
        "publication": provider_capabilities(),
        "video_renderer": freevideoforge_capability(),
        "paid_media": {"status": CapabilityStatus.IMPLEMENTED_FAIL_CLOSED.value, "execution_available": False},
    }
