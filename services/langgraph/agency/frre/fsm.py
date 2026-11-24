"""FRRE incident state machine (W1, pure).

``TRANSITIONS`` is the only legal edge set. It is identical to the model-checked design in
``docs/frre/FRRE-v15-spec.md`` section 4; ``test_frre_w1`` proves that against the preserved
checker (``tests/fixtures/frre/fsm_check_v15.py``), so the two cannot drift silently.

Termination: the graph has cycles (re-triage after BLOCKED/ESCALATED, re-plan after
QUARANTINED, the rollback/observe/recovery loop). Every edge that closes a cycle is listed in
``BUDGETED_EDGES`` and consumes a finite counter. Removing those edges leaves a DAG, so
``(attempts_left, recoveries_left, topological rank)`` strictly decreases on every move:
every run ends in a terminal state or in ESCALATED once a budget is exhausted.

Pure: no persistence, no I/O. Guards that need facts (permits, versions, budgets) live in
:mod:`.guards`.
"""

from __future__ import annotations

from enum import Enum
from typing import Final, Mapping


FRRE_FSM_VERSION: Final = "amc-frre-fsm/v1"


class IncidentState(str, Enum):
    OBSERVED = "OBSERVED"
    DEDUPLICATED = "DEDUPLICATED"
    TRIAGED = "TRIAGED"
    REPRODUCTION_AUTHORIZED = "REPRODUCTION_AUTHORIZED"
    REPRODUCED = "REPRODUCED"
    DIAGNOSED = "DIAGNOSED"
    PLANNED = "PLANNED"
    MUTATION_AUTHORIZED = "MUTATION_AUTHORIZED"
    SANDBOXED = "SANDBOXED"
    PATCHED = "PATCHED"
    CANDIDATE_SEALED = "CANDIDATE_SEALED"
    VALIDATION_AUTHORIZED = "VALIDATION_AUTHORIZED"
    VALIDATED = "VALIDATED"
    REVIEW_READY = "REVIEW_READY"
    RELEASE_APPROVED = "RELEASE_APPROVED"
    RELEASED = "RELEASED"
    POST_RELEASE_OBSERVED = "POST_RELEASE_OBSERVED"
    RESOLVED = "RESOLVED"
    BLOCKED = "BLOCKED"
    QUARANTINED = "QUARANTINED"
    ESCALATED = "ESCALATED"
    REJECTED = "REJECTED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    ROLLED_BACK = "ROLLED_BACK"
    NO_ACTION = "NO_ACTION"


S = IncidentState

MAIN_PATH: Final[tuple[IncidentState, ...]] = tuple(IncidentState)[:18]
TERMINAL: Final = frozenset({S.RESOLVED, S.REJECTED, S.NO_ACTION})
# States before any external effect: they may always stop safely.
PRE_EFFECT: Final = frozenset(MAIN_PATH[: MAIN_PATH.index(S.RELEASED)])
CANDIDATE_BEARING: Final = frozenset({S.SANDBOXED, S.PATCHED, S.CANDIDATE_SEALED, S.VALIDATION_AUTHORIZED, S.VALIDATED})
SAFE_STOPS: Final = frozenset({S.BLOCKED, S.ESCALATED, S.REJECTED, S.NO_ACTION})


def _build_transitions() -> dict[IncidentState, frozenset[IncidentState]]:
    edges: dict[IncidentState, set[IncidentState]] = {s: set() for s in IncidentState}
    for src, dst in zip(MAIN_PATH, MAIN_PATH[1:]):
        edges[src].add(dst)
    for state in PRE_EFFECT:
        edges[state] |= SAFE_STOPS
    for state in CANDIDATE_BEARING:
        edges[state].add(S.QUARANTINED)
    edges[S.RELEASED] |= {S.RECOVERY_REQUIRED, S.ESCALATED}
    edges[S.POST_RELEASE_OBSERVED].add(S.RECOVERY_REQUIRED)
    edges[S.RECOVERY_REQUIRED] = {S.ROLLED_BACK, S.ESCALATED}
    edges[S.ROLLED_BACK] = {S.POST_RELEASE_OBSERVED}
    edges[S.BLOCKED] = {S.TRIAGED, S.ESCALATED}
    edges[S.ESCALATED] = {S.TRIAGED, S.REJECTED, S.NO_ACTION}
    edges[S.QUARANTINED] = {S.PLANNED, S.REJECTED, S.ESCALATED}
    return {state: frozenset(targets) for state, targets in edges.items()}


