"""Mission council API (``/missions``): ideas, dispatch to any engine, timeline, checkpoints, approval resume.

Every route authenticates through ``get_principal`` and authorizes the tenant
and project server-side. Writes require an ``Idempotency-Key``; a replay with
the same key and body returns the first response, a different body is a 409.
Approvals are decided at ``/approvals/{id}/decide`` (approver role, separation
of duties); ``/missions/{id}/resume`` then resumes the paused checkpoint with
that decision, once. Live events stream from ``/runs/{mission_id}/events``.
Errors carry stable codes in the AMC envelope ``{detail, error: {code, ...}}``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, ConfigDict

from services.langgraph.agency.council import gateway, service
from services.langgraph.agency.council.contracts import DispatchRequest, IdeaCreate
from services.langgraph.agency.council.engines import engine_catalog
from services.langgraph.agency.council.mcp_client import (
    configured_servers,
    mcp_installed,
)
from services.langgraph.agency.council.model import (
    default_provider,
    real_models_enabled,
    selected_mode,
)
from services.langgraph.core.errors import AMCError
from services.langgraph.persistence import council as store
from services.langgraph.persistence.idempotency import (
    complete_idempotency,
    fail_idempotency,
    hash_payload,
    reserve_idempotency,
)
from services.langgraph.security.auth import Principal, authorize_project, get_principal

router = APIRouter()
IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60


class _Open(BaseModel):
    model_config = ConfigDict(extra="allow")


class EngineInfo(BaseModel):
    engine: str
    available: bool
    detail: str


class EnginesResponse(BaseModel):
    engines: list[EngineInfo]
    model_mode: str
    real_models_enabled: bool
    default_provider: str


class ToolsResponse(BaseModel):
    tools: list[dict[str, Any]]
    mcp_installed: bool
    mcp_config_errors: list[str]


class IdeaResponse(_Open):
    idea_id: str
    project_id: str
    title: str
    description: str
    status: str
    created_by: str
    created_at: str


class MissionResponse(_Open):
    mission_id: str
    thread_id: str
    idea_id: str
    engine: str
    model_mode: str
    status: str
    phase: str


class Page(BaseModel):
    items: list[dict[str, Any]]
    next_cursor: str | None


def _amc(exc: service.MissionError) -> AMCError:
    return AMCError(str(exc), code=exc.code, status=exc.status, details=exc.details)


def _idempotent(principal: Principal, operation: str, key: str, body: Any, run: Callable[[], dict]) -> dict:
    scope = f"{principal.tenant_id}:{principal.user_id}:{operation}"
    reservation = reserve_idempotency(scope, key, hash_payload(body), IDEMPOTENCY_TTL_SECONDS)
    if reservation["state"] == "replay":
        return reservation["record"]["result"]
    if reservation["state"] == "in_progress":
        raise AMCError("Equivalent request is already executing", code="IDEMPOTENCY_IN_PROGRESS", status=409)
    if reservation["state"] == "conflict":
        raise AMCError("Idempotency-Key was reused with a different request", code="IDEMPOTENCY_CONFLICT", status=409)
    try:
        result = run()
    except service.MissionError as exc:
        fail_idempotency(scope, key, exc.code)
        raise _amc(exc) from exc
    except Exception as exc:
        fail_idempotency(scope, key, type(exc).__name__)
        raise
    complete_idempotency(scope, key, result)
    return result


def _call(fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except service.MissionError as exc:
        raise _amc(exc) from exc


# --------------------------------------------------------------------------- discovery


@router.get("/engines", response_model=EnginesResponse)
def list_engines(principal: Principal = Depends(get_principal)):
    """Which orchestration engines can run here, and which model mode new missions use."""
    return {"engines": engine_catalog(), "model_mode": selected_mode(), "real_models_enabled": real_models_enabled(),
            "default_provider": default_provider()}


@router.get("/tools", response_model=ToolsResponse)
def list_tools(principal: Principal = Depends(get_principal)):
    """The Sentinel gateway allowlist: local tools plus operator-allowlisted MCP tools."""
    return {"tools": [spec.public() for spec in gateway.registry().values()], "mcp_installed": mcp_installed(),
            "mcp_config_errors": configured_servers()[1]}


# -------------------------------------------------------------------------------- ideas


@router.post("/ideas", status_code=201, response_model=IdeaResponse)
def create_idea(body: IdeaCreate, idempotency_key: str = Header(..., alias="Idempotency-Key"),
                principal: Principal = Depends(get_principal)):
    return _idempotent(principal, "missions.idea.create", idempotency_key, body.model_dump(),
                       lambda: service.create_idea(principal, body))


@router.get("/ideas", response_model=Page)
def list_ideas(project_id: str = Query(..., min_length=1), limit: int = Query(20, ge=1, le=100),
               before: str | None = Query(None), principal: Principal = Depends(get_principal)):
    authorize_project(principal, project_id)
    items = store.list_ideas(principal.tenant_id, [project_id], limit=limit, before=before)
    return {"items": items, "next_cursor": items[-1]["created_at"] if len(items) == limit else None}


@router.get("/ideas/{idea_id}")
def get_idea(idea_id: str, principal: Principal = Depends(get_principal)):
    idea = _call(lambda: service.get_idea_for(principal, idea_id))
    missions = [service.describe(m["mission_id"]) for m in store.missions_for_idea(idea_id)]
    return {**idea, "missions": missions, "blueprints": store.list_blueprints(idea_id)}


@router.post("/ideas/{idea_id}/blueprints", status_code=201)
def extract_blueprint(idea_id: str, idempotency_key: str = Header(..., alias="Idempotency-Key"),
                      principal: Principal = Depends(get_principal)):
    """Merge the best parts of the idea's completed missions into a draft blueprint."""
    return _idempotent(principal, f"missions.blueprint.extract:{idea_id}", idempotency_key, {"idea_id": idea_id},
                       lambda: service.extract_blueprint(principal, idea_id))


