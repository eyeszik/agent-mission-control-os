import { z } from 'zod';

/**
 * Project OS contracts — twins of services/langgraph/agency/project_os/{vocabulary,models}.py.
 *
 * Vocabulary arrays are checked against Python by scripts/verify_ontology_parity.py.
 * Object schemas are checked by parsing packages/shared/tests/fixtures/project-os.json,
 * which the Python test suite regenerates from the real Pydantic models and fails on drift.
 * Schemas are strict, like Pydantic extra="forbid".
 */

export const PROJECT_OS_VERSION = 'amc-project-os/v1';
export const WORKSPACE_SCHEMA_VERSION = 'amc-workspace/v2';

export const WORKSPACE_FOLDERS = [
  '00_admin',
  '01_sources',
  '02_research',
  '03_strategy',
  '04_brand',
  '05_product',
  '06_design',
  '07_prompts',
  '08_creative',
  '09_web_app',
  '10_content',
  '11_search',
  '12_social',
  '13_campaigns',
  '14_paid_media',
  '15_crm',
  '16_calendar',
  '17_growth',
  '18_analytics',
  '19_operations',
  '20_exports',
  '21_archive'
] as const;

export const SYSTEM_FOLDERS = [
  'runs',
  'events',
  'lineage',
  'manifests',
  'hashes',
  'approvals',
  'receipts',
  'memory',
  'checkpoints',
  'recovery',
  'objects'
] as const;

export const PROJECT_LIFECYCLE_STATES = ['ACTIVE', 'PAUSED', 'ARCHIVED'] as const;
export const PROJECT_TRANSITIONS: Record<ProjectLifecycle, ProjectLifecycle[]> = {
  ACTIVE: ['PAUSED', 'ARCHIVED'],
  PAUSED: ['ACTIVE', 'ARCHIVED'],
  ARCHIVED: ['ACTIVE']
};

export const STORAGE_BACKENDS = ['LOCAL', 'R2'] as const;
export const STORAGE_OBJECT_STATUSES = ['PRESENT', 'MISSING', 'UNVERIFIED'] as const;

export const ACTIVITY_TYPES = [
  'PROJECT_CREATED',
  'MESSAGE',
  'WORK_STARTED',
  'ARTIFACT_CREATED',
  'ARTIFACT_UPDATED',
  'PREVIEW_READY',
  'VARIANT_READY',
  'QA_BLOCKED',
  'APPROVAL_REQUIRED',
  'APPROVED',
  'REJECTED',
  'SCHEDULED',
  'PUBLISHED',
  'VERIFIED',
  'FAILED',
  'RECOVERING',
  'COMMENT',
  'EDIT_REQUESTED'
] as const;

export const CONTENT_STATES = [
  'IDEA',
  'PLANNED',
  'IN_PRODUCTION',
  'REVIEW',
  'APPROVED',
  'READY',
  'SCHEDULED',
  'DUE',
  'PUBLISHING',
  'PUBLISHED',
  'VERIFIED',
  'MEASURED',
  'REFRESH_DUE',
  'ARCHIVED'
] as const;

export const CONTENT_TRANSITIONS: Record<ContentState, ContentState[]> = {
  IDEA: ['PLANNED', 'ARCHIVED'],
  PLANNED: ['IN_PRODUCTION', 'ARCHIVED'],
  IN_PRODUCTION: ['REVIEW', 'ARCHIVED'],
  REVIEW: ['APPROVED', 'IN_PRODUCTION', 'ARCHIVED'],
  APPROVED: ['READY', 'IN_PRODUCTION', 'ARCHIVED'],
  READY: ['SCHEDULED', 'IN_PRODUCTION', 'ARCHIVED'],
  SCHEDULED: ['DUE', 'READY', 'IN_PRODUCTION'],
  DUE: ['PUBLISHING', 'SCHEDULED', 'IN_PRODUCTION'],
  PUBLISHING: ['PUBLISHED', 'SCHEDULED'],
  PUBLISHED: ['VERIFIED'],
  VERIFIED: ['MEASURED', 'REFRESH_DUE', 'ARCHIVED'],
  MEASURED: ['REFRESH_DUE', 'ARCHIVED'],
  REFRESH_DUE: ['IN_PRODUCTION', 'ARCHIVED'],
  ARCHIVED: []
};

