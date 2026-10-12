"""Governed action plane API (``/actions``).

Every route needs an authenticated principal. Tenant, project, actor, risk,
approvals and budget are derived on the server; request bodies forbid extra
fields, so a client cannot inject them. Approvals are decided only at
``POST /approvals/{id}/decide``. LIVE is never dispatched.
"""

from __future__ import annotations

import functools
import inspect
from typing import Any, Callable, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from services.langgraph.agency.actions import evidence as views
from services.langgraph.agency.actions import gateway, governance
from services.langgraph.agency.actions.broker import ActionForbidden
from services.langgraph.agency.actions.catalog import UnknownAction, catalog
from services.langgraph.agency.actions.safety import UnsafeInput
from services.langgraph.agency.actions.vocabulary import AutonomyLevel
from services.langgraph.persistence import actions as db
from services.langgraph.security.auth import Principal, get_principal

router = APIRouter()


def _envelope(status: int, code: str, message: str, details: Optional[dict] = None) -> JSONResponse:
    body = {"code": code, "message": message, **({"details": details} if details else {})}
    return JSONResponse(status_code=status, content={"detail": body, "error": {"code": code, "message": message, "status": status,
                                                                               **({"details": details} if details else {})}})


def action_errors(handler: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(handler)
    def mapped(*args: Any, **kwargs: Any) -> Any:
        try:
            return handler(*args, **kwargs)
        except HTTPException:
            raise
        except gateway.GatewayError as exc:
            return _envelope(exc.status, exc.code, str(exc), exc.details or None)
        except UnknownAction as exc:
            return _envelope(404, "NOT_IMPLEMENTED", str(exc).removeprefix("NOT_IMPLEMENTED: "))
        except (ActionForbidden, PermissionError) as exc:
            return _envelope(403, "FORBIDDEN", str(exc))
        except LookupError as exc:
            return _envelope(404, "NOT_FOUND", str(exc) or "not found")
        except db.ActionConflict as exc:
            return _envelope(409, "CONFLICT", str(exc))
        except UnsafeInput as exc:
            return _envelope(422, exc.code, str(exc))
        except ValueError as exc:
            return _envelope(422, "INVALID", str(exc))

    mapped.__signature__ = inspect.signature(handler)  # type: ignore[attr-defined]
    return mapped


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ActionProposal(_Body):
    capability_id: str = Field(min_length=3, max_length=120)
    project_id: str = Field(min_length=1, max_length=200)
    environment: Literal["LOCAL", "SANDBOX", "LIVE"] = "SANDBOX"
    args: dict[str, Any] = Field(default_factory=dict)
    dependency_refs: list[str] = Field(default_factory=list, max_length=50)
    requested_class: Optional[Literal["R0", "R1", "R2", "R3", "R4", "R5", "R6"]] = None
    data_class: Optional[Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]] = None
    correlation_id: Optional[str] = Field(default=None, max_length=200)
    ttl_seconds: int = Field(default=gateway.DEFAULT_TTL_SECONDS, ge=60, le=gateway.MAX_TTL_SECONDS)


class Reason(_Body):
    reason: str = Field(default="", max_length=500)


class FreezeRequest(_Body):
    scope_kind: Literal["TENANT", "PROJECT"]
    scope_ref: Optional[str] = None
    reason: str = Field(min_length=3, max_length=500)


class AutonomyRequest(_Body):
    autonomy: Literal["OBSERVE", "DRAFT", "PREPARE", "REQUEST_APPROVAL"]


class BudgetSimulation(_Body):
    scope_kind: Literal["ACTION", "PROJECT", "CLIENT", "TENANT_DAY", "TENANT_MONTH"]
    scope_ref: str = Field(min_length=1, max_length=200)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    ceiling_minor: int = Field(ge=0)


# --------------------------------------------------------------------------- catalogue and capability


@router.get("/catalog")
@action_errors
def get_catalog(principal: Principal = Depends(get_principal)) -> dict:
    return {**catalog().snapshot(), "live": governance.live_enablement()}


@router.get("/catalog/{capability_id}")
@action_errors
def get_capability(capability_id: str, principal: Principal = Depends(get_principal)) -> dict:
    if capability_id.startswith(("EXT-", "ART-")):
        return catalog().reserved(capability_id).model_dump(mode="json")
    d = catalog().get(capability_id)
    risk = d.nominal_risk()
    return {**d.model_dump(mode="json"), "ref": d.ref, "descriptor_hash": d.descriptor_hash,
            "nominal_risk": {"classes": [c.value for c in risk.classes], "effective": risk.effective.value,
                             "controls": [c.value for c in risk.controls],
                             "explanations": [e.model_dump(mode="json") for e in risk.explanations]}}


@router.get("/drift")
@action_errors
def drift(principal: Principal = Depends(get_principal)) -> dict:
    return views.capability_drift()


@router.get("/live")
@action_errors
def live(principal: Principal = Depends(get_principal)) -> dict:
    return governance.live_enablement()


# --------------------------------------------------------------------------- actions


@router.post("/preview")
@action_errors
def preview(body: ActionProposal, principal: Principal = Depends(get_principal)) -> dict:
    return gateway.preview(principal, capability_id=body.capability_id, project_id=body.project_id, environment=body.environment,
                           args=body.args, dependency_refs=tuple(body.dependency_refs), requested_class=body.requested_class,
                           data_class=body.data_class, ttl_seconds=body.ttl_seconds)


