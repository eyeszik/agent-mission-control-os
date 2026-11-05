from datetime import datetime, timezone
from typing import List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from services.langgraph.agency.kernel.lifecycle import release_guard_failures
from services.langgraph.graph.agency.build import AGENCY_PIPELINE_STAGES, build_agency_workflow
from services.langgraph.graph.models import AgentRun
from services.langgraph.app.config import execution_mode
from services.langgraph.persistence.analytics import emit_lifecycle_event
from services.langgraph.persistence.approvals import get_approvals_for_run
from services.langgraph.persistence.events import record_event
from services.langgraph.persistence.idempotency import (
    complete_idempotency,
    fail_idempotency,
    hash_payload,
    reserve_idempotency,
)
from services.langgraph.persistence.jobs import enqueue_job
from services.langgraph.persistence.runs import (
    compare_and_set_run_status,
    create_run_record,
    get_run_record,
    update_run_status,
)
from services.langgraph.runtime import execution as _exec
from services.langgraph.security.auth import Principal, authorize_project, authorize_resource, get_principal
from services.langgraph.security.pii import quarantine_payload
from services.langgraph.security.preprocess import sanitize_deep

router = APIRouter()

PIPELINE_NAME = "branding_marketing_agency"
IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60

# Route-level aliases over the shared execution core so inline HTTP execution
# and the background worker cannot drift apart.
_now = _exec.now_iso
_run_config = _exec.run_config
_agency_payload = _exec.agency_payload
_run_and_record_events = _exec.run_and_record_events
_delivery_context = _exec.delivery_context
_ANALYTICS_REPORTED_BLOCKS = _exec.ANALYTICS_REPORTED_BLOCKS
_DELIVERY_BLOCK_DETAIL = _exec.DELIVERY_BLOCK_DETAIL


class CampaignBriefRequest(BaseModel):
    brand_name: str
    industry: Optional[str] = None
    goals: List[str] = Field(default_factory=list)
    target_audience: str
    tone: Optional[str] = None
    channels: List[str] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list)


class CreateAgencyRunRequest(BaseModel):
    tenant_id: Optional[str] = None
    project_id: str
    brief: CampaignBriefRequest


def _safe_brief(req: CreateAgencyRunRequest) -> dict:
    return quarantine_payload(sanitize_deep(req.brief.model_dump()))


def _authorize_run(principal: Principal, record: dict) -> None:
    authorize_resource(principal, record["tenant_id"], record["project_id"])


def _idempotency_scope(principal: Principal, operation: str, resource: str) -> str:
    return f"{principal.tenant_id}:{principal.user_id}:{operation}:{resource}"


def _reserve_or_replay(scope: str, key: str, request_hash: str) -> Optional[dict]:
    reservation = reserve_idempotency(scope, key, request_hash, IDEMPOTENCY_TTL_SECONDS)
    state = reservation["state"]
    if state == "replay":
        return reservation["record"]["result"]
    if state == "in_progress":
        raise HTTPException(status_code=409, detail="Equivalent request is already executing")
    if state == "conflict":
        raise HTTPException(status_code=409, detail="Idempotency-Key was reused with different input")
    return None


