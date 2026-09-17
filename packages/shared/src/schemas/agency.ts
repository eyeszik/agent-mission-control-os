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

export const BrandComplianceViolationSchema = z.object({
  pattern_id: z.string(),
  matched_text: z.string(),
  description: z.string(),
});

export const BrandComplianceReadabilitySchema = z.object({
  flesch_kincaid_grade: z.union([z.number(), z.literal('NOT_MEASURED')]),
  within_target_band: z.union([z.boolean(), z.literal('NOT_MEASURED')]),
  target_grade_min: z.number(),
  target_grade_max: z.number(),
});

export const BrandComplianceSentimentSchema = z.object({
  compound: z.union([z.number(), z.literal('NOT_MEASURED')]),
  within_target_band: z.union([z.boolean(), z.literal('NOT_MEASURED')]),
  target_min: z.number(),
  target_max: z.number(),
});

export const BrandComplianceSchema = z.object({
  engine_version: z.string(),
  passed: z.boolean(),
  flagged_terms: z.array(z.string()).default([]),
  violations: z.array(BrandComplianceViolationSchema).default([]),
  missing_disclaimers: z.array(z.string()).default([]),
  readability: BrandComplianceReadabilitySchema,
  sentiment: BrandComplianceSentimentSchema,
  advisories: z.array(z.string()).default([]),
});

export const QAReportSchema = z.object({
  brand_safety_passed: z.boolean(),
  flagged_terms: z.array(z.string()).default([]),
  quality_metrics: QualityMetricsSchema,
  brand_compliance: BrandComplianceSchema.partial().default({}),
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

export const AgencyRunSchema = z.object({
  run_id: z.string().uuid(),
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
});

export type AgencyPipelineStage = z.infer<typeof AgencyPipelineStageSchema>;
export type CampaignBrief = z.infer<typeof CampaignBriefSchema>;
export type BrandStrategy = z.infer<typeof BrandStrategySchema>;
export type CreativeConcept = z.infer<typeof CreativeConceptSchema>;
export type CopyVariant = z.infer<typeof CopyVariantSchema>;
export type DesignBrief = z.infer<typeof DesignBriefSchema>;
export type BrandCompliance = z.infer<typeof BrandComplianceSchema>;
export type QAReport = z.infer<typeof QAReportSchema>;
export type CampaignPackage = z.infer<typeof CampaignPackageSchema>;
export type GenerationProvenance = z.infer<typeof GenerationProvenanceSchema>;
export type AgencyRunStatus = z.infer<typeof AgencyRunStatusSchema>;
export type AgencyRun = z.infer<typeof AgencyRunSchema>;
