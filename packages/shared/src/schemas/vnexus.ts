import { z } from 'zod';

// Zod twins of the VNEXUS API (services/langgraph/agency/vnexus/* and
// api/routes/vnexus.py). Objects are .strict() so a drifted backend fails at
// the boundary. Parity is proven by packages/shared/tests/fixtures/vnexus.json:
// the backend suite (test_vnexus_contracts.py) records real responses there
// and checks their structure; this package's tests parse it with these schemas.

export const VNEXUS_GENOME_SCHEMA = 'amc-vnexus-genome/v1' as const;

export const VnexusChromosomeSchema = z.enum(['strategy', 'visual', 'verbal', 'experience', 'production']);
export const VnexusScopeSchema = z.enum(['brand', 'project', 'page', 'component', 'asset']);
export const VnexusVersionStatusSchema = z.enum(['DRAFT', 'EXPERIMENTAL', 'IN_REVIEW', 'APPROVED', 'REJECTED', 'SUPERSEDED']);
export const VnexusConstraintKindSchema = z.enum(['IMMUTABLE', 'REQUIRED', 'ALLOWED_VALUES', 'RANGE', 'HEX_COLOR', 'MIN_CONTRAST']);
export const VnexusSeveritySchema = z.enum(['INFO', 'WARNING', 'ERROR', 'BLOCKING']);
export const VnexusProvenanceKindSchema = z.enum(['USER_SUPPLIED', 'IMPORTED', 'INFERRED', 'DEFAULTED', 'UNRESOLVED']);
export const VnexusConflictReasonSchema = z.enum(['SCOPE_ORDER', 'UNAPPROVED_OVERRIDE', 'IMMUTABLE_OVERRIDE', 'CONSTRAINT_VIOLATION']);
export const VnexusBranchStateSchema = z.enum(['OPEN', 'IN_REVIEW', 'PROMOTED', 'REJECTED', 'ARCHIVED']);
export const VnexusNodeKindSchema = z.enum([
  'Brand', 'GenomeVersion', 'Campaign', 'Audience', 'Insight', 'DesignDecision', 'CreativeConcept', 'Asset', 'Prompt', 'Experiment',
  'Experience', 'Channel', 'ProviderJob', 'Approval', 'Evidence', 'Branch',
]);
export const VnexusEdgeKindSchema = z.enum([
  'DERIVED_FROM', 'APPROVED_BY', 'DEPENDS_ON', 'SUPERSEDES', 'IMPLEMENTS', 'GENERATED_BY', 'TESTED_BY', 'TARGETS', 'CONFLICTS_WITH',
  'SUPPORTED_BY',
]);
export const VnexusJobStateSchema = z.enum([
  'PLANNED', 'VALIDATED', 'AUTHORIZED', 'QUEUED', 'RUNNING', 'ARTIFACT_RECEIVED', 'QC_PASSED', 'FAILED', 'CANCELED',
]);
export const VnexusCapabilitySchema = z.enum([
  'VECTOR_SVG', 'RASTER_PNG', 'RASTER_WEBP', 'DOCUMENT_PDF', 'MOTION_MP4', 'TEXT_TO_IMAGE', 'TEXT_TO_VIDEO', 'IMAGE_TO_VIDEO', 'VIDEO_TRANSFORM',
]);
export const VnexusProviderStatusSchema = z.enum(['AVAILABLE', 'UNAVAILABLE', 'DISABLED']);
export const VnexusClaimClassSchema = z.enum(['VERIFIED_REQUIREMENT', 'INFERRED_DECISION', 'EXPERIMENTAL_SUGGESTION', 'UNSUPPORTED_ASSUMPTION']);

export const GenomeValueSchema = z.union([z.string(), z.number(), z.boolean(), z.null(), z.array(z.string())]);

export const GenomeConstraintSchema = z.object({
  constraint_id: z.string(),
  key: z.string(),
  kind: VnexusConstraintKindSchema,
  params: z.record(z.string(), z.unknown()),
  severity: VnexusSeveritySchema,
  rationale: z.string(),
}).strict();

export const GenomeProvenanceSchema = z.object({
  key: z.string(), kind: VnexusProvenanceKindSchema, source_ref: z.string(), note: z.string(),
}).strict();

export const GenomeDocumentSchema = z.object({
  schema_version: z.literal(VNEXUS_GENOME_SCHEMA),
  chromosomes: z.record(z.string(), z.record(z.string(), GenomeValueSchema)),
  constraints: z.array(GenomeConstraintSchema),
  provenance: z.array(GenomeProvenanceSchema),
}).strict();

