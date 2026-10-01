"""Portfolio, memory, KnowledgeOps, provider routing, growth and learning."""

from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from services.langgraph.agency.project_os.knowledge import SourceDocument
from services.langgraph.agency.project_os.models import ObservedMetric
from services.langgraph.agency.project_os.reliability import reliability_contracts
from services.langgraph.agency.project_os.router import RouteRequest, route
from services.langgraph.agency.project_os.vocabulary import (
    PROJECT_OS_VERSION,
    CapabilityStatus,
    MemoryAuthority,
    MemoryScope,
    ProviderMode,
    RightsClass,
)
from services.langgraph.api.routes._project_common import authorize_project_access, domain_errors, require_approver
from services.langgraph.persistence.portfolio import portfolio_view
from services.langgraph.persistence.project_knowledge import (
    advance_promotion,
    append_learning_signal,
    collect_project_learning,
    conclude_experiment,
    create_experiment,
    ingest_knowledge,
    list_experiments,
    list_knowledge,
    list_learning_signals,
    list_memory,
    list_provider_profiles,
    promote_memory,
    resolve_memory,
    review_knowledge,
    start_promotion,
    upsert_provider_profile,
    write_memory,
)
from services.langgraph.security.approval_authority import approver_roles
from services.langgraph.security.auth import Principal, get_principal

router = APIRouter()

# Writing these authority classes is itself a decision about canon.
_APPROVER_AUTHORITIES = {MemoryAuthority.BRAND_CANON, MemoryAuthority.APPROVED_PROJECT_DECISION}


def _dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_dump(item) for item in value]
    return value


class MemoryRequest(BaseModel):
    scope: MemoryScope
    authority: MemoryAuthority
    subject_key: str = Field(min_length=1, max_length=200)
    body: dict[str, Any]
    thread_id: Optional[str] = None
    source_refs: list[str] = Field(default_factory=list)
    fresh_until: Optional[str] = None


class PromoteMemoryRequest(BaseModel):
    to_authority: MemoryAuthority


class KnowledgeRequest(BaseModel):
    domain: str = Field(min_length=1, max_length=60)
    source_uri: str = Field(min_length=1, max_length=2000)
    text: str = Field(min_length=1, max_length=200_000)
    license: Optional[str] = None
    rights_declared: Optional[RightsClass] = None
    published_at: Optional[str] = None
    fetched_at: Optional[str] = None


class ReviewRequest(BaseModel):
    accept: bool


class ProfileRequest(BaseModel):
    provider: str
    model: str
    task: str
    formats: list[str] = Field(min_length=1)
    locality: Literal["local", "cloud"]
    cost_per_unit: ObservedMetric
    latency_p95_ms: ObservedMetric
    acceptance_rate: ObservedMetric
    failure_rate: ObservedMetric
    rights_constraints: list[str] = Field(default_factory=list)
    benchmark_refs: list[str] = Field(default_factory=list)
    last_verified_at: Optional[str] = None
    mode: ProviderMode = ProviderMode.DISABLED


class RouteRequestBody(BaseModel):
    task: str
    output_format: str
    reusable_approved_asset_ref: Optional[str] = None
    deterministic_transform: bool = False
    premium_justification: Optional[str] = None
    max_failure_rate: float = Field(default=0.25, ge=0.0, le=1.0)


class ExperimentRequest(BaseModel):
    hypothesis: str = Field(min_length=1, max_length=1000)
    target_metric: str = Field(min_length=1, max_length=120)
    segment: str = "all"
    intervention: str = Field(min_length=1, max_length=1000)
    asset_refs: list[str] = Field(default_factory=list)
    start_at: Optional[str] = None
    end_at: Optional[str] = None
    sample_requirement: int = Field(ge=1)


class ConcludeRequest(BaseModel):
    sample_size: int = Field(ge=0)
    lift: Optional[float] = None
    evidence_ref: str = Field(min_length=1)
    notes: Optional[str] = None


class SignalRequest(BaseModel):
    observation: str = Field(min_length=1, max_length=2000)
    evidence_refs: list[str] = Field(default_factory=list)
    target_heuristic: str
    run_refs: list[str] = Field(default_factory=list)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class PromotionRequest(BaseModel):
    signal_id: str


class AdvanceRequest(BaseModel):
    evidence: dict[str, Any]


# --------------------------------------------------------------------------
# Portfolio + platform status
# --------------------------------------------------------------------------


@router.get("/portfolio")
@domain_errors
def portfolio(principal: Principal = Depends(get_principal)):
    allowed = None if "*" in principal.allowed_project_ids else principal.allowed_project_ids
    return portfolio_view(tenant_id=principal.tenant_id, allowed_project_ids=allowed)


