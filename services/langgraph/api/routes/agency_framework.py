"""Agency operating framework API (``/agency-framework``).

The 295-task catalog is readable by any authenticated principal; everything
project-specific authenticates through ``get_principal`` and is scoped to the
principal's tenant and projects server-side (a plan elsewhere is a 404). Writes
require an ``Idempotency-Key``: a replay returns the first response, a different
body is a 409. Task writes also carry ``expected_version`` (compare-and-set).
Approvals of tasks and stage gates are decided at ``/approvals/{id}/decide``;
these routes only open and settle them. Nothing here publishes, sends, spends or
dispatches. Errors use the AMC envelope ``{detail, error: {code, ...}}``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Header, Query

from services.langgraph.agency.operating_framework import assurance, metrics, service
from services.langgraph.agency.operating_framework.contracts import (
    ApplicabilityRequest,
    DecisionRecordRequest,
    FrameworkError,
    InstantiatePlan,
    MeasurementRequest,
    RefsRequest,
    TransitionRequest,
    VersionedRequest,
)
from services.langgraph.core.errors import AMCError
from services.langgraph.persistence.idempotency import (
    complete_idempotency,
    fail_idempotency,
    hash_payload,
    reserve_idempotency,
)
from services.langgraph.security.auth import Principal, get_principal

router = APIRouter()
IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60


def _amc(exc: FrameworkError) -> AMCError:
    return AMCError(exc.message, code=exc.code, status=exc.status, details=exc.details)


def _call(fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except FrameworkError as exc:
        raise _amc(exc) from exc


def _idempotent(principal: Principal, operation: str, key: str, body: Any, run: Callable[[], Any]) -> Any:
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
    except FrameworkError as exc:
        fail_idempotency(scope, key, exc.code)
        raise _amc(exc) from exc
    except Exception as exc:
        fail_idempotency(scope, key, type(exc).__name__)
        raise
    complete_idempotency(scope, key, result)
    return result


# ------------------------------------------------------------------------------ catalog


@router.get("/catalog")
def get_catalog(principal: Principal = Depends(get_principal)):
    return service.catalog_view()


@router.get("/catalog/tasks")
def get_catalog_tasks(principal: Principal = Depends(get_principal)):
    return {"tasks": service.catalog_tasks()}


@router.get("/metrics/definitions")
def get_metric_definitions(principal: Principal = Depends(get_principal)):
    return {"metrics": metrics.definitions()}


# ------------------------------------------------------------------------------ plans


@router.post("/plans", status_code=201)
def create_plan(body: InstantiatePlan, idempotency_key: str = Header(..., alias="Idempotency-Key"),
                principal: Principal = Depends(get_principal)):
    """Instantiate the pinned catalog in a project. Idempotent per project: a repeat returns the existing plan."""
    return _idempotent(principal, "agency-framework.plan", idempotency_key, body.model_dump(mode="json"),
                       lambda: service.instantiate(principal, body))


@router.get("/plans")
def list_plans(project_id: str = Query(..., min_length=1), principal: Principal = Depends(get_principal)):
    return {"items": _call(lambda: service.plans_for(principal, project_id))}


@router.get("/plans/{plan_id}")
def get_plan(plan_id: str, principal: Principal = Depends(get_principal)):
    return _call(lambda: service.plan_view(principal, plan_id))


@router.get("/plans/{plan_id}/tasks")
def list_tasks(plan_id: str, module_id: str | None = Query(None, pattern=r"^AGM-\d{2}$"),
               state: str | None = None, applicability: str | None = None,
               q: str | None = Query(None, max_length=120), principal: Principal = Depends(get_principal)):
    return {"items": _call(lambda: service.task_list(principal, plan_id, module_id=module_id, state=state,
                                                     applicability=applicability, query=q))}


@router.get("/plans/{plan_id}/tasks/{task_id}")
def get_task(plan_id: str, task_id: str, principal: Principal = Depends(get_principal)):
    return _call(lambda: service.task_detail(principal, plan_id, task_id))


@router.post("/plans/{plan_id}/applicability")
def decide_applicability(plan_id: str, body: ApplicabilityRequest, idempotency_key: str = Header(..., alias="Idempotency-Key"),
                         principal: Principal = Depends(get_principal)):
    return _idempotent(principal, f"agency-framework.applicability:{plan_id}", idempotency_key, body.model_dump(mode="json"),
                       lambda: service.decide_applicability(principal, plan_id, body))


@router.post("/plans/{plan_id}/tasks/{task_id}/transition")
def transition(plan_id: str, task_id: str, body: TransitionRequest,
               idempotency_key: str = Header(..., alias="Idempotency-Key"), principal: Principal = Depends(get_principal)):
    return _idempotent(principal, f"agency-framework.transition:{plan_id}:{task_id}", idempotency_key,
                       body.model_dump(mode="json"), lambda: service.transition(principal, plan_id, task_id, body))


@router.post("/plans/{plan_id}/tasks/{task_id}/unblock")
def unblock(plan_id: str, task_id: str, body: VersionedRequest,
            idempotency_key: str = Header(..., alias="Idempotency-Key"), principal: Principal = Depends(get_principal)):
    return _idempotent(principal, f"agency-framework.unblock:{plan_id}:{task_id}", idempotency_key,
                       body.model_dump(mode="json"), lambda: service.unblock(principal, plan_id, task_id, body.expected_version))


@router.put("/plans/{plan_id}/tasks/{task_id}/refs")
def set_refs(plan_id: str, task_id: str, body: RefsRequest,
             idempotency_key: str = Header(..., alias="Idempotency-Key"), principal: Principal = Depends(get_principal)):
    return _idempotent(principal, f"agency-framework.refs:{plan_id}:{task_id}", idempotency_key,
                       body.model_dump(mode="json"), lambda: service.set_refs(principal, plan_id, task_id, body))


@router.post("/plans/{plan_id}/tasks/{task_id}/verify")
def verify(plan_id: str, task_id: str, body: VersionedRequest,
           idempotency_key: str = Header(..., alias="Idempotency-Key"), principal: Principal = Depends(get_principal)):
    """Server re-check of every ref by someone other than the submitter. A failed check is recorded, then a 422."""
    return _idempotent(principal, f"agency-framework.verify:{plan_id}:{task_id}", idempotency_key,
                       body.model_dump(mode="json"), lambda: service.verify(principal, plan_id, task_id, body.expected_version))


@router.post("/plans/{plan_id}/tasks/{task_id}/request-approval")
def request_task_approval(plan_id: str, task_id: str, body: VersionedRequest,
                          idempotency_key: str = Header(..., alias="Idempotency-Key"),
                          principal: Principal = Depends(get_principal)):
    return _idempotent(principal, f"agency-framework.request-approval:{plan_id}:{task_id}", idempotency_key,
                       body.model_dump(mode="json"),
                       lambda: service.request_task_approval(principal, plan_id, task_id, body.expected_version))


@router.post("/plans/{plan_id}/tasks/{task_id}/settle")
def settle(plan_id: str, task_id: str, body: VersionedRequest,
           idempotency_key: str = Header(..., alias="Idempotency-Key"), principal: Principal = Depends(get_principal)):
    """Apply the decision recorded at /approvals/{id}/decide, if it still matches the task's proof."""
    return _idempotent(principal, f"agency-framework.settle:{plan_id}:{task_id}", idempotency_key,
                       body.model_dump(mode="json"), lambda: service.settle_task(principal, plan_id, task_id, body.expected_version))


