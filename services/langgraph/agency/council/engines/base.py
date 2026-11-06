"""The engine contract and the steps every engine shares.

An engine orchestrates George -> Fable/Cipher -> (Sentinel gate) -> Arty with
its own framework, but reports through one ``EngineContext``: the same events,
the same council state, the same checkpoints, the same gate subject. The
service owns persistence, statuses and approvals; engines never write runs or
approvals and never perform side effects.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.security.pii import redact_value

from .. import policy
from ..contracts import POLICY_VERSION, RequestedAction, RiskAssessment
from ..model import SeatModel
from ..seats import ROLES, SeatFailed, now, run_seat, seat_prompt, validate_output

StepStatus = Literal["AWAITING_APPROVAL", "COMPLETED", "REJECTED", "BLOCKED"]


class MissionCancelled(RuntimeError):
    """Raised between seats when the mission was cancelled."""


class EngineUnavailable(RuntimeError):
    def __init__(self, engine: str, reason: str) -> None:
        super().__init__(f"{engine} engine unavailable: {reason}")
        self.engine, self.reason = engine, reason


@dataclass
class EngineContext:
    mission_id: str
    tenant_id: str
    project_id: str
    engine: str
    model: SeatModel
    emit: Callable[[str, str | None, dict], None]
    checkpoint: Callable[[str, dict, str | None], None]
    is_cancelled: Callable[[], bool] = lambda: False


@dataclass
class EngineStep:
    status: StepStatus
    state: dict
    gate: dict | None = None
    extra: dict = field(default_factory=dict)


class CouncilEngine(Protocol):
    name: str

    def availability(self) -> tuple[bool, str]: ...

    def start(self, ctx: EngineContext, state: dict) -> EngineStep: ...

    def resume(self, ctx: EngineContext, state: dict, decision: dict) -> EngineStep: ...

    def recover(self, ctx: EngineContext, state: dict) -> EngineStep: ...


# --------------------------------------------------------------------------------- council state


def initial_state(*, mission_id: str, engine: str, idea: dict, requested_actions: list[dict], model_mode: str) -> dict:
    """JSON-only council state. Idea text is redacted before any model or log sees it."""
    return {"mission_id": mission_id, "engine": engine, "model_mode": model_mode,
            "idea": redact_value({"title": idea["title"], "description": idea["description"]}),
            "requested_actions": requested_actions, "strategy": None, "risk": None, "gate": None, "decision": None,
            "scaffold": None, "results": {}, "terminal": None}


def gate_request(state: dict) -> dict:
    """What a human approves: this mission/thread, these actions, this strategy and risk, this policy."""
    subject = {"mission_id": state["mission_id"], "thread_id": state["mission_id"], "action": "council.prototype",
               "requested_actions": state.get("requested_actions") or [],
               "strategy_hash": canonical_hash(state.get("strategy") or {}),
               "risk_hash": canonical_hash(state.get("risk") or {}), "policy_version": POLICY_VERSION}
    risk = state.get("risk") or {}
    return {"subject": subject, "subject_hash": canonical_hash(subject), "risk_level": risk.get("level"),
            "findings": [f["code"] for f in risk.get("findings") or []],
            "requested_actions": subject["requested_actions"]}


def decision_matches(state: dict, decision: dict | None) -> bool:
    """A resume decision only counts if it is an approval of exactly this gate's subject."""
    if not isinstance(decision, dict) or decision.get("decision") != "approve":
        return False
    return decision.get("subject_hash") == gate_request(state)["subject_hash"] and bool(decision.get("approval_id"))


def _record_result(ctx: EngineContext, state: dict, seat: str, output: dict, attempts: int, started: str) -> None:
    state.setdefault("results", {})[seat] = {"seat": seat, "engine": ctx.engine, "model_mode": ctx.model.mode,
                                             "attempts": attempts, "started_at": started, "completed_at": now()}


def _check_cancel(ctx: EngineContext) -> None:
    if ctx.is_cancelled():
        raise MissionCancelled(ctx.mission_id)


def seat_started(ctx: EngineContext, seat: str) -> str:
    _check_cancel(ctx)
    ctx.emit("SEAT_STARTED", seat, {"seat": seat, "role": ROLES[seat][0], "engine": ctx.engine})
    return now()


