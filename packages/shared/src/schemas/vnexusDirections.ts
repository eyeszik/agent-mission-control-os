import { z } from 'zod';

// Zod twins of the VNEXUS creative-direction routes (services/langgraph/api/routes/vnexus.py, creative directions section)
// over services/langgraph/agency/vnexus/directions. Parity is proven by packages/shared/tests/fixtures/vnexus-directions.json,
// recorded by services/langgraph/tests/test_vnexus_directions_contracts.py from a real run (generation, import, review,
// selection, reconstruction and freeze). Evidence class, provenance and approval state are separate fields on purpose.

const hash = z.string().regex(/^[a-f0-9]{64}$/);
const id = (prefix: string) => z.string().regex(new RegExp(`^${prefix}-[a-f0-9]{16}$`));
const seat = z.string().regex(/^(0[1-9]|1[0-4])$/);
const json = z.record(z.string(), z.unknown());

export const DirectionAssetRoleSchema = z.enum([
  'LOGO_MARK', 'WORDMARK', 'LOCKUP', 'ICON', 'ILLUSTRATION', 'HERO_IMAGE', 'PHOTOGRAPHY', 'TEXTURE',
]);
export const DirectionEvidenceClassSchema = z.enum(['OBSERVED', 'INFERRED', 'PROPOSED', 'UNKNOWN']);
export const DirectionEvidenceSourceSchema = z.enum(['PIXELS', 'GEOMETRY', 'SUPPLIED_SOURCE', 'BRIEF', 'NONE']);
export const DirectionProvenanceSchema = z.enum(['RECORDED', 'USER_REPORTED', 'SIMULATED']);
export const DirectionSeveritySchema = z.enum(['BLOCKER', 'MAJOR', 'MINOR', 'NOTE']);
export const DirectionReviewModeSchema = z.enum(['QUICK', 'FULL', 'COMPARE', 'REFINE', 'VECTOR', 'RELEASE']);
export type DirectionReviewMode = z.infer<typeof DirectionReviewModeSchema>;
export const DirectionVerdictSchema = z.enum(['BLOCKED', 'REVISE', 'RECOMMENDED_DIRECTION', 'READY_FOR_APPROVAL', 'INCONCLUSIVE']);
export type DirectionVerdict = z.infer<typeof DirectionVerdictSchema>;
export const DirectionGateSchema = z.enum([
  'EXACT_IDENTITY_TEXT', 'ACCESSIBILITY', 'SAFETY_PRIVACY_RIGHTS', 'CANONICAL_INTEGRITY', 'OUTPUT_PROVENANCE',
]);
export const DirectionGateStatusSchema = z.enum(['PASS', 'FAIL', 'UNKNOWN', 'NOT_APPLICABLE']);
export const DirectionRouteHealthSchema = z.enum(['AVAILABLE', 'UNAVAILABLE', 'DISABLED']);
export const DirectionRouteTaskSchema = z.enum([
  'TEXT_TO_IMAGE', 'CONCEPT_COMPOSE', 'MANUAL_HANDOFF', 'IMAGE_CRITIQUE', 'LOCAL_MEASURE', 'VECTOR_RECONSTRUCT', 'RESEARCH', 'TEXT',
  'SIMULATED',
]);
const VectorNeedSchema = z.enum(['REQUIRED', 'OPTIONAL', 'KEEP_RASTER']);
const AssessorSchema = z.object({
  kind: z.enum(['LOCAL_MEASUREMENT', 'HUMAN', 'MODEL']), id: z.string(), version: z.string().nullable(),
}).strict();

export const DirectionRouteSchema = z.object({
  route_id: z.string(), provider: z.string(), model: z.string().nullable(), model_pin: z.string().nullable(),
  tasks: z.array(DirectionRouteTaskSchema), formats_in: z.array(z.string()), formats_out: z.array(z.string()),
  credential_ref: z.string().nullable(), quota_scope: z.string(), quota_reset: z.string().nullable(),
  price_per_job_minor: z.number().int().nullable(), currency: z.string(), pricing_source: z.string().nullable(),
  pricing_checked_at: z.string().nullable(), data_policy: z.string(), max_requests_per_minute: z.number().int(),
  max_payload_bytes: z.number().int(), timeout_s: z.number().int(), reconciliation: z.string(), fallback_routes: z.array(z.string()),
  adapter_implemented: z.boolean(), note: z.string(), health: DirectionRouteHealthSchema, blockers: z.array(z.string()),
  credential_present: z.boolean(),
}).strict();

export const DirectionRouteRegistrySchema = z.object({
  registry_version: z.string(), spend_mode: z.enum(['zero', 'approval_required']), routes: z.array(DirectionRouteSchema),
  notes: z.array(z.string()),
}).strict();

