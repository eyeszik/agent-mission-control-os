/**
 * Zod twins of the Pydantic request/record models in `agency/compiled/`
 * (Python is the reference). Every schema is strict (`extra="forbid"`), fills
 * Pydantic's field defaults, and returns exactly the shape the planner modules
 * take. Lax coercions Pydantic allows (numeric strings, `"yes"`, a float for an
 * int, ...) are refused; the parity fixture records them.
 *
 * Float fields (`confidence`, `performance_score`) become `PyFloat`, since
 * Pydantic stores `1` as `1.0` and that changes the hashed text.
 */
import { PyFloat } from '@amc/kernel';
import { z } from 'zod';
import { EXTERNAL_ACTIONS, DECISION_KINDS } from './backchain';
import { DECISION_STATUSES } from './decisions';
import { GENOME_EPISTEMICS } from './context';
import {
  CLAIM_LABELS, EVIDENCE_STRENGTHS, RULE_STATUSES, SOURCE_CLASSES, TARGET_LAYERS, VOLATILE_VERIFICATIONS, VOLATILITIES,
} from './evidence';
import { RESULT_STATUSES } from './validation';
import { bounded, pyArray } from './validate';

const strings = z.array(z.string()).default([]);
const text = z.string().nullable().default(null);
const float = z.number().transform((n) => new PyFloat(n));
const optFloat = float.nullable().default(null);
const stringMap = z.record(z.string(), z.string()).default({}).transform((r) => new Map(Object.entries(r)));

export const DeliverableSpecSchema = z.strictObject({
  id: z.string(),
  requested_outcome: z.string(),
  output_contract: z.string(),
  acceptance_criteria: pyArray(z.string(), 1),
  required_approvals: strings,
  constraints: strings,
  priority: z.number().int().nullable().default(null),
  source_refs: strings,
  domains: strings,
  external_action: z.enum(EXTERNAL_ACTIONS).nullable().default(null),
  live_service: z.boolean().default(false),
});

export const EvidenceItemSchema = z.strictObject({
  ref: z.string(), supports: z.array(z.string()), verified: z.boolean().default(false),
});

export const GenomeAssertionSchema = z.strictObject({
  key: z.string(),
  domain: z.string(),
  value_or_ref: z.string(),
  source_refs: strings,
  epistemic_status: z.enum(GENOME_EPISTEMICS).default('UNKNOWN'),
  confidence: optFloat,
  freshness: text,
  sensitivity: z.string().default('internal'),
  owner_ref: text,
  decision_refs: strings,
  artifact_refs: strings,
});

export const DecisionNodeSchema = z.strictObject({
  id: z.string(),
  kind: z.enum(DECISION_KINDS),
  version: z.number().int().default(1),
  question: z.string(),
  alternatives: z.array(z.string()),
  evidence_refs: strings,
  assumptions: strings,
  selected_option: text,
  owner: z.string(),
  required_approver: text,
  approved_by: text,
  affected_nodes: strings,
  status: z.enum(DECISION_STATUSES).default('PROPOSED'),
  confidence: optFloat,
  supersedes: text,
  created_at: text,
});

export const ApprovalScopeSchema = z.strictObject({
  approval_id: z.string(),
  subject_refs: z.array(z.string()),
  subject_hashes: z.array(z.tuple([z.string(), z.string()])),
  dependency_closure_hash: z.string(),
  preview_hash: text,
  policy_version: z.string(),
  reviewer_class: z.string(),
  authenticated_reviewer_ref: z.string().nullable(),
  decision: z.string().nullable(),
  timestamp: text,
});

export const AuthorityGrantSchema = z.strictObject({
  grant_id: z.string(), actor_role_id: z.string(), operation: z.string(), target: z.string(), issued_by: z.string(),
  expires_at: z.string(),
});

export const VolatileConstraintSchema = z.strictObject({
  key: z.string(),
  source_ref: text,
  retrieved_at: text,
  effective_date: text,
  value: text,
  applicability: strings,
  verification_status: z.enum(VOLATILE_VERIFICATIONS).default('UNVERIFIED'),
  expires_or_recheck_at: text,
});

