"""CrewAI engine: sequential strategy -> security audit -> prototype with explicit task context.

``build_council_crew`` declares the whole council (three agents, three tasks,
``context`` wiring strategy -> audit -> prototype). The engine executes that
definition in two phases around the Sentinel gate: phase A runs strategy and
audit with only George and Fable on the crew (so delegation can never reach
Arty before approval); phase B runs the prototype task after an approval, with
the phase-A outputs restored onto their Task objects so CrewAI's native
context carries them, even after a restart. Task guardrails validate every
output against the shared contracts. The LLM is ``CouncilCrewLLM``, a
``BaseLLM`` over the council model: offline and deterministic in mock mode,
the canonical model router otherwise. Requires the ``council`` extra.
"""

from __future__ import annotations

import json
import os
from typing import Any

from ..contracts import RiskAssessment
from ..model import MockSeatModel, SeatModel
from ..seats import INSTRUCTIONS, ROLES, seat_max_attempts, seat_timeout_seconds
from .base import (
    EngineContext,
    EngineStep,
    apply_audit,
    apply_scaffold,
    apply_strategy,
    arty_context,
    await_gate,
    decision_matches,
    fable_context,
    finish,
    policy_for,
    seat_prompt,
    seat_started,
    validate_output,
)

# CrewAI telemetry and execution traces would leave the host; a mission never needs them.
_OFFLINE_ENV = {"CREWAI_DISABLE_TELEMETRY": "true", "OTEL_SDK_DISABLED": "true", "CREWAI_TRACING_ENABLED": "false",
                "CREWAI_DISABLE_TRACKING": "true"}


def _crewai():
    for key, value in _OFFLINE_ENV.items():
        os.environ.setdefault(key, value)
    import crewai

    return crewai


def _llm_class():
    crewai = _crewai()

    class CouncilCrewLLM(crewai.BaseLLM):
        """CrewAI LLM over the council SeatModel. No tools, no function calling, no network in mock mode."""

        def __init__(self, seat_model: SeatModel, **data: Any) -> None:
            super().__init__(model=f"council-{seat_model.mode.lower()}", **data)
            object.__setattr__(self, "_seat_model", seat_model)

        def call(self, messages, tools=None, callbacks=None, available_functions=None, from_task=None, from_agent=None,
                 response_model=None):
            if isinstance(messages, str):
                text = messages
            else:
                text = "\n".join(str(m.get("content", "")) for m in messages if isinstance(m, dict))
            return "Final Answer: " + self._seat_model.complete(text)

        def supports_function_calling(self) -> bool:
            return False

    return CouncilCrewLLM


def build_council_crew(idea_title: str, idea_description: str, *, seat_model: SeatModel | None = None,
                       policy: RiskAssessment | None = None, state: dict | None = None):
    """Declare the council crew: George, Fable/Cipher, Arty and the strategy -> audit -> prototype tasks."""
    crewai = _crewai()
    llm = _llm_class()(seat_model or MockSeatModel())
    timeout = seat_timeout_seconds()
    george = crewai.Agent(role=ROLES["george"][0], goal=ROLES["george"][1], backstory=ROLES["george"][2], llm=llm,
                          allow_delegation=True, verbose=False, max_iter=3, max_execution_time=timeout)
    fable = crewai.Agent(role=ROLES["fable"][0], goal=ROLES["fable"][1], backstory=ROLES["fable"][2], llm=llm,
                         allow_delegation=False, verbose=False, max_iter=3, max_execution_time=timeout)
    arty = crewai.Agent(role=ROLES["arty"][0], goal=ROLES["arty"][1], backstory=ROLES["arty"][2], llm=llm,
                        allow_delegation=False, verbose=False, max_iter=3, max_execution_time=timeout)
    idea = (state or {}).get("idea") or {"title": idea_title, "description": idea_description}
    scan = policy or policy_for({"idea": idea, "requested_actions": (state or {}).get("requested_actions") or []})

    def guard(seat: str):
        def check(output):
            try:
                return True, json.dumps(validate_output(seat, output.raw, policy=scan if seat == "fable" else None))
            except ValueError as exc:  # includes pydantic.ValidationError
                return False, f"Output must be one JSON object matching the {seat} contract: {str(exc)[:300]}"
        return check

    retries = max(0, seat_max_attempts() - 1)
    strategy = crewai.Task(description=seat_prompt("george", {"idea": idea}),
                           expected_output="One JSON object: summary, goals, architecture, tasks (acyclic DAG).",
                           agent=george, guardrail=guard("george"), guardrail_max_retries=retries)
    # Fable's and Arty's prompts carry the policy scan and the strategy as context blocks; CrewAI's task
    # context appends the upstream task outputs to the same prompt.
    audit = crewai.Task(description=seat_prompt("fable", {"idea": idea, "policy": scan.model_dump(mode="json")}),
                        expected_output="One JSON object: narrative, additional_findings.", agent=fable,
                        context=[strategy], guardrail=guard("fable"), guardrail_max_retries=retries)
    prototype = crewai.Task(
        description=seat_prompt("arty", arty_context(state) if state and state.get("strategy") else {"idea": idea}),
        expected_output="One JSON object: summary, components, design_tokens, files.", agent=arty,
        context=[strategy, audit], guardrail=guard("arty"), guardrail_max_retries=retries)
    return crewai.Crew(agents=[george, fable, arty], tasks=[strategy, audit, prototype],
                       process=crewai.Process.sequential, verbose=False)


