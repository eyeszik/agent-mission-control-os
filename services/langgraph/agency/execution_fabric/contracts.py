"""Execution-plane contracts: what may run, under whose authority, and how it is proven.

Everything here is a *read* of canonical owners, never a second owner:

* authority, approval and permission refs come only from a server-built
  :class:`ExecutionContext`; a client payload that carries any of them is
  rejected outright (:class:`ClientAuthorityInjection`);
* the permit persisted for every dispatch is the trust kernel's own
  ``DispatchPermit``, wrapped by :class:`FabricPermit` with the freshness facts
  the fabric needs (tenant, contract/context hashes, expiry);
* receipts are the trust kernel's ``ExecutionReceipt``/``ObservationReceipt``.

``LIVE`` execution does not exist: an ExecutionContext can only be LOCAL or
SANDBOX, and consequential side effects (``REVERSIBLE_WRITE`` and above) are
never dispatched by the fabric at all.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.execution.models import DispatchPermit

FABRIC_VERSION = "amc-execution-fabric/v1"
ELIGIBILITY_POLICY_VERSION = "amc-execution-fabric/eligibility-v1"
_HASH = r"^[a-f0-9]{64}$"


class ExecutionState(str, Enum):
    """Truthful per-cell outcome. Replaces the planner's blanket EXECUTOR_GAP."""

    EXECUTABLE = "EXECUTABLE"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED_AUTHORITY = "BLOCKED_AUTHORITY"
    BLOCKED_TOOL = "BLOCKED_TOOL"
    BLOCKED_PROVIDER = "BLOCKED_PROVIDER"
    BLOCKED_DEPENDENCY = "BLOCKED_DEPENDENCY"
    BLOCKED_CONTRACT = "BLOCKED_CONTRACT"
    BLOCKED_POLICY = "BLOCKED_POLICY"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    PROVIDER_GAP = "PROVIDER_GAP"


# When a cell has several reasons, the reported state is the most fundamental
# one: an authority problem outranks a missing tool, which outranks a gap.
STATE_PRECEDENCE: tuple[ExecutionState, ...] = (
    ExecutionState.BLOCKED_AUTHORITY,
    ExecutionState.BLOCKED_POLICY,
    ExecutionState.BLOCKED_CONTRACT,
    ExecutionState.NEEDS_HUMAN,
    ExecutionState.BLOCKED_DEPENDENCY,
    ExecutionState.BLOCKED_TOOL,
    ExecutionState.BLOCKED_PROVIDER,
    ExecutionState.PROVIDER_GAP,
)

# Planner/work-order blocker prefixes -> state. Unknown blockers fail closed to
# BLOCKED_POLICY rather than being ignored.
_BLOCKER_STATES: tuple[tuple[str, ExecutionState], ...] = (
    ("WAIT_HUMAN_DECISION", ExecutionState.NEEDS_HUMAN),
    ("MISSING_EXACT_APPROVAL_REF", ExecutionState.NEEDS_HUMAN),
    ("MISSING_HIGH_RISK_APPROVAL_REF", ExecutionState.NEEDS_HUMAN),
    ("APPROVAL_", ExecutionState.NEEDS_HUMAN),
    ("UPSTREAM_", ExecutionState.BLOCKED_DEPENDENCY),
    ("DEPENDENCY_", ExecutionState.BLOCKED_DEPENDENCY),
    ("STALE_", ExecutionState.BLOCKED_DEPENDENCY),
    ("INVALIDATED_CONTEXT", ExecutionState.BLOCKED_DEPENDENCY),
    ("MISSING_AUTHORITY_REF", ExecutionState.BLOCKED_AUTHORITY),
    ("MISSING_PERMISSION_REF", ExecutionState.BLOCKED_AUTHORITY),
    ("AUTHORITY_", ExecutionState.BLOCKED_AUTHORITY),
    ("CAPABILITY_GAP", ExecutionState.BLOCKED_AUTHORITY),
    ("ROLE_", ExecutionState.BLOCKED_AUTHORITY),
    ("PROVIDER_UNAVAILABLE", ExecutionState.BLOCKED_PROVIDER),
    ("PROVIDER_GAP", ExecutionState.PROVIDER_GAP),
    ("GAP_NO_", ExecutionState.PROVIDER_GAP),
    ("TOOL_UNAVAILABLE", ExecutionState.BLOCKED_TOOL),
    ("NO_SKILL_FOR_CONTRACT", ExecutionState.BLOCKED_TOOL),
    ("SANDBOX_UNAVAILABLE", ExecutionState.BLOCKED_TOOL),
    ("VOLATILE_", ExecutionState.BLOCKED_CONTRACT),
    ("NODE_INVARIANT_UNRESOLVED", ExecutionState.BLOCKED_CONTRACT),
    ("EVIDENCE_", ExecutionState.BLOCKED_CONTRACT),
    ("NO_VALID_PCWO", ExecutionState.BLOCKED_CONTRACT),
    ("CONTRACT_", ExecutionState.BLOCKED_CONTRACT),
)


