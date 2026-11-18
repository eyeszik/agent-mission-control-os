/**
 * Twin of `agency/compiled/method_models.py`: strict models for method routing
 * and delegation. The method layer is a deterministic decision/delegation
 * compiler; nothing here grants authority. Every envelope carries empty
 * authority and approval refs, and routing scores never feed permission.
 *
 * Input models (`ObjectiveRequest`, `FamilySpec`, `MethodSpec`) are Zod schemas
 * that reproduce Pydantic's strict-extra, bounds and enum checks. Output
 * models are plain records with Python's field names; floats are `PyFloat`.
 */
import { PyFloat } from '@amc/kernel';
import { z } from 'zod';
import { bounded, pyArray } from './validate';

export const POLICY_VERSION = 'amc-method-policy/v1';
export const PLAN_VERSION = 'amc-method-plan/v1';

export const MAX_ROUTER_PASSES = 3;
export const MAX_RETRIEVAL_PASSES = 5;
export const MAX_TASK_RETRIES = 3;
export const MAX_PLAN_REPAIRS = 3;
export const MAX_DELEGATION_DEPTH = 4;
export const MAX_SPECIALISTS_PER_WAVE = 8;
export const MAX_TOOL_CALLS_PER_NODE = 12;
export const MAX_SHADOW_STACKS = 2;

export const SLOTS = ['MACRO', 'DIAGNOSE', 'DECIDE', 'EXECUTE', 'CONTROL', 'LEARN'] as const;
export type Slot = (typeof SLOTS)[number];
export const SLOT_ORDER: readonly Slot[] = SLOTS;

const slot = z.enum(SLOTS);
const triState = z.boolean().nullable().default(null);
const level = z.enum(['low', 'medium', 'high', 'unknown']).default('unknown');
const strings = z.array(z.string()).default([]);

export const ObjectiveRequestSchema = z.strictObject({
  objective: bounded(1, 2000),
  desired_outcome: bounded(0, 2000).default(''),
  domains: strings,
  constraints: strings,
  non_goals: strings,
  items_to_rank: pyArray(z.string(), 0, 500).default([]),
  options: pyArray(z.string(), 0, 50).default([]),
  current_state_known: triState,
  target_state_known: triState,
  process_exists: triState,
  root_cause_known: triState,
  solution_known: triState,
  measurement_available: triState,
  problem_recurs: triState,
  variation_observed: triState,
  waste_observed: triState,
  throughput_constrained: triState,
  customer_needs_unknown: triState,
  deliverable_scope_defined: triState,
  strategic_question: triState,
  strategy_needs_alignment: triState,
  decision_rights_unclear: triState,
  change_adoption_required: triState,
  feedback_loops_suspected: triState,
  live_service: triState,
  incidents_recurring: triState,
  lessons_to_capture: triState,
  uncertainty: level,
  reversibility: z.enum(['reversible', 'partially_reversible', 'irreversible', 'unknown']).default('unknown'),
  consequence: z.enum(['low', 'medium', 'high', 'critical', 'unknown']).default('unknown'),
  externality: z.enum(['internal', 'external', 'unknown']).default('unknown'),
  data_sensitivity: z.enum(['public', 'internal', 'confidential', 'regulated', 'unknown']).default('unknown'),
  system_coupling: level,
  time_pressure: level,
  evidence_status: z.enum(['verified', 'partial', 'unverified', 'conflicting', 'unknown']).default('unknown'),
});
export type ObjectiveRequest = z.output<typeof ObjectiveRequestSchema>;

export const FamilySpecSchema = z.strictObject({
  family_id: z.string(),
  name: z.string(),
  capability_terms: pyArray(z.string(), 1),
  phase_id: z.string(),
  needs: z.record(z.string(), slot),
  signals: pyArray(z.string(), 1),
  lexical_cues: strings,
});
export type FamilySpec = z.output<typeof FamilySpecSchema>;

export const MethodSpecSchema = z.strictObject({
  method_id: z.string(),
  name: z.string(),
  family: z.string(),
  secondary_families: strings,
  slot,
  aliases: strings,
  purpose: z.string(),
  applicability_predicates: strings,
  contraindications: strings,
  expected_inputs: strings,
  expected_outputs: pyArray(z.string(), 1),
  evidence_needs: strings,
  composable_with: strings,
  conflicts_with: strings,
  effort: z.number().int().min(1).max(5),
  source_refs: strings,
  provenance_status: z.enum(['DESCRIPTION_UNVERIFIED', 'SOURCE_CITED']),
}).refine((m) => m.provenance_status !== 'SOURCE_CITED' || m.source_refs.length > 0, {
  message: 'SOURCE_CITED requires source_refs',
});
export type MethodSpec = z.output<typeof MethodSpecSchema>;

