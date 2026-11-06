"""Operations on a project's agency framework plan, each scoped to a Principal.

Authority stays where it already is:

* tenant and project come from the authenticated principal; a plan in another
  tenant or project is ``PLAN_NOT_FOUND`` (no existence leak);
* refs resolve in their owning stores (``refs.py``); nothing is copied;
* ``verify`` is a server re-check of every ref by someone other than the person
  who submitted the work - a checkbox cannot verify;
* ``APPROVED`` is reachable only by settling an approval opened through
  ``open_artifact_approval`` and decided via ``/approvals/{id}/decide`` (approver
  role + separation of duties), bound to the task's proof hash;
* stage gates pass only through such an approval bound to the gate's evaluation
  hash, in gate order;
* no operation publishes, sends, spends or dispatches anything.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services.langgraph.agency.project_os.vocabulary import ActivityType
from services.langgraph.persistence import operating_framework as store
from services.langgraph.security.auth import Principal

from .bindings import MODULE_BINDINGS, binding
from .catalog import STAGE_GATES, Catalog, load_catalog
from .contracts import (
    MANUAL_TRANSITIONS,
    PIPELINE,
    POLICY_VERSION,
    REQUIRED_REF_KINDS,
    Applicability,
    ApplicabilityRequest,
    DecisionRecordRequest,
    FrameworkError,
    GateStatus,
    InstantiatePlan,
    MeasurementRequest,
    RefsRequest,
    TaskState,
    TransitionRequest,
)
from .engine import (
    evaluate_gate,
    overlay_gate_approval,
    predecessor,
    progress,
    task_proof_hash,
)
from .refs import resolve_ref

_LOCKED_FOR_APPLICABILITY = {TaskState.ACTIVE.value, TaskState.IN_REVIEW.value, TaskState.VERIFIED.value,
                             TaskState.APPROVED.value, TaskState.BLOCKED.value, TaskState.INVALIDATED.value}
_EVENT_FOR_TARGET = {
    TaskState.ACTIVE.value: ActivityType.WORK_STARTED,
    TaskState.BLOCKED.value: ActivityType.QA_BLOCKED,
    TaskState.INVALIDATED.value: ActivityType.QA_BLOCKED,
    TaskState.VERIFIED.value: ActivityType.VERIFIED,
    TaskState.APPROVED.value: ActivityType.APPROVED,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _catalog() -> Catalog:
    return load_catalog()


# ------------------------------------------------------------------------------ scope


def _plan_for(principal: Principal, plan_id: str) -> dict:
    plan = store.get_plan(plan_id)
    if plan is None or plan["tenant_id"] != principal.tenant_id or not principal.can_access_project(plan["project_id"]):
        raise FrameworkError("PLAN_NOT_FOUND", "Plan not found", 404)
    return plan


def _task_for(plan: dict, task_id: str) -> dict:
    task = store.get_task(plan["plan_id"], task_id)
    if task is None:
        raise FrameworkError("TASK_NOT_FOUND", f"Task {task_id} is not in this plan", 404)
    return task


def _adapter():
    from services.langgraph.api.routes._project_common import storage_adapter

    return storage_adapter()


def _update(plan: dict, task: dict, *, expected_version: int, actor: str, changes: dict, event: ActivityType,
            payload: dict) -> dict:
    try:
        return store.update_task(plan["plan_id"], task["task_id"], expected_version=expected_version, actor=actor,
                                 changes=changes, event_type=event, event_payload=payload)
    except store.StaleTaskVersion as exc:
        raise FrameworkError("STALE_VERSION", str(exc), 409,
                             {"task_id": exc.task_id, "expected": exc.expected, "actual": exc.actual}) from exc


# ------------------------------------------------------------------------------ catalog


def catalog_view() -> dict[str, Any]:
    catalog = _catalog()
    return {
        **catalog.summary(),
        "stage_gates": dict(catalog.stage_gates),
        "modules": [
            {**_module_dict(m), "binding": _binding_dict(m.module_id)} for m in catalog.modules
        ],
    }


def catalog_tasks() -> list[dict[str, Any]]:
    return [_definition_dict(t) for t in _catalog().tasks]


def _module_dict(m) -> dict[str, Any]:
    return {"module_id": m.module_id, "title": m.title, "phase": m.phase, "stage_gate": m.stage_gate,
            "expected_task_count": m.expected_task_count, "depends_on_modules": list(m.depends_on_modules),
            "required_deliverable": m.required_deliverable, "owner_role": m.owner_role,
            "acceptance_policy": m.acceptance_policy}


def _binding_dict(module_id: str) -> dict[str, Any]:
    b = binding(module_id)
    return {"n3_role": b.n3_role, "artifact_type": b.artifact_type, "coverage": b.coverage,
            "native_owner": b.native_owner, "capability": b.capability, "external_effect": b.external_effect,
            "note": b.note}


def _definition_dict(t) -> dict[str, Any]:
    return {"task_id": t.task_id, "module_id": t.module_id, "sequence": t.sequence, "title": t.title,
            "definition_source": t.definition_source, "owner_role": t.owner_role, "phase": t.phase,
            "stage_gate": t.stage_gate, "depends_on_modules": list(t.depends_on_modules),
            "output_class": t.output_class, "module_deliverable": t.module_deliverable, "acceptance": t.acceptance}


# ------------------------------------------------------------------------------ plans


def instantiate(principal: Principal, req: InstantiatePlan) -> dict[str, Any]:
    from services.langgraph.persistence.projects import get_project_workspace

    if not principal.can_access_project(req.project_id):
        raise FrameworkError("PROJECT_FORBIDDEN", "Project is outside the authenticated principal scope", 403)
    workspace = get_project_workspace(req.project_id)
    if workspace is None or workspace.tenant_id != principal.tenant_id:
        raise FrameworkError("PROJECT_NOT_FOUND", "Create the project workspace first", 404)
    catalog = _catalog()
    plan, created = store.instantiate_plan(
        tenant_id=principal.tenant_id, project_id=req.project_id, catalog=catalog, archetype=req.archetype.value,
        engagement_scope=req.engagement_scope, actor=principal.user_id,
        assignee_roles={mid: b.n3_role for mid, b in MODULE_BINDINGS.items()},
    )
    return {**plan_view(principal, plan["plan_id"]), "created": created}


def plans_for(principal: Principal, project_id: str) -> list[dict]:
    if not principal.can_access_project(project_id):
        raise FrameworkError("PROJECT_FORBIDDEN", "Project is outside the authenticated principal scope", 403)
    return [p for p in store.plans_for_project(project_id) if p["tenant_id"] == principal.tenant_id]


def plan_view(principal: Principal, plan_id: str) -> dict[str, Any]:
    plan = _plan_for(principal, plan_id)
    catalog = _catalog()
    tasks = store.list_tasks(plan_id)
    gates = _gates(plan, tasks)
    return {
        "plan": plan,
        "catalog": {"catalog_id": catalog.catalog_id, "catalog_version": catalog.catalog_version,
                    "sha256": catalog.sha256, "pinned": plan["catalog_sha256"] == catalog.sha256},
        "progress": progress(catalog, tasks),
        "gates": gates,
        "readiness": _readiness(tasks, gates),
    }


def _readiness(tasks: list[dict], gates: list[dict]) -> dict[str, Any]:
    required = [t for t in tasks if t["applicability"] == Applicability.REQUIRED.value]
    verified = bool(required) and all(t["state"] in (TaskState.VERIFIED.value, TaskState.APPROVED.value) for t in required)
    approved = bool(required) and all(t["state"] == TaskState.APPROVED.value for t in required)
    all_gates = all(g["status"] == GateStatus.PASSED.value for g in gates)
    return {
        "tasks_specified": len(tasks),
        "required_tasks": len(required),
        "required_verified": verified,
        "required_approved": approved,
        "all_gates_passed": all_gates,
        "synthetic_evidence_present": any(g.get("synthetic_only") or "SYNTHETIC" in g.get("evidence_origins", []) for g in gates),
        # Owned elsewhere and never inferred from task progress:
        "release_eligible": False,
        "release_eligibility_owner": "delivery release predicate on a sealed candidate (agency/delivery)",
        "externally_executed": False,
        "external_actions": "disabled: publication dry-run, paid media planning-only, no CRM send, no outreach",
    }


# ------------------------------------------------------------------------------ tasks


def task_list(principal: Principal, plan_id: str, *, module_id: str | None = None, state: str | None = None,
              applicability: str | None = None, query: str | None = None) -> list[dict[str, Any]]:
    plan = _plan_for(principal, plan_id)
    catalog = _catalog()
    needle = (query or "").strip().lower()
    out = []
    for task in store.list_tasks(plan["plan_id"], module_id=module_id):
        if state and task["state"] != state:
            continue
        if applicability and task["applicability"] != applicability:
            continue
        definition = catalog.task(task["task_id"])
        if needle and needle not in f"{definition.task_id} {definition.title} {definition.owner_role}".lower():
            continue
        out.append(_task_row(task, definition))
    return out


def _task_row(task: dict, definition) -> dict[str, Any]:
    return {
        "task_id": task["task_id"], "module_id": task["module_id"], "stage_gate": task["stage_gate"],
        "title": definition.title, "phase": definition.phase, "output_class": definition.output_class,
        "definition_source": definition.definition_source, "owner_role": definition.owner_role,
        "assignee_role": task["assignee_role"], "applicability": task["applicability"], "state": task["state"],
        "status_reason": task.get("status_reason"), "version": task["version"],
        "ref_count": len(task["evidence_refs"]) + len(task["artifact_refs"]) + len(task["decision_refs"]),
        "approval_ref": task.get("approval_ref"), "updated_at": task["updated_at"],
    }


def task_detail(principal: Principal, plan_id: str, task_id: str) -> dict[str, Any]:
    plan = _plan_for(principal, plan_id)
    task = _task_for(plan, task_id)
    catalog = _catalog()
    definition = catalog.task(task_id)
    checks = _checks(plan, task)
    downstream = sorted(m.module_id for m in catalog.modules if definition.module_id in m.depends_on_modules)
    upstream_state = {}
    all_tasks = store.list_tasks(plan_id)
    for mid in definition.depends_on_modules:
        mod_tasks = [t for t in all_tasks if t["module_id"] == mid and t["applicability"] == Applicability.REQUIRED.value]
        upstream_state[mid] = {
            "required": len(mod_tasks),
            "verified": sum(1 for t in mod_tasks if t["state"] in (TaskState.VERIFIED.value, TaskState.APPROVED.value)),
        }
    approval = None
    if task.get("approval_ref"):
        from services.langgraph.persistence.approvals import get_approval

        found = get_approval(task["approval_ref"])
        if found:
            approval = {k: found.get(k) for k in ("approval_id", "status", "decision", "reviewer", "subject_hash", "stale_reason")}
    events = [e for e in store.framework_events(plan["project_id"], plan_id, limit=500)
              if (e.get("payload") or {}).get("task_id") == task_id][:50]
    return {
        "definition": _definition_dict(definition),
        "binding": _binding_dict(definition.module_id),
        "instance": task,
        "ref_checks": checks,
        "required_ref_kinds": list(REQUIRED_REF_KINDS[definition.output_class]),
        "upstream_modules": upstream_state,
        "downstream_modules": downstream,
        "approval": approval,
        "events": events,
    }


def _checks(plan: dict, task: dict) -> list[dict]:
    refs = [*task["evidence_refs"], *task["decision_refs"], *task["artifact_refs"]]
    if not refs:
        return []
    adapter = _adapter() if task["artifact_refs"] else None
    now = _now()
    return [resolve_ref(r, tenant_id=plan["tenant_id"], project_id=plan["project_id"], adapter=adapter, now=now) for r in refs]


def decide_applicability(principal: Principal, plan_id: str, req: ApplicabilityRequest) -> dict[str, Any]:
    plan = _plan_for(principal, plan_id)
    applied, skipped = [], []
    for item in req.decisions:
        task = _task_for(plan, item.task_id)
        if task["state"] in _LOCKED_FOR_APPLICABILITY:
            skipped.append({"task_id": item.task_id, "code": "TASK_IN_PROGRESS",
                            "detail": f"applicability is locked while the task is {task['state']}"})
            continue
        value = item.applicability.value
        if value == Applicability.UNASSESSED.value:
            skipped.append({"task_id": item.task_id, "code": "INVALID_DECISION", "detail": "a decision cannot reset to UNASSESSED"})
            continue
        if value == Applicability.NOT_APPLICABLE.value:
            state = TaskState.NOT_APPLICABLE.value
        elif task["state"] == TaskState.NOT_APPLICABLE.value:
            state = TaskState.BACKLOG.value
        else:
            state = task["state"]
        try:
            updated = _update(plan, task, expected_version=task["version"], actor=principal.user_id,
                              changes={"applicability": value, "applicability_reason": item.reason,
                                       "applicability_by": principal.user_id, "state": state},
                              event=ActivityType.COMMENT,
                              payload={"kind": "agency_framework.applicability", "applicability": value,
                                       "reason": item.reason})
            applied.append({"task_id": item.task_id, "applicability": value, "state": updated["state"],
                            "version": updated["version"]})
        except FrameworkError as exc:
            skipped.append({"task_id": item.task_id, "code": exc.code, "detail": exc.message})
    return {"applied": applied, "skipped": skipped}


def transition(principal: Principal, plan_id: str, task_id: str, req: TransitionRequest) -> dict[str, Any]:
    plan = _plan_for(principal, plan_id)
    task = _task_for(plan, task_id)
    target = req.target.value
    current = task["state"]
    if task["version"] != req.expected_version:
        raise FrameworkError("STALE_VERSION", f"{task_id} is at version {task['version']}, not {req.expected_version}", 409,
                             {"task_id": task_id, "expected": req.expected_version, "actual": task["version"]})
    if target not in MANUAL_TRANSITIONS.get(current, ()):
        code = "TRANSITION_NOT_MANUAL" if target in (TaskState.VERIFIED.value, TaskState.APPROVED.value,
                                                     TaskState.INVALIDATED.value, TaskState.NOT_APPLICABLE.value) \
            else "TRANSITION_NOT_ALLOWED"
        raise FrameworkError(code, f"{current} -> {target} is not a manual transition", 409,
                             {"from": current, "to": target, "allowed": list(MANUAL_TRANSITIONS.get(current, ()))})
    changes: dict[str, Any] = {"state": target, "status_reason": req.reason or None}
    if target == TaskState.READY.value and task["applicability"] not in (Applicability.REQUIRED.value, Applicability.CONDITIONAL.value):
        raise FrameworkError("APPLICABILITY_UNDECIDED", "Decide whether the task applies before starting it", 409)
    if target == TaskState.BLOCKED.value:
        if not req.reason.strip():
            raise FrameworkError("REASON_REQUIRED", "Say why the task is blocked", 422)
        changes["blocked_from"] = current
    if target == TaskState.IN_REVIEW.value:
        definition = _catalog().task(task_id)
        kinds = {"evidence": bool(task["evidence_refs"]), "decision": bool(task["decision_refs"]),
                 "artifact": bool(task["artifact_refs"])}
        missing = [k for k in REQUIRED_REF_KINDS[definition.output_class] if not kinds[k]]
        if missing:
            raise FrameworkError("REFS_REQUIRED", f"A {definition.output_class} task needs {', '.join(missing)} refs before review",
                                 422, {"missing": missing, "present": sorted(k for k, v in kinds.items() if v)})
        unusable = [c for c in _checks(plan, task) if not c["attachable"]]
        if unusable:
            raise FrameworkError("REF_REJECTED", "Some refs no longer resolve in this project", 422, {"checks": unusable})
        changes["submitted_by"] = principal.user_id
        changes["verification"] = None
    if current in (TaskState.VERIFIED.value, TaskState.IN_REVIEW.value) and target == TaskState.ACTIVE.value:
        changes["verification"] = None
        changes["approval_ref"] = None
    updated = _update(plan, task, expected_version=req.expected_version, actor=principal.user_id, changes=changes,
                      event=_EVENT_FOR_TARGET.get(target, ActivityType.COMMENT),
                      payload={"kind": "agency_framework.transition", "from": current, "to": target, "reason": req.reason})
    return updated


def unblock(principal: Principal, plan_id: str, task_id: str, expected_version: int) -> dict[str, Any]:
    plan = _plan_for(principal, plan_id)
    task = _task_for(plan, task_id)
    if task["state"] != TaskState.BLOCKED.value:
        raise FrameworkError("NOT_BLOCKED", "Task is not blocked", 409)
    restore = task.get("blocked_from") or TaskState.BACKLOG.value
    return _update(plan, task, expected_version=expected_version, actor=principal.user_id,
                   changes={"state": restore, "blocked_from": None, "status_reason": None}, event=ActivityType.COMMENT,
                   payload={"kind": "agency_framework.unblocked", "to": restore})


def set_refs(principal: Principal, plan_id: str, task_id: str, req: RefsRequest) -> dict[str, Any]:
    plan = _plan_for(principal, plan_id)
    task = _task_for(plan, task_id)
    if task["state"] not in (TaskState.READY.value, TaskState.ACTIVE.value, TaskState.INVALIDATED.value):
        raise FrameworkError("REFS_LOCKED", f"Refs can change only while the task is READY or ACTIVE (it is {task['state']})", 409)
    probe = {**task, "evidence_refs": req.evidence_refs, "artifact_refs": req.artifact_refs, "decision_refs": req.decision_refs}
    checks = _checks(plan, probe)
    unusable = [c for c in checks if not c["attachable"]]
    if unusable:
        raise FrameworkError("REF_REJECTED", "Refs must exist in this project and be readable", 422, {"checks": unusable})
    return _update(plan, task, expected_version=req.expected_version, actor=principal.user_id,
                   changes={"evidence_refs": req.evidence_refs, "artifact_refs": req.artifact_refs,
                            "decision_refs": req.decision_refs}, event=ActivityType.COMMENT,
                   payload={"kind": "agency_framework.refs", "evidence_refs": req.evidence_refs,
                            "artifact_refs": req.artifact_refs, "decision_refs": req.decision_refs})


def verify(principal: Principal, plan_id: str, task_id: str, expected_version: int) -> dict[str, Any]:
    from services.langgraph.security.approval_authority import approver_roles

    plan = _plan_for(principal, plan_id)
    task = _task_for(plan, task_id)
    if task["state"] != TaskState.IN_REVIEW.value:
        raise FrameworkError("NOT_IN_REVIEW", f"Only a task in review can be verified (it is {task['state']})", 409)
    if principal.role.strip().lower() not in approver_roles():
        raise FrameworkError("VERIFIER_ROLE_REQUIRED", "Verifying work requires an approver role", 403)
    if task.get("submitted_by") == principal.user_id:
        raise FrameworkError("SELF_VERIFICATION", "The person who submitted the work cannot verify it", 403)
    checks = _checks(plan, task)
    failed = [c for c in checks if not c["ok"]]
    record = {"verified_by": principal.user_id, "at": _now().isoformat(), "checks": checks,
              "origins": sorted({c["origin"] for c in checks if c.get("origin")})}
    if failed or not checks:
        record["result"] = "FAILED"
        _update(plan, task, expected_version=expected_version, actor=principal.user_id,
                changes={"verification": record, "status_reason": "verification failed"}, event=ActivityType.QA_BLOCKED,
                payload={"kind": "agency_framework.verification_failed", "failed": [c["ref"] for c in failed]})
        raise FrameworkError("VERIFICATION_FAILED", "One or more refs failed the server re-check", 422,
                             {"checks": failed or [{"detail": "no refs"}]})
    record["result"] = "PASSED"
    record["proof_hash"] = task_proof_hash(plan, task, checks)
    return _update(plan, task, expected_version=expected_version, actor=principal.user_id,
                   changes={"state": TaskState.VERIFIED.value, "verification": record, "status_reason": None},
                   event=ActivityType.VERIFIED,
                   payload={"kind": "agency_framework.verified", "proof_hash": record["proof_hash"],
                            "origins": record["origins"]})


def _subject_ref(plan: dict, task_id: str) -> str:
    return f"agency-task:{plan['plan_id']}:{task_id}"


def request_task_approval(principal: Principal, plan_id: str, task_id: str, expected_version: int) -> dict[str, Any]:
    from services.langgraph.agency.intake.release import open_artifact_approval

    plan = _plan_for(principal, plan_id)
    task = _task_for(plan, task_id)
    if task["state"] != TaskState.VERIFIED.value:
        raise FrameworkError("NOT_VERIFIED", "Only a verified task can be submitted for approval", 409)
    checks = _checks(plan, task)
    proof = task_proof_hash(plan, task, checks)
    if any(not c["ok"] for c in checks) or proof != (task.get("verification") or {}).get("proof_hash"):
        _invalidate(plan, task, principal.user_id, "refs changed since verification")
        raise FrameworkError("VERIFICATION_STALE", "The task's refs changed since it was verified; it was invalidated", 409)
    approval = open_artifact_approval(
        principal, tenant_id=plan["tenant_id"], project_id=plan["project_id"],
        mission_id=f"{plan_id}:{task_id}:{proof[:16]}:{task['version']}", contract_hash=plan["catalog_sha256"],
        artifact_id=_subject_ref(plan, task_id), version=int(task["version"]), content_hash=proof,
        run_pipeline=PIPELINE, policy_version=POLICY_VERSION, subject_type="AGENCY_TASK",
        reason=f"Approve {task_id}: {_catalog().task(task_id).title}",
        metadata={"plan_id": plan_id, "task_id": task_id},
    )
    return _update(plan, task, expected_version=expected_version, actor=principal.user_id,
                   changes={"approval_ref": approval["approval_id"]}, event=ActivityType.COMMENT,
                   payload={"kind": "agency_framework.approval_requested", "approval_id": approval["approval_id"],
                            "subject_hash": proof})


def settle_task(principal: Principal, plan_id: str, task_id: str, expected_version: int) -> dict[str, Any]:
    from services.langgraph.persistence.approvals import (
        get_approval,
        mark_approval_stale,
    )

    plan = _plan_for(principal, plan_id)
    task = _task_for(plan, task_id)
    if task["state"] == TaskState.APPROVED.value:
        return task
    if task["state"] != TaskState.VERIFIED.value or not task.get("approval_ref"):
        raise FrameworkError("NO_APPROVAL_REQUESTED", "Request an approval for the verified task first", 409)
    approval = get_approval(task["approval_ref"])
    if approval is None or (approval["tenant_id"], approval["project_id"]) != (plan["tenant_id"], plan["project_id"]):
        raise FrameworkError("APPROVAL_NOT_FOUND", "The task's approval was not found in this project", 409)
    if approval.get("subject_ref") != _subject_ref(plan, task_id):
        raise FrameworkError("APPROVAL_SUBJECT_MISMATCH", "The approval is for a different subject", 409)
    if approval["status"] == "stale":
        raise FrameworkError("APPROVAL_STALE", "The approval is stale; request a new one", 409)
    if approval["status"] != "resolved":
        raise FrameworkError("APPROVAL_PENDING", "The approval has not been decided", 409)
    if approval["decision"] != "approve":
        return _update(plan, task, expected_version=expected_version, actor=principal.user_id,
                       changes={"state": TaskState.ACTIVE.value, "approval_ref": None, "verification": None,
                                "status_reason": f"approval rejected by {approval.get('reviewer')}"},
                       event=ActivityType.REJECTED,
                       payload={"kind": "agency_framework.approval_rejected", "approval_id": approval["approval_id"]})
    checks = _checks(plan, task)
    proof = task_proof_hash(plan, task, checks)
    if any(not c["ok"] for c in checks) or proof != approval.get("subject_hash"):
        mark_approval_stale(approval["approval_id"], "task proof changed after approval")
        _invalidate(plan, task, principal.user_id, "proof changed after approval; the approval was marked stale")
        raise FrameworkError("APPROVAL_SUBJECT_STALE", "The task's proof no longer matches the approved subject", 409)
    return _update(plan, task, expected_version=expected_version, actor=principal.user_id,
                   changes={"state": TaskState.APPROVED.value, "status_reason": None}, event=ActivityType.APPROVED,
                   payload={"kind": "agency_framework.approved", "approval_id": approval["approval_id"],
                            "reviewer": approval.get("reviewer"), "subject_hash": proof})


def _invalidate(plan: dict, task: dict, actor: str, reason: str) -> dict:
    fresh = store.get_task(plan["plan_id"], task["task_id"]) or task
    return _update(plan, fresh, expected_version=fresh["version"], actor=actor,
                   changes={"state": TaskState.INVALIDATED.value, "status_reason": reason},
                   event=ActivityType.QA_BLOCKED, payload={"kind": "agency_framework.invalidated", "reason": reason})


def revalidate(principal: Principal, plan_id: str) -> dict[str, Any]:
    """Re-resolve the refs of every task in review, verified or approved; a task
    whose evidence expired or whose artifact moved on is INVALIDATED, and its
    pending approval is marked stale. Nothing is re-verified automatically."""
    from services.langgraph.persistence.approvals import (
        get_approval,
        mark_approval_stale,
    )

    plan = _plan_for(principal, plan_id)
    invalidated = []
    for task in store.list_tasks(plan_id):
        if task["state"] not in (TaskState.IN_REVIEW.value, TaskState.VERIFIED.value, TaskState.APPROVED.value):
            continue
        checks = _checks(plan, task)
        failed = [c for c in checks if not c["ok"]]
        proof = task_proof_hash(plan, task, checks)
        expected = (task.get("verification") or {}).get("proof_hash")
        if not failed and (expected is None or proof == expected):
            continue
        if task.get("approval_ref"):
            approval = get_approval(task["approval_ref"])
            if approval and approval["status"] == "pending":
                mark_approval_stale(approval["approval_id"], "task refs changed")
        reason = "; ".join(f"{c['ref']}: {c['status']}" for c in failed) or "refs resolve to different content"
        _invalidate(plan, task, principal.user_id, reason)
        invalidated.append({"task_id": task["task_id"], "reason": reason})
    return {"invalidated": invalidated, "staled_review_approvals": _stale_review_approvals(principal, plan)}


def _stale_review_approvals(principal: Principal, plan: dict) -> list[str]:
    """A pending review decision whose candidates moved on can no longer be decided."""
    from services.langgraph.persistence.approvals import (
        get_approval,
        mark_approval_stale,
    )

    from .assurance import list_records_raw, read_record

    staled = []
    for record in list_records_raw(plan, kinds=("review",)):
        approval_id = (record.get("body") or {}).get("decision_ref")
        if not approval_id:
            continue
        approval = get_approval(approval_id)
        if not approval or approval.get("status") != "pending":
            continue
        now = read_record(principal, plan["plan_id"], record["record_id"])
        if not (now.get("subject_now") or {}).get("subject_current", False):
            mark_approval_stale(approval_id, "review candidates changed after the review was prepared")
            staled.append(approval_id)
    return staled


# ------------------------------------------------------------------------------ gates


def _gate_ref(plan: dict, gate: str) -> str:
    return f"agency-gate:{plan['plan_id']}:{gate}"


def _gates(plan: dict, tasks: list[dict]) -> list[dict]:
    from services.langgraph.persistence.approvals import list_approvals_for_subject_refs

    approvals = list_approvals_for_subject_refs(plan["project_id"], [_gate_ref(plan, g) for g in STAGE_GATES])
    out: list[dict] = []
    passed: dict[str, bool] = {}
    for gate in STAGE_GATES:
        evaluation = evaluate_gate(plan, gate, tasks)
        before = predecessor(gate)
        gate_approvals = [a for a in approvals if a.get("subject_ref") == _gate_ref(plan, gate)]
        result = overlay_gate_approval(evaluation, gate_approvals, predecessor_passed=before is None or passed.get(before, False))
        result["criteria"] = _catalog().stage_gates[gate]
        passed[gate] = result["status"] == GateStatus.PASSED.value
        out.append(result)
    return out


def gates_view(principal: Principal, plan_id: str) -> list[dict]:
    plan = _plan_for(principal, plan_id)
    return _gates(plan, store.list_tasks(plan_id))


def request_gate_approval(principal: Principal, plan_id: str, gate: str) -> dict[str, Any]:
    from services.langgraph.agency.intake.release import open_artifact_approval

    plan = _plan_for(principal, plan_id)
    if gate not in STAGE_GATES:
        raise FrameworkError("UNKNOWN_GATE", f"Unknown stage gate {gate}", 404)
    gates = {g["stage_gate"]: g for g in _gates(plan, store.list_tasks(plan_id))}
    current = gates[gate]
    before = predecessor(gate)
    if before and gates[before]["status"] != GateStatus.PASSED.value:
        raise FrameworkError("PREDECESSOR_GATE_NOT_PASSED", f"{before} has not passed", 409)
    if current["status"] not in (GateStatus.NEEDS_HUMAN.value, GateStatus.STALE.value):
        raise FrameworkError("GATE_NOT_READY", f"{gate} is {current['status']}", 409,
                             {"unmet": current["unmet"], "unassessed": current["unassessed"]})
    approval = open_artifact_approval(
        principal, tenant_id=plan["tenant_id"], project_id=plan["project_id"],
        mission_id=f"{plan_id}:{gate}:{current['evaluation_hash'][:16]}", contract_hash=plan["catalog_sha256"],
        artifact_id=_gate_ref(plan, gate), version=1, content_hash=current["evaluation_hash"], run_pipeline=PIPELINE,
        policy_version=POLICY_VERSION, subject_type="AGENCY_STAGE_GATE",
        reason=f"Stage gate {gate}: {_catalog().stage_gates[gate]}",
        metadata={"plan_id": plan_id, "stage_gate": gate, "synthetic_only": current["synthetic_only"]},
    )
    return {"approval": {k: approval.get(k) for k in ("approval_id", "status", "subject_hash")}, "gate": gate,
            "evaluation_hash": current["evaluation_hash"]}


def record_decision(principal: Principal, plan_id: str, req: DecisionRecordRequest) -> dict[str, Any]:
    """A decision in the N4 kernel store (alternatives kept), referenced as ``decision:<id>``."""
    from uuid import uuid4

    from services.langgraph.persistence.agency_kernel import create_decision
    from services.langgraph.persistence.projects import project_engagement_id

    plan = _plan_for(principal, plan_id)
    if req.selected_option not in req.alternatives:
        raise FrameworkError("INVALID_DECISION", "The selected option must be one of the alternatives", 422)
    checks = [resolve_ref(r, tenant_id=plan["tenant_id"], project_id=plan["project_id"]) for r in req.evidence_refs]
    bad = [c for c in checks if not c["attachable"]]
    if bad:
        raise FrameworkError("REF_REJECTED", "Evidence must exist in this project", 422, {"checks": bad})
    decision_id = f"dec-{uuid4().hex[:20]}"
    record = create_decision(
        decision_id, project_engagement_id(plan["project_id"]), plan["tenant_id"], plan["project_id"], req.question,
        {"basis": "recorded by a person; not a measured confidence"}, alternatives=req.alternatives,
        selected_option=req.selected_option, evidence_ids=req.evidence_refs, assumptions=req.assumptions, status="proposed")
    return {"decision_ref": f"decision:{decision_id}", "decision": record}


def record_measurement(principal: Principal, plan_id: str, req: MeasurementRequest) -> dict[str, Any]:
    """A measured KPI input as N4 kernel evidence. Only an approver's entry counts as verified."""
    from uuid import uuid4

    from services.langgraph.persistence.agency_kernel import create_evidence
    from services.langgraph.persistence.projects import project_engagement_id
    from services.langgraph.security.approval_authority import approver_roles

    from .metrics import DEFINITIONS

    plan = _plan_for(principal, plan_id)
    known = {name for d in DEFINITIONS for name in d.inputs}
    if req.metric_input not in known:
        raise FrameworkError("UNKNOWN_METRIC_INPUT", f"{req.metric_input} is not an input of any KPI", 422,
                             {"known": sorted(known)})
    attested = principal.role.strip().lower() in approver_roles()
    evidence_id = f"msr-{uuid4().hex[:20]}"
    record = create_evidence(
        evidence_id, project_engagement_id(plan["project_id"]), plan["tenant_id"], plan["project_id"], "measurement",
        req.claim or f"{req.metric_input} = {req.value} {req.unit} ({req.window})",
        "verified" if attested else "unverified", 1.0 if attested else 0.0, source_ref=req.source_ref,
        payload={"metric_input": req.metric_input, "value": req.value, "unit": req.unit, "window": req.window},
        metadata={"recorded_by": principal.user_id})
    return {"evidence_ref": f"evidence:{evidence_id}", "evidence": record, "attested": attested}


def audit(principal: Principal, plan_id: str, limit: int = 200) -> list[dict]:
    plan = _plan_for(principal, plan_id)
    return store.framework_events(plan["project_id"], plan_id, limit=limit)


__all__ = [
    "audit", "catalog_tasks", "catalog_view", "decide_applicability", "gates_view", "instantiate", "plan_view",
    "plans_for", "request_gate_approval", "request_task_approval", "revalidate", "set_refs", "settle_task",
    "task_detail", "task_list", "transition", "unblock", "verify",
]