def state_for_blocker(blocker: str) -> ExecutionState:
    for prefix, state in _BLOCKER_STATES:
        if blocker.startswith(prefix):
            return state
    return ExecutionState.BLOCKED_POLICY


def dominant_state(reasons: tuple[str, ...] | list[str]) -> ExecutionState:
    states = {state_for_blocker(r) for r in reasons}
    for state in STATE_PRECEDENCE:
        if state in states:
            return state
    return ExecutionState.BLOCKED_POLICY


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExecutionModeError(ValueError):
    """Raised for a mode the fabric does not implement (anything but LOCAL/SANDBOX)."""


class ClientAuthorityInjection(ValueError):
    """A client tried to supply authority, approval, tenant or mode facts."""


class FabricBudget(_Strict):
    max_invocations: int = Field(default=64, ge=1, le=1000)
    max_output_bytes: int = Field(default=5_000_000, ge=1, le=100_000_000)
    max_attempts_per_cell: int = Field(default=3, ge=1, le=3)
    max_tool_calls_per_node: int = Field(default=12, ge=1, le=12)


# Keys a client payload may never carry: these facts are server-derived.
FORBIDDEN_CLIENT_KEYS = frozenset({
    "authority_refs", "approval_refs", "permission_refs", "grants", "approvals", "provider_status",
    "mode", "tenant_id", "project_id", "actor", "role_id", "side_effect_class", "budget",
    "spend_authorized", "approval_exists", "approval_decision", "release", "publish",
})
ALLOWED_CLIENT_KEYS = frozenset({"objective", "notes", "inputs"})


class ExecutionContext(_Strict):
    """Server-trusted execution facts. Build with :meth:`from_server`."""

    tenant_id: str = Field(min_length=1, max_length=200)
    project_id: str = Field(min_length=1, max_length=200)
    actor: str = Field(min_length=1, max_length=200)
    mode: Literal["LOCAL", "SANDBOX"]
    export_root: Path
    authority_refs: tuple[str, ...] = ()
    approval_refs: tuple[str, ...] = ()
    budget: FabricBudget = FabricBudget()
    permit_ttl_seconds: int = Field(default=900, ge=1, le=86_400)
    max_clock_skew_seconds: int = Field(default=30, ge=0, le=300)
    # An idempotency reservation older than this with no commit is treated as
    # a crashed attempt and reconciled before any retry.
    lease_seconds: int = Field(default=600, ge=0, le=86_400)
    client_inputs: dict[str, Any] = Field(default_factory=dict)

    @field_validator("mode", mode="before")
    @classmethod
    def _no_live(cls, value: Any) -> Any:
        if value not in {"LOCAL", "SANDBOX"}:
            raise ExecutionModeError(f"execution mode {value!r} is not implemented; external execution stays LIVE_GATED")
        return value

    @classmethod
    def from_server(
        cls,
        *,
        tenant_id: str,
        project_id: str,
        actor: str,
        mode: str,
        export_root: Path,
        authority_refs: tuple[str, ...] = (),
        approval_refs: tuple[str, ...] = (),
        budget: FabricBudget | None = None,
        client_payload: Mapping[str, Any] | None = None,
        **limits: int,
    ) -> "ExecutionContext":
        if mode not in {"LOCAL", "SANDBOX"}:
            raise ExecutionModeError(f"execution mode {mode!r} is not implemented; external execution stays LIVE_GATED")
        return cls(
            tenant_id=tenant_id,
            project_id=project_id,
            actor=actor,
            mode=mode,
            export_root=Path(export_root),
            authority_refs=tuple(sorted(set(authority_refs))),
            approval_refs=tuple(sorted(set(approval_refs))),
            budget=budget or FabricBudget(),
            client_inputs=sanitize_client_payload(client_payload or {}),
            **limits,
        )


