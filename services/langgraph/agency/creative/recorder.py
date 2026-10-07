"""Flight recorder: a hash-chained event log that holds references, never content.

Every event value must be a short identifier, enum or hash: free text, copy,
rendered HTML and anything secret-shaped are refused (``RecorderRefused``), so
a trace can be stored or shared without leaking brief content or secrets.
``trace_to_test`` turns a run into a regression fixture whose replay must be
byte-identical in its hashes (Trace -> Test).
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Optional

from pydantic import BaseModel, ConfigDict

from services.langgraph.agency.execution.canonical import canonical_hash

from .critics import _SECRETS

EVENT_KINDS = frozenset({
    "MISSION_COMPILED", "PLAN_COMPILED", "CONTEXT_SELECTED", "CANDIDATE_GENERATED", "CANDIDATE_REGENERATED",
    "CANDIDATE_FAILED", "FEASIBILITY_CHECKED", "EVALUATED", "PARETO_COMPUTED", "HUMAN_ACTION", "CORRECTION_APPLIED",
    "CORRECTION_REJECTED", "TRIDIFF", "APPROVAL_REQUESTED", "APPROVAL_SUPERSEDED", "DELIVERY_GATE", "IMMUNE_ACTION",
    "BUDGET_EXHAUSTED", "DEGRADED", "TERMINAL",
})
_SAFE = re.compile(r"^[A-Za-z0-9_.:@/#=+-]{1,160}$")
GENESIS = "0" * 64


class RecorderRefused(ValueError):
    code = "RECORDER_REFUSED"


class FlightEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    seq: int
    kind: str
    node: str
    status: str
    refs: dict[str, Any]
    prev_hash: str
    event_hash: str


def _check(value: Any, path: str) -> None:
    if value is None or isinstance(value, (bool, int, float)):
        return
    if isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            _check(v, f"{path}[{i}]")
        return
    if isinstance(value, str):
        if not _SAFE.match(value) or any(rx.search(value) for rx in _SECRETS):
            raise RecorderRefused(f"{path}: only identifiers and hashes may be recorded")
        return
    raise RecorderRefused(f"{path}: unsupported type {type(value).__name__}")


class FlightRecorder:
    def __init__(self, events: Iterable[FlightEvent] = ()) -> None:
        self._events = list(events)

    @property
    def head(self) -> str:
        return self._events[-1].event_hash if self._events else GENESIS

    def record(self, kind: str, node: str, status: str = "ok", **refs: Any) -> FlightEvent:
        if kind not in EVENT_KINDS:
            raise RecorderRefused(f"unknown event kind {kind}")
        _check([node, status], "event")
        for key, value in refs.items():
            _check(value, key)
        seq = len(self._events)
        body = {"seq": seq, "kind": kind, "node": node, "status": status, "refs": refs, "prev_hash": self.head}
        event = FlightEvent(**body, event_hash=canonical_hash(body))
        self._events.append(event)
        return event

    @property
    def events(self) -> tuple[FlightEvent, ...]:
        return tuple(self._events)


def verify_chain(events: Iterable[FlightEvent]) -> bool:
    prev = GENESIS
    for i, e in enumerate(events):
        body = {"seq": e.seq, "kind": e.kind, "node": e.node, "status": e.status, "refs": e.refs, "prev_hash": e.prev_hash}
        if e.seq != i or e.prev_hash != prev or canonical_hash(body) != e.event_hash:
            return False
        prev = e.event_hash
    return True


def trace_to_test(run: Any, *, name: Optional[str] = None) -> dict:
    """A deterministic regression fixture for a run (hashes and decisions only)."""
    return {
        "name": name or f"trace-{run.run_id}",
        "brief_hash": run.brief_hash,
        "expect": {
            "state": run.state,
            "mission_hash": run.mission.mission_hash if run.mission else None,
            "plan_hash": run.plan.plan_hash if run.plan else None,
            "topology": run.plan.topology_class if run.plan else None,
            "context_hash": run.context.context_hash if run.context else None,
            "candidates": {c.candidate_id: c.artifact.hash for c in run.candidates},
            "front": list(run.front),
            "event_kinds": [e.kind for e in run.events],
        },
    }


def replay_matches(fixture: dict, run: Any) -> list[str]:
    """Differences between a fixture and a replayed run (empty = identical)."""
    fresh = trace_to_test(run, name=fixture.get("name"))
    diffs = []
    if fresh["brief_hash"] != fixture["brief_hash"]:
        diffs.append("brief_hash")
    for key, value in fixture["expect"].items():
        if fresh["expect"].get(key) != value:
            diffs.append(key)
    return diffs


__all__ = ["EVENT_KINDS", "FlightEvent", "FlightRecorder", "RecorderRefused", "replay_matches", "trace_to_test", "verify_chain"]
