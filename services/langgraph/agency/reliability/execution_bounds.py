"""Execution-layer bounds for agent tool calls (ASI08 cascading failures, ASI10 rogue agents).

A ``SessionGuard`` sits in front of every tool invocation for one session (tenant, project,
mission). It admits or refuses a call before any effect happens.

Bounds (refusals change no admission state):

* ``SESSION_TIMEOUT``       session older than ``session_timeout_s`` (META_CONFIG: 300 s);
* ``DEPTH_EXCEEDED``        nesting depth above ``max_depth`` (META_CONFIG: 12);
* ``CALL_BUDGET_EXHAUSTED`` more admitted calls than ``max_calls``;
* ``LOOP_DETECTED``         the same tool with byte-identical arguments admitted more than
                            ``retry_limit + 1`` times (1 attempt + 3 retries, META_CONFIG);
* ``CIRCUIT_OPEN``          the tool's breaker is open, or a half-open probe is already in flight.

Per-tool circuit breaker: ``failure_threshold`` consecutive failures open it for ``cooldown_s``.
After the cooldown one probe is admitted (half-open). A success closes it; a failed probe reopens it.

Anomaly monitor and terminator (ASI10). Each anomaly is a strike. It refuses the call that shows it,
and it is recorded:

* ``VELOCITY_EXCEEDED``   more than ``max_calls_per_window`` admissions in ``window_s`` seconds;
* ``TOOL_SPRAWL``         more than ``max_novel_tools`` distinct tools in one session;
* ``GOAL_DRIFT``          ``drift_window`` consecutive calls whose text shares no term with the mission
                          objective (only when an objective is supplied; heuristic, English terms);
* ``REFUSAL_STREAK``      ``max_consecutive_refusals`` refusals in a row;
* ``REPLICATION_DETECTED`` more session-spawning calls than ``max_session_spawns``.

When strikes reach ``max_strikes`` the session is **halted**. Every later call is refused with
``SESSION_HALTED`` (HTTP 423). Only ``clear_halt(...)`` lifts a halt, and it requires a named owner.
It is a library function. No API endpoint clears a halt.

Scope and honest limits:

* The spec's ``step_entropy_cap`` has no operational definition. It is implemented as a bound on
  repeated identical calls, not as Shannon entropy.
* State is process-local. A multi-worker deployment needs a persisted guard, otherwise each worker
  enforces its own budget and halt. This is recorded as a gap, not hidden.
* Halted guards are never evicted from the registry, so a halt cannot be cleared by churning sessions.
  When every slot holds a halted session, a new session is refused (``SESSION_REGISTRY_FULL``).
* The goal-drift and replication signals are heuristics with measured baselines still to be collected.
"""
from __future__ import annotations

import re
import threading
import time
from collections import Counter, OrderedDict, deque
from dataclasses import dataclass, field
from typing import Callable, Hashable, Optional

MAX_DEPTH = 12
RETRY_LIMIT = 3
SESSION_TIMEOUT_S = 300.0
MAX_CALLS = 60
FAILURE_THRESHOLD = 3
COOLDOWN_S = 60.0
MAX_SESSIONS = 4096

# ASI10 anomaly defaults. Each is a reviewed starting point, not a measured baseline.
MAX_STRIKES = 3
WINDOW_S = 10.0
MAX_CALLS_PER_WINDOW = 20
MAX_NOVEL_TOOLS = 8
DRIFT_WINDOW = 3
MIN_DRIFT_TERMS = 3
MAX_CONSECUTIVE_REFUSALS = 5
MAX_SESSION_SPAWNS = 2

CLOSED, OPEN, HALF_OPEN = "CLOSED", "OPEN", "HALF_OPEN"
_TERM = re.compile(r"[a-z]{4,}")
_STOP = frozenset({"that", "this", "with", "from", "into", "have", "will", "should", "about", "their", "there",
                   "which", "where", "when", "what", "them", "they", "then", "than", "also", "make", "need"})


