import { z } from 'zod';

// Mirrors services/langgraph/graph/agency/models.py — keep in sync manually
// until schema generation is wired up (see contract_architecture.json).

export const AgencyPipelineStageSchema = z.enum([
  'brief_intake',
  'brand_strategy',
  'creative_concepting',
  'copywriting',
  'design_brief',
  'campaign_assembly',
  'brand_safety_qa',
  'hitl_gate',
  'delivery',
]);

export const CampaignBriefSchema = z.object({
  brand_name: z.string(),
  industry: z.string().optional(),
  goals: z.array(z.string()).default([]),
  target_audience: z.string(),
  tone: z.string().optional(),
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

export const QAReportSchema = z.object({
  brand_safety_passed: z.boolean(),
  flagged_terms: z.array(z.string()).default([]),
  quality_metrics: z.record(z.unknown()).default({}),
  notes: z.string(),
});

export const CampaignPackageSchema = z.object({
  brief: CampaignBriefSchema,
  strategy: BrandStrategySchema,
  concepts: z.array(CreativeConceptSchema),
  copy_variants: z.array(CopyVariantSchema),
  design_brief: DesignBriefSchema,
  qa_report: QAReportSchema.optional(),
});

export const AgencyRunStatusSchema = z.enum([
  'running',
  'needs_approval',
  'completed',
  'failed',
]);

export const AgencyRunSchema = z.object({
  run_id: z.string().uuid(),
  status: AgencyRunStatusSchema,
  pipeline: z.literal('branding_marketing_agency'),
  stages: z.array(AgencyPipelineStageSchema),
  campaign_package: CampaignPackageSchema.nullable().optional(),
  qa_report: QAReportSchema.nullable().optional(),
  delivery: z
    .object({
      campaign_package: CampaignPackageSchema,
      delivered_at: z.string().datetime(),
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
export type QAReport = z.infer<typeof QAReportSchema>;
export type CampaignPackage = z.infer<typeof CampaignPackageSchema>;
export type AgencyRunStatus = z.infer<typeof AgencyRunStatusSchema>;
export type AgencyRun = z.infer<typeof AgencyRunSchema>;