@router.post("/runs", status_code=201)
def create_agency_run(
    req: CreateAgencyRunRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    principal: Principal = Depends(get_principal),
):
    authorize_project(principal, req.project_id)
    if req.tenant_id is not None and req.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=403, detail="tenant_id does not match authenticated principal")

    safe_brief = _safe_brief(req)
    scope = _idempotency_scope(principal, "agency.create", req.project_id)
    request_hash = hash_payload({"project_id": req.project_id, "brief": safe_brief})
    replay = _reserve_or_replay(scope, idempotency_key, request_hash)
    if replay is not None:
        return replay

    run_id = str(uuid4())
    now = datetime.now(timezone.utc)
    metadata = {"input_data": {"brief": safe_brief}}

    background = execution_mode() == "background"
    run = AgentRun(
        id=run_id,
        tenant_id=principal.tenant_id,
        project_id=req.project_id,
        status="queued" if background else "running",
        created_at=now,
        updated_at=now,
        metadata=metadata,
    )
    create_run_record(
        run_id, principal.tenant_id, req.project_id, PIPELINE_NAME,
        "queued" if background else "running", metadata,
    )
    emit_lifecycle_event(
        principal.tenant_id,
        req.project_id,
        "agency_run_created",
        {"pipeline": PIPELINE_NAME, "status": "queued" if background else "running"},
        run_id,
    )

    if background:
        job = enqueue_job(
            "agency.create",
            principal.tenant_id,
            req.project_id,
            {
                "run_id": run_id,
                "idempotency_scope": scope,
                "idempotency_key": idempotency_key,
                "brief": safe_brief,
            },
            run_id=run_id,
        )
        return {
            "run_id": run_id,
            "status": "queued",
            "pipeline": PIPELINE_NAME,
            "stages": AGENCY_PIPELINE_STAGES,
            "job_id": job["job_id"],
            "execution_mode": "background",
            "pending_approval": None,
            "degraded": False,
        }

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
        state = _run_and_record_events(graph, initial_state, config, run)
    except Exception as exc:
        update_run_status(run_id, "failed", {"error": type(exc).__name__})
        record_event(run_id, run.tenant_id, run.project_id, "pipeline", "node_error", safe_payload={"error_class": type(exc).__name__})
        emit_lifecycle_event(
            run.tenant_id,
            run.project_id,
            "agency_run_failed",
            {"pipeline": PIPELINE_NAME, "phase": "generation", "error_class": type(exc).__name__},
            run_id,
        )
        fail_idempotency(scope, idempotency_key, type(exc).__name__)
        raise HTTPException(status_code=500, detail="Agency pipeline failed") from exc

    agency_data = _agency_payload(state)
    record = update_run_status(run_id, "needs_approval", {"agency": agency_data})
    run_approvals = get_approvals_for_run(run_id)
    release_blocked = bool((agency_data.get("qa_report") or {}).get("release_blocked"))
    emit_lifecycle_event(
        principal.tenant_id,
        req.project_id,
        "agency_run_needs_approval",
        {
            "pipeline": PIPELINE_NAME,
            "status": record["status"],
            "degraded": bool(agency_data.get("degraded")),
            "release_blocked": release_blocked,
        },
        run_id,
    )
    response = {
        "run_id": run_id,
        "status": record["status"],
        "pipeline": PIPELINE_NAME,
        "stages": AGENCY_PIPELINE_STAGES,
        "campaign_package": agency_data.get("campaign_package"),
        "qa_report": agency_data.get("qa_report"),
        "pending_approval": run_approvals[0] if run_approvals else None,
        "degraded": bool(agency_data.get("degraded")),
        "generation_provenance": agency_data.get("generation_provenance", []),
    }
    if not complete_idempotency(scope, idempotency_key, response):
        raise HTTPException(status_code=500, detail="Failed to finalize idempotency record")
    return response


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
        "degraded": bool(agency_data.get("degraded")),
        "generation_provenance": agency_data.get("generation_provenance", []),
    }


