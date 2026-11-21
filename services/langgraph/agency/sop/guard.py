"""Fail-closed runtime guard for the SOP pre/post-conditions of live graph stages.

``guard_stage`` wraps a node function. Before it runs, every state key its SOP
step requires must already be in the run's agency payload, so a stage invoked
out of order (or after an upstream stage silently produced nothing) is
refused. After it returns, every key its step declares as output must be
present. A violation raises; it is never downgraded to a warning, and the
API's existing handler records the run as ``failed``.
"""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable, Mapping

from services.langgraph.agency.sop.contracts import SopStep, load_registry

NodeFn = Callable[[Mapping[str, Any]], dict]


class SopContractViolation(RuntimeError):
    """A live stage ran without its SOP entry conditions or broke its exit conditions."""


def _agency(state: Mapping[str, Any]) -> Mapping[str, Any]:
    return ((state or {}).get("extracted_data") or {}).get("agency") or {}


def assert_entry(step: SopStep, state: Mapping[str, Any]) -> None:
    agency = _agency(state)
    missing = [key for key in step.requires_state if agency.get(key) is None]
    if missing:
        raise SopContractViolation(f"{step.sop_id} {step.stage_name}: entry precondition missing {missing}")


def assert_exit(step: SopStep, update: Mapping[str, Any]) -> None:
    agency = _agency(update)
    missing = [key for key in step.output_schema if agency.get(key) is None]
    if missing:
        raise SopContractViolation(f"{step.sop_id} {step.stage_name}: exit postcondition missing {missing}")


def guard_stage(stage_name: str, node: NodeFn) -> NodeFn:
    step = load_registry().pipeline_step(stage_name)
    if step is None:
        raise SopContractViolation(f"stage {stage_name} has no SOP step")

    @wraps(node)
    def guarded(state: Mapping[str, Any]) -> dict:
        assert_entry(step, state)
        update = node(state)
        assert_exit(step, update)
        return update

    return guarded
