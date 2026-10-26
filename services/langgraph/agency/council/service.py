"""Mission lifecycle shared by every engine.

idea -> dispatch(engine) -> queued -> running [George, Fable/Cipher] -> needs_approval (Sentinel gate)
     -> /approvals/{id}/decide (role + separation of duties) -> resume(bound decision) -> Arty
     -> completed | rejected | failed | cancelled -> blueprint (best parts) -> promotion (timeline verified)

A mission is a ``runs`` row (pipeline ``mission_council``): status changes go
through the runs compare-and-set, approvals are ordinary ``approvals`` rows,
events are ``run_events`` (streamed by /runs/{id}/events). One worker holds a
mission at a time (lease); a resume consumes its approval exactly once; a
crashed mission continues from its last checkpoint without repeating seats.
Engines run in a bounded thread pool so the API answers immediately and the
dashboard follows progress through the event stream.
"""

from __future__ import annotations

import concurrent.futures
import os
import socket
import threading
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.persistence import council as store
from services.langgraph.persistence.approvals import (
    create_approval_request,
    get_approval,
    mark_approval_stale,
)
from services.langgraph.persistence.events import list_events_for_run, record_event
from services.langgraph.persistence.runs import (
    RunLimitExceeded,
    compare_and_set_run_status,
    create_run_record,
    get_run_record,
)
from services.langgraph.security.auth import (
    Principal,
    authorize_project,
    authorize_resource,
)
from services.langgraph.security.pii import redact_value

from . import gateway
from .contracts import (
    ENGINES,
    PIPELINE,
    POLICY_VERSION,
    SEVERITY_ORDER,
    TERMINAL_STATUSES,
    DispatchRequest,
    IdeaCreate,
)
from .engines import get_engine
from .engines.base import (
    EngineContext,
    EngineStep,
    EngineUnavailable,
    MissionCancelled,
    gate_request,
    initial_state,
)
from .model import ModelUnavailable, model_for, profile_pin, selected_mode
from .policy import scan
from .seats import SeatFailed

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
RESUME_ACTION = "mission.resume"


class MissionError(Exception):
    """A deterministic, client-visible failure: stable ``code``, HTTP ``status``."""

    def __init__(self, code: str, message: str, status: int = 409, details: dict | None = None) -> None:
        super().__init__(message)
        self.code, self.status, self.details = code, status, details


def _env_int(name: str, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(os.environ.get(name, default))))
    except ValueError:
        return default


def lease_seconds() -> int:
    return _env_int("COUNCIL_LEASE_SECONDS", 300, 5, 3600)


_POOL: concurrent.futures.ThreadPoolExecutor | None = None
_POOL_LOCK = threading.Lock()


def submit(fn: Callable[[], None]) -> None:
    """Run engine work off the request thread. ``COUNCIL_EXECUTION=inline`` runs it synchronously (tests, CLI)."""
    if (os.environ.get("COUNCIL_EXECUTION") or "thread").strip().lower() == "inline":
        fn()
        return
    global _POOL
    with _POOL_LOCK:
        if _POOL is None:
            _POOL = concurrent.futures.ThreadPoolExecutor(
                max_workers=_env_int("COUNCIL_MAX_CONCURRENT_MISSIONS", 4, 1, 32), thread_name_prefix="council-mission")
        _POOL.submit(fn)


# ------------------------------------------------------------------------------------ events


def emit(mission: dict, event_type: str, node_id: str | None, payload: dict) -> None:
    record_event(mission["mission_id"], mission["tenant_id"], mission["project_id"], node_id, event_type,
                 safe_payload=redact_value(payload))


# ------------------------------------------------------------------------------------- ideas


def create_idea(principal: Principal, body: IdeaCreate, *, seed_key: str | None = None) -> dict:
    authorize_project(principal, body.project_id)
    findings = scan(f"{body.title}\n{body.description}", []).findings
    if any(f.code == "SECRET_IN_INPUT" for f in findings):
        # A credential must never be persisted in plaintext, so the idea is refused before it is stored.
        raise MissionError("SECRET_IN_INPUT", "The idea contains a credential-shaped value; remove it and resubmit", 422)
    return store.create_idea(tenant_id=principal.tenant_id, project_id=body.project_id, title=body.title,
                             description=body.description, created_by=principal.user_id, seed_key=seed_key)


