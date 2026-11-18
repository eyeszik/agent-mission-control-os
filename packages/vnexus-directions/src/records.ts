/**
 * Typed records for the creative-direction pipeline (`directions/records.py`; PROPOSED definitions, the original
 * board spec was not supplied). Records are plain snake_case data so serialized shapes match Python and the Zod twins
 * in `@amc/shared` (`vnexusDirections.ts`). Nothing here is authority: the approved genome is, and approvals are
 * decided only on `/approvals/{id}/decide`.
 */
import { canonicalHash, type PyValue } from '@amc/vnexus-brandbook';

export const SCHEMA = 'amc-vnexus-directions/v1';
export const RUBRIC_VERSION = 'amc-vnexus-review-rubric/1.0.0';
export const INTENT_COMPILER_VERSION = 'amc-vnexus-intent/1.0.0';
export const NONE = '@none';

export const ASSET_ROLES = ['LOGO_MARK', 'WORDMARK', 'LOCKUP', 'ICON', 'ILLUSTRATION', 'HERO_IMAGE', 'PHOTOGRAPHY', 'TEXTURE'] as const;
export type AssetRole = (typeof ASSET_ROLES)[number];
export const VECTOR_REQUIRED: ReadonlySet<AssetRole> = new Set<AssetRole>(['LOGO_MARK', 'WORDMARK', 'LOCKUP', 'ICON']);
export const RASTER_NATIVE: ReadonlySet<AssetRole> = new Set<AssetRole>(['PHOTOGRAPHY', 'TEXTURE']);
export const LOGO_ROLES: ReadonlySet<AssetRole> = new Set<AssetRole>(['LOGO_MARK', 'WORDMARK', 'LOCKUP']);

export type VectorNeed = 'REQUIRED' | 'OPTIONAL' | 'KEEP_RASTER';

export function vectorNeed(role: AssetRole): VectorNeed {
  if (VECTOR_REQUIRED.has(role)) return 'REQUIRED';
  return RASTER_NATIVE.has(role) ? 'KEEP_RASTER' : 'OPTIONAL';
}

export const EVIDENCE_CLASSES = ['OBSERVED', 'INFERRED', 'PROPOSED', 'UNKNOWN'] as const;
export type EvidenceClass = (typeof EVIDENCE_CLASSES)[number];
export const EVIDENCE_SOURCES = ['PIXELS', 'GEOMETRY', 'SUPPLIED_SOURCE', 'BRIEF', 'NONE'] as const;
export type EvidenceSource = (typeof EVIDENCE_SOURCES)[number];
export const PROVENANCE_CLASSES = ['RECORDED', 'USER_REPORTED', 'SIMULATED'] as const;
export type ProvenanceClass = (typeof PROVENANCE_CLASSES)[number];
export const SEVERITIES = ['BLOCKER', 'MAJOR', 'MINOR', 'NOTE'] as const;
export type Severity = (typeof SEVERITIES)[number];
export const REVIEW_MODES = ['QUICK', 'FULL', 'COMPARE', 'REFINE', 'VECTOR', 'RELEASE'] as const;
export type ReviewMode = (typeof REVIEW_MODES)[number];
export const VERDICTS = ['BLOCKED', 'REVISE', 'RECOMMENDED_DIRECTION', 'READY_FOR_APPROVAL', 'INCONCLUSIVE'] as const;
export type Verdict = (typeof VERDICTS)[number];
export const GATES = ['EXACT_IDENTITY_TEXT', 'ACCESSIBILITY', 'SAFETY_PRIVACY_RIGHTS', 'CANONICAL_INTEGRITY', 'OUTPUT_PROVENANCE'] as const;
export type Gate = (typeof GATES)[number];
export const GATE_STATUSES = ['PASS', 'FAIL', 'UNKNOWN', 'NOT_APPLICABLE'] as const;
export type GateStatus = (typeof GATE_STATUSES)[number];
export const ASSESSOR_KINDS = ['LOCAL_MEASUREMENT', 'HUMAN', 'MODEL'] as const;
export type AssessorKind = (typeof ASSESSOR_KINDS)[number];

export interface Assessor {
  readonly kind: AssessorKind;
  readonly id: string;
  readonly version: string | null;
}

export interface ReferenceIn {
  readonly ref_id: string;
  readonly role: 'principle_only' | 'approved_asset';
  readonly rights: 'owned' | 'licensed' | 'unknown';
}

/** `None` is a gap (UNKNOWN); `"@none"` is an intentional NONE decision. */
export type Decided = string | null;
export type DecidedList = '@none' | readonly string[] | null;

