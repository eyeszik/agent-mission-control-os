import { z } from 'zod';

// Zod twins of the ACE v12 governed action plane (/actions) and Agency OS
// (/agency-os). Core objects are .strict() so a drifted backend fails at the
// boundary; large evolving documents (receipts, plans) are records.
// Parity: services/langgraph/tests/test_ace12_contracts.py records real
// responses into packages/shared/tests/fixtures/ace12.json and checks every
// enum below against its Python vocabulary.

export const RiskClassSchema = z.enum(['R0', 'R1', 'R2', 'R3', 'R4', 'R5', 'R6']);
export const ActionEnvironmentSchema = z.enum(['LOCAL', 'SANDBOX', 'LIVE']);
export const ActionStateSchema = z.enum([
  'PROPOSED', 'VALIDATED', 'PREPARED', 'AWAITING_APPROVAL', 'AUTHORIZED', 'RESERVED', 'DISPATCHING', 'OBSERVING', 'VERIFIED',
  'COMPLETED', 'REJECTED', 'BLOCKED', 'EXPIRED', 'CANCELLED', 'FAILED', 'UNKNOWN', 'RECONCILING', 'NEEDS_HUMAN',
]);
export const ImplStatusSchema = z.enum([
  'DEFINED', 'IMPLEMENTED', 'TESTED', 'VERIFIED', 'LIVE_GATED', 'UNAVAILABLE', 'BLOCKED', 'NOT_IMPLEMENTED', 'PROVIDER_GAP',
  'VOID_DETECTED',
]);
export const AutonomyLevelSchema = z.enum(['OBSERVE', 'DRAFT', 'PREPARE', 'REQUEST_APPROVAL']);
export const ClientStatusSchema = z.enum(['ACTIVE', 'OFFBOARDING', 'ARCHIVED']);
export const LifecycleStageSchema = z.enum([
  'INTAKE', 'DISCOVERY', 'STRATEGY', 'IDENTITY', 'PRODUCTION', 'REVIEW', 'DELIVERY', 'DISTRIBUTION', 'MEASUREMENT', 'MAINTENANCE',
]);

const record = z.record(z.string(), z.unknown());
const nullableString = z.string().nullable();

export const RiskExplanationSchema = z.object({ rule: z.string(), effect: z.string(), reason: z.string() }).strict();

export const RiskViewSchema = z.object({
  classes: z.array(RiskClassSchema),
  effective: RiskClassSchema,
  controls: z.array(z.string()),
  explanations: z.array(RiskExplanationSchema),
  policy_version: z.string(),
  requires_approval: z.boolean(),
  requires_financial_approval: z.boolean(),
  requires_step_up: z.boolean(),
  requires_privileged_review: z.boolean(),
  live_gated: z.boolean(),
  facts: record.optional(),
  autonomy: AutonomyLevelSchema.optional(),
}).strict();

export const ApprovalSummarySchema = z.object({
  subject: z.string(),
  approval_id: z.string(),
  status: z.string().nullable(),
  decision: nullableString,
  reviewer: nullableString,
  decided_at: nullableString,
  subject_hash: nullableString,
}).strict();

export const ApprovalCheckSchema = z.object({
  satisfied: z.boolean(),
  rejected: z.boolean(),
  expired: z.boolean(),
  stale: z.boolean(),
  pending: z.array(z.string()),
  reasons: z.array(z.string()),
  approvals: z.array(ApprovalSummarySchema),
}).strict();

export const BindingDiffSchema = z.object({ field: z.string(), approved: z.unknown(), current: z.unknown() }).strict();

