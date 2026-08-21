from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from services.langgraph.integrations.paid_media import request_spend_authorization, spend_execution_available
from services.langgraph.integrations.publication import prepare_publication
from services.langgraph.persistence.analytics import emit_lifecycle_event
from services.langgraph.persistence.runs import get_run_record
from services.langgraph.security.auth import Principal, authorize_project, authorize_resource, get_principal

router = APIRouter()


class PublicationPreviewRequest(BaseModel):
    run_id: str
    provider: str = Field(min_length=1, max_length=80)
    payload: dict


class SpendAuthorizationRequest(BaseModel):
    project_id: str
    run_id: str | None = None
    provider: str = Field(min_length=1, max_length=80)
    amount_minor: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    reason: str = Field(min_length=1, max_length=500)


@router.get("/capabilities")
def capabilities(principal: Principal = Depends(get_principal)):
    return {
        "tenant_id": principal.tenant_id,
        "publication": {"live": False, "dry_run": True},
        "paid_media": {"live_spend": spend_execution_available(), "authorization_ledger": True},
        "analytics": {"source": "amc_first_party", "ingestion": True},
    }


@router.post("/publications/preview", status_code=201)
def publication_preview(
    req: PublicationPreviewRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    principal: Principal = Depends(get_principal),
):
    run = get_run_record(req.run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    authorize_resource(principal, run["tenant_id"], run["project_id"])
    job = prepare_publication(
        req.run_id,
        principal.tenant_id,
        run["project_id"],
        req.provider,
        req.payload,
        idempotency_key,
    )
    emit_lifecycle_event(
        principal.tenant_id,
        run["project_id"],
        "publication_previewed",
        {
            "provider": req.provider,
            "mode": job.get("mode"),
            "status": job.get("status"),
        },
        req.run_id,
    )
    return job


@router.post("/spend/authorizations", status_code=201)
def create_spend_authorization(req: SpendAuthorizationRequest, principal: Principal = Depends(get_principal)):
    authorize_project(principal, req.project_id)
    if req.run_id:
        run = get_run_record(req.run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        authorize_resource(principal, run["tenant_id"], run["project_id"])
        if run["project_id"] != req.project_id:
            raise HTTPException(status_code=409, detail="run_id and project_id do not match")
    authorization = request_spend_authorization(
        req.run_id,
        principal.tenant_id,
        req.project_id,
        req.provider,
        req.amount_minor,
        req.currency,
        principal.user_id,
        req.reason,
    )
    emit_lifecycle_event(
        principal.tenant_id,
        req.project_id,
        "spend_authorization_requested",
        {
            "provider": req.provider,
            "authorization_id": authorization.get("authorization_id"),
            "amount_minor": req.amount_minor,
            "currency": req.currency.upper(),
            "status": authorization.get("status"),
        },
        req.run_id,
    )
    return authorization