export interface DirectionBrief {
  readonly asset_role: AssetRole;
  readonly objective: string;
  readonly audience: Decided;
  readonly category: Decided;
  readonly exact_text: DecidedList;
  readonly references: readonly ReferenceIn[];
  readonly rights_constraints: Decided;
  readonly privacy_constraints: Decided;
  readonly applications: DecidedList;
  readonly emotional_targets: readonly string[];
  readonly directions: readonly string[];
  readonly candidate_count: number;
  readonly budget_minor: number;
  readonly width: number;
  readonly height: number;
}

export interface FieldDecision {
  readonly field: string;
  readonly status: 'VALUE' | 'NONE' | 'UNKNOWN';
  readonly consequence: string;
}

export interface SlotInstruction {
  readonly slot: number;
  readonly direction: string;
  readonly prompt: string;
  readonly negative_prompt: string;
  readonly parameters: { readonly [key: string]: PyValue };
  readonly prompt_hash: string;
  readonly compose_mark: string | null;
}

export interface VectorInstructions {
  readonly need: VectorNeed;
  readonly palette_roles: { readonly [role: string]: string };
  readonly fills: string;
  readonly exact_text: readonly string[];
  readonly exact_text_rule: string;
  readonly approved_faces: { readonly display: PyValue; readonly body: PyValue };
  readonly geometry: readonly string[];
  readonly minimum_sizes: readonly string[];
  readonly protected: readonly string[];
}

export interface CreativeIntent {
  readonly schema_version: string;
  readonly compiler_version: string;
  readonly intent_id: string;
  readonly tenant_id: string;
  readonly project_id: string;
  readonly brand_id: string;
  readonly scope: string;
  readonly scope_ref: string;
  readonly genome_ref: string;
  readonly resolution_hash: string;
  readonly asset_role: AssetRole;
  readonly vector_need: VectorNeed;
  readonly brief: DirectionBrief;
  readonly brief_hash: string;
  readonly field_decisions: readonly FieldDecision[];
  readonly prohibited: readonly string[];
  readonly status: 'READY' | 'BLOCKED_INPUT';
  readonly blockers: readonly string[];
  readonly shared: { readonly [key: string]: PyValue };
  readonly prompt_compiler: { readonly [key: string]: PyValue };
  readonly image_instructions: readonly SlotInstruction[];
  readonly vector_instructions: VectorInstructions;
  readonly dependency_hash: string;
}

export interface CandidateObserved {
  readonly sha256: string;
  readonly readback_sha256: string;
  readonly mime: string;
  readonly bytes: number;
  readonly width: number | null;
  readonly height: number | null;
  readonly stored_at: string;
  readonly artifact_id: string | null;
  readonly artifact_version: number | null;
  readonly storage_uri: string | null;
  readonly format_class: 'VECTOR' | 'RASTER_IN_SVG' | 'RASTER';
}

export interface CandidateReported {
  readonly provider: string | null;
  readonly model: string | null;
  readonly model_version: string | null;
  readonly seed: number | null;
  readonly parameters: { readonly [key: string]: PyValue };
  readonly generated_at: string | null;
  readonly job_ref: string | null;
  readonly receipt_ref: string | null;
  readonly cost_minor: number | null;
  readonly currency: string | null;
  readonly rights_basis: string | null;
  readonly reference_ids: readonly string[];
  readonly prompt_used: string | null;
}

export interface GenerationCandidate {
  readonly candidate_id: string;
  readonly intent_id: string;
  readonly slot: number;
  readonly direction: string;
  readonly prompt_hash: string;
  readonly genome_ref: string;
  readonly intent_dependency_hash: string;
  readonly route_id: string;
  readonly provenance: ProvenanceClass;
  readonly observed: CandidateObserved;
  readonly reported: CandidateReported;
  readonly cost_measured_minor: number | null;
  readonly near_duplicate_of: string | null;
  readonly derived_from: string | null;
  readonly reconstruction_id: string | null;
  readonly perceptual_hash: string | null;
  readonly created_by: string;
  readonly created_at: string;
}

/** A reviewer-supplied finding. `candidate` is the blinded label (COMPARE) or candidate id. */
export interface FindingIn {
  readonly candidate: string;
  readonly criterion: string;
  readonly seat: string;
  readonly region_or_element: string;
  readonly evidence_class: EvidenceClass;
  readonly evidence_source: EvidenceSource;
  readonly observation: string;
  readonly severity: Severity;
  readonly rationale: string;
  readonly proposed_change: string | null;
  readonly acceptance_check: string | null;
  readonly uncertainty: string;
  readonly score: number | null;
  readonly gate: Gate | null;
  readonly gate_status: 'PASS' | 'FAIL' | null;
  readonly trait: string | null;
  readonly cue: string | null;
}

