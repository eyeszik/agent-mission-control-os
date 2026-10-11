"""Agency OS API (``/agency-os``): clients, missions, lifecycle, deliverables, attention, analytics.

Thin over existing owners. Missions run through the intake runner, approvals
through ``/approvals/{id}/decide``, and external effects through ``/actions``.
Every route needs a principal; bodies forbid extra fields.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field

from services.langgraph.agency.agency_os import deliverables, missions, service
from services.langgraph.api.routes.actions import action_errors
from services.langgraph.persistence.idempotency import complete_idempotency, fail_idempotency, hash_payload, reserve_idempotency
from services.langgraph.security.auth import Principal, get_principal

router = APIRouter()


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClientCreate(_Body):
    display_name: str = Field(min_length=1, max_length=120)
    notes: str = Field(default="", max_length=2000)


class ClientLink(_Body):
    project_id: str = Field(min_length=1, max_length=200)


class Brief(_Body):
    brief: str = Field(min_length=3, max_length=4000)
    project_id: str = Field(min_length=1, max_length=200)


class Revision(_Body):
    artifact_id: str = Field(min_length=1, max_length=200)
    note: str = Field(min_length=1, max_length=2000)


class ExportRequest(_Body):
    artifact_ids: list[str] = Field(min_length=1, max_length=200)


class ManifestCheck(_Body):
    manifest: dict[str, Any]


def _idempotent(principal: Principal, operation: str, key: str, payload: dict, run) -> dict:
    scope = f"{principal.tenant_id}:{principal.user_id}:agency-os.{operation}"
    reservation = reserve_idempotency(scope, key, hash_payload(payload))
    if reservation["state"] == "replay":
        return reservation["record"]["result"]
    if reservation["state"] in {"in_progress", "conflict"}:
        raise ValueError("Idempotency-Key is in use or was reused with different input")
    try:
        result = run()
    except Exception as exc:
        fail_idempotency(scope, key, type(exc).__name__)
        raise
    complete_idempotency(scope, key, result)
    return result


# --------------------------------------------------------------------------- clients


@router.get("/clients")
@action_errors
def list_clients(principal: Principal = Depends(get_principal)) -> dict:
    return {"clients": service.list_clients(principal)}


@router.post("/clients", status_code=201)
@action_errors
def create_client(body: ClientCreate, principal: Principal = Depends(get_principal)) -> dict:
    return {"client": service.create_client(principal, display_name=body.display_name, notes=body.notes)}


@router.get("/clients/{client_id}")
@action_errors
def get_client(client_id: str, principal: Principal = Depends(get_principal)) -> dict:
    return {"client": service.get_client(principal, client_id), "projects": service.client_projects(principal, client_id)}


@router.post("/clients/{client_id}/projects", status_code=201)
@action_errors
def link_project(client_id: str, body: ClientLink, principal: Principal = Depends(get_principal)) -> dict:
    return {"link": service.link_project(principal, client_id, body.project_id)}


@router.get("/clients/{client_id}/offboarding")
@action_errors
def offboarding(client_id: str, principal: Principal = Depends(get_principal)) -> dict:
    return service.offboarding_report(principal, client_id)


@router.post("/clients/{client_id}/offboarding")
@action_errors
def start_offboarding(client_id: str, principal: Principal = Depends(get_principal)) -> dict:
    return {"client": service.start_offboarding(principal, client_id)}


@router.post("/clients/{client_id}/archive")
@action_errors
def archive(client_id: str, principal: Principal = Depends(get_principal)) -> dict:
    return {"client": service.archive_client(principal, client_id)}


# --------------------------------------------------------------------------- missions


@router.post("/missions/preview")
@action_errors
def preview_mission(body: Brief, principal: Principal = Depends(get_principal)) -> dict:
    return missions.preview(principal, brief=body.brief, project_id=body.project_id)


@router.post("/missions", status_code=201)
@action_errors
def launch_mission(body: Brief, idempotency_key: str = Header(..., alias="Idempotency-Key"),
                   principal: Principal = Depends(get_principal)) -> dict:
    return _idempotent(principal, "mission.launch", idempotency_key, body.model_dump(),
                       lambda: {"mission": missions.launch(principal, brief=body.brief, project_id=body.project_id)})


@router.get("/projects/{project_id}/missions")
@action_errors
def list_missions(project_id: str, principal: Principal = Depends(get_principal)) -> dict:
    return {"missions": missions.list_missions(principal, project_id)}


@router.post("/projects/{project_id}/revisions", status_code=201)
@action_errors
def request_revision(project_id: str, body: Revision, principal: Principal = Depends(get_principal)) -> dict:
    return {"revision": missions.request_revision(principal, project_id=project_id, artifact_id=body.artifact_id, note=body.note)}


# --------------------------------------------------------------------------- lifecycle, deliverables, attention, analytics


@router.get("/projects/{project_id}/lifecycle")
@action_errors
def lifecycle(project_id: str, principal: Principal = Depends(get_principal)) -> dict:
    return service.lifecycle(principal, project_id)


@router.get("/projects/{project_id}/deliverables")
@action_errors
def vault(project_id: str, principal: Principal = Depends(get_principal)) -> dict:
    return {"deliverables": deliverables.vault(principal, project_id)}


@router.post("/projects/{project_id}/deliverables/export")
@action_errors
def export(project_id: str, body: ExportRequest, principal: Principal = Depends(get_principal)) -> dict:
    return {"manifest": deliverables.export_manifest(principal, project_id, body.artifact_ids)}


@router.post("/deliverables/verify-manifest")
@action_errors
def verify_manifest(body: ManifestCheck, principal: Principal = Depends(get_principal)) -> dict:
    return deliverables.verify_manifest(body.manifest)


@router.get("/attention")
@action_errors
def attention(principal: Principal = Depends(get_principal)) -> dict:
    return {"items": service.attention(principal)}


@router.get("/analytics")
@action_errors
def analytics(project_id: Optional[str] = None, principal: Principal = Depends(get_principal)) -> dict:
    return service.analytics(principal, project_id=project_id)
