import { z } from 'zod';

// Zod twins of the VNEXUS brand book routes (services/langgraph/api/routes/vnexus.py, brand book section) over
// services/langgraph/agency/vnexus/brandbook. Parity is proven by packages/shared/tests/fixtures/vnexus-brandbook.json,
// recorded by services/langgraph/tests/test_vnexus_brandbook_contracts.py from a real build.

const hash = z.string().regex(/^[a-f0-9]{64}$/);
const pageId = z.string().regex(/^p[0-9]{2}$/);

export const BrandBookModeSchema = z.enum(['SYSTEM_SPEC_ONLY', 'PROMPTS_ONLY', 'PREVIEW', 'PRODUCTION']);
export type BrandBookMode = z.infer<typeof BrandBookModeSchema>;
export const BrandBookFieldStatusSchema = z.enum(['VALUE', 'NONE', 'NOT_APPLICABLE', 'PROPOSED', 'UNKNOWN']);
export const BrandBookEvidenceClassSchema = z.enum(['OBSERVED', 'USER_REPORTED', 'INFERRED', 'UNKNOWN', 'PROPOSED']);
export const BrandBookAssetKindSchema = z.enum(['VECTOR', 'RASTER_IN_SVG', 'PROPOSED_CONCEPT', 'MISSING']);
export const BrandBookGapBehaviorSchema = z.enum(['BLOCK', 'LABEL', 'DECIDE']);
export const BrandBookPageStatusSchema = z.enum(['READY', 'DRAFT', 'BLOCKED', 'NOT_APPLICABLE', 'NOT_IN_MODE']);
export const BrandBookBuildStatusSchema = z.enum(['READY_FOR_APPROVAL', 'BLOCKED', 'PREVIEW_ONLY', 'DRAFT']);

const genomeValue = z.union([z.string(), z.number(), z.boolean(), z.array(z.string()), z.null()]);

export const BrandBookPageSpecSchema = z.object({
  id: pageId, order: z.number().int(), title: z.string(), objective: z.string(), required_paths: z.array(z.string()),
  optional_paths: z.array(z.string()), exact_copy: z.array(z.string()), asset_refs: z.array(z.enum(['mark', 'wordmark', 'lockup'])),
  evidence_refs: z.boolean(), layout: z.string(), prohibitions: z.array(z.string()), checks: z.array(z.string()),
  output_modes: z.array(BrandBookModeSchema), gap_behavior: BrandBookGapBehaviorSchema, reads_all_pages: z.boolean(),
}).strict();

export const BrandBookTemplateSchema = z.object({
  manifest: z.object({ template_id: z.string(), template_version: z.string(), pages: z.array(BrandBookPageSpecSchema).length(24) }).strict(),
  manifest_hash: hash, modes: z.array(BrandBookModeSchema),
}).strict();
export type BrandBookTemplate = z.infer<typeof BrandBookTemplateSchema>;

const MarkSchema = z.object({ kind: BrandBookAssetKindSchema, sha256: hash.nullable(), source: z.string(), approved: z.boolean() }).strict();

export const BrandBookGapSchema = z.object({
  page_id: pageId, path: z.string(), status: BrandBookFieldStatusSchema, severity: z.enum(['BLOCKING', 'MAJOR', 'MINOR']),
  consequence: z.string(), source: z.string(), next_action: z.string(),
}).strict();
export type BrandBookGap = z.infer<typeof BrandBookGapSchema>;

const FieldStateSchema = z.object({
  path: z.string(), status: BrandBookFieldStatusSchema, value: genomeValue.optional(), reason: z.string(), approved: z.boolean(),
  source_scope: z.string(),
}).strict();

const CopySchema = z.object({ copy_id: z.string(), text: z.string(), source: z.string(), proposed: z.boolean() }).strict();

export const BrandBookPagePackageSchema = z.object({
  page_id: pageId, order: z.number().int(), title: z.string(), status: BrandBookPageStatusSchema,
  blocks: z.array(z.object({ t: z.string() }).passthrough()), copy_blocks: z.array(CopySchema), fields: z.array(FieldStateSchema),
  gaps: z.array(BrandBookGapSchema), assets: z.array(z.object({ asset: z.literal('mark') }).merge(MarkSchema)),
  dependency_hash: hash, instructions: z.string(), package_hash: hash,
}).strict();
export type BrandBookPagePackage = z.infer<typeof BrandBookPagePackageSchema>;

export const BrandBookPackageSchema = z.object({
  schema_version: z.literal('amc-vnexus-brandbook-package/v1'), brand_id: z.string(), brand_name: z.string(), genome_ref: z.string(),
  resolution_hash: hash, mode: BrandBookModeSchema, locale: z.string(), template_id: z.string(), template_version: z.string(),
  manifest_hash: hash, compiler_version: z.string(), shared_rules_hash: hash, context_hash: hash, mark: MarkSchema,
  pages: z.array(BrandBookPagePackageSchema), gaps: z.array(BrandBookGapSchema),
  status: z.enum(['READY', 'DRAFT', 'BLOCKED', 'SPEC_ONLY']), package_hash: hash,
}).strict();