export const ActionViewSchema = z.object({
  action_id: z.string(),
  tenant_id: z.string(),
  project_id: z.string(),
  client_id: nullableString,
  capability_id: z.string(),
  capability_version: z.string(),
  environment: ActionEnvironmentSchema,
  actor_ref: z.string(),
  target_ref: z.string(),
  args: record,
  payload_hash: z.string(),
  context_hash: z.string(),
  policy_version: z.string(),
  dependency_hashes: z.array(z.array(z.string())),
  risk: RiskViewSchema,
  effective_class: RiskClassSchema,
  binding: record,
  binding_hash: z.string(),
  binding_diff: z.array(BindingDiffSchema),
  approvals: ApprovalCheckSchema.nullable(),
  run_id: nullableString,
  budget_reservation_id: nullableString,
  idempotency_key: z.string(),
  correlation_id: z.string(),
  state: ActionStateSchema,
  status_label: z.string(),
  version: z.number().int(),
  attempts: z.number().int(),
  retry_eligible: z.boolean(),
  reasons: z.array(z.string()),
  outcome: record.nullable(),
  injection_flags: z.array(z.string()),
  created_at: z.string(),
  updated_at: z.string(),
  expires_at: z.string(),
  live_execution: z.literal('DISABLED'),
}).strict();

export const CatalogEntrySchema = z.object({
  id: z.string(),
  version: z.string(),
  title: z.string(),
  domain: z.string(),
  provider: z.string(),
  risk: record,
  scopes: z.array(z.string()),
  input_schema: record,
  output_schema: record,
  approval_policy: z.string(),
  preconditions: z.array(z.string()),
  postconditions: z.array(z.string()),
  timeout_seconds: z.number().int(),
  retry: record,
  idempotency: z.string(),
  budget: z.string(),
  verification: z.string(),
  compensation: record,
  status: ImplStatusSchema,
  live_status: ImplStatusSchema,
  environments: z.array(ActionEnvironmentSchema),
  dispatch_owner: z.string(),
  source_ref: z.string(),
  status_reasons: z.array(z.string()),
  tests: z.array(z.string()),
  candidate_ids: z.array(z.string()),
  ref: z.string(),
  descriptor_hash: z.string(),
  nominal_risk: z.object({ classes: z.array(RiskClassSchema), effective: RiskClassSchema, controls: z.array(z.string()) }).strict(),
}).strict();

export const LiveEnablementSchema = z.object({ status: z.literal('DISABLED'), reasons: z.array(z.string()) }).strict();

export const CatalogSnapshotSchema = z.object({
  catalog_version: z.string(),
  entries: z.array(CatalogEntrySchema),
  reserved_namespaces: z.array(z.object({ namespace: z.string(), status: z.literal('VOID_DETECTED'), reason: z.string() }).strict()),
  catalog_hash: z.string(),
  live: LiveEnablementSchema,
}).strict();

export const ActionPreviewSchema = z.object({
  shadow: z.literal(true),
  label: z.string(),
  outcome: z.enum(['WOULD_BE_BLOCKED', 'WOULD_RUN_WITHOUT_APPROVAL', 'WOULD_REQUEST_APPROVAL']),
  capability: record,
  environment: ActionEnvironmentSchema,
  target_ref: z.string(),
  payload_hash: z.string(),
  risk: RiskViewSchema,
  effect: z.string(),
  reversibility: z.string(),
  compensation: record,
  cost: z.object({ currency: nullableString, amount_minor: z.number().int(), basis: z.string() }).strict(),
  approvals_required: z.array(z.string()),
  blockers: z.array(z.string()),
  autonomy: AutonomyLevelSchema,
  frozen: z.array(z.string()),
  live: LiveEnablementSchema,
  budget: record.nullable(),
  dependencies: z.array(z.array(z.string())),
  injection_flags: z.array(z.string()),
  binding_hash: z.string(),
  expires_at: z.string(),
}).strict();

export const EvidenceSchema = z.object({
  action_id: z.string(),
  state: ActionStateSchema,
  status_label: z.string(),
  chain: z.object({ intact: z.boolean(), entries: z.number().int() }).passthrough(),
  transitions: z.array(record),
  permits: z.array(record),
  execution_receipts: z.array(record),
  observation_receipts: z.array(record),
  approvals: z.array(record),
  policy_decisions: z.array(record),
  recovery_cases: z.array(record),
  budget_reservation: record.nullable(),
  sandbox_record: record.nullable(),
  claims: z.array(record),
  binding_hash: z.string(),
  live_execution: z.literal('DISABLED'),
}).strict();