def run_council_crew(idea_title: str, idea_description: str, *, seat_model: SeatModel | None = None) -> str:
    """Kick off the full declared crew in one pass (no gate). Used for offline smoke runs."""
    return str(build_council_crew(idea_title, idea_description, seat_model=seat_model).kickoff())


class CrewAIEngine:
    name = "crewai"

    def availability(self) -> tuple[bool, str]:
        try:
            crewai = _crewai()
        except ImportError:
            return False, "NOT_INSTALLED: pip install -e './services/langgraph[council]'"
        return True, f"crewai {crewai.__version__} (sequential process, guardrailed tasks)"

    def _phase_a(self, ctx: EngineContext, state: dict) -> EngineStep:
        crewai = _crewai()
        scan = policy_for(state)
        crew = build_council_crew("", "", seat_model=ctx.model, policy=scan, state=state)
        george, fable, _ = crew.agents
        strategy, audit, _ = crew.tasks
        started = {"george": seat_started(ctx, "george")}

        def on_strategy(output) -> None:
            apply_strategy(ctx, state, json.loads(output.raw), 1, started["george"])
            started["fable"] = seat_started(ctx, "fable")

        def on_audit(output) -> None:
            apply_audit(ctx, state, json.loads(output.raw), 1, started["fable"])

        strategy.callback, audit.callback = on_strategy, on_audit
        crewai.Crew(agents=[george, fable], tasks=[strategy, audit], process=crewai.Process.sequential,
                    verbose=False).kickoff()
        return self._route(ctx, state)

    def _route(self, ctx: EngineContext, state: dict) -> EngineStep:
        risk = state["risk"]
        if risk["blocked"]:
            return finish(ctx, state, "BLOCKED")
        if risk["requires_approval"]:
            return await_gate(ctx, state)
        return self._phase_b(ctx, state)

    def _phase_b(self, ctx: EngineContext, state: dict) -> EngineStep:
        crewai = _crewai()
        from crewai.tasks.task_output import TaskOutput

        crew = build_council_crew("", "", seat_model=ctx.model, policy=policy_for(state), state=state)
        _, fable_agent, arty = crew.agents
        strategy, audit, prototype = crew.tasks
        # Restore phase-A outputs so the prototype's native context carries them without re-running them.
        strategy.output = TaskOutput(description=strategy.description, raw=json.dumps(state["strategy"]),
                                     agent=crew.agents[0].role)
        audit.output = TaskOutput(description=audit.description, raw=json.dumps(state["risk"]), agent=fable_agent.role)
        started = seat_started(ctx, "arty")
        result = crewai.Crew(agents=[arty], tasks=[prototype], process=crewai.Process.sequential, verbose=False).kickoff()
        apply_scaffold(ctx, state, json.loads(result.tasks_output[-1].raw), 1, started)
        return finish(ctx, state, "COMPLETED")

    def start(self, ctx: EngineContext, state: dict) -> EngineStep:
        return self._phase_a(ctx, state)

    def resume(self, ctx: EngineContext, state: dict, decision: dict) -> EngineStep:
        approved = decision_matches(state, decision)
        reason = "APPROVED" if approved else (
            "SUBJECT_MISMATCH" if decision.get("decision") == "approve" else "REJECTED_BY_REVIEWER")
        state["decision"] = {"approval_id": decision.get("approval_id"), "decision": "approve" if approved else "reject",
                             "decided_by": decision.get("decided_by"), "subject_hash": decision.get("subject_hash"),
                             "reason": reason}
        ctx.emit("APPROVAL_APPLIED", "sentinel_gate", {"decision": state["decision"]["decision"], "reason": reason,
                                                       "approval_id": decision.get("approval_id")})
        if not approved:
            return finish(ctx, state, "REJECTED")
        return self._phase_b(ctx, state)

    def recover(self, ctx: EngineContext, state: dict) -> EngineStep:
        if state.get("terminal"):
            return finish(ctx, state, state["terminal"])
        if state.get("decision"):
            return self._phase_b(ctx, state) if state["decision"]["decision"] == "approve" else finish(ctx, state, "REJECTED")
        if state.get("gate"):
            return await_gate(ctx, state)
        if state.get("strategy") and state.get("risk"):
            return self._route(ctx, state)
        state.update({"strategy": None, "risk": None})  # phase A is atomic: redo it from the start
        return self._phase_a(ctx, state)


__all__ = ["INSTRUCTIONS", "CrewAIEngine", "build_council_crew", "fable_context", "run_council_crew"]