def get_idea_for(principal: Principal, idea_id: str) -> dict:
    idea = store.get_idea(idea_id)
    if idea is None:
        raise MissionError("IDEA_NOT_FOUND", "Idea not found", 404)
    authorize_resource(principal, idea["tenant_id"], idea["project_id"])
    return idea


# ---------------------------------------------------------------------------------- missions


def _mission_or_404(principal: Principal, mission_id: str) -> tuple[dict, dict]:
    row = store.get_mission_row(mission_id)
    run = get_run_record(mission_id)
    if row is None or run is None or run.get("pipeline") != PIPELINE:
        raise MissionError("MISSION_NOT_FOUND", "Mission not found", 404)
    authorize_resource(principal, row["tenant_id"], row["project_id"])
    return row, run


def dispatch(principal: Principal, req: DispatchRequest) -> dict:
    if req.engine not in ENGINES:
        raise MissionError("UNSUPPORTED_ENGINE", f"Unsupported orchestration engine: {req.engine}", 400,
                           {"supported": list(ENGINES)})
    available, reason = get_engine(req.engine).availability()
    if not available:
        raise MissionError("ENGINE_UNAVAILABLE", f"{req.engine} engine is unavailable: {reason}", 503,
                           {"engine": req.engine, "reason": reason})
    idea = get_idea_for(principal, req.idea_id)
    if idea["status"] != "OPEN":
        raise MissionError("IDEA_NOT_OPEN", "This idea was already promoted", 409)
    model_mode = selected_mode()
    pin = profile_pin()
    if pin and pin.get("error"):
        raise MissionError("MODEL_PROFILE_INVALID", f"Real models are enabled but the profile is invalid: {pin['error']}", 422)
    mission_id = f"msn_{uuid4().hex}"
    requested = [gateway.requested_action("workspace.write_scaffold", mission_id)] if req.materialize_scaffold else []
    metadata: dict[str, Any] = {"initiated_by": principal.user_id, "engine": req.engine, "idea_id": idea["idea_id"],
                                "council": {"policy_version": POLICY_VERSION, "model_mode": model_mode,
                                            "requested_actions": requested}}
    if pin:
        metadata["model_profile"] = pin
    try:
        create_run_record(mission_id, idea["tenant_id"], idea["project_id"], PIPELINE, "queued", metadata,
                          enforce_limits=True)
    except RunLimitExceeded as exc:
        raise MissionError("RUN_LIMIT_EXCEEDED", exc.reason, 429, {"retry_after_seconds": exc.retry_after_seconds}) from exc
    row = store.insert_mission(mission_id=mission_id, idea_id=idea["idea_id"], tenant_id=idea["tenant_id"],
                               project_id=idea["project_id"], engine=req.engine, model_mode=model_mode)
    state = initial_state(mission_id=mission_id, engine=req.engine, idea=idea, requested_actions=requested,
                          model_mode=model_mode)
    store.append_checkpoint(mission_id=mission_id, phase="STRATEGY", engine=req.engine, state=state)
    emit(row, "MISSION_QUEUED", None, {"engine": req.engine, "idea_id": idea["idea_id"], "model_mode": model_mode,
                                       "requested_actions": requested})
    submit(lambda: execute(mission_id))
    return describe(mission_id)


def _context(row: dict, run: dict) -> EngineContext:
    def checkpoint(phase: str, state: dict, native: str | None) -> None:
        stored = store.append_checkpoint(mission_id=row["mission_id"], phase=phase, engine=row["engine"], state=state,
                                         native_checkpoint_id=native)
        emit(row, "CHECKPOINT_SAVED", None, {"seq": stored["seq"], "phase": phase, "state_hash": stored["state_hash"],
                                             "native_checkpoint_id": native})

    def cancelled() -> bool:
        current = store.get_mission_row(row["mission_id"])
        return bool(current and current["cancel_requested"])

    return EngineContext(mission_id=row["mission_id"], tenant_id=row["tenant_id"], project_id=row["project_id"],
                         engine=row["engine"], model=model_for(row["model_mode"], run.get("metadata") or {},
                                                               f"council:{row['mission_id']}"),
                         emit=lambda t, n, p: emit(row, t, n, p), checkpoint=checkpoint, is_cancelled=cancelled)


def _current_status(mission_id: str) -> str:
    run = get_run_record(mission_id)
    return run["status"] if run else "missing"