def apply_strategy(ctx: EngineContext, state: dict, output: dict, attempts: int, started: str) -> None:
    state["strategy"] = output
    _record_result(ctx, state, "george", output, attempts, started)
    ctx.emit("SEAT_COMPLETED", "george", {"seat": "george", "summary": output["summary"], "goals": len(output["goals"]),
                                          "tasks": len(output["tasks"]), "attempts": attempts})
    ctx.checkpoint("STRATEGY", state, None)


def apply_audit(ctx: EngineContext, state: dict, output: dict, attempts: int, started: str) -> None:
    state["risk"] = output
    _record_result(ctx, state, "fable", output, attempts, started)
    ctx.emit("RISK_ASSESSED", "fable", {"seat": "fable", "level": output["level"], "blocked": output["blocked"],
                                        "requires_approval": output["requires_approval"],
                                        "findings": [{"code": f["code"], "severity": f["severity"], "source": f["source"]}
                                                     for f in output["findings"]], "attempts": attempts})
    ctx.checkpoint("AUDIT", state, None)


def apply_scaffold(ctx: EngineContext, state: dict, output: dict, attempts: int, started: str) -> None:
    state["scaffold"] = output
    _record_result(ctx, state, "arty", output, attempts, started)
    ctx.emit("SEAT_COMPLETED", "arty", {"seat": "arty", "summary": output["summary"],
                                        "components": [c["name"] for c in output["components"]],
                                        "files": len(output["files"]), "attempts": attempts})
    ctx.checkpoint("PROTOTYPE", state, None)


def policy_for(state: dict) -> RiskAssessment:
    idea = state["idea"]
    actions = [RequestedAction.model_validate(a) for a in state.get("requested_actions") or []]
    return policy.scan(f"{idea['title']}\n{idea['description']}", actions)


# Direct seat steps (LangGraph nodes call these; CrewAI/AutoGen validate framework output with the same functions).

def strategy_step(ctx: EngineContext, state: dict) -> None:
    started = seat_started(ctx, "george")
    output, attempts = run_seat(ctx.model, "george", {"idea": state["idea"]})
    apply_strategy(ctx, state, output, attempts, started)


def audit_step(ctx: EngineContext, state: dict) -> None:
    started = seat_started(ctx, "fable")
    scan = policy_for(state)
    output, attempts = run_seat(ctx.model, "fable", fable_context(state, scan), policy=scan)
    apply_audit(ctx, state, output, attempts, started)


def prototype_step(ctx: EngineContext, state: dict) -> None:
    started = seat_started(ctx, "arty")
    output, attempts = run_seat(ctx.model, "arty", arty_context(state))
    apply_scaffold(ctx, state, output, attempts, started)


def fable_context(state: dict, scan: RiskAssessment) -> dict:
    return {"idea": state["idea"], "strategy": state["strategy"], "policy": scan.model_dump(mode="json")}


def arty_context(state: dict) -> dict:
    risk = state.get("risk") or {}
    return {"idea": state["idea"], "strategy": state["strategy"],
            "risk": {"level": risk.get("level"), "findings": [f["code"] for f in risk.get("findings") or []]}}


def finish(ctx: EngineContext, state: dict, terminal: str, detail: dict | None = None) -> EngineStep:
    state["terminal"] = terminal
    ctx.checkpoint("DONE", state, None)
    status = {"COMPLETED": "COMPLETED", "REJECTED": "REJECTED", "BLOCKED": "BLOCKED"}[terminal]
    return EngineStep(status=status, state=state, extra=detail or {})


def await_gate(ctx: EngineContext, state: dict, native_checkpoint_id: str | None = None) -> EngineStep:
    request = gate_request(state)
    state["gate"] = request
    ctx.checkpoint("GATE", state, native_checkpoint_id)
    return EngineStep(status="AWAITING_APPROVAL", state=state, gate=request)


def safe_text(value: Any) -> Any:
    return redact_value(value)


__all__ = [
    "CouncilEngine", "EngineContext", "EngineStep", "EngineUnavailable", "MissionCancelled", "SeatFailed",
    "apply_audit", "apply_scaffold", "apply_strategy", "arty_context", "audit_step", "await_gate", "decision_matches",
    "fable_context", "finish", "gate_request", "initial_state", "policy_for", "prototype_step", "safe_text",
    "seat_prompt", "seat_started", "strategy_step", "validate_output",
]