export const RecoveryItemSchema = z.object({
  action_id: z.string(),
  project_id: z.string(),
  capability_id: z.string(),
  state: ActionStateSchema,
  status_label: z.string(),
  reasons: z.array(z.string()),
  attempts: z.number().int(),
  reconcile_attempts: z.number().int(),
  retry_eligible: z.boolean(),
  next_step: z.string(),
  updated_at: z.string(),
}).strict();

export const ClientSchema = z.object({
  client_id: z.string(),
  tenant_id: z.string(),
  display_name: z.string(),
  slug: z.string(),
  status: ClientStatusSchema,
  notes: z.string(),
  created_by: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
  projects: z.array(z.object({ project_id: z.string(), display_name: z.string(), lifecycle_state: z.string() }).strict()).optional(),
}).strict();

export const LifecycleSchema = z.object({
  project_id: z.string(),
  stages: z.array(z.object({
    stage: LifecycleStageSchema,
    depends_on: z.array(LifecycleStageSchema),
    status: z.enum(['DONE', 'IN_PROGRESS', 'NOT_STARTED', 'BLOCKED_DEPENDENCY', 'LIVE_GATED', 'NOT_MEASURED', 'ATTENTION', 'READY']),
    evidence: z.array(z.string()),
    unmet: z.array(LifecycleStageSchema),
  }).strict()),
  stale_artifacts: z.array(z.string()),
  edges: z.array(z.object({ from: LifecycleStageSchema, to: LifecycleStageSchema }).strict()),
  computed_at: z.string(),
}).strict();

export const AttentionItemSchema = z.object({
  category: z.enum(['RECOVERY', 'APPROVAL', 'EXPIRING', 'BLOCKED']),
  kind: nullableString,
  ref: z.string(),
  project_id: z.string(),
  title: nullableString,
  risk: RiskClassSchema.nullable(),
  expires_at: nullableString,
  subject_ref: nullableString,
  created_at: nullableString,
}).strict();

export const MissionNodeSchema = z.object({
  cell_id: z.string(),
  node_id: z.string(),
  artifact_type: nullableString,
  objective: z.string(),
  state: z.string(),
  status_label: z.string(),
  blockers: z.array(z.string()),
  wave: z.number().int().nullable(),
  side_effect_class: z.string(),
  role: nullableString,
}).strict();

export const MissionPreviewSchema = z.object({
  preview: z.literal(true),
  label: z.string(),
  outcome: z.enum(['READY_TO_LAUNCH', 'BLOCKED', 'PROVIDER_GAP', 'NEEDS_CLARIFICATION']),
  reasons: z.array(z.string()),
  intent: record,
  project: record,
  external_effects: z.array(record),
  acceptance_criteria: z.array(record),
  cost: z.object({ currency: nullableString, amount_minor: z.number().int(), basis: z.string() }).strict(),
  live_execution: z.literal('DISABLED'),
  nodes: z.array(MissionNodeSchema),
  edges: z.array(z.object({ from: z.string(), to: z.string() }).strict()),
  deliverable: record.optional(),
  brand_context: record.optional(),
  plan_hash: z.string().optional(),
  waves: z.array(z.object({ index: z.number().int(), cells: z.array(z.string()) }).strict()).optional(),
}).strict();

export const MissionSummarySchema = z.object({
  status: z.enum(['AWAITING_APPROVAL', 'BLOCKED', 'NEEDS_CLARIFICATION', 'SIMULATED', 'FAILED']),
  status_label: z.string(),
  reasons: z.array(z.string()),
  mission_id: nullableString,
  contract_hash: nullableString,
  deliverable: nullableString,
  acceptance_criteria: z.array(record),
  verification: record.nullable(),
  approval: record.nullable(),
  non_actions: z.array(record),
  simulation: z.boolean(),
  release_eligible: z.boolean(),
  live_execution: z.literal('DISABLED'),
}).strict();

export const DeliverableSchema = z.object({
  artifact_id: z.string(),
  artifact_key: z.string(),
  artifact_type: z.string(),
  version: z.number().int(),
  content_hash: nullableString,
  mime_type: nullableString,
  status: z.string(),
  preview_uri: nullableString,
  approvals: z.array(record),
  release: z.object({ allowed: z.boolean(), reasons: z.array(z.string()), approval_id: nullableString, note: z.string() }).strict(),
  rights: z.object({ rights_ref: nullableString, status: z.enum(['RECORDED', 'NOT_RECORDED']) }).strict(),
  provenance_ref: nullableString,
  source_refs: z.array(z.string()),
}).strict();

