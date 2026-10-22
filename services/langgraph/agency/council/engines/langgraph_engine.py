"""LangGraph engine: George -> Fable/Cipher -> Sentinel gate (native interrupt) -> Arty -> terminal.

The graph is checkpointed on the repository's shared checkpointer
(``langgraph-checkpoint-sqlite`` locally, ``PostgresSaver`` in production) with
``thread_id = mission_id``, so a paused mission survives a restart. The gate
node calls ``interrupt()`` with the approval request and resumes only from
``Command(resume=decision)``; a decision that does not approve exactly this
gate's subject routes to the terminal rejection, so Arty never runs. Nodes are
side-effect free apart from events and council checkpoints recorded through
the context, and the gate emits nothing before it interrupts, so a re-executed
gate cannot duplicate work.
"""

from __future__ import annotations

import copy
import threading
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, RetryPolicy, interrupt

from .base import (
    EngineContext,
    EngineStep,
    SeatFailed,
    audit_step,
    await_gate,
    decision_matches,
    finish,
    gate_request,
    prototype_step,
    strategy_step,
)

_CONTEXTS: dict[str, EngineContext] = {}
_LOCK = threading.Lock()


class CouncilGraphState(TypedDict, total=False):
    council: dict


def _ctx(config) -> EngineContext:
    with _LOCK:
        return _CONTEXTS[config["configurable"]["thread_id"]]


def _retry_on(exc: BaseException) -> bool:
    # A seat timeout is transient; invalid output already had its bounded retries.
    return isinstance(exc, SeatFailed) and exc.code == "SEAT_TIMEOUT"


def _george(state: CouncilGraphState, config) -> CouncilGraphState:
    council = copy.deepcopy(state["council"])
    strategy_step(_ctx(config), council)
    return {"council": council}


def _fable(state: CouncilGraphState, config) -> CouncilGraphState:
    council = copy.deepcopy(state["council"])
    audit_step(_ctx(config), council)
    return {"council": council}


def _after_fable(state: CouncilGraphState) -> str:
    risk = state["council"]["risk"]
    if risk["blocked"]:
        return "blocked"
    return "sentinel_gate" if risk["requires_approval"] else "arty"


def _sentinel_gate(state: CouncilGraphState, config) -> CouncilGraphState:
    council = copy.deepcopy(state["council"])
    request = gate_request(council)
    decision = interrupt(request)  # pauses here; resumed with Command(resume=decision)
    council["gate"] = request
    decision = decision if isinstance(decision, dict) else {}
    approved = decision_matches(council, decision)
    reason = "APPROVED" if approved else (
        "SUBJECT_MISMATCH" if decision.get("decision") == "approve" else "REJECTED_BY_REVIEWER")
    council["decision"] = {"approval_id": decision.get("approval_id"), "decision": "approve" if approved else "reject",
                           "decided_by": decision.get("decided_by"), "subject_hash": decision.get("subject_hash"),
                           "reason": reason}
    _ctx(config).emit("APPROVAL_APPLIED", "sentinel_gate", {"decision": council["decision"]["decision"], "reason": reason,
                                                            "approval_id": decision.get("approval_id")})
    return {"council": council}


def _after_gate(state: CouncilGraphState) -> str:
    return "arty" if state["council"]["decision"]["decision"] == "approve" else "rejected"


def _arty(state: CouncilGraphState, config) -> CouncilGraphState:
    council = copy.deepcopy(state["council"])
    prototype_step(_ctx(config), council)
    return {"council": council}


def _terminal(name: str):
    def node(state: CouncilGraphState) -> CouncilGraphState:
        council = copy.deepcopy(state["council"])
        council["terminal"] = name
        return {"council": council}
    return node


def build_graph(checkpointer=None):
    retry = RetryPolicy(max_attempts=2, retry_on=_retry_on)
    graph = StateGraph(CouncilGraphState)
    graph.add_node("george", _george, retry_policy=retry)
    graph.add_node("fable", _fable, retry_policy=retry)
    graph.add_node("sentinel_gate", _sentinel_gate)
    graph.add_node("arty", _arty, retry_policy=retry)
    graph.add_node("complete", _terminal("COMPLETED"))
    graph.add_node("rejected", _terminal("REJECTED"))
    graph.add_node("blocked", _terminal("BLOCKED"))
    graph.add_edge(START, "george")
    graph.add_edge("george", "fable")
    graph.add_conditional_edges("fable", _after_fable, {"blocked": "blocked", "sentinel_gate": "sentinel_gate", "arty": "arty"})
    graph.add_conditional_edges("sentinel_gate", _after_gate, {"arty": "arty", "rejected": "rejected"})
    graph.add_edge("arty", "complete")
    for terminal in ("complete", "rejected", "blocked"):
        graph.add_edge(terminal, END)
    return graph.compile(checkpointer=checkpointer)


class LangGraphEngine:
    name = "langgraph"

    def availability(self) -> tuple[bool, str]:
        return True, "langgraph with the shared checkpointer (SQLite locally, PostgreSQL in production)"

    def _graph(self):
        from services.langgraph.persistence.checkpoints import get_checkpointer

        return build_graph(get_checkpointer())

    def _run(self, ctx: EngineContext, payload) -> EngineStep:
        graph = self._graph()
        config = {"configurable": {"thread_id": ctx.mission_id}}
        with _LOCK:
            _CONTEXTS[ctx.mission_id] = ctx
        try:
            graph.invoke(payload, config)
            snapshot = graph.get_state(config)
        finally:
            with _LOCK:
                _CONTEXTS.pop(ctx.mission_id, None)
        native = snapshot.config["configurable"].get("checkpoint_id")
        council = copy.deepcopy(snapshot.values["council"])
        if snapshot.interrupts:
            return await_gate(ctx, council, native)
        return finish(ctx, council, council["terminal"], {"native_checkpoint_id": native})

    def start(self, ctx: EngineContext, state: dict) -> EngineStep:
        return self._run(ctx, {"council": state})

    def resume(self, ctx: EngineContext, state: dict, decision: dict) -> EngineStep:
        return self._run(ctx, Command(resume=decision))

    def recover(self, ctx: EngineContext, state: dict) -> EngineStep:
        """Continue from the last durable checkpoint after a crash (no checkpoint: start over)."""
        graph = self._graph()
        snapshot = graph.get_state({"configurable": {"thread_id": ctx.mission_id}})
        if not snapshot.values:
            return self.start(ctx, state)
        if snapshot.interrupts:
            council = copy.deepcopy(snapshot.values["council"])
            return await_gate(ctx, council, snapshot.config["configurable"].get("checkpoint_id"))
        if not snapshot.next:
            council = copy.deepcopy(snapshot.values["council"])
            return finish(ctx, council, council["terminal"])
        return self._run(ctx, None)

    def history(self, mission_id: str) -> list[dict]:
        """Native LangGraph checkpoints for the viewer, newest first."""
        graph = self._graph()
        out = []
        for snap in graph.get_state_history({"configurable": {"thread_id": mission_id}}):
            council = (snap.values or {}).get("council") or {}
            out.append({"checkpoint_id": snap.config["configurable"].get("checkpoint_id"),
                        "next": list(snap.next), "step": (snap.metadata or {}).get("step"),
                        "created_at": snap.created_at, "interrupted": bool(snap.interrupts),
                        "has_strategy": bool(council.get("strategy")), "has_risk": bool(council.get("risk")),
                        "has_scaffold": bool(council.get("scaffold")), "terminal": council.get("terminal")})
        return out


__all__ = ["LangGraphEngine", "build_graph", "gate_request"]