def _transition(row: dict, to_status: str, payload: dict | None = None) -> bool:
    current = _current_status(row["mission_id"])
    if current == to_status:
        return True
    if current in TERMINAL_STATUSES:
        return False  # a terminal mission never moves again (a rejection can never become a completion)
    return compare_and_set_run_status(row["mission_id"], current, to_status, payload)


def _drive(mission_id: str, run_engine: Callable[[Any, EngineContext, dict], EngineStep],
           pre: Callable[[dict], bool] | None = None) -> None:
    """Run one engine call under the mission lease and apply its outcome."""
    row = store.acquire_lease(mission_id, WORKER_ID, lease_seconds())
    if row is None:
        return  # another worker holds this mission
    try:
        if pre is not None and not pre(row):
            return
        run = get_run_record(mission_id)
        state = store.latest_checkpoint_state(mission_id) or {}
        try:
            engine = get_engine(row["engine"])
            step = run_engine(engine, _context(row, run), state)
        except MissionCancelled:
            _transition(row, "cancelled", {"reason": "cancelled"})
            emit(row, "MISSION_CANCELLED", None, {"phase": row["phase"]})
            return
        except SeatFailed as exc:
            _fail(row, exc.code, {"seat": exc.seat, "attempts": exc.attempts})
            return
        except (EngineUnavailable, ModelUnavailable) as exc:
            _fail(row, getattr(exc, "code", "ENGINE_UNAVAILABLE"), {"detail": str(exc)[:300]})
            return
        except gateway.GatewayDenied as exc:
            _fail(row, exc.code, {"detail": str(exc)[:300]})
            return
        except Exception as exc:  # noqa: BLE001 - an engine bug fails the mission, it never crashes the worker
            _fail(row, "ENGINE_ERROR", {"error": type(exc).__name__})
            return
        _apply(mission_id, step)
    finally:
        store.release_lease(mission_id, WORKER_ID)


def _fail(row: dict, code: str, detail: dict) -> None:
    current = store.get_mission_row(row["mission_id"])
    if current:
        store.update_mission(row["mission_id"], current["version"], last_error=code,
                             attempts=int(current["attempts"]) + 1)
    _transition(row, "failed", {"error": code})
    emit(row, "MISSION_FAILED", None, {"code": code, **detail})


def _apply(mission_id: str, step: EngineStep) -> None:
    row = store.get_mission_row(mission_id)
    if step.status == "AWAITING_APPROVAL":
        approval_id = row.get("approval_id")
        existing = get_approval(approval_id) if approval_id else None
        if not (existing and existing.get("subject_hash") == step.gate["subject_hash"] and existing["status"] == "pending"):
            if existing and existing["status"] == "pending":
                mark_approval_stale(approval_id, "council gate subject changed")
            approval = create_approval_request(
                mission_id, row["tenant_id"], row["project_id"],
                f"Sentinel gate: {row['engine']} mission requests {len(step.gate['requested_actions'])} action(s) at "
                f"risk {step.gate['risk_level']}", None, subject_type="COUNCIL_GATE", subject_ref=mission_id,
                subject_version_ref=step.gate["subject_hash"][:16], subject_hash=step.gate["subject_hash"],
                authority_ref="council-sentinel", policy_version=POLICY_VERSION)
            approval_id = approval["approval_id"]
        store.update_mission(mission_id, row["version"], phase="GATE", approval_id=approval_id,
                             approval_subject_hash=step.gate["subject_hash"])
        _transition(row, "needs_approval")
        emit(row, "APPROVAL_REQUIRED", "sentinel_gate", {"approval_id": approval_id, "subject_hash": step.gate["subject_hash"],
                                                         "risk_level": step.gate["risk_level"],
                                                         "findings": step.gate["findings"],
                                                         "requested_actions": step.gate["requested_actions"]})
        return
    if step.status == "COMPLETED":
        scaffold = step.state.get("scaffold") or {}
        requested = step.state.get("requested_actions") or []
        if any(a["tool_id"] == "workspace.write_scaffold" for a in requested):
            decision = step.state.get("decision") or {}
            if decision.get("decision") != "approve":
                _fail(row, "SIDE_EFFECT_WITHOUT_APPROVAL", {"tool_id": "workspace.write_scaffold"})
                return
            mission_view = {"mission_id": mission_id, "requested_actions": requested,
                            "approval_subject_hash": row.get("approval_subject_hash")}
            result = gateway.invoke("workspace.write_scaffold", {"files": scaffold.get("files") or []},
                                    ctx={"tenant_id": row["tenant_id"], "project_id": row["project_id"],
                                         "mission_id": mission_id, "user_id": decision.get("decided_by")},
                                    seat="arty", mission=mission_view, approval_id=decision.get("approval_id"),
                                    idempotent_retry=True)
            emit(row, "TOOL_INVOKED", "arty", {"tool_id": "workspace.write_scaffold",
                                               "written": result["result"]["written"],
                                               "approval_id": decision.get("approval_id")})
        store.update_mission(mission_id, store.get_mission_row(mission_id)["version"], phase="DONE")
        _transition(row, "completed", {"terminal": "COMPLETED"})
        emit(row, "MISSION_COMPLETED", None, {"components": [c["name"] for c in scaffold.get("components") or []],
                                              "files": len(scaffold.get("files") or [])})
        return
    store.update_mission(mission_id, row["version"], phase="DONE")
    if step.status == "REJECTED":
        reason = (step.state.get("decision") or {}).get("reason", "REJECTED")
        _transition(row, "rejected", {"terminal": "REJECTED", "reason": reason})
        emit(row, "MISSION_REJECTED", None, {"reason": reason})
    else:  # BLOCKED by policy (CRITICAL finding): nothing after the audit ran
        risk = step.state.get("risk") or {}
        _transition(row, "rejected", {"terminal": "BLOCKED"})
        emit(row, "MISSION_BLOCKED", "fable", {"findings": [f["code"] for f in risk.get("findings") or []]})