const decided = z.union([z.literal('@none'), z.string(), z.null()]);
export const DirectionBriefSchema = z.object({
  asset_role: DirectionAssetRoleSchema, objective: z.string().min(1).max(1000), audience: decided, category: decided,
  exact_text: z.union([z.literal('@none'), z.array(z.string()), z.null()]),
  references: z.array(z.object({
    ref_id: z.string(), role: z.enum(['principle_only', 'approved_asset']), rights: z.enum(['owned', 'licensed', 'unknown']),
  }).strict()),
  rights_constraints: decided, privacy_constraints: decided, applications: z.union([z.literal('@none'), z.array(z.string()), z.null()]),
  emotional_targets: z.array(z.string()), directions: z.array(z.string()), candidate_count: z.number().int().min(1).max(4),
  budget_minor: z.number().int().min(0), width: z.number().int(), height: z.number().int(),
}).strict();
export type DirectionBrief = z.infer<typeof DirectionBriefSchema>;

const SlotSchema = z.object({
  slot: z.number().int(), direction: z.string(), prompt: z.string(), negative_prompt: z.string(), parameters: json,
  prompt_hash: hash, compose_mark: z.string().nullable(),
}).strict();

export const CreativeIntentSchema = z.object({
  schema_version: z.literal('amc-vnexus-directions/v1'), compiler_version: z.string(), intent_id: id('vdi'), tenant_id: z.string(),
  project_id: z.string(), brand_id: z.string(), scope: z.string(), scope_ref: z.string(), genome_ref: z.string(),
  resolution_hash: hash, asset_role: DirectionAssetRoleSchema, vector_need: VectorNeedSchema, brief: DirectionBriefSchema,
  brief_hash: hash,
  field_decisions: z.array(z.object({ field: z.string(), status: z.enum(['VALUE', 'NONE', 'UNKNOWN']), consequence: z.string() }).strict()),
  prohibited: z.array(z.string()), status: z.enum(['READY', 'BLOCKED_INPUT']), blockers: z.array(z.string()), shared: json,
  prompt_compiler: json, image_instructions: z.array(SlotSchema), vector_instructions: json, dependency_hash: hash,
}).strict();
export type CreativeIntent = z.infer<typeof CreativeIntentSchema>;

export const DirectionIntentCreatedSchema = z.object({
  intent: CreativeIntentSchema, stored: z.enum(['COMPLETE', 'COMPLETE_UNCHANGED']),
}).strict();

export const GenerationCandidateSchema = z.object({
  candidate_id: id('vdc'), intent_id: id('vdi'), slot: z.number().int(), direction: z.string(), prompt_hash: z.string(),
  genome_ref: z.string(), intent_dependency_hash: hash, route_id: z.string(), provenance: DirectionProvenanceSchema,
  observed: z.object({
    sha256: hash, readback_sha256: hash, mime: z.enum(['image/png', 'image/svg+xml']), bytes: z.number().int(),
    width: z.number().int().nullable(), height: z.number().int().nullable(), stored_at: z.string(), artifact_id: z.string().nullable(),
    artifact_version: z.number().int().nullable(), storage_uri: z.string().nullable(), format_class: z.enum(['VECTOR', 'RASTER_IN_SVG', 'RASTER']),
  }).strict(),
  reported: z.object({
    provider: z.string().nullable(), model: z.string().nullable(), model_version: z.string().nullable(), seed: z.number().int().nullable(),
    parameters: json, generated_at: z.string().nullable(), job_ref: z.string().nullable(), receipt_ref: z.string().nullable(),
    cost_minor: z.number().int().nullable(), currency: z.string().nullable(), rights_basis: z.string().nullable(),
    reference_ids: z.array(z.string()), prompt_used: z.string().nullable(),
  }).strict(),
  cost_measured_minor: z.number().int().nullable(), near_duplicate_of: z.string().nullable(), derived_from: z.string().nullable(),
  reconstruction_id: z.string().nullable(), perceptual_hash: z.string().nullable(), created_by: z.string(), created_at: z.string(),
}).strict();
export type GenerationCandidate = z.infer<typeof GenerationCandidateSchema>;

const RouteDecisionSchema = z.object({
  route_id: z.string(), allowed: z.boolean(), health: DirectionRouteHealthSchema, blockers: z.array(z.string()),
  estimate_minor: z.number().int().nullable(), spend_mode: z.string(), offer: z.string().nullable(), note: z.string(),
}).strict();

export const DirectionHandoffSchema = z.object({
  intent_id: id('vdi'), genome_ref: z.string(), asset_role: DirectionAssetRoleSchema, status: z.enum(['READY', 'BLOCKED_INPUT']),
  blockers: z.array(z.string()),
  slots: z.array(z.object({
    slot: z.number().int(), direction: z.string(), prompt: z.string(), negative_prompt: z.string(), parameters: json, prompt_hash: hash,
  }).strict()),
  vector_instructions: json,
  return: z.object({ formats: z.array(z.string()), max_bytes: z.number().int(), record: z.array(z.string()), provenance: z.string() }).strict(),
  rules: z.array(z.string()),
}).strict();