const nullableString = z.string().nullable();

export const BrandSchema = z.object({
  brand_id: z.string(), tenant_id: z.string(), owner_project_id: z.string(), display_name: z.string(), created_by: z.string(),
  created_at: z.string(),
}).strict();

export const GenomeVersionSchema = z.object({
  version_id: z.string(), brand_id: z.string(), scope: VnexusScopeSchema, scope_ref: z.string(), project_id: z.string(),
  version: z.number().int(), parent_version_id: nullableString, status: VnexusVersionStatusSchema, document: GenomeDocumentSchema,
  content_hash: z.string(), revision: z.number().int(), origin: z.enum(['AUTHORED', 'REVERT', 'BRANCH_PROMOTION', 'IMPORT']),
  origin_ref: nullableString, created_by: z.string(), created_at: z.string(), updated_at: z.string(), submitted_by: nullableString,
  submitted_at: nullableString, approval_id: nullableString, decided_by: nullableString, decided_at: nullableString,
}).strict();

export const GenomeConflictSchema = z.object({
  key: z.string(), reason: VnexusConflictReasonSchema, scope_ref: z.string(), detail: z.string(), constraint_id: nullableString,
}).strict();

export const ConstraintFindingSchema = z.object({
  constraint_id: z.string(), key: z.string(), kind: VnexusConstraintKindSchema, severity: VnexusSeveritySchema, passed: z.boolean(),
  detail: z.string(), declared_by: z.string(),
}).strict();

export const ResolutionSchema = z.object({
  values: z.record(z.string(), GenomeValueSchema),
  sources: z.record(z.string(), z.string()),
  constraints: z.array(GenomeConstraintSchema),
  constraint_owner: z.record(z.string(), z.string()),
  conflicts: z.array(GenomeConflictSchema),
  findings: z.array(ConstraintFindingSchema),
  applied_scopes: z.array(z.string()),
  preview_scope: nullableString,
  authoritative: z.boolean(),
}).strict();

export const ResolveResponseSchema = z.object({
  resolution: ResolutionSchema,
  resolution_hash: z.string(),
  layers: z.array(z.object({
    scope: VnexusScopeSchema, scope_ref: z.string(), status: VnexusVersionStatusSchema, version_id: nullableString,
    version: z.number().int().nullable(), content_hash: z.string(),
  }).strict()),
}).strict();

export const ReadinessSchema = z.object({
  version_id: z.string(), content_hash: z.string(), resolution_hash: z.string(), conflicts: z.array(GenomeConflictSchema),
  blocking_findings: z.array(ConstraintFindingSchema), self_findings: z.array(ConstraintFindingSchema), ready: z.boolean(),
}).strict();

export const ValueChangeSchema = z.object({ key: z.string(), before: GenomeValueSchema, after: GenomeValueSchema }).strict();

export const CompareResponseSchema = z.object({
  from: z.object({ version_id: z.string(), scope: VnexusScopeSchema, scope_ref: z.string(), version: z.number().int(),
    status: VnexusVersionStatusSchema, content_hash: z.string() }).strict(),
  to: z.object({ version_id: z.string(), scope: VnexusScopeSchema, scope_ref: z.string(), version: z.number().int(),
    status: VnexusVersionStatusSchema, content_hash: z.string() }).strict(),
  diff: z.object({
    added: z.array(ValueChangeSchema), removed: z.array(ValueChangeSchema), modified: z.array(ValueChangeSchema),
    unchanged: z.array(z.string()), constraints_added: z.array(z.string()), constraints_removed: z.array(z.string()),
    constraints_modified: z.array(z.string()),
  }).strict(),
  identical: z.boolean(),
}).strict();

export const AuditEntrySchema = z.object({
  entry_id: z.number().int(), tenant_id: z.string(), chain_ref: z.string(), subject_type: z.string(), subject_id: z.string(),
  action: z.string(), actor: z.string(), from_state: nullableString, to_state: nullableString, detail: z.record(z.string(), z.unknown()),
  prev_hash: nullableString, entry_hash: z.string(), created_at: z.string(),
}).strict();

export const AuditResponseSchema = z.object({
  entries: z.array(AuditEntrySchema),
  verification: z.object({ intact: z.boolean(), entries: z.number().int(), head: nullableString.optional(),
    break_at: z.number().int().optional(), reason: z.string().optional() }).strict(),
}).strict();

