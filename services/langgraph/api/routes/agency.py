from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel, Field
from typing import Optional, List
from uuid import uuid4
from datetime import datetime

from services.langgraph.graph.agency.build import build_agency_workflow, AGENCY_PIPELINE_STAGES
from services.langgraph.graph.models import AgentRun
from services.langgraph.persistence.runs import create_run_record, get_run_record, update_run_status
from services.langgraph.persistence.idempotency import verify_idempotency, record_idempotency
from services.langgraph.persistence.approvals import get_approvals_for_run

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
    tenant_id: str
    project_id: str
    brief: CampaignBriefRequest


def _run_config(run_id: str) -> dict:
    return {"configurable": {"thread_id": run_id}}


def _agency_payload(state: dict) -> dict:
    return (state.get("extracted_data") or {}).get("agency", {}) if state else {}


@router.post("/runs", status_code=201)
def create_agency_run(
    req: CreateAgencyRunRequest,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    """
    Kicks off a branding/marketing agency pipeline run and executes it synchronously
    up to (but not including) delivery, where it pauses for human-in-the-loop review.
    """
    if idempotency_key and verify_idempotency(idempotency_key):
        raise HTTPException(status_code=409, detail="Request already processed for this idempotency key")

    run_id = str(uuid4())
    now = datetime.utcnow()
    metadata = {"input_data": {"brief": req.brief.model_dump()}}

    run = AgentRun(
        id=run_id,
        tenant_id=req.tenant_id,
        project_id=req.project_id,
        status="running",
        created_at=now,
        updated_at=now,
        metadata=metadata,
    )
    create_run_record(run_id, req.tenant_id, req.project_id, PIPELINE_NAME, "running", metadata)

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
        state = graph.invoke(initial_state, config=config)
    except Exception as exc:
        update_run_status(run_id, "failed", {"error": str(exc)})
        raise HTTPException(status_code=500, detail=f"Agency pipeline failed: {exc}")

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
def get_agency_run(run_id: str):
    record = get_run_record(run_id)
    if not record:
        raise HTTPException(status_code=404, detail="Run not found")

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
def resume_agency_run(run_id: str):
    """
    Resumes a run past the HITL gate to deliver the campaign, but only once the
    run's approval has been resolved with decision=approve. Idempotent: resuming
    an already-completed run returns the cached delivery result instead of
    re-invoking delivery.
    """
    record = get_run_record(run_id)
    if not record:
        raise HTTPException(status_code=404, detail="Run not found")

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
        state = graph.invoke(None, config=config)
    except Exception as exc:
        update_run_status(run_id, "failed", {"error": str(exc)})
        raise HTTPException(status_code=500, detail=f"Delivery failed: {exc}")

    agency_data = _agency_payload(state)
    update_run_status(run_id, "completed", {"agency": agency_data})

    return {"run_id": run_id, "status": "completed", "delivery": agency_data.get("delivery")}
