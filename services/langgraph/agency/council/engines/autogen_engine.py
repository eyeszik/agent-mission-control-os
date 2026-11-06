"""AutoGen engine (autogen-agentchat / autogen-core 0.7): bounded round-robin team conversations.

Phase A is a ``RoundRobinGroupChat`` of George and Fable/Cipher, terminated by
``MaxMessageTermination`` (task + one turn each) or ``TimeoutTermination``.
Phase B, after an approval, is a one-agent team for Arty. Each agent's system
message carries its seat prompt; ``CouncilChatClient`` is a
``ChatCompletionClient`` over the council model (offline in mock mode, the
model router otherwise). There is no code executor: generated code is text,
validated and never run, until an isolated sandbox exists. Requires the
``council`` extra.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Any

from ..model import SeatModel, parse_prompt
from ..seats import (
    INSTRUCTIONS,
    ROLES,
    seat_max_attempts,
    seat_prompt,
    seat_timeout_seconds,
)
from .base import (
    EngineContext,
    EngineStep,
    apply_audit,
    apply_scaffold,
    apply_strategy,
    arty_context,
    await_gate,
    decision_matches,
    finish,
    policy_for,
    seat_started,
    validate_output,
)


def _run(coro_factory):
    """Run a coroutine to completion from sync code, also when called inside a running loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro_factory())
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(coro_factory())).result()


def _client_class():
    from autogen_core.models import (
        ChatCompletionClient,
        CreateResult,
        ModelInfo,
        RequestUsage,
    )

    class CouncilChatClient(ChatCompletionClient):
        """ChatCompletionClient over the council SeatModel. No tools, no streaming, no network in mock mode."""

        def __init__(self, seat_model: SeatModel) -> None:
            self._seat_model = seat_model
            self._usage = RequestUsage(prompt_tokens=0, completion_tokens=0)

        async def create(self, messages, *, tools=(), tool_choice="auto", json_output=None, extra_create_args=None,
                         cancellation_token=None) -> CreateResult:
            if tools:
                raise ValueError("council agents have no tools")
            text = "\n".join(m.content if isinstance(getattr(m, "content", None), str) else str(getattr(m, "content", ""))
                             for m in messages)
            content = await asyncio.to_thread(self._seat_model.complete, text)
            return CreateResult(finish_reason="stop", content=content, usage=self._usage, cached=False)

        async def create_stream(self, messages, **kwargs: Any):
            yield await self.create(messages, **kwargs)

        async def close(self) -> None:
            return None

        def actual_usage(self) -> RequestUsage:
            return self._usage

        def total_usage(self) -> RequestUsage:
            return self._usage

        def count_tokens(self, messages, *, tools=()) -> int:
            return 0

        def remaining_tokens(self, messages, *, tools=()) -> int:
            return 1_000_000

        @property
        def capabilities(self):  # deprecated alias of model_info, still abstract in 0.7
            return self.model_info

        @property
        def model_info(self) -> ModelInfo:
            return ModelInfo(vision=False, function_calling=False, json_output=True, family="unknown",
                             structured_output=False, multiple_system_messages=False)

    return CouncilChatClient


def _agent(name: str, seat: str, context: dict, client):
    from autogen_agentchat.agents import AssistantAgent

    return AssistantAgent(name=name, model_client=client, system_message=seat_prompt(seat, context),
                          description=ROLES[seat][1], tools=None, reflect_on_tool_use=False)


def _team(participants: list, max_messages: int):
    from autogen_agentchat.conditions import MaxMessageTermination, TimeoutTermination
    from autogen_agentchat.teams import RoundRobinGroupChat

    termination = MaxMessageTermination(max_messages) | TimeoutTermination(seat_timeout_seconds() * len(participants))
    return RoundRobinGroupChat(participants, termination_condition=termination, max_turns=len(participants))


def _by_source(result) -> dict[str, str]:
    out: dict[str, str] = {}
    for message in result.messages:
        content = getattr(message, "content", None)
        if isinstance(content, str):
            out[message.source] = content
    return out


class AutoGenEngine:
    name = "autogen"

    def availability(self) -> tuple[bool, str]:
        try:
            import autogen_agentchat
            import autogen_core  # noqa: F401
        except ImportError:
            return False, "NOT_INSTALLED: pip install -e './services/langgraph[council]'"
        return True, f"autogen-agentchat {autogen_agentchat.__version__} (bounded RoundRobinGroupChat, no code execution)"

    def _phase_a(self, ctx: EngineContext, state: dict) -> EngineStep:
        scan = policy_for(state)
        client = _client_class()(ctx.model)
        task = (f"Mission {state['mission_id']}: George decomposes the idea, then Fable/Cipher audits the plan. "
                "Each answers once with one JSON object.")
        last = "SEAT_OUTPUT_INVALID"
        for attempt in range(1, seat_max_attempts() + 1):
            started = seat_started(ctx, "george")
            george = _agent("George_Commander", "george", {"idea": state["idea"]}, client)
            fable = _agent("Fable_Sentinel", "fable", {"idea": state["idea"], "policy": scan.model_dump(mode="json")}, client)
            team = _team([george, fable], 3)
            result = _run(lambda team=team: team.run(task=task))
            said = _by_source(result)
            try:
                strategy = validate_output("george", said.get("George_Commander", ""))
                risk = validate_output("fable", said.get("Fable_Sentinel", ""), policy=scan)
            except ValueError:  # includes pydantic.ValidationError
                continue
            apply_strategy(ctx, state, strategy, attempt, started)
            fable_started = seat_started(ctx, "fable")
            apply_audit(ctx, state, risk, attempt, fable_started)
            return self._route(ctx, state)
        from ..seats import SeatFailed

        raise SeatFailed("george", last, seat_max_attempts())

    def _route(self, ctx: EngineContext, state: dict) -> EngineStep:
        risk = state["risk"]
        if risk["blocked"]:
            return finish(ctx, state, "BLOCKED")
        if risk["requires_approval"]:
            return await_gate(ctx, state)
        return self._phase_b(ctx, state)

    def _phase_b(self, ctx: EngineContext, state: dict) -> EngineStep:
        client = _client_class()(ctx.model)
        for attempt in range(1, seat_max_attempts() + 1):
            started = seat_started(ctx, "arty")
            arty = _agent("Arty_Maker", "arty", arty_context(state), client)
            team = _team([arty], 2)
            result = _run(lambda team=team: team.run(
                task=f"Mission {state['mission_id']} is approved. Arty produces the scaffold as one JSON object."))
            try:
                scaffold = validate_output("arty", _by_source(result).get("Arty_Maker", ""))
            except ValueError:
                continue
            apply_scaffold(ctx, state, scaffold, attempt, started)
            return finish(ctx, state, "COMPLETED")
        from ..seats import SeatFailed

        raise SeatFailed("arty", "SEAT_OUTPUT_INVALID", seat_max_attempts())

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
        state.update({"strategy": None, "risk": None})
        return self._phase_a(ctx, state)


__all__ = ["INSTRUCTIONS", "AutoGenEngine", "parse_prompt"]