type Tri = boolean | null;
type Lvl = 'low' | 'medium' | 'high' | 'unknown';

export interface ProblemSignature {
  readonly objective: string;
  readonly desired_outcome: string;
  readonly problem_families: readonly string[];
  readonly domains: readonly string[];
  readonly current_state_known: Tri;
  readonly target_state_known: Tri;
  readonly process_exists: Tri;
  readonly root_cause_known: Tri;
  readonly solution_known: Tri;
  readonly measurement_available: Tri;
  readonly uncertainty: Lvl;
  readonly reversibility: string;
  readonly consequence: string;
  readonly externality: string;
  readonly data_sensitivity: string;
  readonly system_coupling: Lvl;
  readonly time_pressure: Lvl;
  readonly change_adoption_required: Tri;
  readonly evidence_status: string;
  readonly constraints: readonly string[];
  readonly non_goals: readonly string[];
  readonly observations: readonly string[];
}

export interface MinimalityCertificate {
  readonly method_id: string;
  readonly necessary_for: readonly string[];
  readonly downstream_effect_if_removed: string;
  readonly redundant: false;
}

export interface ExcludedMethod {
  readonly method_id: string;
  readonly reason: string;
}

export interface ShadowDuel {
  readonly candidates: readonly [string, string];
  readonly winner: string;
  readonly rule: string;
}

export interface MethodStack {
  readonly macro_methodologies: readonly string[];
  readonly diagnostic_methods: readonly string[];
  readonly decision_methods: readonly string[];
  readonly execution_methods: readonly string[];
  readonly control_methods: readonly string[];
  readonly learning_methods: readonly string[];
  readonly excluded_methods: readonly ExcludedMethod[];
  readonly source_refs: readonly string[];
  readonly selection_confidence: PyFloat;
  readonly stack_hash: string;
}

export function stackSelected(stack: MethodStack): string[] {
  return [
    ...stack.macro_methodologies, ...stack.diagnostic_methods, ...stack.decision_methods, ...stack.execution_methods,
    ...stack.control_methods, ...stack.learning_methods,
  ];
}

export type SideEffectClass = 'PURE' | 'DRAFT' | 'REVERSIBLE_WRITE' | 'IRREVERSIBLE_WRITE';

export interface DelegationEnvelope {
  readonly node_id: string;
  readonly objective: string;
  readonly problem_family: string;
  readonly method_refs: readonly string[];
  readonly dependencies: readonly string[];
  readonly required_capabilities: readonly string[];
  readonly inputs: readonly string[];
  readonly expected_outputs: readonly string[];
  readonly acceptance_criteria: readonly string[];
  readonly evidence_requirements: readonly string[];
  readonly tool_plan: readonly string[];
  readonly side_effect_class: SideEffectClass;
  readonly risk_level: 'low' | 'medium' | 'high' | 'critical';
  readonly authority_refs: readonly string[];
  readonly approval_refs: readonly string[];
  readonly idempotency_class: SideEffectClass;
  readonly retry_limit: number;
  readonly stop_conditions: readonly string[];
  readonly completion_proof: readonly string[];
  readonly slot: Slot;
  readonly justified_by: readonly string[];
  readonly delegation_depth: number;
  readonly mutation_targets: readonly string[];
  readonly context_hash: string;
}

export interface HumanGate {
  readonly gate_id: string;
  readonly node_id: string | null;
  readonly kind: 'EXECUTION_AUTHORITY' | 'MATERIAL_DECISION' | 'CLARIFICATION';
  readonly requires: readonly string[];
  readonly separation_of_duties: boolean;
  readonly enforced_by: string;
}

export interface FamilyEvidence {
  readonly family_id: string;
  readonly structural_signals: readonly string[];
  readonly lexical_cues: readonly string[];
  readonly selected: boolean;
}

export interface MethodPlan {
  readonly version: 'amc-method-plan/v1';
  readonly policy_version: string;
  readonly catalog_hash: string;
  readonly request_hash: string;
  readonly problem_signature: ProblemSignature;
  readonly classification: readonly FamilyEvidence[];
  readonly method_stack: MethodStack;
  readonly minimality_certificates: readonly MinimalityCertificate[];
  readonly shadow_duels: readonly ShadowDuel[];
  readonly delegation_envelopes: readonly DelegationEnvelope[];
  readonly human_gates: readonly HumanGate[];
  readonly unresolved: readonly string[];
  readonly plan_hash: string;
}
