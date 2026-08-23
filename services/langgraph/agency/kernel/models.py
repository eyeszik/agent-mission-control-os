from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EngagementStatus(str, Enum):
    intake = "intake"
    discovery = "discovery"
    research = "research"
    strategy = "strategy"
    brand = "brand"
    product = "product"
    build = "build"
    launch_ready = "launch_ready"
    launched = "launched"
    growth = "growth"
    optimizing = "optimizing"
    complete = "complete"
    blocked = "blocked"
    degraded = "degraded"
    review_required = "review_required"
    paused = "paused"
    failed = "failed"
    cancelled = "cancelled"


class WorkstreamStatus(str, Enum):
    blocked = "blocked"
    ready = "ready"
    executing = "executing"
    validating = "validating"
    review = "review"
    approved = "approved"
    released = "released"
    degraded = "degraded"
    failed = "failed"
    rejected = "rejected"
    cancelled = "cancelled"


class ArtifactStatus(str, Enum):
    draft = "draft"
    validating = "validating"
    approved = "approved"
    release_eligible = "release_eligible"
    released = "released"
    review_required = "review_required"
    invalidated = "invalidated"
    archived = "archived"


class DecisionStatus(str, Enum):
    proposed = "proposed"
    accepted = "accepted"
    superseded = "superseded"
    rejected = "rejected"


class EpistemicStatus(str, Enum):
    verified = "verified"
    inferred = "inferred"
    assumption = "assumption"
    hypothesis = "hypothesis"
    stale = "stale"
    conflict = "conflict"
    unverified = "unverified"
    blocked = "blocked"


class DependencyStrength(str, Enum):
    hard = "hard"
    soft = "soft"


class ConfidenceVector(BaseModel):
    evidence: float = Field(ge=0.0, le=1.0)
    freshness: float = Field(ge=0.0, le=1.0)
    contract: float = Field(ge=0.0, le=1.0)
    execution: float = Field(ge=0.0, le=1.0)
    safety: float = Field(ge=0.0, le=1.0)
    strategic_coherence: float = Field(ge=0.0, le=1.0)
    aggregate: float = Field(ge=0.0, le=1.0)


class Engagement(BaseModel):
    engagement_id: str
    tenant_id: str
    project_id: str
    objective: str
    desired_outcome: str
    status: EngagementStatus = EngagementStatus.intake
    constraints: dict[str, Any] = Field(default_factory=dict)
    permissions: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class Workstream(BaseModel):
    workstream_id: str
    engagement_id: str
    tenant_id: str
    project_id: str
    department: str
    objective: str
    status: WorkstreamStatus = WorkstreamStatus.ready
    dependencies: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class Evidence(BaseModel):
    evidence_id: str
    engagement_id: str
    tenant_id: str
    project_id: str
    evidence_type: str
    source_ref: str | None = None
    claim: str
    epistemic_status: EpistemicStatus
    confidence: float = Field(ge=0.0, le=1.0)
    collected_at: datetime
    freshness_seconds: int | None = Field(default=None, ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Decision(BaseModel):
    decision_id: str
    engagement_id: str
    tenant_id: str
    project_id: str
    question: str
    alternatives: list[Any] = Field(default_factory=list)
    selected_option: Any = None
    evidence_ids: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    affected_artifact_ids: list[str] = Field(default_factory=list)
    confidence: ConfidenceVector
    status: DecisionStatus = DecisionStatus.proposed
    approver: str | None = None
    created_at: datetime
    updated_at: datetime


class Artifact(BaseModel):
    artifact_id: str
    engagement_id: str
    tenant_id: str
    project_id: str
    workstream_id: str | None = None
    artifact_type: str
    subtype: str | None = None
    owner_department: str
    version: int = Field(default=1, ge=1)
    status: ArtifactStatus = ArtifactStatus.draft
    content_location: str | None = None
    content_hash: str | None = None
    semantic_fingerprint: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    validation: dict[str, Any] = Field(default_factory=dict)
    approval: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