export const APPROVAL_BOUND_CONTENT_STATES = ['APPROVED', 'READY', 'SCHEDULED', 'DUE', 'PUBLISHING'] as const;
export const CALENDAR_HORIZON_DAYS = [14, 30, 90, 182, 365] as const;

export const CONTENT_KINDS = [
  'article',
  'email',
  'newsletter',
  'carousel',
  'social_post',
  'thread',
  'video_script',
  'short_video',
  'reel',
  'story',
  'podcast_episode',
  'faq',
  'landing_section',
  'ai_search_answer',
  'paid_creative'
] as const;

export const SCHEDULED_JOB_KINDS = ['PUBLISH', 'REFRESH', 'LIFECYCLE'] as const;
export const SCHEDULED_JOB_STATUSES = ['PENDING', 'BLOCKED', 'ENQUEUED', 'DELIVERED', 'FAILED', 'CANCELLED'] as const;

export const PUBLICATION_STATES = [
  'SPEC',
  'VALIDATED',
  'AUTHORIZED',
  'APPROVED',
  'EXECUTING',
  'READBACK',
  'RECONCILED',
  'VERIFIED',
  'BLOCKED',
  'FAILED',
  'UNCERTAIN'
] as const;
export const PROVIDER_MODES = ['DISABLED', 'DRY_RUN', 'LIVE'] as const;

export const MEMORY_SCOPES = [
  'M0_AGENCY',
  'M1_BRAND_CANON',
  'M2_PROJECT',
  'M3_CONVERSATION',
  'M4_EVIDENCE',
  'M5_PERFORMANCE',
  'M6_LEARNING'
] as const;

/** Highest first. A lower class may never silently override a higher one. */
export const MEMORY_AUTHORITY_ORDER = [
  'BRAND_CANON',
  'APPROVED_PROJECT_DECISION',
  'VERIFIED_EVIDENCE',
  'WORKING_CONTEXT',
  'LEARNING_SIGNAL'
] as const;
export const MEMORY_STATUSES = ['ACTIVE', 'SUPERSEDED', 'INVALIDATED', 'QUARANTINED'] as const;

export const KNOWLEDGE_STAGES = [
  'DISCOVER',
  'FETCH',
  'SANITIZE',
  'INJECTION_SCAN',
  'RIGHTS_CLASSIFY',
  'CLAIM_EXTRACT',
  'DATE_FRESHNESS',
  'DEDUPE',
  'TRIANGULATE',
  'CONTRADICTION_CHECK',
  'EVIDENCE_SCORE',
  'CAPSULE',
  'REVIEW',
  'PROMOTE'
] as const;
export const RIGHTS_CLASSES = ['OPEN_LICENSE', 'LICENSED', 'SUMMARY_ONLY', 'PROPRIETARY_NO_COPY', 'UNKNOWN'] as const;
export const KNOWLEDGE_STATUSES = ['IN_PIPELINE', 'AWAITING_REVIEW', 'PROMOTED', 'REJECTED'] as const;

export const ROUTING_TIERS = [
  'reuse_approved_asset',
  'deterministic_transform',
  'local_free_execution',
  'cheap_draft',
  'evaluate',
  'premium_final',
  'post_process'
] as const;

export const LEARNING_PROMOTION_STAGES = [
  'SIGNAL',
  'QUARANTINE',
  'DATASET',
  'BASELINE',
  'SHADOW_TEST',
  'DIGITAL_TWIN',
  'REGRESSION_COMPARISON',
  'GOVERNANCE_PROPOSAL',
  'HUMAN_APPROVAL',
  'VERSIONED_PROMOTION',
  'MONITOR',
  'ROLLBACK'
] as const;

export const CAPABILITY_STATUSES = [
  'IMPLEMENTED',
  'IMPLEMENTED_FAIL_CLOSED',
  'DRY_RUN_ONLY',
  'LOCAL_ONLY',
  'EXTERNAL_ACTIVATION_REQUIRED',
  'NOT_AVAILABLE'
] as const;

export const ProjectLifecycleSchema = z.enum(PROJECT_LIFECYCLE_STATES);
export const ActivityTypeSchema = z.enum(ACTIVITY_TYPES);
export const ContentStateSchema = z.enum(CONTENT_STATES);
export const ContentKindSchema = z.enum(CONTENT_KINDS);
export const PublicationStateSchema = z.enum(PUBLICATION_STATES);
export const ProviderModeSchema = z.enum(PROVIDER_MODES);
export const MemoryScopeSchema = z.enum(MEMORY_SCOPES);
export const MemoryAuthoritySchema = z.enum(MEMORY_AUTHORITY_ORDER);
export const CapabilityStatusSchema = z.enum(CAPABILITY_STATUSES);

