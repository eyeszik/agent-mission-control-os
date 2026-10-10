"""Track B: the persistent run state machine F = (S, T, G, A).

S is ``RunState``. T is ``TRANSITIONS`` (the only legal edges). G (guards) and
A (actions) live in :mod:`.ticks`, which is the only code that moves a job, and
every move is written to ``durable_transitions`` with its fencing token and
logical tick. Pure: no persistence imports.
"""

from __future__ import annotations

from enum import Enum

RUN_FSM_VERSION = "amc-run-fsm/v1"


class RunState(str, Enum):
    DORMANT = "DORMANT"
    SCHEDULED = "SCHEDULED"
    LEASED = "LEASED"
    PRECHECK = "PRECHECK"
    READY = "READY"
    RUNNING = "RUNNING"
    OBSERVING = "OBSERVING"
    VERIFYING = "VERIFYING"
    COMMITTING = "COMMITTING"
    RECONCILING = "RECONCILING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    RETRY_PENDING = "RETRY_PENDING"
    DEGRADED = "DEGRADED"
    BLOCKED_PROVIDER = "BLOCKED_PROVIDER"
    BLOCKED_AUTHORITY = "BLOCKED_AUTHORITY"
    BLOCKED_ENVIRONMENT = "BLOCKED_ENVIRONMENT"
    INCONCLUSIVE = "INCONCLUSIVE"
    DEAD_LETTER = "DEAD_LETTER"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"


S = RunState
# States in which a worker holds (or held) a lease. A job found in one of these
# with an expired lease was interrupted, and is only claimable into RECONCILING.
IN_FLIGHT = frozenset({S.LEASED, S.PRECHECK, S.READY, S.RUNNING, S.OBSERVING, S.VERIFYING, S.COMMITTING, S.RECONCILING})
# States from which a fresh lease may be taken when due.
CLAIMABLE = frozenset({S.SCHEDULED, S.RETRY_PENDING})
TERMINAL = frozenset({S.STOPPED})
BLOCKED = frozenset({S.BLOCKED_PROVIDER, S.BLOCKED_AUTHORITY, S.BLOCKED_ENVIRONMENT})

TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    S.DORMANT: frozenset({S.SCHEDULED, S.STOPPED}),
    S.SCHEDULED: frozenset({S.LEASED, S.PAUSED, S.STOPPED}),
    S.LEASED: frozenset({S.PRECHECK, S.SCHEDULED, S.RECONCILING}),
    S.PRECHECK: frozenset({S.READY, S.RECONCILING, S.WAITING_APPROVAL, S.DORMANT, *BLOCKED}),
    S.READY: frozenset({S.RUNNING, S.RECONCILING}),
    S.RUNNING: frozenset({S.OBSERVING, S.RETRY_PENDING, S.DEGRADED, S.INCONCLUSIVE, S.DEAD_LETTER, S.RECONCILING, *BLOCKED}),
    S.OBSERVING: frozenset({S.VERIFYING, S.INCONCLUSIVE, S.RECONCILING}),
    S.VERIFYING: frozenset({S.COMMITTING, S.RETRY_PENDING, S.INCONCLUSIVE, S.DEAD_LETTER, S.RECONCILING}),
    S.COMMITTING: frozenset({S.WAITING_APPROVAL, S.SCHEDULED, S.DORMANT, S.RECONCILING}),
    S.RECONCILING: frozenset({S.READY, S.OBSERVING, S.DEAD_LETTER, S.WAITING_APPROVAL}),
    S.WAITING_APPROVAL: frozenset({S.SCHEDULED, S.DORMANT, S.STOPPED}),
    S.RETRY_PENDING: frozenset({S.LEASED, S.DEAD_LETTER, S.PAUSED, S.STOPPED}),
    S.DEGRADED: frozenset({S.SCHEDULED, S.PAUSED, S.STOPPED}),
    S.BLOCKED_PROVIDER: frozenset({S.SCHEDULED, S.PAUSED, S.STOPPED}),
    S.BLOCKED_AUTHORITY: frozenset({S.SCHEDULED, S.PAUSED, S.STOPPED}),
    S.BLOCKED_ENVIRONMENT: frozenset({S.SCHEDULED, S.PAUSED, S.STOPPED}),
    S.INCONCLUSIVE: frozenset({S.SCHEDULED, S.DEAD_LETTER, S.PAUSED, S.STOPPED}),
    S.DEAD_LETTER: frozenset({S.PAUSED, S.STOPPED}),
    S.PAUSED: frozenset({S.SCHEDULED, S.STOPPED}),
    S.STOPPED: frozenset(),
}


class IllegalTransition(ValueError):
    pass


def assert_transition(src: RunState | str, dst: RunState | str) -> None:
    a, b = RunState(src), RunState(dst)
    if b not in TRANSITIONS[a]:
        raise IllegalTransition(f"{a.value} -> {b.value} is not a legal run transition")


def reachable(start: RunState = S.DORMANT) -> set[RunState]:
    seen, stack = {start}, [start]
    while stack:
        for nxt in TRANSITIONS[stack.pop()]:
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


__all__ = ["BLOCKED", "CLAIMABLE", "IN_FLIGHT", "IllegalTransition", "RUN_FSM_VERSION", "RunState", "TERMINAL",
           "TRANSITIONS", "assert_transition", "reachable"]
