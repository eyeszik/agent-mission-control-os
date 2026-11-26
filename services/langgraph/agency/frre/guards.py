"""FRRE runtime guards (W1, pure): may this transition happen, given these facts?

``decide`` is the single decision point a future tick (W2+) must call before persisting a
``Transition``. It never performs an effect; it returns APPLY, NOOP or REFUSE with reason codes.

Facts are fail closed by absence, matching ``agency/kernel/lifecycle.TransitionContext``: an
unknown halt state, an unchecked permit, a missing validation verdict or an unobserved release
outcome is "unproven", and the move is refused. Untrusted incident content (severity, symptom
text, confidence) is not an input here, so it cannot widen authority (noninterference).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

from .contracts import Permit, PermitStage, Transition
from .fsm import BUDGETED_EDGES, PERMIT_GATES, PERMIT_STAGE_FOR, IncidentState
from .policy import DELIVERY_ENABLED

S = IncidentState


@dataclass(frozen=True)
class PermitContext:
    """The live facts a permit is checked against at the moment of use."""

    stage: PermitStage
    now: datetime
    tenant_id: str
    project_id: str
    baseline_sha: str
    policy_digest: str
    plan_digest: Optional[str] = None
    candidate_digest: Optional[str] = None
    revoked: frozenset[str] = frozenset()
    used_permit_ids: frozenset[str] = frozenset()


@dataclass(frozen=True)
class IncidentFacts:
    """What the store says about the incident now. ``None`` means unknown, which refuses."""

    tenant_id: str
    state: IncidentState
    version: int
    last_fencing_token: int
    attempts_left: int
    recoveries_left: int
    applied_idempotency_keys: frozenset[str] = frozenset()
    halted: Optional[bool] = None
    permit_refusals: Optional[tuple[str, ...]] = None
    validation_verdict: Optional[str] = None
    post_release_healthy: Optional[bool] = None


@dataclass(frozen=True)
class Decision:
    kind: Literal["APPLY", "NOOP", "REFUSE"]
    codes: tuple[str, ...] = ()
    attempts_left: int = 0
    recoveries_left: int = 0
    new_version: Optional[int] = None
    consumed: Optional[str] = field(default=None)


def _identity_refusals(permit: Permit, ctx: PermitContext) -> list[str]:
    codes = []
    if permit.stage is not ctx.stage:
        codes.append("PERMIT_STAGE_MISMATCH")
    if permit.tenant_id != ctx.tenant_id:
        codes.append("TENANT_MISMATCH")
    if permit.project_id != ctx.project_id:
        codes.append("PROJECT_MISMATCH")
    if permit.id in ctx.used_permit_ids:
        codes.append("PERMIT_REPLAYED")
    if permit.id in ctx.revoked or permit.revocation_ref is not None:
        codes.append("PERMIT_REVOKED")
    return codes


def _freshness_refusals(permit: Permit, ctx: PermitContext) -> list[str]:
    codes = []
    if ctx.now < permit.issued_at:
        codes.append("PERMIT_NOT_YET_VALID")
    if ctx.now >= permit.expires_at:
        codes.append("PERMIT_EXPIRED")
    if permit.baseline_sha != ctx.baseline_sha:
        codes.append("BASELINE_DRIFT")
    if permit.policy_digest != ctx.policy_digest:
        codes.append("POLICY_DRIFT")
    if permit.plan_digest is not None and permit.plan_digest != ctx.plan_digest:
        codes.append("PLAN_MISMATCH")
    if permit.candidate_digest is not None and permit.candidate_digest != ctx.candidate_digest:
        codes.append("CANDIDATE_MISMATCH")
    return codes


def permit_refusals(permit: Permit, ctx: PermitContext) -> tuple[str, ...]:
    """Every reason ``permit`` may not be used now. Empty means it is valid for ``ctx``."""
    return tuple(_identity_refusals(permit, ctx) + _freshness_refusals(permit, ctx))


def _state_refusals(t: Transition, f: IncidentFacts) -> list[str]:
    codes = []
    if t.tenant_id != f.tenant_id:
        codes.append("TENANT_MISMATCH")
    if f.halted is None:
        codes.append("HALT_STATE_UNKNOWN")
    elif f.halted:
        codes.append("HALTED")
    if t.from_state is not f.state:
        codes.append("STALE_STATE")
    if t.expected_version != f.version:
        codes.append("CAS_CONFLICT")
    if t.fencing_token < f.last_fencing_token:
        codes.append("FENCED_STALE_LEASE")
    return codes


def _permit_gate_refusals(t: Transition, f: IncidentFacts) -> list[str]:
    if t.to_state not in PERMIT_GATES:
        return []
    if f.permit_refusals is None:
        return [f"PERMIT_UNCHECKED:{PERMIT_STAGE_FOR[t.to_state]}"]
    return list(f.permit_refusals)


def _evidence_refusals(t: Transition, f: IncidentFacts) -> list[str]:
    codes = []
    if t.to_state is S.VALIDATED and f.validation_verdict != "PASS":
        codes.append("VALIDATION_NOT_PASSED")
    if t.to_state is S.RESOLVED and f.post_release_healthy is not True:
        codes.append("RECOVERY_NOT_OBSERVED")
    if t.to_state is S.RELEASED and not DELIVERY_ENABLED:
        codes.append("DELIVERY_DISABLED")
    return codes


def _budget(t: Transition, f: IncidentFacts) -> tuple[list[str], int, int, Optional[str]]:
    counter = BUDGETED_EDGES.get((t.from_state, t.to_state))
    attempts, recoveries = f.attempts_left, f.recoveries_left
    if counter == "attempts":
        if attempts <= 0:
            return ["BUDGET_EXHAUSTED:attempts"], attempts, recoveries, None
        attempts -= 1
    elif counter == "recoveries":
        if recoveries <= 0:
            return ["BUDGET_EXHAUSTED:recoveries"], attempts, recoveries, None
        recoveries -= 1
    return [], attempts, recoveries, counter


def decide(t: Transition, f: IncidentFacts) -> Decision:
    """APPLY, NOOP (already applied: idempotent) or REFUSE, with every reason found."""
    if t.idempotency_key in f.applied_idempotency_keys and t.tenant_id == f.tenant_id:
        return Decision("NOOP", ("IDEMPOTENT_REPLAY",), f.attempts_left, f.recoveries_left)
    codes = _state_refusals(t, f) + _permit_gate_refusals(t, f) + _evidence_refusals(t, f)
    budget_codes, attempts, recoveries, consumed = _budget(t, f)
    codes += budget_codes
    if codes:
        return Decision("REFUSE", tuple(codes), f.attempts_left, f.recoveries_left)
    return Decision("APPLY", (), attempts, recoveries, t.new_version, consumed)


__all__ = ["Decision", "IncidentFacts", "PermitContext", "decide", "permit_refusals"]
