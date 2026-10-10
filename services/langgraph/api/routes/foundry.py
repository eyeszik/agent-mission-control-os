"""Creative Foundry API: run a local-first design mission into a project and review its artifacts.

Every route requires an authenticated principal and resolves the project's
*recorded* tenant before touching it; the brief never carries authority. Missions
run synchronously and locally (draft quality by default). Nothing here publishes,
deploys, purchases or contacts a third-party design service; approvals go
through the existing ``/approvals/{id}/decide`` route.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.foundry import discovery
from services.langgraph.agency.foundry.capabilities import discover
from services.langgraph.agency.foundry.contracts import UserBrief
from services.langgraph.agency.foundry.grammars import GRAMMARS
from services.langgraph.agency.foundry.studio import Mission, create_variant, observe, request_approval
from services.langgraph.api.routes._project_common import authorize_project_access, domain_errors, storage_adapter
from services.langgraph.persistence.idempotency import complete_idempotency, fail_idempotency, hash_payload, reserve_idempotency
from services.langgraph.persistence.projects import list_project_artifacts
from services.langgraph.security.auth import Principal, get_principal

router = APIRouter()
INLINE_TYPES = {"image/svg+xml", "image/png", "video/mp4", "application/json", "text/css", "text/html"}


class MissionRequest(BaseModel):
    brief: UserBrief
    copy_text: dict[str, str] = Field(default_factory=dict)
    counterfactual: bool = False

    model_config = {"extra": "forbid"}


class VariantRequest(BaseModel):
    dimensions: list[str] = Field(default_factory=list, max_length=12)
    seed: int = Field(default=1, ge=0, le=2**31 - 1)
    edits: dict = Field(default_factory=dict)

    model_config = {"extra": "forbid"}


class ApprovalRequest(BaseModel):
    mission_id: str = Field(min_length=1, max_length=120)

    model_config = {"extra": "forbid"}


@router.get("/capabilities")
def capabilities(principal: Principal = Depends(get_principal)) -> dict:
    return {"capabilities": [c.model_dump(mode="json") for c in discover()], "discovery_adapters": discovery.inventory(),
            "grammars": [{"grammar_id": g.grammar_id, "name": g.name, "lineage_note": g.lineage_note,
                          "variation_axes": list(g.variation_axes)} for g in GRAMMARS.values()],
            "hosted_generation": "NONE"}


@router.post("/projects/{project_id}/missions", status_code=201)
@domain_errors
def run_mission(project_id: str, req: MissionRequest, idempotency_key: str = Header(..., alias="Idempotency-Key"),
                principal: Principal = Depends(get_principal)) -> dict:
    authorize_project_access(principal, project_id)
    scope = f"{principal.tenant_id}:{principal.user_id}:foundry.mission:{project_id}"
    reservation = reserve_idempotency(scope, idempotency_key, hash_payload(req.model_dump(mode="json")))
    if reservation["state"] == "replay":
        return reservation["record"]["result"]
    if reservation["state"] in {"in_progress", "conflict"}:
        raise HTTPException(status_code=409, detail="Idempotency-Key is in use or was reused with different input")
    try:
        with tempfile.TemporaryDirectory(prefix="amc-foundry-") as work:
            mission = Mission(principal, project_id, req.brief, adapter=storage_adapter(), work_dir=Path(work), copy=req.copy_text)
            doc = mission.run(counterfactual=req.counterfactual)
    except Exception as exc:
        fail_idempotency(scope, idempotency_key, type(exc).__name__)
        raise
    response = {"mission_id": "fm-" + canonical_hash({"project": project_id, "brief": req.brief.model_dump(mode="json")})[:20],
                "genome_hash": doc["genome_hash"], "genome_artifact": doc["genome_artifact"],
                "artifacts": [{k: a[k] for k in ("deliverable", "name", "artifact_id", "version", "action", "mime_type", "sha256",
                                                 "bytes", "invalidated")} | {"proof_state": a["proof"]["state"],
                                                                             "blocked_at": a["proof"]["blocked_at"],
                                                                             "validations": a["proof"]["validation_results"]}
                              for a in doc["artifacts"]],
                "routes": doc["routes"], "capability_gaps": doc["capability_gaps"], "assumptions": doc["assumptions"],
                "external_effects": doc["external_effects"]}
    complete_idempotency(scope, idempotency_key, response)
    return response


@router.post("/projects/{project_id}/variants", status_code=201)
@domain_errors
def variant(project_id: str, req: VariantRequest, principal: Principal = Depends(get_principal)) -> dict:
    authorize_project_access(principal, project_id)
    with tempfile.TemporaryDirectory(prefix="amc-foundry-") as work:
        return create_variant(principal, project_id, adapter=storage_adapter(), work_dir=Path(work),
                              dimensions=tuple(req.dimensions), seed=req.seed, edits=req.edits or None)


@router.get("/projects/{project_id}/artifacts")
@domain_errors
def artifacts(project_id: str, principal: Principal = Depends(get_principal)) -> dict:
    authorize_project_access(principal, project_id)
    rows = [a.model_dump(mode="json") for a in list_project_artifacts(project_id) if a.artifact_key.startswith("foundry-")]
    return {"artifacts": rows}


@router.get("/projects/{project_id}/artifacts/{artifact_id}/content")
@domain_errors
def content(project_id: str, artifact_id: str, principal: Principal = Depends(get_principal)) -> Response:
    authorize_project_access(principal, project_id)
    data, head = observe(artifact_id, storage_adapter())
    if head["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="Artifact not found in this project")
    mime = ((head.get("metadata") or {}).get("v2") or {}).get("mime_type") or "application/octet-stream"
    if mime not in INLINE_TYPES:
        mime = "application/octet-stream"
    headers = {"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox; default-src 'none'; img-src data:; style-src 'unsafe-inline'",
               "X-AMC-Content-SHA256": head.get("content_hash") or "", "X-AMC-Artifact-Version": str(head["version"])}
    return Response(content=data, media_type=mime, headers=headers)


@router.post("/projects/{project_id}/artifacts/{artifact_id}/approval", status_code=201)
@domain_errors
def approval(project_id: str, artifact_id: str, req: ApprovalRequest, principal: Principal = Depends(get_principal)) -> dict:
    authorize_project_access(principal, project_id)
    result = request_approval(principal, project_id, artifact_id, adapter=storage_adapter(), mission_id=req.mission_id)
    return {"approval": result}


__all__ = ["router"]
