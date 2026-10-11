"""Mission Builder: a plain-English brief → an editable, inspectable plan → governed local work.

``preview`` composes the existing intake pieces without executing anything:
``compile_intent`` → ``resolve_project`` → ``compile_context`` → the compiled
planner (``runner._plan``). It returns the work DAG with each node's real
state and blockers, the external effects the brief mentions (always
non-dispatched here, each mapped to its catalogue entry and risk class), the
acceptance criteria (Outcome Compiler) and the cost basis.

``launch`` is ``intake.runner.run_mission`` unchanged. It executes LOCAL work
through the execution fabric, verifies the stored bytes, opens a hash-bound
approval, and never publishes, spends or sends.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from services.langgraph.agency.actions import broker
from services.langgraph.agency.actions.catalog import UnknownAction, catalog
from services.langgraph.agency.actions.vocabulary import STATUS_LABELS
from services.langgraph.security.auth import Principal

# The brief's external effects and the catalogue entries that would carry them.
EFFECT_ACTIONS = {"PUBLISH": "publication.publish", "SPEND": "paid_media.execute_spend", "SEND": "sandbox.email.send"}

DELIVERABLE_CHECKS = {
    "VECTOR_MARK": ("sha256 of the stored bytes equals the recorded hash", "root <svg> has a viewBox",
                    "svg_safety: no scripts, external references or event handlers",
                    "every colour is within ΔE76 of the approved palette"),
    "DESIGN_TOKENS": ("sha256 of the stored bytes equals the recorded hash",
                      "no independent token verifier is wired into intake yet: verification reports INCONCLUSIVE"),
    "RASTER_IMAGE": ("no image provider is installed: the work plans as PROVIDER_GAP",),
    "GENERATED_VIDEO": ("no video provider is installed: the work plans as PROVIDER_GAP",),
}


def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


def _label(state: str) -> str:
    return STATUS_LABELS.get(state, state.replace("_", " ").capitalize())


def preview(principal: Principal, *, brief: str, project_id: str, now: Optional[datetime] = None) -> dict[str, Any]:
    from services.langgraph.agency.execution_fabric.contracts import dominant_state
    from services.langgraph.agency.intake.context import compile_context, project_fingerprint
    from services.langgraph.agency.intake.intent import compile_intent
    from services.langgraph.agency.intake.resolver import resolve_project
    from services.langgraph.agency.intake.runner import (
        BRAND_AUTHORITY_FLOOR,
        BRAND_SUBJECT,
        ROUTES,
        _existing_inputs,
        _plan,
        _predicates,
    )

    moment = _now(now)
    broker.authorize_scope(principal, project_id, write=True)
    intent = compile_intent(brief)
    resolution = resolve_project(principal, intent, active_project_id=project_id, now=moment)
    effects = []
    for effect in intent.side_effects:
        action_id = EFFECT_ACTIONS[effect.value]
        try:
            d = catalog().get(action_id)
            risk = d.nominal_risk()
            effects.append({"effect": effect.value, "capability_id": d.id, "risk": risk.effective.value,
                            "status": d.status.value, "status_label": _label(d.status.value),
                            "dispatch": "NOT_DISPATCHED: a separate governed action with its own approval is required"})
        except UnknownAction:
            effects.append({"effect": effect.value, "capability_id": None, "risk": None, "status": "NOT_IMPLEMENTED",
                            "status_label": _label("NOT_IMPLEMENTED"), "dispatch": "NOT_DISPATCHED"})
    base: dict[str, Any] = {
        "preview": True, "label": "PREVIEW: nothing was executed",
        "intent": {"deliverable": intent.deliverable.value if intent.deliverable else None, "mode": intent.mode.value,
                   "utterance_type": intent.utterance_type.value, "request_hash": intent.request_hash,
                   "clarifications": list(intent.clarifications),
                   "facts": [f.model_dump(mode="json") for f in intent.facts]},
        "project": {"status": resolution.status, "project_id": resolution.project_id, "reasons": list(resolution.reasons)},
        "external_effects": effects,
        "acceptance_criteria": [p.model_dump(mode="json") for p in _predicates(intent.side_effects)],
        "cost": {"currency": None, "amount_minor": 0, "basis": "local execution on this host; no provider is called"},
        "live_execution": "DISABLED",
    }
    if resolution.status != "BOUND" or resolution.project_id != project_id:
        return {**base, "outcome": "NEEDS_CLARIFICATION", "reasons": [f"PROJECT_{resolution.status}", *resolution.reasons],
                "nodes": [], "edges": []}
    if intent.deliverable is None:
        return {**base, "outcome": "NEEDS_CLARIFICATION", "reasons": ["DELIVERABLE_UNKNOWN", *intent.clarifications],
                "nodes": [], "edges": []}
    artifact_type, skill_id = ROUTES[intent.deliverable]
    capability = catalog().get(f"fabric.{skill_id}")
    capsule, receipt = compile_context(tenant_id=principal.tenant_id, project_id=project_id,
                                       subjects={BRAND_SUBJECT: BRAND_AUTHORITY_FLOOR}, now=moment,
                                       fingerprint=project_fingerprint(project_id, exclude_types=(artifact_type,)))
    brand_choice = next((c for c in receipt.choices if c.subject_key == BRAND_SUBJECT), None)
    brand_ok = BRAND_SUBJECT in capsule.memory
    schedule = _plan(project_id, artifact_type, brief, moment, _existing_inputs(project_id))
    wave_of = {cid: w.index for w in schedule.wave_plan.waves for cid in w.cells}
    nodes = []
    for cid, cell in sorted(schedule.cells.items()):
        state = dominant_state(cell.blockers).value if cell.blockers else "EXECUTABLE"
        nodes.append({"cell_id": cid, "node_id": cell.node_id, "artifact_type": cell.artifact_type, "objective": cell.cell.objective,
                      "state": state, "status_label": _label(state), "blockers": list(cell.blockers),
                      "wave": wave_of.get(cid), "side_effect_class": cell.side_effect_class, "role": cell.n3_role_id})
    edges = [{"from": dep, "to": nid} for nid, node in schedule.graph.nodes.items() for dep in node.dependencies]
    target = next((n for n in nodes if n["artifact_type"] == artifact_type), None)
    reasons: list[str] = []
    if not brand_ok:
        reasons.append(f"BRAND_CONTEXT_{brand_choice.status if brand_choice else 'UNRESOLVED'}: approved brand canon memory is needed")
    if capability.status.value == "PROVIDER_GAP":
        reasons.append(f"PROVIDER_GAP: {capability.id} has no installed provider")
    if target and target["state"] != "EXECUTABLE":
        reasons.extend(target["blockers"])
    upstream_missing = [n for n in nodes if n["artifact_type"] != artifact_type and n["state"] != "EXECUTABLE"]
    for n in upstream_missing:
        reasons.append(f"WAITING_ON_PREREQUISITE: {n['artifact_type'] or n['node_id']}")
    outcome = "READY_TO_LAUNCH" if not reasons else ("PROVIDER_GAP" if any(r.startswith("PROVIDER_GAP") for r in reasons) else "BLOCKED")
    return {**base, "outcome": outcome, "reasons": reasons, "deliverable": {"artifact_type": artifact_type, "skill": skill_id,
            "capability": capability.id, "capability_status": capability.status.value,
            "checks": list(DELIVERABLE_CHECKS.get(intent.deliverable.value, ()))},
            "brand_context": {"admissible": brand_ok, "status": brand_choice.status if brand_choice else "UNRESOLVED",
                              "capsule_hash": capsule.capsule_hash},
            "plan_hash": schedule.plan_hash, "nodes": nodes, "edges": edges,
            "waves": [{"index": w.index, "cells": list(w.cells)} for w in schedule.wave_plan.waves]}


def launch(principal: Principal, *, brief: str, project_id: str, now: Optional[datetime] = None) -> dict[str, Any]:
    from services.langgraph.agency.exporter import resolve_export_root
    from services.langgraph.agency.intake.runner import run_mission

    broker.authorize_scope(principal, project_id, write=True)
    client_id = _client(project_id)
    if client_id:
        from services.langgraph.persistence.actions import get_client

        client = get_client(client_id)
        if client and client["status"] != "ACTIVE":
            raise broker.ActionForbidden(f"the client is {client['status']}: no new work starts")
    outcome = run_mission(principal, brief, export_root=resolve_export_root(), active_project_id=project_id, now=now)
    return summarize(outcome)


def _client(project_id: str) -> Optional[str]:
    from services.langgraph.persistence.actions import client_for_project

    return client_for_project(project_id)


def summarize(outcome: Any) -> dict[str, Any]:
    mission = outcome.mission
    verification = outcome.verification
    return {
        "status": outcome.status, "status_label": _label(outcome.status), "reasons": list(outcome.reasons),
        "mission_id": mission.mission_id if mission else None, "contract_hash": mission.contract_hash if mission else None,
        "deliverable": mission.deliverable.value if mission else None,
        "acceptance_criteria": [p.model_dump(mode="json") for p in (mission.acceptance_predicates if mission else ())],
        "verification": verification.model_dump(mode="json") if verification else None,
        "approval": {k: outcome.approval.get(k) for k in ("approval_id", "status", "subject_hash", "subject_ref")} if outcome.approval else None,
        "non_actions": [n.model_dump(mode="json") for n in outcome.non_actions],
        "simulation": outcome.simulation, "release_eligible": outcome.release_eligible, "live_execution": "DISABLED",
    }


def list_missions(principal: Principal, project_id: str) -> list[dict[str, Any]]:
    """Missions from the project event stream (written by the intake runner)."""
    from services.langgraph.persistence.projects import list_project_events

    broker.authorize_scope(principal, project_id, write=False)
    missions: dict[str, dict[str, Any]] = {}
    for e in list_project_events(project_id, limit=1000):
        payload = e.payload or {}
        mid = payload.get("mission_id")
        # Intake missions are "msn-…"; the execution fabric's own work events use
        # other ids and belong to the mission's execution, not a new mission.
        if not mid or not str(mid).startswith("msn-"):
            continue
        m = missions.setdefault(mid, {"mission_id": mid, "events": [], "started_at": e.created_at, "deliverable": None,
                                      "status": "STARTED"})
        m["events"].append({"sequence": e.sequence, "type": e.event_type.value, "subject_ref": e.subject_ref, "at": e.created_at})
        if e.event_type.value == "WORK_STARTED":
            m["deliverable"] = payload.get("deliverable")
            m["simulation"] = payload.get("simulation", False)
        elif e.event_type.value == "APPROVAL_REQUIRED":
            m["status"], m["approval_id"] = "AWAITING_APPROVAL", payload.get("approval_id")
        elif e.event_type.value == "VERIFIED" and payload.get("verification"):
            m["verified_ref"] = e.subject_ref
        elif e.event_type.value == "QA_BLOCKED":
            m["status"], m["reasons"] = payload.get("status", "BLOCKED"), payload.get("reasons", [])
        elif e.event_type.value == "FAILED":
            m["status"] = "FAILED"
    for m in missions.values():
        m["status_label"] = _label(m["status"])
    return sorted(missions.values(), key=lambda m: m["started_at"], reverse=True)


def request_revision(principal: Principal, *, project_id: str, artifact_id: str, note: str) -> dict[str, Any]:
    """Record an edit request against a specific artifact version. The revised
    work is a new mission; its approval supersedes the old pending one."""
    from services.langgraph.agency.project_os.vocabulary import ActivityType
    from services.langgraph.persistence.agency_kernel import get_artifact
    from services.langgraph.persistence.projects import append_project_event

    broker.authorize_scope(principal, project_id, write=True)
    head = get_artifact(artifact_id)
    if head is None or head.get("project_id") != project_id:
        raise LookupError("artifact not found")
    if not note.strip():
        raise ValueError("a revision request needs a note")
    event = append_project_event(tenant_id=principal.tenant_id, project_id=project_id, event_type=ActivityType.EDIT_REQUESTED,
                                 actor=principal.user_id, subject_ref=f"{artifact_id}:v{head['version']}",
                                 payload={"artifact_id": artifact_id, "version": head["version"], "note": note.strip()[:2000],
                                          "content_hash": head.get("content_hash")})
    return {"event_id": event.event_id if hasattr(event, "event_id") else None, "artifact_id": artifact_id,
            "version": head["version"], "note": note.strip()[:2000]}


__all__ = ["DELIVERABLE_CHECKS", "EFFECT_ACTIONS", "launch", "list_missions", "preview", "request_revision", "summarize"]