export const ValidationResultSchema = z.strictObject({
  node_id: z.string(),
  obligation: z.string(),
  status: z.enum(RESULT_STATUSES),
  validator_ref: z.string(),
  attempt: z.number().int().default(1),
  failure_fingerprint: text,
});

export const CompiledAgencyRequestSchema = z.strictObject({
  project_id: bounded(1, 200),
  as_of: bounded(10, 40),
  deliverables: pyArray(DeliverableSpecSchema, 1, 50),
  genome: z.array(GenomeAssertionSchema).default([]),
  evidence: z.array(EvidenceItemSchema).default([]),
  existing_artifacts: stringMap,
  decisions: z.array(DecisionNodeSchema).default([]),
  approvals: z.array(ApprovalScopeSchema).default([]),
  grants: z.array(AuthorityGrantSchema).default([]),
  volatile_constraints: z.array(VolatileConstraintSchema).default([]),
  validation_results: z.array(ValidationResultSchema).default([]),
  generation_modes: stringMap,
  provider_status: stringMap,
  artifact_hashes: stringMap,
  policy_version: z.string().default('amc-approval/v1'),
});

export const LearningSignalSchema = z.strictObject({
  id: z.string(),
  tenant_scope: z.string(),
  run_refs: z.array(z.string()),
  observation: z.string(),
  evidence_refs: z.array(z.string()),
  target_heuristic: z.string(),
  confidence: optFloat,
  status: z.enum(['QUARANTINED', 'GOVERNANCE_PROPOSAL', 'REJECTED']).default('QUARANTINED'),
  created_at: text,
  prev_hash: z.string().default('0'.repeat(64)),
  hash: z.string().default(''),
});

export const SourceRecordSchema = z.strictObject({
  id: z.string(), title: z.string(), canonical_ref: z.string(), source_type: z.enum(SOURCE_CLASSES), publisher: z.string(),
  author: text, date: text, domains: strings, stages: strings, departments: strings, artifacts: strings,
  primary: z.boolean().default(false), quality: text, claims: strings, limitations: strings,
});

export const ClaimSchema = z.strictObject({
  id: z.string(), statement: z.string(), label: z.enum(CLAIM_LABELS), source_refs: strings,
});

export const RuleCandidateSchema = z.strictObject({
  id: z.string(),
  statement: z.string(),
  source_refs: strings,
  source_class: z.enum(SOURCE_CLASSES),
  jurisdiction: text,
  domain: strings,
  applicable_context: strings,
  freshness: text,
  recheck_at: text,
  organization_specific: z.boolean().default(false),
  volatility: z.enum(VOLATILITIES).default('STABLE'),
  evidence_strength: z.enum(EVIDENCE_STRENGTHS).default('WEAK'),
  conflicts: strings,
  target_layer: z.enum(TARGET_LAYERS).default('A_INDUSTRY_EVIDENCE'),
  status: z.enum(RULE_STATUSES).default('SOURCE_CLAIM'),
  runtime_ref: text,
});

export const PromotionContextSchema = z.strictObject({
  as_of: z.string(),
  applicability_verified: z.boolean().default(false),
  repository_contract_compatible: z.boolean().nullable().default(null),
  org_policy_approval_ref: text,
  jurisdictions_in_scope: strings,
});

const level = z.enum(['low', 'medium', 'high']);

export const TaskSuitabilitySchema = z.strictObject({
  determinism: level,
  ambiguity: level,
  consequence: level,
  reversible: z.boolean(),
  data_sensitivity: level,
  creative_judgment: level,
  factual_verifiability: level,
  tool_reliability: level,
  evaluation_history: z.number().int().min(0).default(0),
  legal_public_financial_or_client_binding: z.boolean().default(false),
  rights_privacy_security_uncertain: z.boolean().default(false),
  evidence_sufficient: z.boolean().default(true),
  performance_score: optFloat,
  governance_approval_ref: text,
  proven_narrow_scope: z.boolean().default(false),
});