def execute(mission_id: str) -> None:
    def start(row: dict) -> bool:
        # Only the lease holder may move queued -> running, so a mission starts exactly once.
        if not compare_and_set_run_status(mission_id, "queued", "running"):
            return False
        emit(row, "MISSION_STARTED", None, {"engine": row["engine"], "worker": WORKER_ID})
        return True

    _drive(mission_id, lambda engine, ctx, state: engine.start(ctx, state), pre=start)


def resume(principal: Principal, mission_id: str) -> dict:
    """Resume the paused checkpoint with the decision recorded on its bound approval (used once)."""
    row, run = _mission_or_404(principal, mission_id)
    if row["phase"] != "GATE" or run["status"] not in ("needs_approval", "rejected"):
        raise MissionError("MISSION_NOT_AWAITING_APPROVAL", f"Mission is not paused at the Sentinel gate (status={run['status']})")
    approval = get_approval(row["approval_id"]) if row.get("approval_id") else None
    if approval is None:
        raise MissionError("APPROVAL_NOT_FOUND", "The gate has no approval request", 409)
    if approval["status"] == "pending":
        raise MissionError("APPROVAL_PENDING", "Decide the approval at /approvals/{id}/decide before resuming", 409,
                           {"approval_id": approval["approval_id"]})
    if approval["status"] == "stale":
        raise MissionError("APPROVAL_STALE", "The approval is stale; the gate subject changed", 409)
    state = store.latest_checkpoint_state(mission_id) or {}
    expected = gate_request(state)["subject_hash"] if state.get("strategy") else None
    if approval.get("subject_hash") != row.get("approval_subject_hash") or approval.get("subject_hash") != expected:
        mark_approval_stale(approval["approval_id"], "council gate subject changed before resume")
        raise MissionError("APPROVAL_STALE", "The approval does not bind the current gate subject", 409)
    if approval.get("policy_version") != POLICY_VERSION:
        raise MissionError("APPROVAL_POLICY_MISMATCH", "The approval was decided under a different policy version", 409)
    if not store.consume_approval(approval_id=approval["approval_id"], mission_id=mission_id, action_hash=RESUME_ACTION,
                                  consumed_by=principal.user_id):
        raise MissionError("APPROVAL_REPLAY", "This approval was already used to resume the mission", 409)
    decision = {"approval_id": approval["approval_id"], "decision": approval["decision"],
                "decided_by": approval.get("reviewer"), "subject_hash": approval["subject_hash"],
                "policy_version": approval.get("policy_version")}
    if approval["decision"] == "approve" and not compare_and_set_run_status(mission_id, "needs_approval", "resuming"):
        raise MissionError("MISSION_STATE_RACE", "Mission state changed while resuming", 409)
    store.update_mission(mission_id, row["version"], consumed_approval_id=approval["approval_id"])
    emit(row, "MISSION_RESUMING", "sentinel_gate", {"decision": approval["decision"], "approval_id": approval["approval_id"],
                                                    "decided_by": approval.get("reviewer"), "resumed_by": principal.user_id})
    submit(lambda: _drive(mission_id, lambda engine, ctx, st: engine.resume(ctx, st, decision)))
    return describe(mission_id)


