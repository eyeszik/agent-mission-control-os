import { z } from 'zod';

// Wire twins of agency/innovation/contracts.py. Simulation grants no authority.
const text = z.string();
const hash = z.string();
export const InnovationBriefSchema = z.object({
  objective: text.min(10).max(4000).refine((v) => v.trim().length >= 10),
  mode: z.enum(['AUTO', 'GENERAL', 'VENTURE', 'HYBRID']).default('AUTO'),
  provider: z.enum(['simulated', 'live']).default('simulated'),
  constraints: z.array(text.trim().min(1).max(300)).max(20).default([]),
}).strict();
const CommercialSchema = z.object({ buyer: text, purchased_outcome: text, payment_model: text, differentiation_hypothesis: text }).strict();
export const InnovationConceptSchema = z.object({
  concept_id: text, generation: z.enum(['raw', 'hybrid', 'meta']), title: text, mechanism: text,
  lens_tags: z.array(text).min(1).max(12), assumptions: z.array(text), speculative: z.literal(true).default(true),
  provenance: z.literal('SIMULATED_OFFLINE_FIXTURE').default('SIMULATED_OFFLINE_FIXTURE'),
  parent_ids: z.array(text).max(5).default([]), commercial_fields: CommercialSchema.nullable().default(null),
  version: z.literal(1).default(1), content_hash: hash,
}).strict();
const WildcardSchema = z.object({ concept_id: text, broken_assumption: text, mechanism: text, insight: text }).strict();
const EdgeSchema = z.object({ parent_id: text, child_id: text, source_version: z.literal(1).default(1), transformation: z.enum(['FIRST_ORDER_SYNTHESIS', 'SECOND_ORDER_SYNTHESIS']), rationale: text }).strict();
const EvaluationSchema = z.object({ concept_id: text, rubric_version: z.enum(['GENERAL/v1', 'VENTURE/v1']), criterion_scores: z.record(text, z.number()), composite: z.number().min(0).max(5), evidence_status: z.literal('SIMULATED').default('SIMULATED'), reviewer_notes: text }).strict();
const ExperimentSchema = z.object({
  experiment_id: text, concept_id: text, hypothesis: text, assumptions: z.array(text), falsification_criteria: text,
  method: text, measurements: z.array(text).min(1), success_rule: text, stop_conditions: z.array(text).min(1), required_integrations: z.array(text),
  execution_class: z.literal('RETRY_SAFE').default('RETRY_SAFE'), execution_state: z.literal('NOT_RUN').default('NOT_RUN'),
  approval_state: z.literal('NOT_REQUESTED').default('NOT_REQUESTED'), resource_budget: z.record(text, z.number().int()),
  evidence_refs: z.array(text).max(0).default([]), decision: z.null().default(null), learning: z.null().default(null), version: z.literal(1).default(1), content_hash: hash,
}).strict();
export const InnovationRunSchema = z.object({
  run_id: text, objective: text, mode: z.enum(['GENERAL', 'VENTURE', 'HYBRID']),
  status: z.enum(['COMPLETED', 'BLOCKED', 'CANCELLED', 'PAUSED', 'RECEIVED']), phase: z.enum(['RECEIVED', 'PAUSED', 'CANCELLED', 'PROVIDER_GAP', 'RETRY_EXHAUSTED', 'COMPLETED']), simulation: z.boolean(),
  prompt_version: z.literal('unbound-h02/simulation-v1').default('unbound-h02/simulation-v1'),
  ideas: z.array(InnovationConceptSchema).max(35).default([]), wildcards: z.array(WildcardSchema).max(5).default([]),
  hybrids: z.array(InnovationConceptSchema).max(4).default([]), meta_hybrids: z.array(InnovationConceptSchema).max(2).default([]),
  lineage: z.array(EdgeSchema).max(30).default([]), shortlist: z.array(text).max(5).default([]),
  evaluations: z.array(EvaluationSchema).max(41).default([]), experiments: z.array(ExperimentSchema).max(5).default([]),
  evidence: z.array(z.record(text, z.unknown())).max(0).default([]), limitations: z.array(text), usage: z.null().default(null),
}).strict().refine((run) => run.status === 'BLOCKED'
  ? ['PROVIDER_GAP', 'RETRY_EXHAUSTED'].includes(run.phase)
  : run.phase === run.status, { message: 'status and phase disagree', path: ['phase'] });
export const InnovationDetailSchema = z.object({ run: InnovationRunSchema, version: z.number().int().positive(), artifact_id: text, content_hash: hash }).strict();
export const InnovationListSchema = z.object({
  runs: z.array(z.object({ run_id: text, version: z.number().int().positive(), status: text, phase: text, objective: text, simulation: z.boolean() }).strict()),
  total: z.number().int().nonnegative(),
}).strict();
export type InnovationBrief = z.infer<typeof InnovationBriefSchema>;
export type InnovationDetail = z.infer<typeof InnovationDetailSchema>;
export type InnovationRun = z.infer<typeof InnovationRunSchema>;
export type InnovationConcept = z.infer<typeof InnovationConceptSchema>;
export type InnovationList = z.infer<typeof InnovationListSchema>;
