from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from services.langgraph.persistence.analytics import record_analytics_event
from services.langgraph.security.auth import Principal, authorize_project, get_principal

router = APIRouter()


class AnalyticsEventRequest(BaseModel):
    project_id: str
    event_name: str = Field(min_length=1, max_length=120)
    run_id: str | None = None
    properties: dict = Field(default_factory=dict)


@router.post("/events", status_code=201)
def create_analytics_event(req: AnalyticsEventRequest, principal: Principal = Depends(get_principal)):
    authorize_project(principal, req.project_id)
    return record_analytics_event(
        principal.tenant_id,
        req.project_id,
        req.event_name,
        req.properties,
        req.run_id,
    )