@router.post("/runs/{run_id}/resume")
def resume_agency_run(
    run_id: str,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    principal: Principal = Depends(get_principal),
):
    record = get_run_record(run_id)
    if not record:
        raise HTTPException(status_code=404, detail="Run not found")
    _authorize_run(principal, record)

    scope = _idempotency_scope(principal, "agency.resume", run_id)
    replay = _reserve_or_replay(scope, idempotency_key, hash_payload({"run_id": run_id}))
    if replay is not None:
        return replay

    if record["status"] == "completed":
        response = {
            "run_id": run_id,
            "status": "completed",
            "delivery": (record["result"] or {}).get("agency", {}).get("delivery"),
        }
        complete_idempotency(scope, idempotency_key, response)
        return response

    if record["status"] != "needs_approval":
        fail_idempotency(scope, idempotency_key, f"invalid_status:{record['status']}")
        raise HTTPException(status_code=409, detail=f"Run is not awaiting delivery (status={record['status']})")

    if execution_mode() == "background":
        job = enqueue_job(
            "agency.resume",
            principal.tenant_id,
            record["project_id"],
            {
                "run_id": run_id,
                "idempotency_scope": scope,
                "idempotency_key": idempotency_key,
            },
            run_id=run_id,
        )
        return {
            "run_id": run_id,
            "status": record["status"],
            "job_id": job["job_id"],
            "execution_mode": "background",
        }

    stored_agency = (record.get("result") or {}).get("agency", {})
    run_approvals = get_approvals_for_run(run_id)
    latest = run_approvals[0] if run_approvals else None

    # Delivery is gated by the declared N2 release guards rather than by ad-hoc
    # checks, so the transition matrix stays the single authority on what may
    # reach a client. The guard codes map onto this route's existing error
    # contract below; behavior is unchanged.
    failures = release_guard_failures(_delivery_context(stored_agency, latest))
    if failures:
        blocker = failures[0]
        # A run blocked on its own approval state is an ordinary interaction —
        # someone resumed before deciding — so it stays out of the lifecycle
        # analytics stream. Only a substantive release block is recorded.
        if blocker.code in _ANALYTICS_REPORTED_BLOCKS:
            emit_lifecycle_event(
                record["tenant_id"],
                record["project_id"],
                "agency_run_delivery_blocked",
                {"pipeline": record["pipeline"], "reason": blocker.code},
                run_id,
            )
        fail_idempotency(scope, idempotency_key, blocker.code)
        raise HTTPException(status_code=409, detail=_DELIVERY_BLOCK_DETAIL[blocker.code](latest))

    if not compare_and_set_run_status(run_id, "needs_approval", "delivering"):
        fail_idempotency(scope, idempotency_key, "resume_race_lost")
        current = get_run_record(run_id)
        if current and current["status"] == "completed":
            return {
                "run_id": run_id,
                "status": "completed",
                "delivery": (current["result"] or {}).get("agency", {}).get("delivery"),
            }
        raise HTTPException(status_code=409, detail="Run delivery is already being processed")

    emit_lifecycle_event(
        record["tenant_id"],
        record["project_id"],
        "agency_run_delivery_started",
        {"pipeline": record["pipeline"], "status": "delivering"},
        run_id,
    )

    graph = build_agency_workflow()
    config = _run_config(run_id)
    run_model = AgentRun(
        id=run_id,
        tenant_id=record["tenant_id"],
        project_id=record["project_id"],
        status=record["status"],
        created_at=datetime.fromisoformat(record["created_at"]),
        updated_at=datetime.fromisoformat(record["updated_at"]),
        metadata=record.get("metadata"),
    )
    try:
        state = _run_and_record_events(graph, None, config, run_model)
    except Exception as exc:
        update_run_status(run_id, "failed", {"error": type(exc).__name__})
        record_event(run_id, record["tenant_id"], record["project_id"], "delivery", "node_error", safe_payload={"error_class": type(exc).__name__})
        emit_lifecycle_event(
            record["tenant_id"],
            record["project_id"],
            "agency_run_failed",
            {"pipeline": record["pipeline"], "phase": "delivery", "error_class": type(exc).__name__},
            run_id,
        )
        fail_idempotency(scope, idempotency_key, type(exc).__name__)
        raise HTTPException(status_code=500, detail="Delivery failed") from exc

    agency_data = _agency_payload(state)
    update_run_status(run_id, "completed", {"agency": agency_data})
    emit_lifecycle_event(
        record["tenant_id"],
        record["project_id"],
        "agency_run_completed",
        {"pipeline": record["pipeline"], "status": "completed"},
        run_id,
    )
    response = {"run_id": run_id, "status": "completed", "delivery": agency_data.get("delivery")}
    if not complete_idempotency(scope, idempotency_key, response):
        raise HTTPException(status_code=500, detail="Failed to finalize idempotency record")
    return response
