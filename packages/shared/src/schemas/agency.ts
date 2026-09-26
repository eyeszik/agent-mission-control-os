import { z } from 'zod';
import { ApprovalRequestSchema } from './approvals';
import { DesignStyleDirectionSchema, DesignStyleSelectionSchema } from './styleLibrary';

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
  business_idea: z.string().optional().nullable(),
  offer_summary: z.string().optional().nullable(),
  product_type: z.string().optional().nullable(),
  goals: z.array(z.string()).default([]),
  target_audience: z.string(),
  tone: z.string().optional().nullable(),
  channels: z.array(z.string()).default([]),
  constraints: z.array(z.string()).default([]),
  business_model: z.string().optional().nullable(),
  affiliate_model: z.boolean().optional().nullable(),
  workflow_idea: z.string().optional().nullable(),
  differentiators: z.array(z.string()).default([]),
  brand_style_notes: z.array(z.string()).default([]),
  // Design Mode selection; the backend recomposes it against the catalog.
  style_selection: DesignStyleSelectionSchema.optional().nullable(),
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
  // The resolved style direction that shaped this brief (artifact lineage).
  style_direction: DesignStyleDirectionSchema.optional().nullable(),
});

export const WorkspaceDocumentSchema = z.object({
  path: z.string(),
  title: z.string(),
  kind: z.string(),
  body: z.string(),
  metadata: z.record(z.unknown()).default({}),
});

export const BusinessWorkspaceSchema = z.object({
  overview: z.record(z.unknown()).default({}),
  internal_docs: z.array(WorkspaceDocumentSchema).default([]),
  production_docs: z.array(WorkspaceDocumentSchema).default([]),
  prompt_library: z.array(WorkspaceDocumentSchema).default([]),
});

export const BrandingWorkspaceSchema = z.object({
  raw_brand_data: z.record(z.unknown()).default({}),
  internal_assets: z.array(WorkspaceDocumentSchema).default([]),
  external_assets: z.array(WorkspaceDocumentSchema).default([]),
  visual_asset_prompts: z.array(WorkspaceDocumentSchema).default([]),
});

export const DesignSystemPackageSchema = z.object({
  tokens_json: z.record(z.unknown()).default({}),
  tailwind_config: z.record(z.unknown()).default({}),
  global_tokens_css: z.string(),
  component_scaffolds: z.array(WorkspaceDocumentSchema).default([]),
  asset_recipes: z.array(WorkspaceDocumentSchema).default([]),
  validation_notes: z.array(z.string()).default([]),
});

export const RenderedAssetSchema = z.object({
  asset_id: z.string(),
  asset_type: z.string(),
  title: z.string(),
  prompt_path: z.string(),
  spec_path: z.string(),
  output_path: z.string(),
  format: z.string(),
  review_status: z.string(),
  approval_required: z.boolean().default(true),
  generation_mode: z.string(),
  lineage_refs: z.array(z.string()).default([]),
  notes: z.array(z.string()).default([]),
});

export const AssetReviewQueueSchema = z.object({
  review_status: z.string(),
  approval_required: z.boolean().default(true),
  review_artifact_path: z.string(),
  checklist: z.array(z.string()).default([]),
  blocking_issues: z.array(z.string()).default([]),
});

export const PublishingAdapterSchema = z.object({
  adapter_id: z.string(),
  target: z.string(),
  status: z.string(),
  approval_required: z.boolean().default(true),
  exported_asset_types: z.array(z.string()).default([]),
  notes: z.array(z.string()).default([]),
});

export const AssetExecutionPackageSchema = z.object({
  rendered_assets: z.array(RenderedAssetSchema).default([]),
  review_queue: AssetReviewQueueSchema,
  publishing_adapters: z.array(PublishingAdapterSchema).default([]),
  execution_notes: z.array(z.string()).default([]),
});

export const WorkspaceExportSchema = z.object({
  root_folder: z.string(),
  business_folder: z.string(),
  branding_folder: z.string(),
  design_system_folder: z.string(),
  rendered_assets_folder: z.string(),
  files_written: z.array(z.string()).default([]),
});

export const ArtifactBindingSchema = z.object({
  artifact_key: z.string(),
  artifact_id: z.string(),
  artifact_type: z.string(),
  owner_department: z.string(),
  version: z.number().int().positive(),
  version_ref: z.string(),
  content_location: z.string().nullable().optional(),
  content_hash: z.string().nullable().optional(),
  changed: z.boolean(),
  created: z.boolean(),
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
  business_workspace: BusinessWorkspaceSchema.optional(),
  branding_workspace: BrandingWorkspaceSchema.optional(),
  design_system: DesignSystemPackageSchema.optional(),
  asset_execution: AssetExecutionPackageSchema.optional(),
  workspace_export: WorkspaceExportSchema.nullable().optional(),
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
  workspace_export: WorkspaceExportSchema.nullable().optional(),
  artifact_bindings: z.array(ArtifactBindingSchema).default([]),
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
export type BrandCompliance = z.infer<typeof BrandComplianceSchema>;
export type QAReport = z.infer<typeof QAReportSchema>;
export type CampaignPackage = z.infer<typeof CampaignPackageSchema>;
export type WorkspaceDocument = z.infer<typeof WorkspaceDocumentSchema>;
export type BusinessWorkspace = z.infer<typeof BusinessWorkspaceSchema>;
export type BrandingWorkspace = z.infer<typeof BrandingWorkspaceSchema>;
export type DesignSystemPackage = z.infer<typeof DesignSystemPackageSchema>;
export type RenderedAsset = z.infer<typeof RenderedAssetSchema>;
export type AssetReviewQueue = z.infer<typeof AssetReviewQueueSchema>;
export type PublishingAdapter = z.infer<typeof PublishingAdapterSchema>;
export type AssetExecutionPackage = z.infer<typeof AssetExecutionPackageSchema>;
export type WorkspaceExport = z.infer<typeof WorkspaceExportSchema>;
export type ArtifactBinding = z.infer<typeof ArtifactBindingSchema>;
export type GenerationProvenance = z.infer<typeof GenerationProvenanceSchema>;
export type AgencyRunStatus = z.infer<typeof AgencyRunStatusSchema>;
export type AgencyRun = z.infer<typeof AgencyRunSchema>;
export type RunProof = z.infer<typeof RunProofSchema>;