export type ProjectLifecycle = z.infer<typeof ProjectLifecycleSchema>;
export type ActivityType = z.infer<typeof ActivityTypeSchema>;
export type ContentState = z.infer<typeof ContentStateSchema>;
export type ContentKind = z.infer<typeof ContentKindSchema>;
export type MemoryScope = z.infer<typeof MemoryScopeSchema>;
export type MemoryAuthority = z.infer<typeof MemoryAuthoritySchema>;

const Hash = z.string().regex(/^[a-f0-9]{64}$/);
const Nullable = <T extends z.ZodTypeAny>(schema: T) => schema.nullable().optional();
const Strings = z.array(z.string()).default([]);
const Json = z.record(z.unknown());

export const ProjectWorkspaceV2Schema = z
  .object({
    project_id: z.string(),
    tenant_id: z.string(),
    slug: z.string().regex(/^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$/),
    display_name: z.string(),
    description: z.string().default(''),
    lifecycle_state: ProjectLifecycleSchema,
    brand_id: Nullable(z.string()),
    brand_name: Nullable(z.string()),
    workspace_schema_version: z.literal(WORKSPACE_SCHEMA_VERSION),
    manifest_hash: Hash,
    created_by: z.string(),
    created_at: z.string(),
    updated_at: z.string()
  })
  .strict();

export const ProjectManifestSchema = z
  .object({
    schema_version: z.literal(WORKSPACE_SCHEMA_VERSION),
    project_id: z.string(),
    tenant_id: z.string(),
    slug: z.string(),
    display_name: z.string(),
    brand_id: Nullable(z.string()),
    lifecycle_state: ProjectLifecycleSchema,
    folders: z.array(z.enum(WORKSPACE_FOLDERS)),
    system_folders: z.array(z.enum(SYSTEM_FOLDERS)),
    memory_namespace: z.string(),
    artifact_index_ref: z.string(),
    source_registry_ref: z.string(),
    rights_registry_ref: z.string(),
    authority_note: z.string()
  })
  .strict();

export const ArtifactHeadSchema = z
  .object({
    artifact_id: z.string(),
    artifact_type: z.string(),
    version: z.number().int().min(1),
    version_ref: z.string(),
    status: z.string(),
    content_hash: Nullable(z.string())
  })
  .strict();

export const ProjectSnapshotSchema = z
  .object({
    project_id: z.string(),
    tenant_id: z.string(),
    lifecycle_state: ProjectLifecycleSchema,
    artifact_heads: z.array(ArtifactHeadSchema),
    run_ids: z.array(z.string()),
    open_approval_count: z.number().int().min(0),
    stale_artifact_count: z.number().int().min(0),
    snapshot_hash: Hash
  })
  .strict();

export const ProjectEventSchema = z
  .object({
    event_id: z.string(),
    tenant_id: z.string(),
    project_id: z.string(),
    sequence: z.number().int().min(1),
    event_type: ActivityTypeSchema,
    actor: z.string(),
    thread_id: Nullable(z.string()),
    subject_ref: Nullable(z.string()),
    payload: Json.default({}),
    created_at: z.string()
  })
  .strict();

export const StorageObjectSchema = z
  .object({
    object_id: z.string(),
    tenant_id: z.string(),
    project_id: z.string(),
    backend: z.enum(STORAGE_BACKENDS),
    storage_uri: z.string(),
    content_hash: Hash,
    byte_size: z.number().int().min(0),
    mime_type: z.string(),
    status: z.enum(STORAGE_OBJECT_STATUSES),
    created_at: z.string(),
    verified_at: Nullable(z.string())
  })
  .strict();

