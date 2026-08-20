from datetime import datetime
from typing import List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from services.langgraph.graph.agency.build import AGENCY_PIPELINE_STAGES, build_agency_workflow
from services.langgraph.graph.models import AgentRun
from services.langgraph.persistence.approvals import get_approvals_for_run
from services.langgraph.persistence.events import record_event
from services.langgraph.persistence.idempotency import record_idempotency, verify_idempotency
from services.langgraph.persistence.runs import create_run_record, get_run_record, update_run_status
from services.langgraph.security.auth import Principal, authorize_project, authorize_resource, get_principal
from services.langgraph.security.pii import quarantine_payload
from services.langgraph.security.preprocess import sanitize_deep

router = APIRouter()

PIPELINE_NAME = "branding_marketing_agency"


class CampaignBriefRequest(BaseModel):
    brand_name: str
    industry: Optional[str] = None
    goals: List[str] = Field(default_factory=list)
    target_audience: str
    tone: Optional[str] = None
    channels: List[str] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list)


class CreateAgencyRunRequest(BaseModel):
    # Deprecated compatibility field. It is never authoritative; the server
    # principal supplies tenant identity and a mismatch is denied.
    tenant_id: Optional[str] = None
    project_id: str
    brief: CampaignBriefRequest


def _run_config(run_id: str) -> dict:
    return {"configurable": {"thread_id": run_id}}


def _agency_payload(state: dict) -> dict:
    return (state.get("extracted_data") or {}).get("agency", {}) if state else {}


def _safe_brief(req: CreateAgencyRunRequest) -> dict:
    sanitized = sanitize_deep(req.brief.model_dump())
    return quarantine_payload(sanitized)


def _run_and_record_events(graph, input_state, config: dict, run_id: str) -> dict:
    # This remains history recording rather than genuine live progress. The
    # event model is hardened separately; do not synthesize timing claims here.
    for step in graph.stream(input_state, config=config, stream_mode="updates"):
        for node_id, _delta in step.items():
            if node_id == "__interrupt__":
                continue
            record_event(run_id, node_id, "node_start")
            record_event(run_id, node_id, "node_complete")

    snapshot = graph.get_state(config)
    return dict(snapshot.values) if snapshot and snapshot.values else {}


def _authorize_run(principal: Principal, record: dict) -> None:
    authorize_resource(principal, record["tenant_id"], record["project_id"])


@router.post("/runs", status_code=201)
def create_agency_run(
    req: CreateAgencyRunRequest,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(get_principal),
):
    """Create an agency run using only server-derived tenant identity."""

    authorize_project(principal, req.project_id)
    if req.tenant_id is not None and req.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=403, detail="tenant_id does not match authenticated principal")

    if idempotency_key and verify_idempotency(idempotency_key):
        raise HTTPException(status_code=409, detail="Request already processed for this idempotency key")

    run_id = str(uuid4())
    now = datetime.utcnow()

    # Security invariant: only sanitized/redacted input crosses the persistence
    # and checkpoint boundary. The raw request object is never placed in AgentRun.
    safe_brief = _safe_brief(req)
    metadata = {"input_data": {"brief": safe_brief}}

    run = AgentRun(
        id=run_id,
        tenant_id=principal.tenant_id,
        project_id=req.project_id,
        status="running",
        created_at=now,
        updated_at=now,
        metadata=metadata,
    )
    create_run_record(run_id, principal.tenant_id, req.project_id, PIPELINE_NAME, "running", metadata)

    graph = build_agency_workflow()
    config = _run_config(run_id)
    initial_state = {
        "run": run,
        "current_node": "start",
        "messages": [],
        "extracted_data": {},
        "validation_status": "pending",
    }

    try:
        state = _run_and_record_events(graph, initial_state, config, run_id)
    except Exception as exc:
        update_run_status(run_id, "failed", {"error": str(exc)})
        raise HTTPException(status_code=500, detail="Agency pipeline failed") from exc

    agency_data = _agency_payload(state)
    record = update_run_status(run_id, "needs_approval", {"agency": agency_data})

    if idempotency_key:
        record_idempotency(idempotency_key, {"run_id": run_id})

    run_approvals = get_approvals_for_run(run_id)

    return {
        "run_id": run_id,
        "status": record["status"],
        "pipeline": PIPELINE_NAME,
        "stages": AGENCY_PIPELINE_STAGES,
        "campaign_package": agency_data.get("campaign_package"),
        "qa_report": agency_data.get("qa_report"),
        "pending_approval": run_approvals[0] if run_approvals else None,
    }


@router.get("/runs/{run_id}")
def get_agency_run(run_id: str, principal: Principal = Depends(get_principal)):
    record = get_run_record(run_id)
    if not record:
        raise HTTPException(status_code=404, detail="Run not found")
    _authorize_run(principal, record)

    graph = build_agency_workflow()
    snapshot = graph.get_state(_run_config(run_id))
    agency_data = _agency_payload(dict(snapshot.values)) if snapshot and snapshot.values else {}

    return {
        "run_id": run_id,
        "status": record["status"],
        "pipeline": record["pipeline"],
        "stages": AGENCY_PIPELINE_STAGES,
        "pending_next_node": list(snapshot.next) if snapshot else [],
        "campaign_package": agency_data.get("campaign_package"),
        "qa_report": agency_data.get("qa_report"),
        "delivery": agency_data.get("delivery"),
        "approvals": get_approvals_for_run(run_id),
    }


@router.post("/runs/{run_id}/resume")
def resume_agency_run(run_id: str, principal: Principal = Depends(get_principal)):
    record = get_run_record(run_id)
    if not record:
        raise HTTPException(status_code=404, detail="Run not found")
    _authorize_run(principal, record)

    if record["status"] == "completed":
        return {
            "run_id": run_id,
            "status": "completed",
            "delivery": (record["result"] or {}).get("agency", {}).get("delivery"),
        }

    if record["status"] != "needs_approval":
        raise HTTPException(status_code=409, detail=f"Run is not awaiting delivery (status={record['status']})")

    run_approvals = get_approvals_for_run(run_id)
    if not run_approvals:
        raise HTTPException(status_code=409, detail="No approval found for this run")

    latest = run_approvals[0]
    if latest["status"] != "resolved":
        raise HTTPException(status_code=409, detail="Run still has an unresolved approval")
    if latest["decision"] != "approve":
        raise HTTPException(status_code=409, detail=f"Run was not approved (decision={latest['decision']})")

    graph = build_agency_workflow()
    config = _run_config(run_id)
    try:
        state = _run_and_record_events(graph, None, config, run_id)
    except Exception as exc:
        update_run_status(run_id, "failed", {"error": str(exc)})
        raise HTTPException(status_code=500, detail="Delivery failed") from exc

    agency_data = _agency_payload(state)
    update_run_status(run_id, "completed", {"agency": agency_data})

    return {"run_id": run_id, "status": "completed", "delivery": agency_data.get("delivery")}