@router.post("", status_code=201)
@action_errors
def propose(body: ActionProposal, idempotency_key: str = Header(..., alias="Idempotency-Key"),
            principal: Principal = Depends(get_principal)) -> Any:
    row, created = gateway.propose(principal, capability_id=body.capability_id, project_id=body.project_id,
                                   environment=body.environment, args=body.args, idempotency_key=idempotency_key,
                                   dependency_refs=tuple(body.dependency_refs), requested_class=body.requested_class,
                                   data_class=body.data_class, correlation_id=body.correlation_id, ttl_seconds=body.ttl_seconds)
    payload = {"action": gateway.view(row), "replayed": not created}
    return payload if created else JSONResponse(status_code=200, content=payload)


@router.get("")
@action_errors
def list_actions(project_id: Optional[str] = None, state: Optional[str] = None, limit: int = Query(default=100, ge=1, le=500),
                 principal: Principal = Depends(get_principal)) -> dict:
    if project_id is not None and not principal.can_access_project(project_id):
        raise PermissionError("project is outside the principal's scope")
    rows = db.list_requests(principal.tenant_id, project_ids=[project_id] if project_id else None,
                            states=[state] if state else (), limit=limit)
    rows = [r for r in rows if principal.can_access_project(r["project_id"])]
    return {"actions": [gateway.view(r) for r in rows]}


@router.get("/recovery")
@action_errors
def recovery(principal: Principal = Depends(get_principal)) -> dict:
    return {"items": views.recovery_workbench(principal)}


@router.post("/recovery/sweep")
@action_errors
def recovery_sweep(principal: Principal = Depends(get_principal)) -> dict:
    from services.langgraph.agency.actions.broker import FREEZE_ROLES, require_role

    require_role(principal, FREEZE_ROLES, "a recovery sweep")
    reconciled = gateway.recover_stale(principal=principal)
    expired = gateway.expire_due(principal.tenant_id)
    return {"reconciled": [r["action_id"] for r in reconciled], "expired": expired}


@router.get("/budget")
@action_errors
def budget(principal: Principal = Depends(get_principal)) -> dict:
    return views.budget_envelope(principal)


@router.post("/budget/simulate")
@action_errors
def simulate_budget(body: BudgetSimulation, principal: Principal = Depends(get_principal)) -> dict:
    return governance.simulate_budget_policy(principal, scope_kind=body.scope_kind, scope_ref=body.scope_ref,
                                             currency=body.currency, ceiling_minor=body.ceiling_minor)


@router.get("/expiring")
@action_errors
def expiring(hours: int = Query(default=24, ge=1, le=336), principal: Principal = Depends(get_principal)) -> dict:
    return {"items": views.expiring(principal, within_hours=hours)}


@router.get("/freezes")
@action_errors
def freezes(principal: Principal = Depends(get_principal)) -> dict:
    return {"system_frozen": governance.system_frozen(), "freezes": db.active_freezes(principal.tenant_id)}


@router.post("/freezes", status_code=201)
@action_errors
def create_freeze(body: FreezeRequest, principal: Principal = Depends(get_principal)) -> dict:
    return {"freeze": governance.freeze(principal, scope_kind=body.scope_kind, scope_ref=body.scope_ref, reason=body.reason)}


@router.post("/freezes/{freeze_id}/lift")
@action_errors
def lift_freeze(freeze_id: str, body: Reason, principal: Principal = Depends(get_principal)) -> dict:
    return {"freeze": governance.lift(principal, freeze_id, reason=body.reason)}


@router.get("/projects/{project_id}/autonomy")
@action_errors
def get_autonomy(project_id: str, principal: Principal = Depends(get_principal)) -> dict:
    from services.langgraph.agency.actions.broker import authorize_scope

    authorize_scope(principal, project_id, write=False)
    level = governance.autonomy(project_id)
    return {"project_id": project_id, "autonomy": level.value, "auto_ceiling": level.auto_ceiling.value}


@router.put("/projects/{project_id}/autonomy")
@action_errors
def put_autonomy(project_id: str, body: AutonomyRequest, principal: Principal = Depends(get_principal)) -> dict:
    row = governance.set_autonomy(principal, project_id, AutonomyLevel(body.autonomy))
    level = AutonomyLevel(row["autonomy"])
    return {"project_id": project_id, "autonomy": level.value, "auto_ceiling": level.auto_ceiling.value}


@router.get("/{action_id}")
@action_errors
def get_action(action_id: str, principal: Principal = Depends(get_principal)) -> dict:
    from services.langgraph.agency.actions.broker import visible

    visible(principal, db.get_request(action_id))
    row = gateway.settle(action_id)
    return {"action": gateway.view(row)}


@router.get("/{action_id}/evidence")
@action_errors
def get_evidence(action_id: str, principal: Principal = Depends(get_principal)) -> dict:
    return views.evidence(principal, action_id)


@router.post("/{action_id}/dispatch")
@action_errors
def dispatch(action_id: str, principal: Principal = Depends(get_principal)) -> dict:
    return {"action": gateway.view(gateway.dispatch(principal, action_id))}


@router.post("/{action_id}/cancel")
@action_errors
def cancel(action_id: str, body: Reason, principal: Principal = Depends(get_principal)) -> dict:
    return {"action": gateway.view(gateway.cancel(principal, action_id, reason=body.reason))}


@router.post("/{action_id}/reconcile")
@action_errors
def reconcile(action_id: str, principal: Principal = Depends(get_principal)) -> dict:
    return {"action": gateway.view(gateway.reconcile(action_id, principal=principal))}


@router.post("/{action_id}/retry")
@action_errors
def retry(action_id: str, principal: Principal = Depends(get_principal)) -> dict:
    return {"action": gateway.view(gateway.retry(principal, action_id))}


@router.post("/{action_id}/compensate")
@action_errors
def compensate(action_id: str, body: Reason, principal: Principal = Depends(get_principal)) -> dict:
    return {"action": gateway.view(gateway.compensate(principal, action_id, reason=body.reason or "compensation"))}