export const ArtifactMetadataV2Schema = z
  .object({
    artifact_id: z.string(),
    project_id: z.string(),
    campaign_id: Nullable(z.string()),
    artifact_key: z.string(),
    artifact_type: z.string(),
    owner_department: z.string(),
    subtype: Nullable(z.string()),
    media_type: Nullable(z.enum(['text', 'image', 'video', 'audio', 'data', 'bundle'])),
    mime_type: Nullable(z.string()),
    language: Nullable(z.string()),
    locale: Nullable(z.string()),
    channel: Nullable(z.string()),
    dimensions: Nullable(z.string()),
    duration_seconds: Nullable(z.number().min(0)),
    version: z.number().int().min(1),
    version_ref: z.string(),
    parent_artifact_id: Nullable(z.string()),
    master_artifact_id: Nullable(z.string()),
    variant_of: Nullable(z.string()),
    source_refs: Strings,
    evidence_refs: Strings,
    prompt_refs: Strings,
    dependency_refs: Strings,
    storage_uri: Nullable(z.string()),
    preview_uri: Nullable(z.string()),
    thumbnail_uri: Nullable(z.string()),
    content_hash: Nullable(z.string()),
    status: z.string(),
    approval_state: z.enum(['none', 'pending', 'approved', 'rejected', 'stale']).default('none'),
    rights_ref: Nullable(z.string()),
    provenance_ref: Nullable(z.string())
  })
  .strict();

export const ArtifactVersionRecordSchema = z
  .object({
    artifact_id: z.string(),
    version: z.number().int().min(1),
    version_ref: z.string(),
    content_hash: Nullable(z.string()),
    content_location: Nullable(z.string()),
    semantic_fingerprint: Nullable(z.string()),
    change_kind: z.enum(['create', 'revise', 'restore', 'replace_master']),
    restored_from_version: Nullable(z.number().int()),
    created_by: z.string(),
    created_at: z.string()
  })
  .strict();

export const ArtifactDiffSchema = z
  .object({
    artifact_id: z.string(),
    from_version_ref: z.string(),
    to_version_ref: z.string(),
    content_changed: z.boolean(),
    location_changed: z.boolean(),
    fingerprint_changed: z.boolean(),
    metadata_changes: Json,
    text_diff: Strings,
    visual_diff: Nullable(Json)
  })
  .strict();

export const AssetRightsSchema = z
  .object({
    rights_id: z.string(),
    tenant_id: z.string(),
    project_id: z.string(),
    artifact_id: z.string(),
    license: z.string(),
    territory: z.string(),
    usage_scope: z.string(),
    attribution: Nullable(z.string()),
    source_ref: Nullable(z.string()),
    expires_at: Nullable(z.string()),
    status: z.enum(['active', 'expired', 'revoked']),
    created_at: z.string()
  })
  .strict();

export const ConversationThreadSchema = z
  .object({
    thread_id: z.string(),
    tenant_id: z.string(),
    project_id: z.string(),
    campaign_id: Nullable(z.string()),
    title: z.string(),
    status: z.enum(['open', 'archived']),
    created_by: z.string(),
    created_at: z.string(),
    updated_at: z.string()
  })
  .strict();

export const MessageArtifactRefSchema = z
  .object({
    artifact_id: z.string(),
    version_ref: z.string(),
    relation: z.enum(['created', 'updated', 'referenced', 'variant', 'preview'])
  })
  .strict();

export const ConversationMessageSchema = z
  .object({
    message_id: z.string(),
    thread_id: z.string(),
    tenant_id: z.string(),
    project_id: z.string(),
    author: z.string(),
    role: z.enum(['user', 'agent', 'system']),
    activity_type: ActivityTypeSchema,
    body: z.string(),
    artifact_refs: z.array(MessageArtifactRefSchema).default([]),
    created_at: z.string()
  })
  .strict();

export const ClaimSchema = z
  .object({
    claim_id: z.string(),
    text: z.string(),
    evidence_refs: Strings,
    verification: z.enum(['VERIFIED', 'UNVERIFIED', 'CONTRADICTED'])
  })
  .strict();

export const ContentAtomSchema = z
  .object({
    atom_id: z.string(),
    tenant_id: z.string(),
    project_id: z.string(),
    campaign_id: Nullable(z.string()),
    title: z.string(),
    claims: z.array(ClaimSchema),
    source_refs: Strings,
    version: z.number().int().min(1),
    content_hash: Hash,
    created_at: z.string()
  })
  .strict();

export const ContentVariantSpecSchema = z
  .object({
    kind: ContentKindSchema,
    channel: z.string(),
    title: z.string(),
    sections: z.array(z.string()),
    claim_refs: z.array(z.string()),
    constraints: Strings,
    atom_id: z.string(),
    atom_version: z.number().int().min(1),
    release_blockers: Strings
  })
  .strict();