export const DirectionGenerateSchema = z.object({
  status: z.enum(['COMPLETE', 'PROVISIONAL', 'FAILED_VALIDATION', 'BLOCKED']), decision: RouteDecisionSchema,
  candidates: z.array(z.object({
    slot: z.number().int(), status: z.enum(['COMPLETE', 'FAILED', 'RECONCILE_REQUIRED']), job_id: z.string(),
    candidate_id: z.string().optional(), provenance: DirectionProvenanceSchema.optional(), state: z.string().optional(),
    error: z.string().nullable().optional(),
  }).strict()),
  handoff: DirectionHandoffSchema.nullable(), note: z.string().optional(),
}).strict();

export const DirectionImportSchema = z.object({ candidate: GenerationCandidateSchema, provenance_note: z.string() }).strict();

export const ReviewFindingSchema = z.object({
  finding_id: id('vdf'), candidate_id: z.string(), criterion: z.string(), seat, asset_hash: hash, region_or_element: z.string(),
  evidence_class: DirectionEvidenceClassSchema, evidence_source: DirectionEvidenceSourceSchema, observation: z.string(),
  severity: DirectionSeveritySchema, rationale: z.string(), proposed_change: z.string().nullable(), acceptance_check: z.string().nullable(),
  uncertainty: z.string(), actionable: z.boolean(), assessor: AssessorSchema, measurement: json.nullable(),
}).strict();

export const CriterionAssessmentSchema = z.object({
  candidate_id: z.string(), criterion: z.string(), seat, score: z.number().int().min(0).max(10).nullable(),
  status: z.enum(['ASSESSED', 'NOT_REVIEWED', 'NOT_APPLICABLE']), reason: z.string(), finding_ids: z.array(z.string()),
  assessors: z.array(AssessorSchema),
}).strict().refine((a) => (a.status === 'ASSESSED') === (a.score !== null), {
  message: 'a score exists exactly when the criterion was assessed (unassessed is null, never zero)',
});

export const GateResultSchema = z.object({
  candidate_id: z.string(), gate: DirectionGateSchema, status: DirectionGateStatusSchema, evidence: z.string(),
  evidence_class: DirectionEvidenceClassSchema, finding_ids: z.array(z.string()),
}).strict();

export const RevisionWorkOrderSchema = z.object({
  work_order_id: id('vdw'), candidate_id: z.string(), asset_hash: hash, change: z.string().min(1), why: z.string(),
  protected_invariants: z.array(z.string()), dependencies: json, verification: z.string().min(1), finding_ids: z.array(z.string()),
  authority: z.literal('PROPOSAL_ONLY'), execution: z.string(),
}).strict();

export const DirectionRecommendationSchema = z.object({
  verdict: DirectionVerdictSchema, candidate_id: z.string().nullable(), label: z.string().nullable(), reasons: z.array(z.string()),
  aggregate: json.nullable(), note: z.string(),
}).strict();

export const ReviewSessionSchema = z.object({
  schema_version: z.literal('amc-vnexus-directions/v1'), rubric_version: z.string(), session_id: id('vdr'), intent_id: id('vdi'),
  tenant_id: z.string(), project_id: z.string(), brand_id: z.string(), genome_ref: z.string(), mode: DirectionReviewModeSchema,
  blinded: z.boolean(), labels: z.record(z.string(), z.string()), candidates: z.record(z.string(), hash), lenses_active: z.array(seat),
  lenses_required_missing: z.array(seat), routes: z.record(z.string(), DirectionRouteHealthSchema), findings: z.array(ReviewFindingSchema),
  assessments: z.array(CriterionAssessmentSchema), gates: z.array(GateResultSchema),
  outcomes: z.array(z.object({
    candidate_id: z.string(), label: z.string(), asset_hash: hash, verdict: DirectionVerdictSchema, reasons: z.array(z.string()),
  }).strict()),
  recommendation: DirectionRecommendationSchema, work_orders: z.array(RevisionWorkOrderSchema),
  emotional_map: z.object({
    targets: z.array(z.string()), targets_source: z.string().nullable(), entries: z.array(json),
    status: z.enum(['ASSESSED', 'NOT_ASSESSED']), note: z.string(),
  }).strict(),
  brand_memory: z.object({
    entries: z.array(json), measured_recall: z.literal('HUMAN_RECALL_NOT_TESTED'), recall_protocol: z.string(),
    trademark_clearance: z.string().startsWith('NOT_ASSESSED'),
  }).strict(),
  regressions: z.array(json), measurements: z.record(z.string(), json), base_session_id: z.string().nullable(),
  correlation_note: z.string(),
  // A review never acts: these are fixed false by construction.
  effects: z.object({
    regenerated: z.literal(false), spent: z.literal(false), approved: z.literal(false), mutated_master: z.literal(false),
    published: z.literal(false),
  }).strict(),
  created_by: z.string(), created_at: z.string(),
}).strict();
export type ReviewSession = z.infer<typeof ReviewSessionSchema>;