export const DeliveryManifestSchema = z.object({
  manifest_version: z.literal('amc-delivery-manifest/v1'),
  tenant_id: z.string(),
  project_id: z.string(),
  items: z.array(record),
  excluded: z.array(record),
  manifest_hash: z.string(),
  signature: record,
  exported_at: z.string(),
  delivered_externally: z.literal(false),
}).strict();

export const AnalyticsSchema = z.object({
  as_of: z.string(),
  scope: z.string(),
  metrics: z.array(z.object({
    metric: z.string(),
    value: z.unknown(),
    source: nullableString,
    definition: z.string(),
    status: z.literal('NOT_MEASURED').optional(),
  }).strict()),
  note: z.string(),
}).strict();

export type RiskClass = z.infer<typeof RiskClassSchema>;
export type ActionState = z.infer<typeof ActionStateSchema>;
export type ImplStatus = z.infer<typeof ImplStatusSchema>;
export type AutonomyLevel = z.infer<typeof AutonomyLevelSchema>;
export type ActionView = z.infer<typeof ActionViewSchema>;
export type CatalogEntry = z.infer<typeof CatalogEntrySchema>;
export type CatalogSnapshot = z.infer<typeof CatalogSnapshotSchema>;
export type ActionPreview = z.infer<typeof ActionPreviewSchema>;
export type ActionEvidence = z.infer<typeof EvidenceSchema>;
export type RecoveryItem = z.infer<typeof RecoveryItemSchema>;
export type AgencyClient = z.infer<typeof ClientSchema>;
export type Lifecycle = z.infer<typeof LifecycleSchema>;
export type AttentionItem = z.infer<typeof AttentionItemSchema>;
export type MissionPreview = z.infer<typeof MissionPreviewSchema>;
export type MissionSummary = z.infer<typeof MissionSummarySchema>;
export type Deliverable = z.infer<typeof DeliverableSchema>;
export type DeliveryManifest = z.infer<typeof DeliveryManifestSchema>;
export type AgencyAnalytics = z.infer<typeof AnalyticsSchema>;

// Small response envelopes used by the web client (it does not import zod directly).
export const DriftReportSchema = z.object({
  checked_at: z.string(),
  drifted: z.number().int(),
  entries: z.array(z.object({ id: z.string(), declared: z.string(), observed: z.string(), drift: z.boolean(), reasons: z.array(z.string()) }).strict()),
}).strict();
export const BudgetEnvelopeSchema = z.object({
  as_of: z.string(),
  policies: z.array(record),
  currencies: z.record(z.string(), z.record(z.string(), z.number())),
  note: z.string(),
}).strict();
export const FreezeListSchema = z.object({ system_frozen: z.boolean(), freezes: z.array(record) }).strict();
export const AutonomyResponseSchema = z.object({ project_id: z.string(), autonomy: AutonomyLevelSchema, auto_ceiling: RiskClassSchema }).strict();
export const LooseRecordSchema = record;

export type DriftReport = z.infer<typeof DriftReportSchema>;
export type BudgetEnvelope = z.infer<typeof BudgetEnvelopeSchema>;
export type FreezeList = z.infer<typeof FreezeListSchema>;

export const AuthorityTwinSchema = z.object({
  user_id: z.string(),
  tenant_id: z.string(),
  role: z.string(),
  projects: z.array(z.string()),
  can: z.object({
    read: z.boolean(), propose_actions: z.boolean(), launch_missions: z.boolean(), decide_approvals: z.boolean(),
    decide_spend_approvals: z.boolean(), decide_governance_approvals: z.boolean(), freeze_dispatch: z.boolean(),
    lift_freeze: z.boolean(), raise_autonomy: z.boolean(), offboard_clients: z.boolean(), self_approve: z.literal(false),
  }).strict(),
  never: z.array(z.string()),
}).strict();
export type AuthorityTwin = z.infer<typeof AuthorityTwinSchema>;