export const ChangeSetSchema = z.object({
  set: z.record(z.string(), GenomeValueSchema),
  unset: z.array(z.string()),
  add_constraints: z.array(GenomeConstraintSchema),
  remove_constraints: z.array(z.string()),
}).strict();

export const BranchEvaluationSchema = z.object({
  evaluation_id: z.string(), tenant_id: z.string(), branch_id: z.string(), kind: z.enum(['DETERMINISTIC', 'HUMAN']), evaluator: z.string(),
  changes_hash: z.string(), payload: z.record(z.string(), z.unknown()), payload_hash: z.string(), created_at: z.string(),
}).strict();

export const BranchSchema = z.object({
  branch_id: z.string(), tenant_id: z.string(), brand_id: z.string(), scope: VnexusScopeSchema, scope_ref: z.string(),
  project_id: z.string(), base_version_id: z.string(), parent_branch_id: nullableString, name: z.string(), hypothesis: z.string(),
  changes: ChangeSetSchema, changes_hash: z.string(), state: VnexusBranchStateSchema, revision: z.number().int(),
  proposal_version_id: nullableString, decision_note: nullableString, created_by: z.string(), created_at: z.string(),
  updated_at: z.string(), evaluations: z.array(BranchEvaluationSchema).optional(),
}).strict();

export const BranchComparisonSchema = z.object({
  branch_document_hash: z.string(), base_document_hash: z.string(),
  values: z.object({ added: z.array(ValueChangeSchema), removed: z.array(ValueChangeSchema), modified: z.array(ValueChangeSchema),
    unchanged: z.array(z.string()) }).strict(),
  constraints: z.object({ added: z.array(z.string()), removed: z.array(z.string()), modified: z.array(z.string()),
    unchanged_own: z.array(z.string()), unchanged_inherited: z.array(z.string()) }).strict(),
  invariant_violations: z.array(z.object({ kind: z.string(), key: z.string(), constraint_id: nullableString, detail: z.string() }).strict()),
  failed_findings: z.array(ConstraintFindingSchema),
  resolution_hash: z.string(),
  promotable: z.boolean(),
  base_is_current: z.boolean(),
  changes_hash: z.string(),
}).strict();

export const GraphNodeSchema = z.object({
  node_id: z.string(), kind: VnexusNodeKindSchema, label: z.string(), attributes: z.record(z.string(), z.unknown()),
  content_hash: z.string(), valid_from: z.string(), valid_to: nullableString, superseded_by: nullableString,
}).strict();

export const GraphEdgeSchema = z.object({
  edge_id: z.string(), kind: VnexusEdgeKindSchema, src_node_id: z.string(), dst_node_id: z.string(),
  provenance: z.record(z.string(), z.unknown()), valid_from: z.string(), valid_to: nullableString,
}).strict();

export const GraphViewSchema = z.object({
  as_of: nullableString,
  nodes: z.array(GraphNodeSchema),
  edges: z.array(GraphEdgeSchema),
  lineage_cycles: z.array(z.array(z.string())),
  snapshot: z.object({ as_of: nullableString, nodes: z.record(z.string(), z.string()), edges: z.array(z.string()),
    snapshot_hash: z.string() }).strict(),
}).strict();

export const ImpactSchema = z.object({
  changed: z.array(z.string()),
  affected: z.array(z.object({ node_id: z.string(), kind: VnexusNodeKindSchema, label: z.string(), path: z.array(z.string()) }).strict()),
}).strict();

export const ProviderSchema = z.object({
  provider_id: z.string(), kind: z.enum(['LOCAL', 'HOSTED', 'MOCK']), version: z.string(), description: z.string(),
  capabilities: z.array(VnexusCapabilitySchema), status: VnexusProviderStatusSchema, blockers: z.array(z.string()),
  cost_per_job_minor: z.number().int(), currency: z.string(), timeout_s: z.number().int(), rate_limit_per_minute: z.number().int(),
  simulated: z.boolean(),
}).strict();

export const MediaJobSchema = z.object({
  job_id: z.string(), project_id: z.string(), provider_id: z.string(), capability: VnexusCapabilitySchema, request_hash: z.string(),
  idempotency_key: z.string(), state: VnexusJobStateSchema, estimate: z.record(z.string(), z.unknown()),
  budget_ceiling_minor: z.number().int(), currency: z.string(), authorized_by: nullableString, authorized_at: nullableString,
  attempts: z.number().int(), max_attempts: z.number().int(), provider_job_ref: nullableString,
  artifact: z.record(z.string(), z.unknown()), qc: z.record(z.string(), z.unknown()), error: nullableString, created_by: z.string(),
  created_at: z.string(), updated_at: z.string(), version: z.number().int(), label: z.string(), claimable_as_generated: z.boolean(),
  simulated: z.boolean(),
  transitions: z.array(z.object({ transition_id: z.number().int(), job_id: z.string(), tenant_id: z.string(), from_state: z.string(),
    to_state: z.string(), reason: z.string(), actor: z.string(), observed_at: z.string() }).strict()).optional(),
}).strict();

