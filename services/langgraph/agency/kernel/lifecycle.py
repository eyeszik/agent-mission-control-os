"""N2 — canonical project phase graphs and lifecycle transition rules.

The kernel enums (``EngagementStatus``, ``WorkstreamStatus``, ``ArtifactStatus``)
name the states. This module says which moves between them are legal and under
what conditions, so that "can this run advance?" is answered by a declared
matrix rather than by whichever call site happens to run first.

Two properties matter more than the individual edges:

* **Closed transitions.** A move not present in the matrix is rejected. Adding
  a state without adding its edges makes that state terminal, which is the safe
  failure direction.
* **Guarded release.** Degraded generation output and unresolved human approval
  each independently block the transitions that would put work in front of a
  client. These are checked as transition *guards*, not as advisory flags, so a
  caller cannot reach a released state by skipping a status check.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from services.langgraph.agency.kernel.models import (
    ArtifactStatus,
    EngagementStatus,
    WorkstreamStatus,
)

LIFECYCLE_VERSION = "amc-agency-lifecycle/n2-v1"

# Provenance modes that must never reach a client-visible state. Mirrors the
# generation provenance vocabulary used by the agency graph.
DEGRADED_PROVENANCE_MODES = frozenset({"FALLBACK_DEGRADED"})


class TransitionError(ValueError):
    """Raised when a lifecycle move is not permitted."""


@dataclass(frozen=True)
class TransitionContext:
    """Facts a guard may consult. Absent facts are treated as unproven."""

    generation_mode: str | None = None
    approval_decision: str | None = None
    approval_resolved: bool = False
    brand_safety_passed: bool | None = None
    external_side_effect: bool = False
    spend_authorized: bool = False
    unmet_hard_dependencies: tuple[str, ...] = ()

    @property
    def is_degraded(self) -> bool:
        return (self.generation_mode or "") in DEGRADED_PROVENANCE_MODES


# --------------------------------------------------------------------------
# Guards
# --------------------------------------------------------------------------

def _guard_not_degraded(context: TransitionContext) -> str | None:
    if context.is_degraded:
        return (
            "generation provenance is FALLBACK_DEGRADED; degraded output cannot reach "
            "a client-visible state"
        )
    return None


def _guard_approved(context: TransitionContext) -> str | None:
    if not context.approval_resolved:
        return "human approval is unresolved"
    if context.approval_decision != "approve":
        return f"human approval decision is '{context.approval_decision}', not 'approve'"
    return None


def _guard_brand_safety(context: TransitionContext) -> str | None:
    if context.brand_safety_passed is not True:
        return "brand safety review has not passed"
    return None


def _guard_dependencies_met(context: TransitionContext) -> str | None:
    if context.unmet_hard_dependencies:
        return "unmet hard dependencies: " + ", ".join(sorted(context.unmet_hard_dependencies))
    return None


def _guard_spend_authorized(context: TransitionContext) -> str | None:
    if context.external_side_effect and not context.spend_authorized:
        return "external side effect requires an explicit spend/publication authorization"
    return None


# Guards applied to any transition entering a client-visible state.
RELEASE_GUARDS = (
    _guard_not_degraded,
    _guard_approved,
    _guard_brand_safety,
    _guard_spend_authorized,
)


# --------------------------------------------------------------------------
# Transition matrices
# --------------------------------------------------------------------------

E = EngagementStatus
W = WorkstreamStatus
A = ArtifactStatus

# Terminal-ish states every phase may fall into. Declared once so the matrices
# below stay readable.
_ENGAGEMENT_INTERRUPTS = (E.blocked, E.degraded, E.review_required, E.paused, E.failed, E.cancelled)

ENGAGEMENT_TRANSITIONS: dict[EngagementStatus, frozenset[EngagementStatus]] = {
    E.intake: frozenset((E.discovery, *_ENGAGEMENT_INTERRUPTS)),
    E.discovery: frozenset((E.research, *_ENGAGEMENT_INTERRUPTS)),
    E.research: frozenset((E.strategy, *_ENGAGEMENT_INTERRUPTS)),
    E.strategy: frozenset((E.brand, E.product, *_ENGAGEMENT_INTERRUPTS)),
    E.brand: frozenset((E.product, E.build, *_ENGAGEMENT_INTERRUPTS)),
    E.product: frozenset((E.build, *_ENGAGEMENT_INTERRUPTS)),
    E.build: frozenset((E.launch_ready, *_ENGAGEMENT_INTERRUPTS)),
    E.launch_ready: frozenset((E.launched, *_ENGAGEMENT_INTERRUPTS)),
    E.launched: frozenset((E.growth, *_ENGAGEMENT_INTERRUPTS)),
    E.growth: frozenset((E.optimizing, E.complete, *_ENGAGEMENT_INTERRUPTS)),
    E.optimizing: frozenset((E.growth, E.complete, *_ENGAGEMENT_INTERRUPTS)),
    # Interrupt states resume into the phases that can legitimately continue work.
    E.blocked: frozenset((E.discovery, E.research, E.strategy, E.brand, E.product, E.build, E.cancelled, E.failed)),
    E.degraded: frozenset((E.research, E.strategy, E.brand, E.product, E.build, E.review_required, E.failed, E.cancelled)),
    E.review_required: frozenset((E.strategy, E.brand, E.product, E.build, E.launch_ready, E.blocked, E.failed, E.cancelled)),
    E.paused: frozenset((E.discovery, E.research, E.strategy, E.brand, E.product, E.build, E.growth, E.cancelled)),
    E.complete: frozenset(),
    E.failed: frozenset(),
    E.cancelled: frozenset(),
}

WORKSTREAM_TRANSITIONS: dict[WorkstreamStatus, frozenset[WorkstreamStatus]] = {
    W.blocked: frozenset((W.ready, W.cancelled, W.failed)),
    W.ready: frozenset((W.executing, W.blocked, W.cancelled)),
    W.executing: frozenset((W.validating, W.degraded, W.failed, W.blocked, W.cancelled)),
    W.validating: frozenset((W.review, W.executing, W.degraded, W.failed, W.cancelled)),
    W.review: frozenset((W.approved, W.rejected, W.executing, W.cancelled)),
    W.approved: frozenset((W.released, W.rejected, W.cancelled)),
    W.degraded: frozenset((W.executing, W.failed, W.cancelled)),
    W.released: frozenset(),
    W.failed: frozenset(),
    W.rejected: frozenset(),
    W.cancelled: frozenset(),
}

ARTIFACT_TRANSITIONS: dict[ArtifactStatus, frozenset[ArtifactStatus]] = {
    A.draft: frozenset((A.validating, A.invalidated, A.archived)),
    A.validating: frozenset((A.approved, A.review_required, A.draft, A.invalidated)),
    A.approved: frozenset((A.release_eligible, A.review_required, A.invalidated)),
    A.release_eligible: frozenset((A.released, A.review_required, A.invalidated)),
    A.released: frozenset((A.review_required, A.invalidated, A.archived)),
    A.review_required: frozenset((A.validating, A.draft, A.invalidated, A.archived)),
    A.invalidated: frozenset((A.draft, A.archived)),
    A.archived: frozenset(),
}

# Transitions that put work in front of a client. Entering any of these runs
# the full RELEASE_GUARDS set.
CLIENT_VISIBLE_TRANSITIONS: dict[str, frozenset] = {
    "engagement": frozenset((E.launched,)),
    "workstream": frozenset((W.released,)),
    "artifact": frozenset((A.release_eligible, A.released)),
}

# Transitions that additionally require all hard dependencies to be satisfied.
DEPENDENCY_GATED_TRANSITIONS: dict[str, frozenset] = {
    "engagement": frozenset((E.build, E.launch_ready)),
    "workstream": frozenset((W.executing,)),
    "artifact": frozenset((A.release_eligible,)),
}

_MATRICES: dict[str, dict] = {
    "engagement": ENGAGEMENT_TRANSITIONS,
    "workstream": WORKSTREAM_TRANSITIONS,
    "artifact": ARTIFACT_TRANSITIONS,
}

_ENUMS: dict[str, Any] = {
    "engagement": EngagementStatus,
    "workstream": WorkstreamStatus,
    "artifact": ArtifactStatus,
}


def _resolve(entity: str, value: Any):
    if entity not in _MATRICES:
        raise TransitionError(f"Unknown lifecycle entity '{entity}'")
    enum_cls = _ENUMS[entity]
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(value)
    except ValueError as exc:
        raise TransitionError(f"Unknown {entity} status '{value}'") from exc


def allowed_transitions(entity: str, current: Any) -> frozenset:
    """States reachable from ``current`` in one legal move."""
    return _MATRICES[entity][_resolve(entity, current)]


def transition_blockers(
    entity: str,
    current: Any,
    target: Any,
    context: TransitionContext | None = None,
) -> list[str]:
    """Return every reason this move is illegal. Empty means the move is legal."""
    resolved_current = _resolve(entity, current)
    resolved_target = _resolve(entity, target)
    context = context or TransitionContext()
    blockers: list[str] = []

    if resolved_target not in _MATRICES[entity][resolved_current]:
        blockers.append(
            f"{entity} cannot move from '{resolved_current.value}' to '{resolved_target.value}'"
        )
        # An illegal edge makes guard results meaningless; report the edge alone.
        return blockers

    if resolved_target in CLIENT_VISIBLE_TRANSITIONS[entity]:
        for guard in RELEASE_GUARDS:
            reason = guard(context)
            if reason:
                blockers.append(reason)

    if resolved_target in DEPENDENCY_GATED_TRANSITIONS[entity]:
        reason = _guard_dependencies_met(context)
        if reason:
            blockers.append(reason)

    return blockers


def can_transition(
    entity: str,
    current: Any,
    target: Any,
    context: TransitionContext | None = None,
) -> bool:
    return not transition_blockers(entity, current, target, context)


def assert_transition(
    entity: str,
    current: Any,
    target: Any,
    context: TransitionContext | None = None,
) -> None:
    """Fail closed on an illegal or unguarded move."""
    blockers = transition_blockers(entity, current, target, context)
    if blockers:
        raise TransitionError(
            f"Illegal {entity} transition "
            f"{_resolve(entity, current).value} -> {_resolve(entity, target).value}: "
            + "; ".join(blockers)
        )


def terminal_states(entity: str) -> frozenset:
    """States with no outbound edges."""
    return frozenset(state for state, targets in _MATRICES[entity].items() if not targets)


def validate_matrices() -> list[str]:
    """Structural self-check: every state declared, every target reachable.

    Returned by the graph-validation-run gate rather than raised, so the caller
    can report all defects at once.
    """
    problems: list[str] = []
    for entity, matrix in _MATRICES.items():
        enum_cls = _ENUMS[entity]
        declared = set(matrix)
        known = set(enum_cls)
        for missing in sorted(known - declared, key=lambda item: item.value):
            problems.append(f"{entity} status '{missing.value}' has no declared transitions")
        for extra in sorted(declared - known, key=lambda item: str(item)):
            problems.append(f"{entity} matrix declares unknown status '{extra}'")
        for state, targets in matrix.items():
            for target in targets:
                if target not in known:
                    problems.append(
                        f"{entity} transition {state.value} -> '{target}' targets an unknown status"
                    )
        for visible in CLIENT_VISIBLE_TRANSITIONS[entity]:
            if visible not in known:
                problems.append(f"{entity} client-visible state '{visible}' is not a known status")
    return problems


def lifecycle_snapshot() -> dict[str, Any]:
    """Serializable view used by the cross-language parity gate."""
    return {
        "lifecycle_version": LIFECYCLE_VERSION,
        "entities": {
            entity: {
                "transitions": {
                    state.value: sorted(target.value for target in targets)
                    for state, targets in sorted(matrix.items(), key=lambda item: item[0].value)
                },
                "client_visible": sorted(item.value for item in CLIENT_VISIBLE_TRANSITIONS[entity]),
                "dependency_gated": sorted(item.value for item in DEPENDENCY_GATED_TRANSITIONS[entity]),
            }
            for entity, matrix in _MATRICES.items()
        },
    }


def iter_entities() -> Iterable[str]:
    return tuple(_MATRICES)
