import { z } from 'zod';
import { ApprovalRequestSchema } from './approvals';

export const AGENCY_PIPELINE_STAGES = [
  'brief_intake',
  'brand_strategy',
  'creative_concepting',
  'copywriting',
  'design_brief',
  'campaign_assembly',
  'brand_safety_qa',
  'hitl_gate',
  'delivery',
] as const;

export const AgencyPipelineStageSchema = z.enum(AGENCY_PIPELINE_STAGES);

export const CampaignBriefSchema = z.object({
  brand_name: z.string(),
  industry: z.string().optional().nullable(),
  goals: z.array(z.string()).default([]),
  target_audience: z.string(),
  tone: z.string().optional().nullable(),
  channels: z.array(z.string()).default([]),
  constraints: z.array(z.string()).default([]),
});

export const BrandStrategySchema = z.object({
  positioning_statement: z.string(),
  brand_pillars: z.array(z.string()),
  tone_of_voice: z.string(),
  target_audience_summary: z.string(),
});

export const CreativeConceptSchema = z.object({
  id: z.string(),
  name: z.string(),
  tagline: z.string(),
  rationale: z.string(),
});

export const CopyVariantSchema = z.object({
  concept_id: z.string(),
  headline: z.string(),
  body: z.string(),
  cta: z.string(),
});

export const DesignBriefSchema = z.object({
  palette: z.array(z.string()),
  typography_direction: z.string(),
  imagery_style: z.string(),
  layout_notes: z.string(),
});

export const QualityMetricsSchema = z.object({
  evaluation_mode: z.literal('heuristic'),
  schema_valid: z.boolean(),
  non_empty: z.boolean(),
  length_chars: z.number().int().nonnegative(),
  length_sufficient: z.boolean(),
  faithfulness: z.literal('NOT_MEASURED'),
  hallucination_rate: z.literal('NOT_MEASURED'),
  tool_selection_accuracy: z.literal('NOT_MEASURED'),
  output_relevance: z.literal('NOT_MEASURED'),
  threshold_passed: z.boolean(),
});

export const QAReportSchema = z.object({
  brand_safety_passed: z.boolean(),
  flagged_terms: z.array(z.string()).default([]),
  quality_metrics: QualityMetricsSchema,
  notes: z.string(),
  release_blocked: z.boolean().default(false),
  degradation_reasons: z.array(z.string()).default([]),
});

export const CampaignPackageSchema = z.object({
  brief: CampaignBriefSchema,
  strategy: BrandStrategySchema,
  concepts: z.array(CreativeConceptSchema),
  copy_variants: z.array(CopyVariantSchema),
  design_brief: DesignBriefSchema,
  qa_report: QAReportSchema.optional(),
});

export const GenerationProvenanceSchema = z.object({
  task: z.string(),
  mode: z.enum(['PROVIDER_SUCCESS', 'FALLBACK_DEGRADED', 'VALIDATION_FAILED', 'PROVIDER_FAILED', 'BLOCKED']),
  provider: z.string().nullable(),
  model: z.string().nullable(),
  schema_version: z.string(),
  prompt_version: z.string(),
  prompt_hash: z.string(),
  attempts: z.number().int().nonnegative(),
  started_at: z.string().datetime({ offset: true }),
  completed_at: z.string().datetime({ offset: true }),
  fallback_used: z.boolean(),
  error_class: z.string().nullable(),
});

export const AgencyRunStatusSchema = z.enum([
  'running',
  'needs_approval',
  'delivering',
  'completed',
  'rejected',
  'failed',
]);

export const DispatchPermitSchema = z.object({
  run_id: z.string().uuid(),
  tenant_id: z.string(),
  project_id: z.string(),
  permit_id: z.string(),
  work_order_id: z.string(),
  project_snapshot_hash: z.string().regex(/^[a-f0-9]{64}$/),
  causal_epoch: z.number().int().nonnegative(),
  dependency_version_refs: z.array(z.string()).default([]),
  authority_refs: z.array(z.string()).default([]),
  approval_refs: z.array(z.string()).default([]),
  tool_contract_refs: z.array(z.string()).default([]),
  eligibility_policy_version: z.string(),
  issued_at: z.string().datetime({ offset: true }),
});

export const ExecutionReceiptSchema = z.object({
  run_id: z.string().uuid(),
  tenant_id: z.string(),
  project_id: z.string(),
  operation_id: z.string(),
  work_order_id: z.string(),
  actor_role_id: z.string(),
  tool: z.string(),
  tool_contract_ref: z.string(),
  args_hash: z.string().regex(/^[a-f0-9]{64}$/),
  target: z.string(),
  idempotency_key: z.string(),
  attempt: z.number().int().min(1).max(3),
  started_at: z.string().datetime({ offset: true }),
  ended_at: z.string().datetime({ offset: true }),
  returned_state: z.string(),
  result_ref: z.string().nullable().optional(),
});