def cancel(principal: Principal, mission_id: str) -> dict:
    row, run = _mission_or_404(principal, mission_id)
    if run["status"] in TERMINAL_STATUSES:
        raise MissionError("MISSION_TERMINAL", f"Mission already ended (status={run['status']})")
    store.update_mission(mission_id, row["version"], cancel_requested=1)
    if run["status"] in ("queued", "needs_approval"):
        # Nothing is executing: cancel now and retire any pending approval.
        if row.get("approval_id"):
            approval = get_approval(row["approval_id"])
            if approval and approval["status"] == "pending":
                mark_approval_stale(row["approval_id"], "mission cancelled")
        if compare_and_set_run_status(mission_id, run["status"], "cancelled", {"reason": "cancelled"}):
            emit(row, "MISSION_CANCELLED", None, {"phase": row["phase"], "by": principal.user_id})
    else:
        emit(row, "CANCEL_REQUESTED", None, {"by": principal.user_id})
    return describe(mission_id)


def retry(principal: Principal, mission_id: str) -> dict:
    """Continue a failed mission from its last checkpoint; completed seats are not repeated."""
    row, run = _mission_or_404(principal, mission_id)
    if run["status"] != "failed":
        raise MissionError("MISSION_NOT_FAILED", f"Only failed missions can be retried (status={run['status']})")
    if not compare_and_set_run_status(mission_id, "failed", "running"):
        raise MissionError("MISSION_STATE_RACE", "Mission state changed while retrying", 409)
    store.update_mission(mission_id, row["version"], last_error=None)
    emit(row, "MISSION_RETRYING", None, {"attempt": int(row["attempts"]) + 1, "by": principal.user_id})
    submit(lambda: _drive(mission_id, lambda engine, ctx, state: engine.recover(ctx, state)))
    return describe(mission_id)


def recover(principal: Principal, mission_id: str) -> dict:
    """Restore a mission whose worker stopped (restart, crash) once its lease has expired."""
    row, run = _mission_or_404(principal, mission_id)
    if run["status"] not in ("queued", "running", "resuming"):
        raise MissionError("MISSION_NOT_RECOVERABLE", f"Nothing to recover (status={run['status']})")
    if not store.lease_expired(row):
        raise MissionError("MISSION_LEASE_ACTIVE", "A worker still holds this mission's lease", 409,
                           {"lease_expires_at": row.get("lease_expires_at")})
    emit(row, "MISSION_RECOVERING", None, {"from_status": run["status"], "by": principal.user_id})
    if run["status"] == "queued":
        submit(lambda: execute(mission_id))
    else:
        submit(lambda: _drive(mission_id, lambda engine, ctx, state: engine.recover(ctx, state)))
    return describe(mission_id)


def recover_stale() -> list[str]:
    """Resubmit every mission whose worker stopped; returns their ids (startup/maintenance hook)."""
    ids = [r["mission_id"] for r in store.stale_running_missions()]
    for mission_id in ids:
        if _current_status(mission_id) == "queued":
            submit(lambda m=mission_id: execute(m))
        else:
            submit(lambda m=mission_id: _drive(m, lambda engine, ctx, state: engine.recover(ctx, state)))
    return ids


# ------------------------------------------------------------------------------------- views


def describe(mission_id: str) -> dict:
    row = store.get_mission_row(mission_id)
    run = get_run_record(mission_id)
    state = store.latest_checkpoint_state(mission_id) or {}
    approval = get_approval(row["approval_id"]) if row.get("approval_id") else None
    scaffold = state.get("scaffold") or None
    return {
        "mission_id": mission_id, "thread_id": mission_id, "idea_id": row["idea_id"], "tenant_id": row["tenant_id"],
        "project_id": row["project_id"], "engine": row["engine"], "model_mode": row["model_mode"],
        "status": run["status"], "phase": row["phase"], "attempts": row["attempts"], "last_error": row["last_error"],
        "cancel_requested": bool(row["cancel_requested"]), "created_at": row["created_at"], "updated_at": row["updated_at"],
        "lease_expires_at": row.get("lease_expires_at"), "initiated_by": (run.get("metadata") or {}).get("initiated_by"),
        "strategy": state.get("strategy"), "risk": state.get("risk"), "gate": state.get("gate"),
        "decision": state.get("decision"), "requested_actions": state.get("requested_actions") or [],
        "scaffold": None if scaffold is None else {**scaffold, "files": [
            {"path": f["path"], "bytes": len(f["content"].encode())} for f in scaffold.get("files") or []]},
        "results": state.get("results") or {},
        "approval": None if approval is None else {k: approval.get(k) for k in (
            "approval_id", "status", "decision", "reviewer", "subject_hash", "policy_version", "created_at", "decided_at")},
    }