@router.get("/project-os/status")
def project_os_status(principal: Principal = Depends(get_principal)):
    return {
        "version": PROJECT_OS_VERSION,
        "tenant_id": principal.tenant_id,
        "capabilities": {
            "project_workspaces": CapabilityStatus.IMPLEMENTED.value,
            "artifact_graph_v2": CapabilityStatus.IMPLEMENTED.value,
            "object_storage_local": CapabilityStatus.LOCAL_ONLY.value,
            "object_storage_r2": CapabilityStatus.EXTERNAL_ACTIVATION_REQUIRED.value,
            "conversations": CapabilityStatus.IMPLEMENTED.value,
            "content_operations": CapabilityStatus.IMPLEMENTED.value,
            "calendar_scheduler": CapabilityStatus.IMPLEMENTED.value,
            "publication": CapabilityStatus.DRY_RUN_ONLY.value,
            "paid_media": CapabilityStatus.IMPLEMENTED_FAIL_CLOSED.value,
            "memory": CapabilityStatus.IMPLEMENTED.value,
            "knowledge_ops": CapabilityStatus.IMPLEMENTED.value,
            "knowledge_fetching": CapabilityStatus.NOT_AVAILABLE.value,
            "video_render": CapabilityStatus.LOCAL_ONLY.value,
            "provider_routing": CapabilityStatus.IMPLEMENTED.value,
            "brand_stewardship": CapabilityStatus.IMPLEMENTED.value,
            "portfolio": CapabilityStatus.IMPLEMENTED.value,
            "learning_governance": CapabilityStatus.IMPLEMENTED.value,
            "crm_sending": CapabilityStatus.DRY_RUN_ONLY.value,
        },
        "reliability": reliability_contracts(),
    }


# --------------------------------------------------------------------------
# Memory
# --------------------------------------------------------------------------


@router.get("/projects/{project_id}/memory")
@domain_errors
def project_memory(project_id: str, scope: Optional[MemoryScope] = None, principal: Principal = Depends(get_principal)):
    workspace = authorize_project_access(principal, project_id)
    return {"memory": _dump(list_memory(tenant_id=workspace.tenant_id, project_id=project_id, scope=scope.value if scope else None))}


@router.post("/projects/{project_id}/memory", status_code=201)
@domain_errors
def add_memory(project_id: str, req: MemoryRequest, principal: Principal = Depends(get_principal)):
    workspace = authorize_project_access(principal, project_id)
    if req.scope is MemoryScope.M0_AGENCY:
        raise HTTPException(status_code=422, detail="agency (M0) memory is written through /agency-memory, not a project")
    if req.authority in _APPROVER_AUTHORITIES:
        require_approver(principal, f"Writing {req.authority.value} memory")
    result = write_memory(
        tenant_id=workspace.tenant_id, actor=principal.user_id, scope=req.scope.value, authority=req.authority.value,
        subject_key=req.subject_key, body=req.body, project_id=project_id, thread_id=req.thread_id,
        source_refs=req.source_refs, fresh_until=req.fresh_until,
    )
    return {**result, "memory": _dump(result["memory"])}


@router.get("/projects/{project_id}/memory/resolve")
@domain_errors
def memory_resolve(project_id: str, subject_key: str = Query(min_length=1), principal: Principal = Depends(get_principal)):
    workspace = authorize_project_access(principal, project_id)
    return resolve_memory(tenant_id=workspace.tenant_id, project_id=project_id, subject_key=subject_key)