@router.get("/blueprints/{blueprint_id}")
def get_blueprint(blueprint_id: str, principal: Principal = Depends(get_principal)):
    return _call(lambda: service.blueprint_for(principal, blueprint_id))


@router.post("/blueprints/{blueprint_id}/promote")
def promote_blueprint(blueprint_id: str, idempotency_key: str = Header(..., alias="Idempotency-Key"),
                      principal: Principal = Depends(get_principal)):
    """Promote a draft blueprint after verifying every source mission's timeline and checkpoint chain."""
    return _idempotent(principal, f"missions.blueprint.promote:{blueprint_id}", idempotency_key,
                       {"blueprint_id": blueprint_id}, lambda: service.promote_blueprint(principal, blueprint_id))


# ------------------------------------------------------------------------------ missions


@router.post("/dispatch", status_code=202, response_model=MissionResponse)
def dispatch_mission(body: DispatchRequest, idempotency_key: str = Header(..., alias="Idempotency-Key"),
                     principal: Principal = Depends(get_principal)):
    """Dispatch an idea to ``langgraph``, ``crewai`` or ``autogen``. Progress streams from /runs/{mission_id}/events."""
    return _idempotent(principal, "missions.dispatch", idempotency_key, body.model_dump(),
                       lambda: service.dispatch(principal, body))


@router.get("", response_model=Page)
def list_missions(project_id: str = Query(..., min_length=1), idea_id: str | None = Query(None),
                  limit: int = Query(20, ge=1, le=100), before: str | None = Query(None),
                  principal: Principal = Depends(get_principal)):
    authorize_project(principal, project_id)
    rows = store.list_missions(principal.tenant_id, [project_id], idea_id=idea_id, limit=limit, before=before)
    return {"items": [service.describe(r["mission_id"]) for r in rows],
            "next_cursor": rows[-1]["created_at"] if len(rows) == limit else None}


@router.get("/{mission_id}", response_model=MissionResponse)
def get_mission(mission_id: str, principal: Principal = Depends(get_principal)):
    return _call(lambda: service.describe_for(principal, mission_id))


@router.get("/{mission_id}/timeline")
def mission_timeline(mission_id: str, after: int = Query(-1, ge=-1), limit: int = Query(200, ge=1, le=500),
                     principal: Principal = Depends(get_principal)):
    return _call(lambda: service.timeline_for(principal, mission_id, after=after, limit=limit))


@router.get("/{mission_id}/checkpoints")
def mission_checkpoints(mission_id: str, principal: Principal = Depends(get_principal)):
    return _call(lambda: service.checkpoints_for(principal, mission_id))


@router.get("/{mission_id}/tool-audits")
def mission_tool_audits(mission_id: str, principal: Principal = Depends(get_principal)):
    return {"items": _call(lambda: service.tool_audits_for(principal, mission_id))}


@router.post("/{mission_id}/resume", response_model=MissionResponse)
def resume_mission(mission_id: str, idempotency_key: str = Header(..., alias="Idempotency-Key"),
                   principal: Principal = Depends(get_principal)):
    """Resume the paused checkpoint with the decision recorded on its approval (decide it first)."""
    return _idempotent(principal, f"missions.resume:{mission_id}", idempotency_key, {"mission_id": mission_id},
                       lambda: service.resume(principal, mission_id))


@router.post("/{mission_id}/cancel", response_model=MissionResponse)
def cancel_mission(mission_id: str, idempotency_key: str = Header(..., alias="Idempotency-Key"),
                   principal: Principal = Depends(get_principal)):
    return _idempotent(principal, f"missions.cancel:{mission_id}", idempotency_key, {"mission_id": mission_id},
                       lambda: service.cancel(principal, mission_id))


@router.post("/{mission_id}/retry", response_model=MissionResponse)
def retry_mission(mission_id: str, idempotency_key: str = Header(..., alias="Idempotency-Key"),
                  principal: Principal = Depends(get_principal)):
    return _idempotent(principal, f"missions.retry:{mission_id}", idempotency_key, {"mission_id": mission_id},
                       lambda: service.retry(principal, mission_id))


@router.post("/{mission_id}/recover", response_model=MissionResponse)
def recover_mission(mission_id: str, idempotency_key: str = Header(..., alias="Idempotency-Key"),
                    principal: Principal = Depends(get_principal)):
    return _idempotent(principal, f"missions.recover:{mission_id}", idempotency_key, {"mission_id": mission_id},
                       lambda: service.recover(principal, mission_id))