export const ContentItemSchema = z
  .object({
    content_item_id: z.string(),
    tenant_id: z.string(),
    project_id: z.string(),
    campaign_id: Nullable(z.string()),
    atom_id: Nullable(z.string()),
    artifact_id: Nullable(z.string()),
    kind: ContentKindSchema,
    channel: z.string(),
    title: z.string(),
    state: ContentStateSchema,
    version: z.number().int().min(1),
    claim_refs: Strings,
    rights_ref: Nullable(z.string()),
    approved_version: Nullable(z.number().int()),
    approval_ref: Nullable(z.string()),
    evidence_fresh_until: Nullable(z.string()),
    created_by: z.string(),
    created_at: z.string(),
    updated_at: z.string()
  })
  .strict();

export const CalendarSchema = z
  .object({
    calendar_id: z.string(),
    tenant_id: z.string(),
    project_id: z.string(),
    name: z.string(),
    timezone: z.string(),
    created_at: z.string()
  })
  .strict();

export const ScheduleSlotSchema = z
  .object({
    slot_id: z.string(),
    calendar_id: z.string(),
    tenant_id: z.string(),
    project_id: z.string(),
    content_item_id: Nullable(z.string()),
    channel: z.string(),
    scheduled_for: z.string(),
    state: z.enum(['open', 'filled', 'released', 'cancelled']),
    created_at: z.string()
  })
  .strict();

export const ScheduledJobSchema = z
  .object({
    job_id: z.string(),
    tenant_id: z.string(),
    project_id: z.string(),
    slot_id: Nullable(z.string()),
    content_item_id: Nullable(z.string()),
    job_kind: z.enum(SCHEDULED_JOB_KINDS),
    due_at: z.string(),
    status: z.enum(SCHEDULED_JOB_STATUSES),
    idempotency_key: z.string(),
    outbox_message_id: Nullable(z.string()),
    block_reasons: Strings,
    payload: Json.default({}),
    attempts: z.number().int().min(0),
    created_at: z.string(),
    updated_at: z.string()
  })
  .strict();

export const ScheduleCadenceSchema = z
  .object({
    channel: z.string(),
    kind: ContentKindSchema,
    posts_per_week: z.number().gt(0).max(70),
    weekdays: z.array(z.number().int().min(0).max(6)).default([0, 1, 2, 3, 4]),
    hour_utc: z.number().int().min(0).max(23).default(15)
  })
  .strict();

export const PublicationAttemptSchema = z
  .object({
    attempt_id: z.string(),
    tenant_id: z.string(),
    project_id: z.string(),
    job_id: Nullable(z.string()),
    content_item_id: z.string(),
    provider: z.string(),
    mode: ProviderModeSchema,
    state: PublicationStateSchema,
    request_hash: Hash,
    idempotency_key: z.string(),
    external_ref: Nullable(z.string()),
    readback: Json.default({}),
    error: Nullable(z.string()),
    created_at: z.string(),
    updated_at: z.string()
  })
  .strict();

export const PublicationReceiptSchema = z
  .object({
    receipt_id: z.string(),
    attempt_id: z.string(),
    tenant_id: z.string(),
    project_id: z.string(),
    kind: z.enum(['dispatch_permit', 'execution', 'observation']),
    payload: Json,
    receipt_hash: Hash,
    created_at: z.string()
  })
  .strict();

export const MemoryRecordSchema = z
  .object({
    memory_id: z.string(),
    tenant_id: z.string(),
    project_id: Nullable(z.string()),
    thread_id: Nullable(z.string()),
    scope: MemoryScopeSchema,
    authority: MemoryAuthoritySchema,
    subject_key: z.string(),
    body: Json,
    source_refs: Strings,
    fresh_until: Nullable(z.string()),
    status: z.enum(MEMORY_STATUSES),
    supersedes: Nullable(z.string()),
    content_hash: Hash,
    created_by: z.string(),
    created_at: z.string()
  })
  .strict();

export const KnowledgeClaimSchema = z
  .object({
    text: z.string(),
    observed_date: Nullable(z.string()),
    corroborating_sources: Strings,
    contradicted_by: Strings
  })
  .strict();

export const KnowledgeCapsuleMetaSchema = z
  .object({
    item_id: z.string(),
    tenant_id: z.string(),
    project_id: Nullable(z.string()),
    domain: z.string(),
    source_uri: z.string(),
    rights_class: z.enum(RIGHTS_CLASSES),
    stage: z.string(),
    status: z.enum(KNOWLEDGE_STATUSES),
    claims: z.array(KnowledgeClaimSchema).default([]),
    evidence_score: z.number().min(0).max(1),
    rejection_reasons: Strings,
    content_hash: Hash,
    fetched_at: Nullable(z.string()),
    created_at: z.string(),
    updated_at: z.string()
  })
  .strict();