export const BrandBookCompileSchema = z.object({ package: BrandBookPackageSchema, prompts: z.record(pageId, z.string()) }).strict();
export type BrandBookCompile = z.infer<typeof BrandBookCompileSchema>;

const CheckSummarySchema = z.object({ PASSED: z.number().int(), FAILED: z.number().int(), NOT_RUN: z.number().int(),
  INCONCLUSIVE: z.number().int() }).strict();

const BuildPageSchema = z.object({
  page_id: pageId, order: z.number().int(), title: z.string(), status: BrandBookPageStatusSchema, dependency_hash: hash,
  package_hash: hash, parts: z.array(z.string()), sections_sha256: hash.nullable(), artifact_id: z.string().nullable(),
  gaps: z.array(BrandBookGapSchema), checks: CheckSummarySchema,
}).strict();

const StoredRef = z.object({ artifact_id: z.string(), version: z.number().int(), sha256: hash }).strict();

export const BrandBookBuildRecordSchema = z.object({
  schema_version: z.literal('amc-vnexus-brandbook-build/v1'), brand_id: z.string(), scope: z.string(), scope_ref: z.string(),
  project_id: z.string(), mode: BrandBookModeSchema, locale: z.string(), genome_ref: z.string(), resolution_hash: hash,
  proposal_ref: z.string().nullable(), template_id: z.string(), template_version: z.string(), manifest_hash: hash,
  compiler_version: z.string(), renderer_version: z.string(), validator_version: z.string(), context_hash: hash,
  page_format: z.object({ name: z.string(), width: z.number().int(), height: z.number().int(), provisional: z.boolean() }).strict(),
  palette: z.object({ neutral: z.boolean() }).strict(), mark: MarkSchema, pages: z.array(BuildPageSchema).length(24),
  gaps: z.array(BrandBookGapSchema),
  checks: z.object({ summary: CheckSummarySchema, measured: z.boolean(), blocking: z.array(z.record(z.string(), z.unknown())) }).strict(),
  book: StoredRef, package: z.object({ artifact_id: z.string(), sha256: hash, package_hash: hash }).strict(),
  pdf: StoredRef.nullable(), status: BrandBookBuildStatusSchema,
  states: z.object({ prompt: z.string(), rendered: z.string(), validated: z.enum(['PASSED', 'FAILED', 'NOT_RUN', 'INCONCLUSIVE']),
    released: z.string() }).strict(),
  build_hash: hash,
}).strict();

export const BrandBookBuildSchema = BrandBookBuildRecordSchema.extend({
  build_artifact: z.object({ artifact_id: z.string(), version: z.number().int(), action: z.enum(['created', 'revised', 'reused_unchanged']) }).strict(),
  telemetry: z.object({
    browser_runs: z.number().int(), pages_compiled: z.number().int(), pages_reused: z.number().int(), pages_rendered: z.number().int(),
    pages_measured: z.number().int(), checks_reused: z.number().int(), cache_hits: z.number().int(), model_calls: z.literal(0),
    stage_ms: z.record(z.string(), z.number()), total_ms: z.number(), peak_rss_kb: z.number(),
  }).strict(),
}).strict();
export type BrandBookBuild = z.infer<typeof BrandBookBuildSchema>;

export const BrandBookCurrentSchema = BrandBookBuildRecordSchema.extend({
  freshness: z.object({ fresh: z.boolean(), reasons: z.array(z.string()) }).strict(),
}).strict();
export type BrandBookCurrent = z.infer<typeof BrandBookCurrentSchema>;

export const BrandBookGapsSchema = z.object({
  mode: BrandBookModeSchema, genome_ref: z.string(), mark: MarkSchema, evidence_records: z.number().int(),
  decisions: z.array(z.object({ path: z.string(), status: BrandBookFieldStatusSchema, severity: z.enum(['BLOCKING', 'MAJOR', 'MINOR']),
    pages: z.array(pageId), consequence: z.string(), next_action: z.string() }).strict()),
}).strict();
export type BrandBookGaps = z.infer<typeof BrandBookGapsSchema>;

export const BrandBookEvidenceSchema = z.object({
  source_id: z.string(), locator: z.string(), kind: z.enum(['document', 'image', 'interview', 'website', 'existing_asset', 'other']),
  evidence_class: BrandBookEvidenceClassSchema, observations: z.array(z.string()), inferences: z.array(z.string()),
  unknowns: z.array(z.string()), contradictions: z.array(z.string()),
  reuse: z.enum(['evidence_only', 'licensed_reuse', 'owned', 'unknown']), privacy: z.enum(['none', 'contains_pii_redacted', 'restricted']),
}).strict();

export const BrandBookIntakeSchema = z.object({
  intake: z.object({ schema_version: z.literal('amc-vnexus-brandbook-intake/v1'), evidence: z.array(BrandBookEvidenceSchema),
    proposals: z.record(z.string(), genomeValue) }).strict(),
  sha256: hash.nullable(),
}).strict();
export type BrandBookIntake = z.infer<typeof BrandBookIntakeSchema>;

export const BrandBookIntakeSavedSchema = z.object({ artifact_id: z.string(), version: z.number().int(), sha256: hash,
  action: z.enum(['created', 'revised', 'reused_unchanged']) }).strict();