export const DirectionReviewSchema = z.object({ session: ReviewSessionSchema }).strict();

export const ApprovalBindingSchema = z.object({
  binding_id: id('vdb'), kind: z.enum(['SELECTION', 'MASTER']), intent_id: id('vdi'), subject_artifact_id: z.string(),
  subject_version: z.number().int(), subject_sha256: hash, approval_id: z.string().nullable(), genome_version_id: z.string().nullable(),
  genome_keys: z.record(z.string(), z.string()), status: z.string(), created_by: z.string(), created_at: z.string(),
}).strict();

export const DirectionSelectionSchema = z.union([
  z.object({ status: z.literal('PENDING'), approval_id: z.string(), binding: ApprovalBindingSchema }).strict(),
  z.object({ status: z.literal('BLOCKED'), reasons: z.array(z.string()) }).strict(),
]);

const CheckSchema = z.object({
  check: z.string(), status: z.enum(['PASS', 'FAIL', 'NOT_VERIFIED', 'NOT_APPLICABLE']), detail: z.string(),
}).strict();

export const VectorReconstructionSchema = z.object({
  reconstruction_id: id('vdv'), intent_id: id('vdi'), candidate_id: z.string(), candidate_sha256: hash, selection_approval_id: z.string(),
  need: VectorNeedSchema, method: z.enum(['controlled_trace', 'native_path_import']), artifact_id: z.string().nullable(),
  artifact_version: z.number().int().nullable(), sha256: hash.nullable(), classification: z.enum(['VECTOR', 'RASTER_IN_SVG', 'REJECTED']),
  checks: z.array(CheckSchema), fidelity: json, status: z.enum(['PASSED', 'FAILED', 'NOT_VERIFIED']), reasons: z.array(z.string()),
  text_handling: z.string(), created_by: z.string(), created_at: z.string(),
}).strict().refine((r) => r.status !== 'PASSED' || (r.classification === 'VECTOR' && r.fidelity.status === 'PASS'), {
  message: 'a reconstruction passes only as native vector with a measured fidelity pass',
});

export const DirectionReconstructionSchema = z.object({
  reconstruction: VectorReconstructionSchema, candidate: GenerationCandidateSchema.nullable(), trace: json,
}).strict();

export const DirectionFreezeSchema = z.union([
  z.object({
    status: z.literal('PENDING_GENOME_REVIEW'), binding: ApprovalBindingSchema, genome_version_id: z.string(),
    approval_id: z.string().nullable(), note: z.string(),
  }).strict(),
  z.object({ status: z.literal('BLOCKED'), reasons: z.array(z.string()) }).strict(),
]);

export const DirectionStateSchema = z.object({
  intent: CreativeIntentSchema, current_genome_ref: z.string(), stale: z.boolean(),
  candidates: z.array(GenerationCandidateSchema.extend({
    stored_bytes_match: z.boolean(), stale: z.boolean(), decision: z.enum(['RECONSTRUCT', 'OPTIONAL', 'NOT_REQUIRED', 'KEEP_RASTER']),
  })),
  sessions: z.array(z.object({
    session_id: id('vdr'), mode: DirectionReviewModeSchema, verdict: DirectionVerdictSchema, label: z.string().nullable(),
    candidate_id: z.string().nullable(), created_at: z.string(), created_by: z.string(), stale: z.boolean(),
    lenses_required_missing: z.array(seat), work_orders: z.number().int(),
  }).strict()),
  reconstructions: z.array(VectorReconstructionSchema),
  bindings: z.array(ApprovalBindingSchema.extend({
    selected: z.boolean().optional(), reasons: z.array(z.string()).optional(), genome_status: z.string().optional(),
  })),
  events: z.array(z.object({ op: z.string(), status: z.string(), at: z.string(), duration_ms: z.number().int() }).passthrough()),
}).strict();
export type DirectionState = z.infer<typeof DirectionStateSchema>;

export const DirectionIntentListSchema = z.object({
  intents: z.array(z.object({
    intent_id: id('vdi'), asset_role: DirectionAssetRoleSchema, status: z.enum(['READY', 'BLOCKED_INPUT']), objective: z.string(),
    genome_ref: z.string(),
  }).strict()),
}).strict();
