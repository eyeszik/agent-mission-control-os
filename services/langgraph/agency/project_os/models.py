"""Typed project OS contracts.

Every model here is the backend twin of a Zod schema in
``packages/shared/src/schemas/projectOs.ts``. Parity is proven the same way
the UI/UX IR proves it: ``tests/test_project_os_contracts.py`` regenerates
``packages/shared/tests/fixtures/project-os.json`` from these models and fails
if the checked-in fixture drifts, and the shared vitest suite parses that
fixture with the Zod schemas in strict mode.

Timestamps are ISO-8601 strings, not ``datetime``: SQLite stores text and
PostgreSQL ``timestamptz`` is normalized to ISO text on read, so the contract
is the string both backends actually return.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .vocabulary import (
    ActivityType,
    ContentKind,
    ContentState,
    KnowledgeStatus,
    MemoryAuthority,
    MemoryScope,
    MemoryStatus,
    ProjectLifecycle,
    ProviderMode,
    PublicationState,
    RightsClass,
    ScheduledJobKind,
    ScheduledJobStatus,
    StorageBackend,
    StorageObjectStatus,
)

HASH = r"^[a-f0-9]{64}$"
SLUG = r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$"


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --------------------------------------------------------------------------
# W0/W1 project workspace
# --------------------------------------------------------------------------


class ProjectWorkspaceV2(Contract):
    project_id: str
    tenant_id: str
    slug: str = Field(pattern=SLUG)
    display_name: str
    description: str = ""
    lifecycle_state: ProjectLifecycle
    brand_id: Optional[str] = None
    brand_name: Optional[str] = None
    workspace_schema_version: Literal["amc-workspace/v2"] = "amc-workspace/v2"
    manifest_hash: str = Field(pattern=HASH)
    created_by: str
    created_at: str
    updated_at: str


class ProjectManifest(Contract):
    schema_version: Literal["amc-workspace/v2"] = "amc-workspace/v2"
    project_id: str
    tenant_id: str
    slug: str
    display_name: str
    brand_id: Optional[str] = None
    lifecycle_state: ProjectLifecycle
    folders: tuple[str, ...]
    system_folders: tuple[str, ...]
    memory_namespace: str
    artifact_index_ref: str
    source_registry_ref: str
    rights_registry_ref: str
    authority_note: str = (
        "The relational store is canonical. This manifest and the workspace mirror "
        "are materialized views and are never transactional authority."
    )


class ArtifactHead(Contract):
    artifact_id: str
    artifact_type: str
    version: int = Field(ge=1)
    version_ref: str
    status: str
    content_hash: Optional[str] = None


class ProjectSnapshot(Contract):
    project_id: str
    tenant_id: str
    lifecycle_state: ProjectLifecycle
    artifact_heads: tuple[ArtifactHead, ...]
    run_ids: tuple[str, ...]
    open_approval_count: int = Field(ge=0)
    stale_artifact_count: int = Field(ge=0)
    snapshot_hash: str = Field(pattern=HASH)


class ProjectEvent(Contract):
    event_id: str
    tenant_id: str
    project_id: str
    sequence: int = Field(ge=1)
    event_type: ActivityType
    actor: str
    thread_id: Optional[str] = None
    subject_ref: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str


# --------------------------------------------------------------------------
# Storage authority
# --------------------------------------------------------------------------


class StorageObject(Contract):
    object_id: str
    tenant_id: str
    project_id: str
    backend: StorageBackend
    storage_uri: str
    content_hash: str = Field(pattern=HASH)
    byte_size: int = Field(ge=0)
    mime_type: str
    status: StorageObjectStatus
    created_at: str
    verified_at: Optional[str] = None


# --------------------------------------------------------------------------
# Artifact graph v2 (metadata over the canonical N4 registry)
# --------------------------------------------------------------------------


class ArtifactMetadataV2(Contract):
    artifact_id: str
    project_id: str
    campaign_id: Optional[str] = None
    artifact_key: str
    artifact_type: str
    owner_department: str
    subtype: Optional[str] = None
    media_type: Optional[Literal["text", "image", "video", "audio", "data", "bundle"]] = None
    mime_type: Optional[str] = None
    language: Optional[str] = None
    locale: Optional[str] = None
    channel: Optional[str] = None
    dimensions: Optional[str] = None
    duration_seconds: Optional[float] = Field(default=None, ge=0)
    version: int = Field(ge=1)
    version_ref: str
    parent_artifact_id: Optional[str] = None
    master_artifact_id: Optional[str] = None
    variant_of: Optional[str] = None
    source_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    prompt_refs: tuple[str, ...] = ()
    dependency_refs: tuple[str, ...] = ()
    storage_uri: Optional[str] = None
    preview_uri: Optional[str] = None
    thumbnail_uri: Optional[str] = None
    content_hash: Optional[str] = None
    status: str
    approval_state: Literal["none", "pending", "approved", "rejected", "stale"] = "none"
    rights_ref: Optional[str] = None
    provenance_ref: Optional[str] = None


class ArtifactVersionRecord(Contract):
    artifact_id: str
    version: int = Field(ge=1)
    version_ref: str
    content_hash: Optional[str] = None
    content_location: Optional[str] = None
    semantic_fingerprint: Optional[str] = None
    change_kind: Literal["create", "revise", "restore", "replace_master"]
    restored_from_version: Optional[int] = None
    created_by: str
    created_at: str


class ArtifactDiff(Contract):
    artifact_id: str
    from_version_ref: str
    to_version_ref: str
    content_changed: bool
    location_changed: bool
    fingerprint_changed: bool
    metadata_changes: dict[str, Any]
    text_diff: tuple[str, ...] = ()
    visual_diff: Optional[dict[str, Any]] = None


class AssetRights(Contract):
    rights_id: str
    tenant_id: str
    project_id: str
    artifact_id: str
    license: str
    territory: str = "UNSPECIFIED"
    usage_scope: str = "UNSPECIFIED"
    attribution: Optional[str] = None
    source_ref: Optional[str] = None
    expires_at: Optional[str] = None
    status: Literal["active", "expired", "revoked"]
    created_at: str


# --------------------------------------------------------------------------
# Conversations (project activity stream)
# --------------------------------------------------------------------------


class ConversationThread(Contract):
    thread_id: str
    tenant_id: str
    project_id: str
    campaign_id: Optional[str] = None
    title: str
    status: Literal["open", "archived"]
    created_by: str
    created_at: str
    updated_at: str


class MessageArtifactRef(Contract):
    artifact_id: str
    version_ref: str
    relation: Literal["created", "updated", "referenced", "variant", "preview"]


class ConversationMessage(Contract):
    message_id: str
    thread_id: str
    tenant_id: str
    project_id: str
    author: str
    role: Literal["user", "agent", "system"]
    activity_type: ActivityType
    body: str
    artifact_refs: tuple[MessageArtifactRef, ...] = ()
    created_at: str


class ArtifactComment(Contract):
    comment_id: str
    tenant_id: str
    project_id: str
    artifact_id: str
    version_ref: str
    author: str
    body: str
    created_at: str


class ArtifactEditRequest(Contract):
    request_id: str
    tenant_id: str
    project_id: str
    artifact_id: str
    base_version_ref: str
    instruction: str
    status: Literal["open", "applied", "rejected", "stale"]
    requested_by: str
    created_at: str
    resolved_at: Optional[str] = None


# --------------------------------------------------------------------------
# Content operations
# --------------------------------------------------------------------------


class Claim(Contract):
    claim_id: str
    text: str
    evidence_refs: tuple[str, ...] = ()
    verification: Literal["VERIFIED", "UNVERIFIED", "CONTRADICTED"]


class ContentAtom(Contract):
    atom_id: str
    tenant_id: str
    project_id: str
    campaign_id: Optional[str] = None
    title: str
    claims: tuple[Claim, ...]
    source_refs: tuple[str, ...] = ()
    version: int = Field(ge=1)
    content_hash: str = Field(pattern=HASH)
    created_at: str


class ContentVariantSpec(Contract):
    kind: ContentKind
    channel: str
    title: str
    sections: tuple[str, ...]
    claim_refs: tuple[str, ...]
    constraints: tuple[str, ...] = ()
    atom_id: str
    atom_version: int = Field(ge=1)
    release_blockers: tuple[str, ...] = ()


class ContentItem(Contract):
    content_item_id: str
    tenant_id: str
    project_id: str
    campaign_id: Optional[str] = None
    atom_id: Optional[str] = None
    artifact_id: Optional[str] = None
    kind: ContentKind
    channel: str
    title: str
    state: ContentState
    version: int = Field(ge=1)
    claim_refs: tuple[str, ...] = ()
    rights_ref: Optional[str] = None
    approved_version: Optional[int] = None
    approval_ref: Optional[str] = None
    evidence_fresh_until: Optional[str] = None
    created_by: str
    created_at: str
    updated_at: str


# --------------------------------------------------------------------------
# Calendar + scheduler
# --------------------------------------------------------------------------


class Calendar(Contract):
    calendar_id: str
    tenant_id: str
    project_id: str
    name: str
    timezone: str = "UTC"
    created_at: str


class ScheduleSlot(Contract):
    slot_id: str
    calendar_id: str
    tenant_id: str
    project_id: str
    content_item_id: Optional[str] = None
    channel: str
    scheduled_for: str
    state: Literal["open", "filled", "released", "cancelled"]
    created_at: str


class ScheduledJob(Contract):
    job_id: str
    tenant_id: str
    project_id: str
    slot_id: Optional[str] = None
    content_item_id: Optional[str] = None
    job_kind: ScheduledJobKind
    due_at: str
    status: ScheduledJobStatus
    idempotency_key: str
    outbox_message_id: Optional[str] = None
    block_reasons: tuple[str, ...] = ()
    payload: dict[str, Any] = Field(default_factory=dict)
    attempts: int = Field(ge=0)
    created_at: str
    updated_at: str


class ScheduleCadence(Contract):
    channel: str
    kind: ContentKind
    posts_per_week: float = Field(gt=0, le=70)
    weekdays: tuple[int, ...] = (0, 1, 2, 3, 4)
    hour_utc: int = Field(default=15, ge=0, le=23)


# --------------------------------------------------------------------------
# Publishing
# --------------------------------------------------------------------------


class PublicationAttempt(Contract):
    attempt_id: str
    tenant_id: str
    project_id: str
    job_id: Optional[str] = None
    content_item_id: str
    provider: str
    mode: ProviderMode
    state: PublicationState
    request_hash: str = Field(pattern=HASH)
    idempotency_key: str
    external_ref: Optional[str] = None
    readback: dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    created_at: str
    updated_at: str


class PublicationReceipt(Contract):
    receipt_id: str
    attempt_id: str
    tenant_id: str
    project_id: str
    kind: Literal["dispatch_permit", "execution", "observation"]
    payload: dict[str, Any]
    receipt_hash: str = Field(pattern=HASH)
    created_at: str


# --------------------------------------------------------------------------
# Memory + knowledge
# --------------------------------------------------------------------------


class MemoryRecord(Contract):
    memory_id: str
    tenant_id: str
    project_id: Optional[str] = None
    thread_id: Optional[str] = None
    scope: MemoryScope
    authority: MemoryAuthority
    subject_key: str
    body: dict[str, Any]
    source_refs: tuple[str, ...] = ()
    fresh_until: Optional[str] = None
    status: MemoryStatus
    supersedes: Optional[str] = None
    content_hash: str = Field(pattern=HASH)
    created_by: str
    created_at: str


class KnowledgeClaim(Contract):
    text: str
    observed_date: Optional[str] = None
    corroborating_sources: tuple[str, ...] = ()
    contradicted_by: tuple[str, ...] = ()


class KnowledgeCapsuleMeta(Contract):
    item_id: str
    tenant_id: str
    project_id: Optional[str] = None
    domain: str
    source_uri: str
    rights_class: RightsClass
    stage: str
    status: KnowledgeStatus
    claims: tuple[KnowledgeClaim, ...] = ()
    evidence_score: float = Field(ge=0.0, le=1.0)
    rejection_reasons: tuple[str, ...] = ()
    content_hash: str = Field(pattern=HASH)
    fetched_at: Optional[str] = None
    created_at: str
    updated_at: str


# --------------------------------------------------------------------------
# Provider routing, growth, brand stewardship, reproducibility
# --------------------------------------------------------------------------


class ObservedMetric(Contract):
    value: Optional[float] = None
    unit: str
    sample_size: int = Field(default=0, ge=0)
    evidence_ref: Optional[str] = None
    status: Literal["OBSERVED", "UNKNOWN"]


class ProviderCapabilityProfile(Contract):
    profile_id: str
    tenant_id: str
    provider: str
    model: str
    task: str
    formats: tuple[str, ...]
    locality: Literal["local", "cloud"]
    cost_per_unit: ObservedMetric
    latency_p95_ms: ObservedMetric
    acceptance_rate: ObservedMetric
    failure_rate: ObservedMetric
    rights_constraints: tuple[str, ...] = ()
    benchmark_refs: tuple[str, ...] = ()
    last_verified_at: Optional[str] = None
    mode: ProviderMode
    created_at: str


class GrowthExperiment(Contract):
    experiment_id: str
    tenant_id: str
    project_id: str
    hypothesis: str
    target_metric: str
    segment: str
    intervention: str
    asset_refs: tuple[str, ...] = ()
    start_at: Optional[str] = None
    end_at: Optional[str] = None
    sample_requirement: int = Field(ge=1)
    status: Literal["DRAFT", "RUNNING", "CONCLUDED", "ABANDONED"]
    observed_result: Optional[dict[str, Any]] = None
    decision: Optional[Literal["ADOPT", "REJECT", "INCONCLUSIVE"]] = None
    learning_signal_id: Optional[str] = None
    created_at: str
    updated_at: str


class BrandDriftFinding(Contract):
    category: Literal[
        "logo_misuse", "colors", "typography", "voice", "naming", "claims",
        "stale_product_facts", "old_pricing", "old_screenshots", "expired_rights",
        "accessibility", "duplicate_content", "creative_repetition",
    ]
    severity: Literal["info", "warning", "blocking"]
    artifact_id: str
    detail: str
    evidence: tuple[str, ...] = ()


class BrandDriftReport(Contract):
    project_id: str
    tenant_id: str
    brand_core_ref: Optional[str] = None
    findings: tuple[BrandDriftFinding, ...]
    refresh_candidates: tuple[str, ...]
    not_evaluated: tuple[str, ...] = ()
    autonomous_overwrites: Literal[0] = 0
    report_hash: str = Field(pattern=HASH)


class ReproducibilityRecord(Contract):
    subject_ref: str
    source_hashes: tuple[str, ...]
    prompt_hashes: tuple[str, ...] = ()
    schema_version: str
    provider: Optional[str] = None
    model: Optional[str] = None
    seed: Optional[int] = None
    generation_config_hash: Optional[str] = None
    tool_contract_version: Optional[str] = None
    environment_signature: str
    execution_args_hash: str = Field(pattern=HASH)
    input_artifact_refs: tuple[str, ...] = ()
    output_hash: Optional[str] = None
    guarantee: Literal["BYTE_IDENTICAL", "DETERMINISTIC_PIPELINE", "SEEDED_BEST_EFFORT", "NON_DETERMINISTIC"]
