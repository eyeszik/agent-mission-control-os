from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import Field

from ..execution.models import StrictModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class BindingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class TenantProjectBinding(StrictModel):
    tenant_id: str
    project_id: str
    status: BindingStatus = BindingStatus.ACTIVE
    binding_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    created_at: datetime = Field(default_factory=utc_now)
    revoked_at: datetime | None = None


class PolicyEffect(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"


class PolicyDecisionRecord(StrictModel):
    decision_id: str
    tenant_id: str
    project_id: str
    subject_ref: str
    action: str
    target: str
    policy_version: str
    input_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    effect: PolicyEffect
    required_authority_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    decision_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    decided_at: datetime = Field(default_factory=utc_now)


class IdempotencyStatus(str, Enum):
    CLAIMED = "CLAIMED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    AMBIGUOUS = "AMBIGUOUS"


class IdempotencyRecord(StrictModel):
    idempotency_key: str
    tenant_id: str
    project_id: str
    operation_id: str
    request_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: IdempotencyStatus = IdempotencyStatus.CLAIMED
    result_ref: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class OutboxStatus(str, Enum):
    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"


class OutboxMessage(StrictModel):
    message_id: str
    tenant_id: str
    project_id: str
    topic: str
    payload_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    payload_ref: str
    idempotency_key: str
    status: OutboxStatus = OutboxStatus.PENDING
    attempts: int = Field(default=0, ge=0, le=3)
    claimed_by: str | None = None
    next_attempt_at: datetime | None = None
    delivered_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class AuditCheckpoint(StrictModel):
    seq: int = Field(ge=1)
    tenant_id: str
    project_id: str
    event_type: str
    object_ref: str
    payload_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    previous_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    checkpoint_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    created_at: datetime = Field(default_factory=utc_now)


class RecoveryStatus(str, Enum):
    OPEN = "OPEN"
    RECONCILED = "RECONCILED"
    COMPENSATED = "COMPENSATED"
    ESCALATED = "ESCALATED"


class RecoveryCase(StrictModel):
    recovery_id: str
    tenant_id: str
    project_id: str
    operation_id: str
    reason: Literal[
        "EXECUTION_WITHOUT_OBSERVATION",
        "OBSERVATION_MISMATCH",
        "AMBIGUOUS_EXTERNAL_RESULT",
        "IDEMPOTENCY_CONFLICT",
    ]
    execution_ref: str | None = None
    observation_ref: str | None = None
    idempotency_key: str | None = None
    status: RecoveryStatus = RecoveryStatus.OPEN
    evidence_refs: tuple[str, ...] = ()
    created_at: datetime = Field(default_factory=utc_now)
    resolved_at: datetime | None = None


class ReliabilitySnapshot(StrictModel):
    tenant_id: str
    project_id: str
    policy_decisions: int = 0
    pending_outbox: int = 0
    open_recovery_cases: int = 0
    audit_head_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    idempotency_claims: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)