export const ObservedMetricSchema = z
  .object({
    value: Nullable(z.number()),
    unit: z.string(),
    sample_size: z.number().int().min(0).default(0),
    evidence_ref: Nullable(z.string()),
    status: z.enum(['OBSERVED', 'UNKNOWN'])
  })
  .strict();

export const ProviderCapabilityProfileSchema = z
  .object({
    profile_id: z.string(),
    tenant_id: z.string(),
    provider: z.string(),
    model: z.string(),
    task: z.string(),
    formats: z.array(z.string()),
    locality: z.enum(['local', 'cloud']),
    cost_per_unit: ObservedMetricSchema,
    latency_p95_ms: ObservedMetricSchema,
    acceptance_rate: ObservedMetricSchema,
    failure_rate: ObservedMetricSchema,
    rights_constraints: Strings,
    benchmark_refs: Strings,
    last_verified_at: Nullable(z.string()),
    mode: ProviderModeSchema,
    created_at: z.string()
  })
  .strict();

export const GrowthExperimentSchema = z
  .object({
    experiment_id: z.string(),
    tenant_id: z.string(),
    project_id: z.string(),
    hypothesis: z.string(),
    target_metric: z.string(),
    segment: z.string(),
    intervention: z.string(),
    asset_refs: Strings,
    start_at: Nullable(z.string()),
    end_at: Nullable(z.string()),
    sample_requirement: z.number().int().min(1),
    status: z.enum(['DRAFT', 'RUNNING', 'CONCLUDED', 'ABANDONED']),
    observed_result: Nullable(Json),
    decision: Nullable(z.enum(['ADOPT', 'REJECT', 'INCONCLUSIVE'])),
    learning_signal_id: Nullable(z.string()),
    created_at: z.string(),
    updated_at: z.string()
  })
  .strict();

export const BrandDriftFindingSchema = z
  .object({
    category: z.enum([
      'logo_misuse',
      'colors',
      'typography',
      'voice',
      'naming',
      'claims',
      'stale_product_facts',
      'old_pricing',
      'old_screenshots',
      'expired_rights',
      'accessibility',
      'duplicate_content',
      'creative_repetition'
    ]),
    severity: z.enum(['info', 'warning', 'blocking']),
    artifact_id: z.string(),
    detail: z.string(),
    evidence: Strings
  })
  .strict();

export const BrandDriftReportSchema = z
  .object({
    project_id: z.string(),
    tenant_id: z.string(),
    brand_core_ref: Nullable(z.string()),
    findings: z.array(BrandDriftFindingSchema),
    refresh_candidates: z.array(z.string()),
    not_evaluated: Strings,
    autonomous_overwrites: z.literal(0),
    report_hash: Hash
  })
  .strict();

export const ReproducibilityRecordSchema = z
  .object({
    subject_ref: z.string(),
    source_hashes: z.array(z.string()),
    prompt_hashes: Strings,
    schema_version: z.string(),
    provider: Nullable(z.string()),
    model: Nullable(z.string()),
    seed: Nullable(z.number().int()),
    generation_config_hash: Nullable(z.string()),
    tool_contract_version: Nullable(z.string()),
    environment_signature: z.string(),
    execution_args_hash: Hash,
    input_artifact_refs: Strings,
    output_hash: Nullable(z.string()),
    guarantee: z.enum(['BYTE_IDENTICAL', 'DETERMINISTIC_PIPELINE', 'SEEDED_BEST_EFFORT', 'NON_DETERMINISTIC'])
  })
  .strict();

