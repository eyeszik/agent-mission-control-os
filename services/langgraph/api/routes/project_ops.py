"""Conversations, content operations, calendar, scheduler and publishing."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from services.langgraph.agency.project_os.calendar import ForecastInput, forecast_supply
from services.langgraph.agency.project_os.content import exhaustion_map, derive_variant
from services.langgraph.agency.project_os.models import ScheduleCadence
from services.langgraph.agency.project_os.publishing import provider_capabilities
from services.langgraph.agency.project_os.vocabulary import ActivityType, ContentKind, ContentState
from services.langgraph.api.routes._project_common import authorize_project_access, domain_errors, storage_adapter
from services.langgraph.persistence.project_ops import (
    create_calendar,
    create_content_item_from_atom,
    create_thread,
    get_content_atom,
    get_content_item,
    list_calendars,
    list_content_atoms,
    list_content_items,
    list_jobs,
    list_messages,
    list_publication_attempts,
    list_publication_receipts,
    list_slots,
    list_threads,
    plan_calendar,
    post_message,
    revise_content_item,
    run_scheduler_tick,
    save_content_atom,
    schedule_content_item,
    schedule_journey,
    schedule_refresh,
    transition_content_item,
)
from services.langgraph.persistence.projects import ProjectNotFoundError
from services.langgraph.security.approval_authority import assert_may_decide
from services.langgraph.security.auth import Principal, get_principal

router = APIRouter()


def _dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_dump(item) for item in value]
    return value


class ThreadRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    campaign_id: Optional[str] = None


class ArtifactRefInput(BaseModel):
    artifact_id: str
    version_ref: Optional[str] = None
    relation: Literal["created", "updated", "referenced", "variant", "preview"] = "referenced"


class MessageRequest(BaseModel):
    body: str = Field(min_length=1, max_length=20_000)
    activity_type: ActivityType = ActivityType.MESSAGE
    artifact_refs: list[ArtifactRefInput] = Field(default_factory=list, max_length=20)


class ClaimInput(BaseModel):
    claim_id: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=2000)
    evidence_refs: list[str] = Field(default_factory=list)
    verification: Literal["VERIFIED", "UNVERIFIED", "CONTRADICTED"]


class AtomRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    claims: list[ClaimInput] = Field(min_length=1, max_length=100)
    source_refs: list[str] = Field(default_factory=list)
    atom_id: Optional[str] = None
    campaign_id: Optional[str] = None


class ContentItemRequest(BaseModel):
    atom_id: str
    kind: ContentKind
    channel: str = Field(min_length=1, max_length=40)
    campaign_id: Optional[str] = None
    evidence_fresh_until: Optional[str] = None


class TransitionRequest(BaseModel):
    target: ContentState
    expected_version: Optional[int] = Field(default=None, ge=1)


class ReviseItemRequest(BaseModel):
    expected_version: int = Field(ge=1)
    body_patch: dict[str, Any]


class ScheduleRequest(BaseModel):
    scheduled_for: Optional[str] = None
    slot_id: Optional[str] = None


class RefreshRequest(BaseModel):
    due_at: str


class CalendarRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    timezone: str = "UTC"


class PlanRequest(BaseModel):
    horizon_days: Literal[14, 30, 90, 182, 365]
    cadences: list[ScheduleCadence] = Field(min_length=1, max_length=50)
    start: Optional[str] = None


class JourneyStep(BaseModel):
    content_item_id: str
    delay_days: float = Field(ge=0, le=730)
    channel: Optional[str] = None
    trigger: Literal["time", "behavior"] = "time"


class JourneyRequest(BaseModel):
    journey: Literal[
        "welcome", "onboarding", "education", "abandoned_cart", "purchase", "post_purchase", "cross_sell", "upsell",
        "retention", "win_back", "referral", "renewal", "feedback", "customer_success",
    ]
    start: Optional[str] = None
    steps: list[JourneyStep] = Field(min_length=1, max_length=50)


class ForecastRequest(BaseModel):
    horizon_days: Literal[14, 30, 90, 182, 365]
    cadences: list[ScheduleCadence] = Field(min_length=1)
    brands: int = Field(default=1, ge=1, le=200)
    campaigns: int = Field(default=1, ge=1, le=500)
    approval_batch_size: int = Field(default=10, ge=1, le=500)
    research_refresh_days: int = Field(default=30, ge=1, le=365)
    unit_costs: dict[str, float] = Field(default_factory=dict)


# --------------------------------------------------------------------------
# Conversations
# --------------------------------------------------------------------------


@router.get("/{project_id}/threads")
@domain_errors
def threads(project_id: str, principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    return {"threads": _dump(list_threads(project_id))}


@router.post("/{project_id}/threads", status_code=201)
@domain_errors
def new_thread(project_id: str, req: ThreadRequest, principal: Principal = Depends(get_principal)):
    workspace = authorize_project_access(principal, project_id)
    return {"thread": _dump(create_thread(tenant_id=workspace.tenant_id, project_id=project_id, actor=principal.user_id, title=req.title, campaign_id=req.campaign_id))}


@router.get("/{project_id}/threads/{thread_id}/messages")
@domain_errors
def messages(project_id: str, thread_id: str, principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    found = [t for t in list_threads(project_id) if t.thread_id == thread_id]
    if not found:
        raise ProjectNotFoundError("thread not found in project")
    return {"messages": _dump(list_messages(thread_id))}


@router.post("/{project_id}/threads/{thread_id}/messages", status_code=201)
@domain_errors
def new_message(project_id: str, thread_id: str, req: MessageRequest, principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    message = post_message(
        thread_id=thread_id, project_id=project_id, author=principal.user_id, body=req.body, role="user",
        activity_type=req.activity_type, artifact_refs=[ref.model_dump() for ref in req.artifact_refs],
    )
    return {"message": _dump(message)}


# --------------------------------------------------------------------------
# Content
# --------------------------------------------------------------------------


@router.get("/{project_id}/content/atoms")
@domain_errors
def atoms(project_id: str, principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    return {"atoms": _dump(list_content_atoms(project_id))}


@router.post("/{project_id}/content/atoms", status_code=201)
@domain_errors
def save_atom(project_id: str, req: AtomRequest, principal: Principal = Depends(get_principal)):
    workspace = authorize_project_access(principal, project_id)
    result = save_content_atom(
        tenant_id=workspace.tenant_id, project_id=project_id, actor=principal.user_id, title=req.title,
        claims=[claim.model_dump() for claim in req.claims], source_refs=req.source_refs, atom_id=req.atom_id, campaign_id=req.campaign_id,
    )
    return {"atom": _dump(result["atom"]), "created": result["created"]}


@router.get("/{project_id}/content/atoms/{atom_id}/exhaustion")
@domain_errors
def atom_exhaustion(project_id: str, atom_id: str, principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    atom = get_content_atom(atom_id)
    if atom is None or atom.project_id != project_id:
        raise ProjectNotFoundError("atom not found in project")
    produced = [derive_variant(atom, item.kind, item.channel) for item in list_content_items(project_id) if item.atom_id == atom_id]
    return exhaustion_map(atom, produced)


@router.get("/{project_id}/content/items")
@domain_errors
def items(project_id: str, state: Optional[ContentState] = None, principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    return {"items": _dump(list_content_items(project_id, state=state.value if state else None))}


@router.post("/{project_id}/content/items", status_code=201)
@domain_errors
def new_item(project_id: str, req: ContentItemRequest, principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    item = create_content_item_from_atom(
        project_id=project_id, actor=principal.user_id, atom_id=req.atom_id, kind=req.kind.value, channel=req.channel,
        adapter=storage_adapter(), campaign_id=req.campaign_id, evidence_fresh_until=req.evidence_fresh_until,
    )
    return {"item": _dump(item)}


@router.post("/{project_id}/content/items/{item_id}/transition")
@domain_errors
def transition(project_id: str, item_id: str, req: TransitionRequest, principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    item = get_content_item(item_id)
    if item is None or item.project_id != project_id:
        raise ProjectNotFoundError("content item not found in project")
    if req.target is ContentState.APPROVED:
        assert_may_decide(principal, item.created_by, "approve", subject="content item")
    elif item.state is ContentState.REVIEW and req.target is ContentState.IN_PRODUCTION:
        assert_may_decide(principal, item.created_by, "reject", subject="content item")
    return {"item": _dump(transition_content_item(project_id=project_id, item_id=item_id, target=req.target.value, actor=principal.user_id,
                                                  expected_version=req.expected_version))}


@router.post("/{project_id}/content/items/{item_id}/revise")
@domain_errors
def revise_item(project_id: str, item_id: str, req: ReviseItemRequest, principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    return {"item": _dump(revise_content_item(project_id=project_id, item_id=item_id, actor=principal.user_id,
                                              expected_version=req.expected_version, body_patch=req.body_patch, adapter=storage_adapter()))}


@router.post("/{project_id}/content/items/{item_id}/schedule", status_code=201)
@domain_errors
def schedule(project_id: str, item_id: str, req: ScheduleRequest, principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    return {"job": _dump(schedule_content_item(project_id=project_id, item_id=item_id, actor=principal.user_id,
                                               scheduled_for=req.scheduled_for, slot_id=req.slot_id))}


@router.post("/{project_id}/content/items/{item_id}/refresh", status_code=201)
@domain_errors
def refresh(project_id: str, item_id: str, req: RefreshRequest, principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    return {"job": _dump(schedule_refresh(project_id=project_id, item_id=item_id, due_at=req.due_at))}


# --------------------------------------------------------------------------
# Calendar + scheduler
# --------------------------------------------------------------------------


@router.get("/{project_id}/calendars")
@domain_errors
def calendars(project_id: str, principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    return {"calendars": _dump(list_calendars(project_id))}


@router.post("/{project_id}/calendars", status_code=201)
@domain_errors
def new_calendar(project_id: str, req: CalendarRequest, principal: Principal = Depends(get_principal)):
    workspace = authorize_project_access(principal, project_id)
    return {"calendar": _dump(create_calendar(tenant_id=workspace.tenant_id, project_id=project_id, name=req.name, timezone_name=req.timezone))}


@router.post("/{project_id}/calendars/{calendar_id}/plan", status_code=201)
@domain_errors
def plan(project_id: str, calendar_id: str, req: PlanRequest, principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    start = datetime.fromisoformat(req.start) if req.start else datetime.now(timezone.utc)
    slots = plan_calendar(project_id=project_id, calendar_id=calendar_id, horizon_days=req.horizon_days, cadences=req.cadences, start=start)
    return {"created_slots": len(slots), "slots": _dump(slots)}


@router.get("/{project_id}/calendar")
@domain_errors
def calendar_view(project_id: str, start: Optional[str] = None, end: Optional[str] = None, calendar_id: Optional[str] = None, principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    return {
        "slots": _dump(list_slots(project_id, calendar_id=calendar_id, start=start, end=end)),
        "jobs": _dump(list_jobs(project_id)),
        "items": _dump(list_content_items(project_id)),
    }


@router.post("/{project_id}/journeys", status_code=201)
@domain_errors
def journey(project_id: str, req: JourneyRequest, principal: Principal = Depends(get_principal)):
    workspace = authorize_project_access(principal, project_id)
    start = datetime.fromisoformat(req.start) if req.start else datetime.now(timezone.utc)
    jobs = schedule_journey(tenant_id=workspace.tenant_id, project_id=project_id, journey=req.journey, start=start,
                            steps=[step.model_dump() for step in req.steps])
    return {"jobs": _dump(jobs)}


@router.post("/{project_id}/forecast")
@domain_errors
def forecast(project_id: str, req: ForecastRequest, principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    return forecast_supply(ForecastInput(
        horizon_days=req.horizon_days, cadences=tuple(req.cadences), brands=req.brands, campaigns=req.campaigns,
        approval_batch_size=req.approval_batch_size, research_refresh_days=req.research_refresh_days, unit_costs=req.unit_costs,
    ))


@router.post("/{project_id}/scheduler/tick")
@domain_errors
def tick(project_id: str, limit: int = Query(default=50, ge=1, le=500), principal: Principal = Depends(get_principal)):
    """Process this project's due jobs now. Time is server time, never client input."""
    authorize_project_access(principal, project_id)
    return run_scheduler_tick(now=datetime.now(timezone.utc), worker_id=f"api:{principal.user_id}", project_id=project_id, limit=limit)


@router.get("/{project_id}/publications")
@domain_errors
def publications(project_id: str, content_item_id: Optional[str] = None, principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    attempts = list_publication_attempts(project_id, content_item_id=content_item_id)
    return {
        "capabilities": provider_capabilities(),
        "attempts": [{**_dump(a), "receipts": _dump(list_publication_receipts(a.attempt_id))} for a in attempts],
    }