export interface ReviewFinding {
  readonly finding_id: string;
  readonly candidate_id: string;
  readonly criterion: string;
  readonly seat: string;
  readonly asset_hash: string;
  readonly region_or_element: string;
  readonly evidence_class: EvidenceClass;
  readonly evidence_source: EvidenceSource;
  readonly observation: string;
  readonly severity: Severity;
  readonly rationale: string;
  readonly proposed_change: string | null;
  readonly acceptance_check: string | null;
  readonly uncertainty: string;
  readonly actionable: boolean;
  readonly assessor: Assessor;
  readonly measurement: { readonly [key: string]: PyValue } | null;
}

export interface CriterionAssessment {
  readonly candidate_id: string;
  readonly criterion: string;
  readonly seat: string;
  readonly score: number | null;
  readonly status: 'ASSESSED' | 'NOT_REVIEWED' | 'NOT_APPLICABLE';
  readonly reason: string;
  readonly finding_ids: readonly string[];
  readonly assessors: readonly Assessor[];
}

export interface GateResult {
  readonly candidate_id: string;
  readonly gate: Gate;
  readonly status: GateStatus;
  readonly evidence: string;
  readonly evidence_class: EvidenceClass;
  readonly finding_ids: readonly string[];
}

export const WORK_ORDER_EXECUTION = 'a separate authorized generation/import or reconstruction must act on this; it rechecks identity, '
  + 'permissions, budget and current versions. Changes outside approved rules go to genome review.';

export interface RevisionWorkOrder {
  readonly work_order_id: string;
  readonly candidate_id: string;
  readonly asset_hash: string;
  readonly change: string;
  readonly why: string;
  readonly protected_invariants: readonly string[];
  readonly dependencies: { readonly [key: string]: PyValue };
  readonly verification: string;
  readonly finding_ids: readonly string[];
  readonly authority: 'PROPOSAL_ONLY';
  readonly execution: string;
}

export const RECOMMENDATION_NOTE = 'a recommendation is not an approval; human selection uses the existing approval route';

export interface DirectionRecommendation {
  readonly verdict: Verdict;
  readonly candidate_id: string | null;
  readonly label: string | null;
  readonly reasons: readonly string[];
  readonly aggregate: { readonly [key: string]: PyValue } | null;
  readonly note: string;
}

export interface CandidateOutcome {
  readonly candidate_id: string;
  readonly label: string;
  readonly asset_hash: string;
  readonly verdict: Verdict;
  readonly reasons: readonly string[];
}

export const CORRELATION_NOTE = 'seats sharing one assessor are correlated perspectives, not independent corroboration; '
  + 'local measurements are not creative judgments';

export interface ReviewSession {
  readonly schema_version: string;
  readonly rubric_version: string;
  readonly session_id: string;
  readonly intent_id: string;
  readonly tenant_id: string;
  readonly project_id: string;
  readonly brand_id: string;
  readonly genome_ref: string;
  readonly mode: ReviewMode;
  readonly blinded: boolean;
  readonly labels: { readonly [label: string]: string };
  readonly candidates: { readonly [candidateId: string]: string };
  readonly lenses_active: readonly string[];
  readonly lenses_required_missing: readonly string[];
  readonly routes: { readonly [routeId: string]: string };
  readonly findings: readonly ReviewFinding[];
  readonly assessments: readonly CriterionAssessment[];
  readonly gates: readonly GateResult[];
  readonly outcomes: readonly CandidateOutcome[];
  readonly recommendation: DirectionRecommendation;
  readonly work_orders: readonly RevisionWorkOrder[];
  readonly emotional_map: { readonly [key: string]: PyValue };
  readonly brand_memory: { readonly [key: string]: PyValue };
  readonly regressions: ReadonlyArray<{ readonly [key: string]: PyValue }>;
  readonly measurements: { readonly [candidateId: string]: { readonly [key: string]: PyValue } };
  readonly base_session_id: string | null;
  readonly correlation_note: string;
  readonly effects: { readonly regenerated: false; readonly spent: false; readonly approved: false; readonly mutated_master: false;
    readonly published: false };
  readonly created_by: string;
  readonly created_at: string;
}

export function recordId(prefix: string, payload: unknown): string {
  return `${prefix}-${canonicalHash(payload).slice(0, 16)}`;
}