export type ProjectWorkspaceV2 = z.infer<typeof ProjectWorkspaceV2Schema>;
export type ProjectSnapshot = z.infer<typeof ProjectSnapshotSchema>;
export type ProjectEvent = z.infer<typeof ProjectEventSchema>;
export type StorageObject = z.infer<typeof StorageObjectSchema>;
export type ArtifactMetadataV2 = z.infer<typeof ArtifactMetadataV2Schema>;
export type ArtifactVersionRecord = z.infer<typeof ArtifactVersionRecordSchema>;
export type ArtifactDiff = z.infer<typeof ArtifactDiffSchema>;
export type ConversationThread = z.infer<typeof ConversationThreadSchema>;
export type ConversationMessage = z.infer<typeof ConversationMessageSchema>;
export type ContentAtom = z.infer<typeof ContentAtomSchema>;
export type ContentItem = z.infer<typeof ContentItemSchema>;
export type ScheduleSlot = z.infer<typeof ScheduleSlotSchema>;
export type ScheduledJob = z.infer<typeof ScheduledJobSchema>;
export type PublicationAttempt = z.infer<typeof PublicationAttemptSchema>;
export type MemoryRecord = z.infer<typeof MemoryRecordSchema>;
export type KnowledgeCapsuleMeta = z.infer<typeof KnowledgeCapsuleMetaSchema>;
export type ProviderCapabilityProfile = z.infer<typeof ProviderCapabilityProfileSchema>;
export type GrowthExperiment = z.infer<typeof GrowthExperimentSchema>;
export type BrandDriftReport = z.infer<typeof BrandDriftReportSchema>;

export function canTransitionContent(from: ContentState, to: ContentState): boolean {
  return CONTENT_TRANSITIONS[from].includes(to);
}

export function memoryAuthorityRank(authority: MemoryAuthority): number {
  return MEMORY_AUTHORITY_ORDER.length - MEMORY_AUTHORITY_ORDER.indexOf(authority);
}

// --------------------------------------------------------------------------
// HTTP response envelopes for the project OS routes
// --------------------------------------------------------------------------

export const ProjectListResponseSchema = z.object({ projects: z.array(ProjectWorkspaceV2Schema) });
export const ProjectDetailResponseSchema = z.object({ project: ProjectWorkspaceV2Schema, snapshot: ProjectSnapshotSchema });
export const CreatedProjectResponseSchema = z.object({
  project: ProjectWorkspaceV2Schema,
  created: z.boolean(),
  mirror: z.record(z.unknown()).nullable()
});
export const ProjectEventsResponseSchema = z.object({ events: z.array(ProjectEventSchema) });
export const ProjectArtifactsResponseSchema = z.object({ artifacts: z.array(ArtifactMetadataV2Schema) });
export const WorkspaceViewSchema = z.object({
  root: z.string(),
  files: z.array(z.object({ folder: z.string(), path: z.string(), bytes: z.number() })),
  storage: z.record(z.unknown()),
  objects: z.array(StorageObjectSchema),
  authority: z.string()
});
export const ThreadsResponseSchema = z.object({ threads: z.array(ConversationThreadSchema) });
export const ThreadResponseSchema = z.object({ thread: ConversationThreadSchema });
export const MessagesResponseSchema = z.object({ messages: z.array(ConversationMessageSchema) });
export const MessageResponseSchema = z.object({ message: ConversationMessageSchema });
export const ContentItemsResponseSchema = z.object({ items: z.array(ContentItemSchema) });
export const ContentItemResponseSchema = z.object({ item: ContentItemSchema });
export const CalendarViewSchema = z.object({
  slots: z.array(ScheduleSlotSchema),
  jobs: z.array(ScheduledJobSchema),
  items: z.array(ContentItemSchema)
});

export const PortfolioProjectSchema = z
  .object({
    project_id: z.string(),
    display_name: z.string(),
    brand_name: Nullable(z.string()),
    lifecycle_state: z.string(),
    production_queue: z.number(),
    approval_queue: z.object({ content_review: z.number(), run_approvals: z.number() }),
    upcoming_calendar_14d: z.number(),
    publication_queue: z.record(z.number()),
    active_campaigns: z.array(z.string()),
    stale_assets: z.number(),
    rights_expiry: z.object({ expired: z.number(), expiring_30d: z.number(), media_without_rights: z.number() }),
    open_risks: z.array(z.string()),
    brand_health: z.enum(['OK', 'AT_RISK']),
    performance: z.unknown(),
    search_visibility: z.unknown()
  })
  .passthrough();

export const PortfolioSchema = z.object({
  tenant_id: z.string(),
  generated_at: z.string(),
  projects: z.array(PortfolioProjectSchema),
  shared_resources: z.record(z.unknown()),
  isolation: z.string()
});

export type WorkspaceView = z.infer<typeof WorkspaceViewSchema>;
export type CalendarView = z.infer<typeof CalendarViewSchema>;
export type Portfolio = z.infer<typeof PortfolioSchema>;
export type PortfolioProject = z.infer<typeof PortfolioProjectSchema>;