def describe_for(principal: Principal, mission_id: str) -> dict:
    _mission_or_404(principal, mission_id)
    return describe(mission_id)


def checkpoints_for(principal: Principal, mission_id: str) -> dict:
    row, _ = _mission_or_404(principal, mission_id)
    ok, detail = store.verify_checkpoint_chain(mission_id)
    native: list[dict] = []
    if row["engine"] == "langgraph":
        from .engines.langgraph_engine import LangGraphEngine

        native = LangGraphEngine().history(mission_id)
    return {"mission_id": mission_id, "chain_verified": ok, "chain_detail": detail,
            "checkpoints": store.list_checkpoints(mission_id), "native": native}


def timeline_for(principal: Principal, mission_id: str, *, after: int = -1, limit: int = 200) -> dict:
    _mission_or_404(principal, mission_id)
    events = list_events_for_run(mission_id, after_sequence=after, limit=max(1, min(limit, 500)))
    items = [{"sequence": e["sequence"], "event_type": e["event_type"], "node_id": e["node_id"],
              "observed_at": e["observed_at"], "payload": e["safe_payload"]} for e in events]
    return {"mission_id": mission_id, "events": items, "next_cursor": items[-1]["sequence"] if items else after}


def tool_audits_for(principal: Principal, mission_id: str) -> list[dict]:
    _mission_or_404(principal, mission_id)
    return store.list_tool_audits(mission_id)


# -------------------------------------------------------------------------------- blueprints


def extract_blueprint(principal: Principal, idea_id: str) -> dict:
    """Merge the best parts of an idea's completed missions; failed or rejected ones are listed, not used."""
    idea = get_idea_for(principal, idea_id)
    missions = store.missions_for_idea(idea_id)
    completed = [m for m in missions if m["status"] == "completed"]
    if not completed:
        raise MissionError("NO_COMPLETED_MISSIONS", "No mission for this idea has completed yet", 409)
    states = {m["mission_id"]: store.latest_checkpoint_state(m["mission_id"]) or {} for m in missions}

    def rank(m: dict, key: str) -> tuple:
        part = states[m["mission_id"]].get(key) or {}
        size = len(part.get("tasks") or part.get("components") or [])
        return (-size, ENGINES.index(m["engine"]), m["created_at"])

    strategy_src = min(completed, key=lambda m: rank(m, "strategy"))
    scaffold_src = min(completed, key=lambda m: rank(m, "scaffold"))
    findings: dict[str, dict] = {}
    for m in missions:
        for finding in (states[m["mission_id"]].get("risk") or {}).get("findings") or []:
            prior = findings.get(finding["code"])
            seen = prior["seen_in"] if prior else []
            if prior is None or SEVERITY_ORDER[finding["severity"]] > SEVERITY_ORDER[prior["severity"]]:
                findings[finding["code"]] = {**finding, "seen_in": seen}
            if m["mission_id"] not in seen:
                seen.append(m["mission_id"])
    level = max((f["severity"] for f in findings.values()), key=lambda s: SEVERITY_ORDER[s], default="LOW")
    scaffold = states[scaffold_src["mission_id"]]["scaffold"]
    content = {
        "idea": {"idea_id": idea_id, "title": idea["title"]},
        "strategy": {**states[strategy_src["mission_id"]]["strategy"], "source_engine": strategy_src["engine"]},
        "security": {"level": level, "findings": sorted(findings.values(), key=lambda f: f["code"]),
                     "approvals": [{"mission_id": m["mission_id"], "engine": m["engine"],
                                    "decision": (states[m["mission_id"]].get("decision") or {}).get("decision")}
                                   for m in completed]},
        "scaffold": {"summary": scaffold["summary"], "components": scaffold["components"],
                     "design_tokens": scaffold["design_tokens"], "source_engine": scaffold_src["engine"],
                     "files": [{"path": f["path"], "sha256": canonical_hash(f["content"])} for f in scaffold["files"]]},
    }
    sources = [{"mission_id": m["mission_id"], "engine": m["engine"], "status": m["status"],
                "used_for": [part for part, src in (("strategy", strategy_src), ("scaffold", scaffold_src))
                             if src["mission_id"] == m["mission_id"]] + (["security"] if states[m["mission_id"]].get("risk") else []),
                "excluded_reason": None if m["status"] == "completed" else f"mission {m['status']}"}
               for m in missions]
    return store.create_blueprint(idea_id=idea_id, tenant_id=idea["tenant_id"], project_id=idea["project_id"],
                                  content=content, sources=sources, created_by=principal.user_id)