TRANSITIONS: Final[Mapping[IncidentState, frozenset[IncidentState]]] = _build_transitions()

# Each effect stage may be entered only from the state that holds its permit.
PERMIT_GATES: Final[Mapping[IncidentState, IncidentState]] = {
    S.REPRODUCED: S.REPRODUCTION_AUTHORIZED,
    S.SANDBOXED: S.MUTATION_AUTHORIZED,
    S.VALIDATED: S.VALIDATION_AUTHORIZED,
    S.RELEASED: S.RELEASE_APPROVED,
}
# Permit stage required to *leave* a permit state into its effect stage.
PERMIT_STAGE_FOR: Final[Mapping[IncidentState, str]] = {
    S.REPRODUCED: "REPRODUCE", S.SANDBOXED: "MUTATE", S.VALIDATED: "VALIDATE", S.RELEASED: "RELEASE",
}

# Cycle-closing edges and the finite counter each one consumes. Each source state also has an
# unbudgeted exit (ESCALATED, REJECTED or NO_ACTION), so an exhausted budget never strands an
# incident. That is why the recovery budget sits on RECOVERY_REQUIRED -> ROLLED_BACK (which has
# ESCALATED beside it) and not on ROLLED_BACK -> POST_RELEASE_OBSERVED (ROLLED_BACK's only exit).
BUDGETED_EDGES: Final[Mapping[tuple[IncidentState, IncidentState], str]] = {
    (S.BLOCKED, S.TRIAGED): "attempts",
    (S.ESCALATED, S.TRIAGED): "attempts",
    (S.QUARANTINED, S.PLANNED): "attempts",
    (S.RECOVERY_REQUIRED, S.ROLLED_BACK): "recoveries",
}


class IllegalTransition(ValueError):
    """Raised for an edge outside ``TRANSITIONS``."""


def assert_transition(src: IncidentState | str, dst: IncidentState | str) -> None:
    source, target = IncidentState(src), IncidentState(dst)
    if target not in TRANSITIONS[source]:
        raise IllegalTransition(f"{source.value} -> {target.value} is not a legal FRRE transition")


def reachable(start: IncidentState = S.OBSERVED,
              edges: Mapping[IncidentState, frozenset[IncidentState]] = TRANSITIONS) -> set[IncidentState]:
    seen, todo = {start}, [start]
    while todo:
        for nxt in edges.get(todo.pop(), frozenset()):
            if nxt not in seen:
                seen.add(nxt)
                todo.append(nxt)
    return seen


def without_budgeted_edges() -> dict[IncidentState, frozenset[IncidentState]]:
    """``TRANSITIONS`` minus every budget-consuming edge. Must be acyclic (see module doc)."""
    return {src: frozenset(d for d in dsts if (src, d) not in BUDGETED_EDGES) for src, dsts in TRANSITIONS.items()}


__all__ = [
    "BUDGETED_EDGES", "CANDIDATE_BEARING", "FRRE_FSM_VERSION", "IllegalTransition", "IncidentState", "MAIN_PATH",
    "PERMIT_GATES", "PERMIT_STAGE_FOR", "PRE_EFFECT", "SAFE_STOPS", "TERMINAL", "TRANSITIONS", "assert_transition",
    "reachable", "without_budgeted_edges",
]
