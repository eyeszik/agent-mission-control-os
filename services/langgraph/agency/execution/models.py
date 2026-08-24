from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ArtifactLifecycle(str, Enum):
    DRAFT = "DRAFT"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    VALIDATED = "VALIDATED"
    APPROVED = "APPROVED"
    RELEASED = "RELEASED"
    INVALIDATED = "INVALIDATED"


class DependencyImpact(str, Enum):
    UNAFFECTED = "UNAFFECTED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    STALE = "STALE"
    REBUILD_REQUIRED = "REBUILD_REQUIRED"


class DependencyPolicy(str, Enum):
    HARD = "HARD"
    SOFT = "SOFT"


class SemanticChange(str, Enum):
    NONE = "NONE"
    COMPATIBLE = "COMPATIBLE"
    BREAKING = "BREAKING"
    UNKNOWN = "UNKNOWN"


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    STALE = "STALE"


class WorkOrderState(str, Enum):
    PLANNED = "PLANNED"
    READY = "READY"
    RUNNING = "RUNNING"
    BLOCKED = "BLOCKED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    ESCALATED = "ESCALATED"
    INVESTIGATION_REQUIRED = "INVESTIGATION_REQUIRED"


class CriterionStatus(str, Enum):
    SATISFIED = "SATISFIED"
    UNSATISFIED = "UNSATISFIED"
    STALE = "STALE"
    BLOCKED = "BLOCKED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ArtifactIdentity(StrictModel):
    artifact_id: str
    project_id: str
    engagement_id: str
    artifact_type: str
    owner_department: str


class ArtifactVersion(StrictModel):
    artifact_version_id: str
    artifact_id: str
    version: int = Field(ge=1)
    parent_version_ref: str | None = None
    branch: str = "main"
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    semantic_fingerprint: str | None = None
    generation_mode: str = "UNKNOWN"
    dependency_version_refs: tuple[str, ...] = ()
    validation_refs: tuple[str, ...] = ()
    work_order_ref: str
    lifecycle: ArtifactLifecycle = ArtifactLifecycle.DRAFT
    created_at: datetime = Field(default_factory=utc_now)


class ArtifactDependency(StrictModel):
    upstream_artifact_id: str
    downstream_artifact_id: str
    policy: DependencyPolicy


class VersionDependencyBinding(StrictModel):
    output_artifact_version_id: str
    input_artifact_version_ids: tuple[str, ...]


class ApprovalBinding(StrictModel):
    approval_id: str
    subject_type: Literal["ARTIFACT_VERSION", "RELEASE_SUBJECT"]
    subject_ref: str
    subject_version_ref: str
    subject_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    authority_ref: str
    policy_version: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    reviewer_ref: str | None = None
    decision: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    decided_at: datetime | None = None
    staled_at: datetime | None = None
    stale_reason: str | None = None


class ExecutionReceipt(StrictModel):
    operation_id: str
    work_order_id: str
    actor_role_id: str
    tool: str
    tool_contract_ref: str
    args_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    target: str
    idempotency_key: str
    attempt: int = Field(ge=1, le=3)
    started_at: datetime
    ended_at: datetime
    returned_state: str
    result_ref: str | None = None


class ObservationReceipt(StrictModel):
    operation_id: str
    target: str
    expected_postcondition: Any
    observed_postcondition: Any
    observation_method: str
    evidence_refs: tuple[str, ...] = ()
    observed_at: datetime = Field(default_factory=utc_now)
    matches: bool


class FailureFingerprint(StrictModel):
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    failure_class: str
    causal_node: str
    work_order_input_hash: str
    dependency_snapshot_hash: str
    tool_contract_hash: str
    environment_signature: str
    error_class: str
    error_code: str | None = None
    observed_postcondition: Any = None


class ProjectExecutionProjection(StrictModel):
    project_id: str
    engagement_id: str
    mission_id: str
    current_phase: str
    causal_epoch: int = Field(ge=0)
    active_work_order_ids: tuple[str, ...] = ()
    ready_work_order_ids: tuple[str, ...] = ()
    blocked_work_order_ids: tuple[str, ...] = ()
    awaiting_approval_ids: tuple[str, ...] = ()
    artifact_head_refs: tuple[str, ...] = ()
    stale_artifact_ids: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    proof_coverage: float = Field(ge=0.0, le=1.0)
    updated_at: datetime = Field(default_factory=utc_now)
    snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class DispatchPermit(StrictModel):
    permit_id: str
    work_order_id: str
    project_snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    causal_epoch: int = Field(ge=0)
    dependency_version_refs: tuple[str, ...] = ()
    authority_refs: tuple[str, ...] = ()
    approval_refs: tuple[str, ...] = ()
    tool_contract_refs: tuple[str, ...] = ()
    eligibility_policy_version: str
    issued_at: datetime = Field(default_factory=utc_now)


class CompletionCriterion(StrictModel):
    criterion_ref: str
    mandatory: bool = True
    required_artifact_version_refs: tuple[str, ...] = ()
    required_test_refs: tuple[str, ...] = ()
    required_execution_receipt_refs: tuple[str, ...] = ()
    required_observation_refs: tuple[str, ...] = ()
    required_evidence_refs: tuple[str, ...] = ()
    required_approval_refs: tuple[str, ...] = ()
    required_metric_refs: tuple[str, ...] = ()


class CompletionCriterionResult(StrictModel):
    criterion_ref: str
    status: CriterionStatus
    missing_refs: tuple[str, ...] = ()
    stale_refs: tuple[str, ...] = ()


class CompletionEvaluation(StrictModel):
    terminal_candidate: Literal["COMPLETE", "BLOCKED"]
    criteria: tuple[CompletionCriterionResult, ...]
    proof_coverage: float = Field(ge=0.0, le=1.0)
    evidence_score: float = Field(ge=0.0, le=1.0)
    quality_score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