def verify_timeline(mission_id: str) -> dict:
    """A promotable mission has a gap-free event log that ends in completion and an intact checkpoint chain."""
    events = list_events_for_run(mission_id, after_sequence=-1, limit=5000)
    problems = []
    sequences = [e["sequence"] for e in events]
    if sequences != list(range(len(sequences))):
        problems.append("event sequence has gaps")
    types = [e["event_type"] for e in events]
    if not types or types[0] != "MISSION_QUEUED":
        problems.append("timeline does not start with MISSION_QUEUED")
    if "MISSION_COMPLETED" not in types:
        problems.append("timeline has no MISSION_COMPLETED")
    if "APPROVAL_REQUIRED" in types:
        applied = [e for e in events if e["event_type"] == "APPROVAL_APPLIED"]
        if not applied or applied[-1]["safe_payload"].get("decision") != "approve":
            problems.append("gated mission has no applied approval")
        elif types.index("APPROVAL_REQUIRED") > types.index("APPROVAL_APPLIED"):
            problems.append("approval applied before it was requested")
    chain_ok, chain_detail = store.verify_checkpoint_chain(mission_id)
    if not chain_ok:
        problems.append(chain_detail)
    if _current_status(mission_id) != "completed":
        problems.append("mission is not completed")
    return {"mission_id": mission_id, "events": len(events), "checkpoints": chain_detail, "verified": not problems,
            "problems": problems}


def promote_blueprint(principal: Principal, blueprint_id: str) -> dict:
    blueprint = store.get_blueprint(blueprint_id)
    if blueprint is None:
        raise MissionError("BLUEPRINT_NOT_FOUND", "Blueprint not found", 404)
    authorize_resource(principal, blueprint["tenant_id"], blueprint["project_id"])
    if blueprint["status"] != "DRAFT":
        raise MissionError("BLUEPRINT_NOT_DRAFT", "Blueprint was already promoted", 409)
    used = [s for s in blueprint["sources"] if s["status"] == "completed"]
    reports = [verify_timeline(s["mission_id"]) for s in used]
    verification = {"verified": all(r["verified"] for r in reports), "missions": reports,
                    "content_hash_ok": canonical_hash(blueprint["content"]) == blueprint["content_hash"]}
    if not (verification["verified"] and verification["content_hash_ok"]):
        store.record_verification(blueprint_id, verification)
        raise MissionError("TIMELINE_VERIFICATION_FAILED", "A source mission's timeline did not verify", 409, verification)
    promoted = store.promote_blueprint(blueprint_id, promoted_by=principal.user_id, verification=verification)
    if promoted is None:
        raise MissionError("BLUEPRINT_NOT_DRAFT", "Blueprint was already promoted", 409)
    store.set_idea_status(blueprint["idea_id"], "PROMOTED")
    return promoted


def blueprint_for(principal: Principal, blueprint_id: str) -> dict:
    blueprint = store.get_blueprint(blueprint_id)
    if blueprint is None:
        raise MissionError("BLUEPRINT_NOT_FOUND", "Blueprint not found", 404)
    authorize_resource(principal, blueprint["tenant_id"], blueprint["project_id"])
    return blueprint


__all__ = ["MissionError", "blueprint_for", "cancel", "checkpoints_for", "create_idea", "describe", "describe_for",
           "dispatch", "execute", "extract_blueprint", "get_idea_for", "promote_blueprint", "recover", "recover_stale",
           "resume", "retry", "submit", "timeline_for", "tool_audits_for", "verify_timeline"]