def sanitize_client_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Accept only descriptive client keys; reject any authority-shaped key."""
    injected = sorted(set(payload) & FORBIDDEN_CLIENT_KEYS)
    if injected:
        raise ClientAuthorityInjection(f"client payload may not carry server-derived facts: {injected}")
    unknown = sorted(set(payload) - ALLOWED_CLIENT_KEYS)
    if unknown:
        raise ClientAuthorityInjection(f"client payload has unknown keys: {unknown}")
    return {k: payload[k] for k in sorted(payload)}


class ExecutionRequest(_Strict):
    """One dispatch, bound to exact contract, context and dependency versions."""

    tenant_id: str
    project_id: str
    mission_id: str
    cell_id: str
    node_id: str
    work_order_id: str
    role_id: str
    skill_id: str
    artifact_type: str
    contract_hash: str = Field(pattern=_HASH)
    context_hash: str = Field(pattern=_HASH)
    dependency_hashes: tuple[tuple[str, str], ...] = ()
    input_hash: str = Field(pattern=_HASH)
    idempotency_key: str = Field(pattern=_HASH)

    @property
    def request_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


def execution_key(*, tenant_id: str, project_id: str, mission_id: str, work_order_id: str, contract_hash: str, input_hash: str) -> str:
    """Idempotency identity: hash(tenant, project, mission, work_order, contract, input).

    The tenant is part of the hash *and* of the reservation scope, so two
    tenants can never collide on, or replay, each other's execution."""
    return canonical_hash({
        "tenant": tenant_id,
        "project": project_id,
        "mission": mission_id,
        "work_order": work_order_id,
        "contract_hash": contract_hash,
        "input_hash": input_hash,
    })


def reservation_scope(tenant_id: str) -> str:
    return f"execution-fabric:{tenant_id}"


class FabricPermit(_Strict):
    """The trust kernel's DispatchPermit plus the facts that make it checkable."""

    permit: DispatchPermit
    tenant_id: str
    contract_hash: str = Field(pattern=_HASH)
    context_hash: str = Field(pattern=_HASH)
    idempotency_key: str = Field(pattern=_HASH)
    expires_at: datetime


class PermitInvalid(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def issue_permit(
    request: ExecutionRequest,
    *,
    context: ExecutionContext,
    snapshot_hash: str,
    causal_epoch: int,
    dependency_version_refs: tuple[str, ...],
    authority_refs: tuple[str, ...],
    approval_refs: tuple[str, ...],
    now: datetime,
) -> FabricPermit:
    permit = DispatchPermit(
        permit_id=f"permit-{request.idempotency_key[:32]}",
        work_order_id=request.work_order_id,
        project_snapshot_hash=snapshot_hash,
        causal_epoch=causal_epoch,
        dependency_version_refs=dependency_version_refs,
        authority_refs=authority_refs,
        approval_refs=approval_refs,
        tool_contract_refs=(f"skill:{request.skill_id}",),
        eligibility_policy_version=ELIGIBILITY_POLICY_VERSION,
        issued_at=now,
    )
    return FabricPermit(
        permit=permit,
        tenant_id=request.tenant_id,
        contract_hash=request.contract_hash,
        context_hash=request.context_hash,
        idempotency_key=request.idempotency_key,
        expires_at=now + timedelta(seconds=context.permit_ttl_seconds),
    )


def verify_permit(fp: FabricPermit, request: ExecutionRequest, *, now: datetime, max_skew_seconds: int) -> None:
    """Fail closed unless the permit is for exactly this request and is current.

    A permit issued "in the future" beyond the skew allowance (EC11 clock
    desync) is as invalid as an expired one."""
    skew = timedelta(seconds=max_skew_seconds)
    if fp.tenant_id != request.tenant_id:
        raise PermitInvalid("PERMIT_TENANT_MISMATCH")
    if fp.permit.work_order_id != request.work_order_id:
        raise PermitInvalid("PERMIT_WORK_ORDER_MISMATCH")
    if (fp.contract_hash, fp.context_hash, fp.idempotency_key) != (request.contract_hash, request.context_hash, request.idempotency_key):
        raise PermitInvalid("PERMIT_SUBJECT_MISMATCH")
    if fp.permit.issued_at > now + skew:
        raise PermitInvalid("PERMIT_ISSUED_IN_FUTURE")
    if now > fp.expires_at + skew:
        raise PermitInvalid("PERMIT_EXPIRED")


Clock = Callable[[], datetime]


def system_clock() -> datetime:
    return datetime.now(timezone.utc)


__all__ = [
    "ALLOWED_CLIENT_KEYS",
    "ClientAuthorityInjection",
    "Clock",
    "ELIGIBILITY_POLICY_VERSION",
    "ExecutionContext",
    "ExecutionModeError",
    "ExecutionRequest",
    "ExecutionState",
    "FABRIC_VERSION",
    "FORBIDDEN_CLIENT_KEYS",
    "FabricBudget",
    "FabricPermit",
    "PermitInvalid",
    "STATE_PRECEDENCE",
    "dominant_state",
    "execution_key",
    "issue_permit",
    "reservation_scope",
    "sanitize_client_payload",
    "state_for_blocker",
    "system_clock",
    "verify_permit",
]