export const ImmuneFindingSchema = z.object({
  finding_id: z.string(), code: z.string(), severity: VnexusSeveritySchema, subject: z.string(), detail: z.string(),
  evidence: z.record(z.string(), z.unknown()), remediation: z.record(z.string(), z.unknown()).nullable(),
}).strict();

export const ImmuneScanSchema = z.object({
  brand_id: z.string(), scope: VnexusScopeSchema, scope_ref: z.string(), outputs_scanned: z.number().int(),
  findings: z.array(ImmuneFindingSchema),
  counts: z.object({ INFO: z.number().int(), WARNING: z.number().int(), ERROR: z.number().int(), BLOCKING: z.number().int() }).strict(),
  healthy: z.boolean(), scan_hash: z.string(),
}).strict();

export const TwinSnapshotSchema = z.object({
  brand_id: z.string(),
  approved_scopes: z.array(z.object({ scope: VnexusScopeSchema, scope_ref: z.string(), version: z.number().int(), version_id: z.string(),
    resolution_hash: z.string(), failed_findings: z.array(z.string()), conflicts: z.array(z.string()) }).strict()),
  graph: z.object({ as_of: nullableString, nodes: z.record(z.string(), z.string()), edges: z.array(z.string()), snapshot_hash: z.string() }).strict(),
  produced_outputs: z.number().int(), open_branches: z.number().int(), versions_in_review: z.number().int(),
  release_readiness: z.object({ scopes_with_failed_findings: z.number().int(), scopes_with_conflicts: z.number().int(),
    pending_human_decisions: z.number().int() }).strict(),
  label: z.string(),
}).strict();

export const ArtDirectionClaimSchema = z.object({
  section: z.string(), statement: z.string(), claim_class: VnexusClaimClassSchema, basis: z.array(z.string()), rationale: z.string(),
}).strict();

export const PromptInventorySchema = z.object({
  expected_originals: z.number().int(), imported_originals: z.number().int(), imported_ids: z.array(z.string()), missing: z.number().int(),
  status: z.enum(['COMPLETE', 'PARTIAL_IMPORT', 'SOURCE_REQUIRED']), note: z.string(),
}).strict();

export type GenomeDocument = z.infer<typeof GenomeDocumentSchema>;
export type GenomeConstraint = z.infer<typeof GenomeConstraintSchema>;
export type GenomeValue = z.infer<typeof GenomeValueSchema>;
export type GenomeVersion = z.infer<typeof GenomeVersionSchema>;
export type VnexusBrand = z.infer<typeof BrandSchema>;
export type VnexusResolution = z.infer<typeof ResolutionSchema>;
export type ResolveResponse = z.infer<typeof ResolveResponseSchema>;
export type Readiness = z.infer<typeof ReadinessSchema>;
export type CompareResponse = z.infer<typeof CompareResponseSchema>;
export type AuditResponse = z.infer<typeof AuditResponseSchema>;
export type ChangeSet = z.infer<typeof ChangeSetSchema>;
export type VnexusBranch = z.infer<typeof BranchSchema>;
export type BranchComparison = z.infer<typeof BranchComparisonSchema>;
export type GraphView = z.infer<typeof GraphViewSchema>;
export type GraphNode = z.infer<typeof GraphNodeSchema>;
export type Impact = z.infer<typeof ImpactSchema>;
export type MediaProvider = z.infer<typeof ProviderSchema>;
export type MediaJob = z.infer<typeof MediaJobSchema>;
export type ImmuneScan = z.infer<typeof ImmuneScanSchema>;
export type ImmuneFinding = z.infer<typeof ImmuneFindingSchema>;
export type TwinSnapshot = z.infer<typeof TwinSnapshotSchema>;
export type ArtDirectionClaim = z.infer<typeof ArtDirectionClaimSchema>;
export type PromptInventory = z.infer<typeof PromptInventorySchema>;
export type VnexusScope = z.infer<typeof VnexusScopeSchema>;
export type VnexusChromosome = z.infer<typeof VnexusChromosomeSchema>;