export const ObservationReceiptSchema = z.object({
  run_id: z.string().uuid(),
  tenant_id: z.string(),
  project_id: z.string(),
  operation_id: z.string(),
  target: z.string(),
  expected_postcondition: z.record(z.unknown()),
  observed_postcondition: z.record(z.unknown()),
  observation_method: z.string(),
  evidence_refs: z.array(z.string()).default([]),
  observed_at: z.string().datetime({ offset: true }),
  matches: z.boolean(),
});

export const FailureFingerprintSchema = z.object({
  run_id: z.string().uuid(),
  tenant_id: z.string(),
  project_id: z.string(),
  operation_id: z.string(),
  fingerprint: z.string().regex(/^[a-f0-9]{64}$/),
  failure_class: z.string(),
  causal_node: z.string(),
  work_order_input_hash: z.string().regex(/^[a-f0-9]{64}$/),
  dependency_snapshot_hash: z.string().regex(/^[a-f0-9]{64}$/),
  tool_contract_hash: z.string().regex(/^[a-f0-9]{64}$/),
  environment_signature: z.string(),
  error_class: z.string(),
  error_code: z.string().nullable().optional(),
  observed_postcondition: z.unknown().optional(),
});

export const CompletionCriterionResultSchema = z.object({
  criterion_ref: z.string(),
  status: z.enum(['SATISFIED', 'UNSATISFIED', 'STALE', 'BLOCKED', 'NOT_APPLICABLE']),
  missing_refs: z.array(z.string()).default([]),
  stale_refs: z.array(z.string()).default([]),
});

export const CompletionEvaluationSchema = z.object({
  terminal_candidate: z.enum(['COMPLETE', 'BLOCKED']),
  criteria: z.array(CompletionCriterionResultSchema),
  proof_coverage: z.number().min(0).max(1),
  evidence_score: z.number().min(0).max(1),
  quality_score: z.number().min(0).max(1),
  confidence: z.number().min(0).max(1),
});

export const ProofSummarySchema = z.object({
  dispatch_count: z.number().int().nonnegative(),
  execution_count: z.number().int().nonnegative(),
  observation_count: z.number().int().nonnegative(),
  matched_observation_count: z.number().int().nonnegative(),
  failure_count: z.number().int().nonnegative(),
  latest_terminal_candidate: z.enum(['COMPLETE', 'BLOCKED']).nullable().optional(),
  latest_confidence: z.number().min(0).max(1).nullable().optional(),
});

export const RunProofSchema = z.object({
  dispatch_permits: z.array(DispatchPermitSchema),
  execution_receipts: z.array(ExecutionReceiptSchema),
  observation_receipts: z.array(ObservationReceiptSchema),
  failure_fingerprints: z.array(FailureFingerprintSchema),
  completion_evaluation: CompletionEvaluationSchema.nullable().optional(),
  summary: ProofSummarySchema,
});

export const AgencyRunSchema = z.object({
  run_id: z.string().uuid(),
  project_id: z.string().optional(),
  status: AgencyRunStatusSchema,
  pipeline: z.literal('branding_marketing_agency').optional(),
  stages: z.array(AgencyPipelineStageSchema).optional(),
  pending_next_node: z.array(z.string()).optional(),
  campaign_package: CampaignPackageSchema.nullable().optional(),
  qa_report: QAReportSchema.nullable().optional(),
  pending_approval: ApprovalRequestSchema.nullable().optional(),
  approvals: z.array(ApprovalRequestSchema).optional(),
  degraded: z.boolean().optional(),
  generation_provenance: z.array(GenerationProvenanceSchema).optional(),
  delivery: z
    .object({
      campaign_package: CampaignPackageSchema,
      delivered_at: z.string().datetime({ offset: true }),
      approval_id: z.string().uuid().nullable(),
      format: z.literal('json_bundle_v1'),
    })
    .nullable()
    .optional(),
  proof: RunProofSchema.optional(),
});

export type AgencyPipelineStage = z.infer<typeof AgencyPipelineStageSchema>;
export type CampaignBrief = z.infer<typeof CampaignBriefSchema>;
export type BrandStrategy = z.infer<typeof BrandStrategySchema>;
export type CreativeConcept = z.infer<typeof CreativeConceptSchema>;
export type CopyVariant = z.infer<typeof CopyVariantSchema>;
export type DesignBrief = z.infer<typeof DesignBriefSchema>;
export type QAReport = z.infer<typeof QAReportSchema>;
export type CampaignPackage = z.infer<typeof CampaignPackageSchema>;
export type GenerationProvenance = z.infer<typeof GenerationProvenanceSchema>;
export type AgencyRunStatus = z.infer<typeof AgencyRunStatusSchema>;
export type AgencyRun = z.infer<typeof AgencyRunSchema>;
export type RunProof = z.infer<typeof RunProofSchema>;