@router.post("/projects/{project_id}/memory/{memory_id}/promote")
@domain_errors
def memory_promote(project_id: str, memory_id: str, req: PromoteMemoryRequest, principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    require_approver(principal, "Promoting memory")
    return {"memory": _dump(promote_memory(memory_id=memory_id, to_authority=req.to_authority.value, actor=principal.user_id, project_id=project_id))}


@router.get("/agency-memory")
@domain_errors
def agency_memory(principal: Principal = Depends(get_principal)):
    return {"memory": _dump(list_memory(tenant_id=principal.tenant_id, project_id=None, scope="M0_AGENCY"))}


@router.post("/agency-memory", status_code=201)
@domain_errors
def add_agency_memory(req: MemoryRequest, principal: Principal = Depends(get_principal)):
    if req.scope is not MemoryScope.M0_AGENCY:
        raise HTTPException(status_code=422, detail="only M0_AGENCY memory is tenant-wide")
    require_approver(principal, "Writing agency-wide memory")
    result = write_memory(tenant_id=principal.tenant_id, actor=principal.user_id, scope=req.scope.value, authority=req.authority.value,
                          subject_key=req.subject_key, body=req.body, source_refs=req.source_refs, fresh_until=req.fresh_until)
    return {**result, "memory": _dump(result["memory"])}


# --------------------------------------------------------------------------
# KnowledgeOps
# --------------------------------------------------------------------------


@router.post("/projects/{project_id}/knowledge", status_code=201)
@domain_errors
def add_knowledge(project_id: str, req: KnowledgeRequest, principal: Principal = Depends(get_principal)):
    workspace = authorize_project_access(principal, project_id)
    document = SourceDocument(**req.model_dump())
    return {"item": _dump(ingest_knowledge(tenant_id=workspace.tenant_id, document=document, project_id=project_id))}


@router.get("/projects/{project_id}/knowledge")
@domain_errors
def knowledge(project_id: str, status: Optional[str] = None, principal: Principal = Depends(get_principal)):
    workspace = authorize_project_access(principal, project_id)
    return {"items": _dump(list_knowledge(tenant_id=workspace.tenant_id, project_id=project_id, status=status))}


@router.post("/projects/{project_id}/knowledge/{item_id}/review")
@domain_errors
def knowledge_review(project_id: str, item_id: str, req: ReviewRequest, principal: Principal = Depends(get_principal)):
    workspace = authorize_project_access(principal, project_id)
    require_approver(principal, "Reviewing knowledge for promotion")
    return review_knowledge(item_id=item_id, tenant_id=workspace.tenant_id, project_id=project_id, reviewer=principal.user_id, accept=req.accept)


# --------------------------------------------------------------------------
# Provider routing
# --------------------------------------------------------------------------


@router.get("/providers/profiles")
@domain_errors
def profiles(task: Optional[str] = None, principal: Principal = Depends(get_principal)):
    return {"profiles": _dump(list_provider_profiles(principal.tenant_id, task=task))}


@router.post("/providers/profiles", status_code=201)
@domain_errors
def add_profile(req: ProfileRequest, principal: Principal = Depends(get_principal)):
    require_approver(principal, "Registering provider profiles")
    if req.mode is ProviderMode.LIVE:
        raise HTTPException(status_code=409, detail="profiles cannot be registered LIVE; provider activation is a reviewed code change")
    return {"profile": _dump(upsert_provider_profile(tenant_id=principal.tenant_id, profile=req.model_dump(mode="json")))}


@router.post("/providers/route")
@domain_errors
def route_task(req: RouteRequestBody, principal: Principal = Depends(get_principal)):
    return route(RouteRequest(**req.model_dump()), list_provider_profiles(principal.tenant_id, task=req.task))


# --------------------------------------------------------------------------
# Growth experiments
# --------------------------------------------------------------------------


@router.get("/projects/{project_id}/experiments")
@domain_errors
def experiments(project_id: str, principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    return {"experiments": _dump(list_experiments(project_id))}


@router.post("/projects/{project_id}/experiments", status_code=201)
@domain_errors
def add_experiment(project_id: str, req: ExperimentRequest, principal: Principal = Depends(get_principal)):
    workspace = authorize_project_access(principal, project_id)
    return {"experiment": _dump(create_experiment(tenant_id=workspace.tenant_id, project_id=project_id, spec=req.model_dump()))}


@router.post("/projects/{project_id}/experiments/{experiment_id}/conclude")
@domain_errors
def conclude(project_id: str, experiment_id: str, req: ConcludeRequest, principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    return {"experiment": _dump(conclude_experiment(project_id=project_id, experiment_id=experiment_id, observed=req.model_dump(), actor=principal.user_id))}


# --------------------------------------------------------------------------
# Learning
# --------------------------------------------------------------------------


@router.get("/learning/signals")
@domain_errors
def signals(principal: Principal = Depends(get_principal)):
    return list_learning_signals(principal.tenant_id)


@router.post("/learning/signals", status_code=201)
@domain_errors
def add_signal(req: SignalRequest, principal: Principal = Depends(get_principal)):
    return append_learning_signal(tenant_id=principal.tenant_id, observation=req.observation, evidence_refs=req.evidence_refs,
                                  target_heuristic=req.target_heuristic, run_refs=req.run_refs, confidence=req.confidence)


@router.post("/learning/promotions", status_code=201)
@domain_errors
def new_promotion(req: PromotionRequest, principal: Principal = Depends(get_principal)):
    return {"promotion": start_promotion(tenant_id=principal.tenant_id, signal_id=req.signal_id)}


@router.post("/learning/promotions/{promotion_id}/advance")
@domain_errors
def advance(promotion_id: str, req: AdvanceRequest, principal: Principal = Depends(get_principal)):
    is_approver = principal.role.strip().lower() in approver_roles()
    return {"promotion": advance_promotion(tenant_id=principal.tenant_id, promotion_id=promotion_id, evidence=req.evidence,
                                           actor=principal.user_id, actor_is_approver=is_approver)}


@router.get("/projects/{project_id}/learning/post-mortem")
@domain_errors
def post_mortem(project_id: str, principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    return collect_project_learning(project_id)
