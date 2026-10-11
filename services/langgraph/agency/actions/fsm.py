"""The ActionRequest state machine. Pure.

Happy path::

    PROPOSED → VALIDATED → PREPARED → AWAITING_APPROVAL → AUTHORIZED → RESERVED
      → DISPATCHING → OBSERVING → VERIFIED → COMPLETED

A timeout after dispatch is UNKNOWN, and UNKNOWN only leaves through
RECONCILING (I09). The one edge beyond the brief is FAILED → AUTHORIZED, the
bounded retry. The gateway only takes it for a RETRY_SAFE action whose failure
is known to have had no effect, within the attempt limit.
"""

from __future__ import annotations

from enum import Enum

ACTION_FSM_VERSION = "amc-action-fsm/v1"
MAX_ATTEMPTS = 3


class ActionState(str, Enum):
    PROPOSED = "PROPOSED"
    VALIDATED = "VALIDATED"
    PREPARED = "PREPARED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    AUTHORIZED = "AUTHORIZED"
    RESERVED = "RESERVED"
    DISPATCHING = "DISPATCHING"
    OBSERVING = "OBSERVING"
    VERIFIED = "VERIFIED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    RECONCILING = "RECONCILING"
    NEEDS_HUMAN = "NEEDS_HUMAN"


A = ActionState
PRE_DISPATCH = frozenset({A.PROPOSED, A.VALIDATED, A.PREPARED, A.AWAITING_APPROVAL, A.AUTHORIZED, A.RESERVED})
# States in which a worker holds a lease on the action.
LEASED = frozenset({A.DISPATCHING, A.OBSERVING, A.RECONCILING})
TERMINAL = frozenset({A.COMPLETED, A.REJECTED, A.BLOCKED, A.EXPIRED, A.CANCELLED})
_STOP = frozenset({A.BLOCKED, A.CANCELLED, A.EXPIRED})

TRANSITIONS: dict[ActionState, frozenset[ActionState]] = {
    A.PROPOSED: frozenset({A.VALIDATED, A.REJECTED, A.BLOCKED, A.CANCELLED}),
    A.VALIDATED: frozenset({A.PREPARED, A.BLOCKED, A.CANCELLED}),
    A.PREPARED: frozenset({A.AWAITING_APPROVAL, A.AUTHORIZED, *_STOP}),
    A.AWAITING_APPROVAL: frozenset({A.AUTHORIZED, A.REJECTED, *_STOP}),
    A.AUTHORIZED: frozenset({A.RESERVED, A.DISPATCHING, *_STOP}),
    A.RESERVED: frozenset({A.DISPATCHING, *_STOP}),
    A.DISPATCHING: frozenset({A.OBSERVING, A.UNKNOWN, A.FAILED}),
    A.OBSERVING: frozenset({A.VERIFIED, A.FAILED, A.UNKNOWN}),
    A.VERIFIED: frozenset({A.COMPLETED}),
    A.UNKNOWN: frozenset({A.RECONCILING}),
    A.RECONCILING: frozenset({A.VERIFIED, A.FAILED, A.NEEDS_HUMAN, A.UNKNOWN}),
    A.NEEDS_HUMAN: frozenset({A.RECONCILING, A.FAILED}),
    A.FAILED: frozenset({A.AUTHORIZED}),
    A.COMPLETED: frozenset(),
    A.REJECTED: frozenset(),
    A.BLOCKED: frozenset(),
    A.EXPIRED: frozenset(),
    A.CANCELLED: frozenset(),
}


class IllegalActionTransition(ValueError):
    pass


def assert_transition(src: ActionState | str, dst: ActionState | str) -> None:
    a, b = ActionState(src), ActionState(dst)
    if b not in TRANSITIONS[a]:
        raise IllegalActionTransition(f"{a.value} -> {b.value} is not a legal action transition")


__all__ = ["ACTION_FSM_VERSION", "ActionState", "IllegalActionTransition", "LEASED", "MAX_ATTEMPTS", "PRE_DISPATCH",
           "TERMINAL", "TRANSITIONS", "assert_transition"]