class BoundViolation(Exception):
    """A call was refused before execution. ``code`` is stable and safe to surface."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True)
class Limits:
    max_depth: int = MAX_DEPTH
    retry_limit: int = RETRY_LIMIT
    session_timeout_s: float = SESSION_TIMEOUT_S
    max_calls: int = MAX_CALLS
    failure_threshold: int = FAILURE_THRESHOLD
    cooldown_s: float = COOLDOWN_S
    max_strikes: int = MAX_STRIKES
    window_s: float = WINDOW_S
    max_calls_per_window: int = MAX_CALLS_PER_WINDOW
    max_novel_tools: int = MAX_NOVEL_TOOLS
    drift_window: int = DRIFT_WINDOW
    max_consecutive_refusals: int = MAX_CONSECUTIVE_REFUSALS
    max_session_spawns: int = MAX_SESSION_SPAWNS

    def __post_init__(self) -> None:
        if not 1 <= self.max_depth <= 12:
            raise ValueError("max_depth must be between 1 and 12")
        if not 0 <= self.retry_limit <= 3:
            raise ValueError("retry_limit must be between 0 and 3")
        if self.session_timeout_s <= 0 or self.max_calls < 1 or self.failure_threshold < 1 or self.cooldown_s <= 0:
            raise ValueError("limits must be positive")
        if self.max_strikes < 1 or self.window_s <= 0 or self.max_calls_per_window < 1 or self.max_novel_tools < 1:
            raise ValueError("anomaly limits must be positive")
        if self.drift_window < 1 or self.max_consecutive_refusals < 1 or self.max_session_spawns < 0:
            raise ValueError("anomaly limits must be positive")

    @property
    def max_identical(self) -> int:
        return self.retry_limit + 1


@dataclass
class _Breaker:
    state: str = CLOSED
    failures: int = 0
    opened_at: float = 0.0
    probing: bool = False


def objective_terms(text: str) -> frozenset[str]:
    """Content terms of a goal text, used for drift comparison."""
    return frozenset(t for t in _TERM.findall((text or "").lower()) if t not in _STOP)


@dataclass
class SessionGuard:
    limits: Limits = field(default_factory=Limits)
    clock: Callable[[], float] = time.monotonic

    def __post_init__(self) -> None:
        self._started = self.clock()
        self._calls = 0
        self._identical: Counter = Counter()
        self._breakers: dict[str, _Breaker] = {}
        self._seen_tools: set[str] = set()
        self._window: deque[float] = deque()
        self._drift_run = 0
        self._refusal_run = 0
        self._spawns = 0
        self._strikes: list[str] = []
        self._halted = False
        self._halt_reason = ""
        self._clears: list[dict] = []
        self._lock = threading.Lock()

    # ---- inspection (for audit and tests) --------------------------------------
    @property
    def admitted_calls(self) -> int:
        return self._calls

    @property
    def halted(self) -> bool:
        return self._halted

    def breaker_state(self, node: str) -> str:
        return self._breakers.get(node, _Breaker()).state

    def anomaly_state(self) -> dict:
        with self._lock:
            return {"halted": self._halted, "halt_reason": self._halt_reason, "strikes": list(self._strikes),
                    "clears": [dict(c) for c in self._clears]}

    # ---- admission -------------------------------------------------------------
    def admit(self, node: str, args_hash: str, *, depth: int = 1, objective: frozenset[str] = frozenset(),
              text: str = "", spawns_session: bool = False) -> None:
        """Admit one call or raise ``BoundViolation``. A refusal admits nothing; anomaly strikes are recorded."""
        with self._lock:
            if self._halted:
                raise BoundViolation("SESSION_HALTED", f"session halted: {self._halt_reason}")
            try:
                self._check_bounds(node, args_hash, depth)
                pending = self._check_anomalies(node, objective, text, spawns_session)
            except BoundViolation as exc:
                self._refusal_run += 1
                if exc.code in _STRIKE_CODES:
                    self._strike(exc.code)
                elif self._refusal_run >= self.limits.max_consecutive_refusals:
                    self._strike("REFUSAL_STREAK")
                raise
            # Every check passed: commit.
            now = self.clock()
            self._window.append(now)
            while self._window and now - self._window[0] > self.limits.window_s:
                self._window.popleft()
            self._seen_tools.add(node)
            self._drift_run = pending["drift_run"]
            self._spawns += 1 if spawns_session else 0
            self._refusal_run = 0
            breaker = self._breakers.setdefault(node, _Breaker())
            if breaker.state == HALF_OPEN:
                breaker.probing = True
            self._identical[(node, args_hash)] += 1
            self._calls += 1

    def _check_bounds(self, node: str, args_hash: str, depth: int) -> None:
        now = self.clock()
        if now - self._started > self.limits.session_timeout_s:
            raise BoundViolation("SESSION_TIMEOUT", f"session exceeded {self.limits.session_timeout_s:g}s")
        if depth > self.limits.max_depth:
            raise BoundViolation("DEPTH_EXCEEDED", f"depth {depth} > {self.limits.max_depth}")
        if self._calls >= self.limits.max_calls:
            raise BoundViolation("CALL_BUDGET_EXHAUSTED", f"{self.limits.max_calls} calls already admitted")
        if self._identical[(node, args_hash)] + 1 > self.limits.max_identical:
            raise BoundViolation("LOOP_DETECTED",
                                 f"{node} repeated with identical arguments more than {self.limits.max_identical} times")
        breaker = self._breakers.get(node) or _Breaker()
        if breaker.state == OPEN:
            if now - breaker.opened_at < self.limits.cooldown_s:
                raise BoundViolation("CIRCUIT_OPEN", f"{node} is cooling down")
            breaker.state = HALF_OPEN
            breaker.probing = False
        if breaker.state == HALF_OPEN and breaker.probing:
            raise BoundViolation("CIRCUIT_OPEN", f"{node} is already probing after cooldown")
        self._breakers[node] = breaker

    def _check_anomalies(self, node: str, objective: frozenset[str], text: str, spawns_session: bool) -> dict:
        now = self.clock()
        recent = [t for t in self._window if now - t <= self.limits.window_s]
        if len(recent) >= self.limits.max_calls_per_window:
            raise BoundViolation("VELOCITY_EXCEEDED", f"more than {self.limits.max_calls_per_window} calls in "
                                                      f"{self.limits.window_s:g}s")
        if node not in self._seen_tools and len(self._seen_tools) >= self.limits.max_novel_tools:
            raise BoundViolation("TOOL_SPRAWL", f"more than {self.limits.max_novel_tools} distinct tools in one session")
        if spawns_session and self._spawns >= self.limits.max_session_spawns:
            raise BoundViolation("REPLICATION_DETECTED", "session-spawning calls exceed the session allowance")
        drift_run = self._drift_run
        terms = objective_terms(text)
        if objective and len(terms) >= MIN_DRIFT_TERMS:
            drift_run = 0 if terms & objective else self._drift_run + 1
            if drift_run >= self.limits.drift_window:
                raise BoundViolation("GOAL_DRIFT", f"{drift_run} consecutive calls share no term with the objective")
        return {"drift_run": drift_run}

    def _strike(self, code: str) -> None:
        self._strikes.append(code)
        if not self._halted and len(self._strikes) >= self.limits.max_strikes:
            self._halted = True
            self._halt_reason = ", ".join(self._strikes)

    def clear_halt(self, owner: str, *, note: str) -> dict:
        """Lift a halt. A named owner is required and the clear is recorded. Not reachable over HTTP."""
        if not isinstance(owner, str) or not owner.strip() or owner.strip().lower() in {"service", "system", "agent"}:
            raise ValueError("clear_halt needs a named human owner")
        if not note or not note.strip():
            raise ValueError("clear_halt needs a note explaining the decision")
        with self._lock:
            record = {"owner": owner.strip(), "note": note.strip()[:300], "halt_reason": self._halt_reason,
                      "strikes": list(self._strikes)}
            self._clears.append(record)
            self._halted = False
            self._halt_reason = ""
            self._strikes = []
            self._refusal_run = 0
            self._drift_run = 0
            return dict(record)

    def record(self, node: str, *, ok: bool) -> None:
        """Report the outcome of an admitted call."""
        with self._lock:
            breaker = self._breakers.setdefault(node, _Breaker())
            if ok:
                breaker.state, breaker.failures, breaker.probing = CLOSED, 0, False
                return
            breaker.failures += 1
            breaker.probing = False
            if breaker.state == HALF_OPEN or breaker.failures >= self.limits.failure_threshold:
                breaker.state, breaker.opened_at = OPEN, self.clock()


_STRIKE_CODES = frozenset({"VELOCITY_EXCEEDED", "TOOL_SPRAWL", "GOAL_DRIFT", "REFUSAL_STREAK",
                           "REPLICATION_DETECTED"})

_REGISTRY: "OrderedDict[Hashable, SessionGuard]" = OrderedDict()
_REGISTRY_LOCK = threading.Lock()


def guard_for(session_key: Hashable, *, limits: Optional[Limits] = None,
              clock: Callable[[], float] = time.monotonic) -> SessionGuard:
    """Return the guard for one session, creating it on first use.

    Oldest non-halted sessions are evicted. Halted sessions are never evicted. If every slot holds a
    halted session, a new session is refused rather than displacing a halt.
    """
    with _REGISTRY_LOCK:
        guard = _REGISTRY.get(session_key)
        if guard is None:
            while len(_REGISTRY) >= MAX_SESSIONS:
                evict = next((k for k, g in _REGISTRY.items() if not g.halted), None)
                if evict is None:
                    raise BoundViolation("SESSION_REGISTRY_FULL", "every session slot holds a halted session")
                del _REGISTRY[evict]
            guard = SessionGuard(limits=limits or Limits(), clock=clock)
            _REGISTRY[session_key] = guard
        else:
            _REGISTRY.move_to_end(session_key)
        return guard


def clear_halt(session_key: Hashable, owner: str, *, note: str) -> dict:
    """Owner-initiated lift of a halt for one session. Raises KeyError if the session has no guard."""
    with _REGISTRY_LOCK:
        guard = _REGISTRY.get(session_key)
    if guard is None:
        raise KeyError("no guard for this session")
    return guard.clear_halt(owner, note=note)


def reset_registry() -> None:
    """Test and maintenance hook. Clears all process-local session guards."""
    with _REGISTRY_LOCK:
        _REGISTRY.clear()


__all__ = ["BoundViolation", "Limits", "SessionGuard", "clear_halt", "guard_for", "objective_terms",
           "reset_registry", "CLOSED", "OPEN", "HALF_OPEN"]