@router.post("/plans/{plan_id}/revalidate")
def revalidate(plan_id: str, idempotency_key: str = Header(..., alias="Idempotency-Key"),
               principal: Principal = Depends(get_principal)):
    return _idempotent(principal, f"agency-framework.revalidate:{plan_id}", idempotency_key, {"plan_id": plan_id},
                       lambda: service.revalidate(principal, plan_id))


@router.get("/plans/{plan_id}/gates")
def get_gates(plan_id: str, principal: Principal = Depends(get_principal)):
    return {"gates": _call(lambda: service.gates_view(principal, plan_id))}


@router.post("/plans/{plan_id}/gates/{stage_gate}/request-approval")
def request_gate_approval(plan_id: str, stage_gate: str, idempotency_key: str = Header(..., alias="Idempotency-Key"),
                          principal: Principal = Depends(get_principal)):
    return _idempotent(principal, f"agency-framework.gate:{plan_id}:{stage_gate}", idempotency_key,
                       {"plan_id": plan_id, "stage_gate": stage_gate},
                       lambda: service.request_gate_approval(principal, plan_id, stage_gate))


@router.post("/plans/{plan_id}/decisions", status_code=201)
def record_decision(plan_id: str, body: DecisionRecordRequest, idempotency_key: str = Header(..., alias="Idempotency-Key"),
                    principal: Principal = Depends(get_principal)):
    """Record a decision with its alternatives in the N4 kernel store; reference it as ``decision:<id>``."""
    return _idempotent(principal, f"agency-framework.decision:{plan_id}", idempotency_key, body.model_dump(mode="json"),
                       lambda: service.record_decision(principal, plan_id, body))


@router.post("/plans/{plan_id}/measurements", status_code=201)
def record_measurement(plan_id: str, body: MeasurementRequest, idempotency_key: str = Header(..., alias="Idempotency-Key"),
                       principal: Principal = Depends(get_principal)):
    """Record a measured KPI input as N4 kernel evidence. Synthetic sources stay labelled SYNTHETIC."""
    return _idempotent(principal, f"agency-framework.measurement:{plan_id}", idempotency_key, body.model_dump(mode="json"),
                       lambda: service.record_measurement(principal, plan_id, body))


@router.get("/plans/{plan_id}/audit")
def get_audit(plan_id: str, limit: int = Query(200, ge=1, le=1000), principal: Principal = Depends(get_principal)):
    return {"events": _call(lambda: service.audit(principal, plan_id, limit))}


@router.get("/plans/{plan_id}/metrics")
def get_metrics(plan_id: str, principal: Principal = Depends(get_principal)):
    return _call(lambda: metrics.plan_metrics(principal, plan_id))


# ------------------------------------------------------------------------------ assurance


@router.get("/plans/{plan_id}/assurance")
def list_assurance(plan_id: str, kind: str | None = Query(None, pattern=r"^(meaning|mutation|probe|renewal|review)$"),
                   principal: Principal = Depends(get_principal)):
    return {"items": _call(lambda: assurance.list_records(principal, plan_id, kind=kind))}


@router.get("/plans/{plan_id}/assurance/{record_id}")
def get_assurance(plan_id: str, record_id: str, principal: Principal = Depends(get_principal)):
    return _call(lambda: assurance.read_record(principal, plan_id, record_id))


@router.post("/plans/{plan_id}/assurance/{kind}", status_code=201)
def create_assurance(plan_id: str, kind: str, body: dict[str, Any], idempotency_key: str = Header(..., alias="Idempotency-Key"),
                     principal: Principal = Depends(get_principal)):
    """Record a Meaning, Mutation, Probe, Renewal or Review finding. Records are findings, never authority."""
    return _idempotent(principal, f"agency-framework.assurance:{plan_id}:{kind}", idempotency_key, {"kind": kind, **body},
                       lambda: assurance.create_record(principal, plan_id, kind, body))
