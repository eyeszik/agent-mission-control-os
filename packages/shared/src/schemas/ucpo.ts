import { z } from 'zod';

// Zod twins of services/langgraph/agency/ucpo/contracts.py and the /ucpo route responses.
// Parity is proven by packages/shared/tests/fixtures/ucpo.json, recorded by
// services/langgraph/tests/test_ucpo_contracts.py from the real backend.

const hash = z.string().regex(/^[a-f0-9]{64}$/);

export const UcpoSectionKindSchema = z.enum(['hero', 'editorial', 'statement', 'index', 'gallery', 'contact']);
export const UcpoRequirementKindSchema = z.enum([
  'LANG', 'PAGE_EXISTS', 'NAV_LINK', 'BRAND_ON_PAGE', 'SECTION_HEADING', 'SECTION_BODY', 'ITEM_TEXT', 'LABEL_TEXT',
  'REQUIRED_PHRASE', 'FORBIDDEN_PHRASE', 'CTA', 'IMAGE_ALT', 'IMAGE_RIGHTS', 'PSEM_COLOUR', 'A11Y_AUTOMATED',
  'RESPONSIVE_REFLOW', 'TEXT_ZOOM', 'REDUCED_MOTION', 'KEYBOARD_FOCUS', 'NO_CONSOLE_ERRORS', 'NO_EXTERNAL_REQUESTS',
]);
export const UcpoStageSchema = z.enum(['ir', 'source', 'rendered']);
export const UcpoRequirementStatusSchema = z.enum([
  'PRESERVED', 'APPROVED_CHANGE', 'UNAPPROVED_CHANGE', 'OMITTED', 'UNRESOLVED', 'NOT_APPLICABLE',
]);
export const UcpoCheckResultValueSchema = z.enum(['PASS', 'FAIL', 'NOT_RUN', 'INCONCLUSIVE', 'BLOCKED']);
export const UcpoBuildStatusSchema = z.enum(['PASSED', 'FAILED', 'BLOCKED_ISOLATION', 'TIMED_OUT']);
export const UcpoBrowserStatusSchema = z.enum(['PASSED', 'FAILED', 'BLOCKED', 'NOT_RUN']);

const Item = z.object({ title: z.string().min(1).max(120), body: z.string().max(600) }).strict();
const ImageAsset = z.object({
  asset_id: z.string().regex(/^[a-z0-9][a-z0-9-]{0,39}$/), alt: z.string().min(1).max(240),
  rights: z.enum(['procedural_owned', 'owned', 'licensed']), license_ref: z.string().max(200).nullable(),
  source: z.literal('procedural:psem'), motif_seed: z.number().int().min(0).max(10000),
}).strict();
const SectionBrief = z.object({
  kind: UcpoSectionKindSchema, heading: z.string().min(1).max(140), body: z.string().max(1200), label: z.string().max(40),
  items: z.array(Item).max(12), image: z.string().nullable(), cta: z.boolean(), anchor: z.string().nullable(),
}).strict();
const PageBrief = z.object({
  slug: z.string(), title: z.string().min(1).max(80), description: z.string().min(1).max(200),
  sections: z.array(SectionBrief).min(1).max(10),
}).strict();

export const UcpoWebsiteBriefSchema = z.object({
  schema_version: z.literal('amc-ucpo-brief/v1'), organization: z.string().min(1).max(80), tagline: z.string().max(140),
  offering: z.string().max(300), audience: z.string().max(300), locale: z.string(), cta_label: z.string().max(40),
  cta_target: z.string().max(80), pages: z.array(PageBrief).min(1).max(8), images: z.array(ImageAsset).max(16),
  required_phrases: z.array(z.string()).max(20), forbidden_phrases: z.array(z.string()).max(20),
  seed: z.number().int().nullable(), existing_project_id: z.string().nullable(),
}).strict();
export type UcpoWebsiteBrief = z.infer<typeof UcpoWebsiteBriefSchema>;

export const UcpoRequirementSchema = z.object({
  req_id: z.string(), kind: UcpoRequirementKindSchema, statement: z.string(), subject: z.record(z.string(), z.unknown()),
  mandatory: z.boolean(), source_ref: z.string(), stages: z.array(UcpoStageSchema),
}).strict();
export const UcpoRequirementsPackageSchema = z.object({
  schema_version: z.literal('amc-ucpo-requirements/v1'), project_ref: z.string(), brief_hash: hash,
  requirements: z.array(UcpoRequirementSchema), capability_gaps: z.array(z.record(z.string(), z.string())),
}).strict();

export const UcpoCoverageEntrySchema = z.object({
  req_id: z.string(), kind: UcpoRequirementKindSchema, mandatory: z.boolean(), status: UcpoRequirementStatusSchema,
  stages: z.record(z.string(), z.enum(['PASS', 'FAIL', 'NOT_RUN', 'N/A'])), loss_stage: UcpoStageSchema.nullable(),
  detail: z.string(),
}).strict();
export const UcpoSemanticDebtEntrySchema = z.object({
  req_id: z.string(), origin_revision: hash, loss_stage: UcpoStageSchema.nullable(), affected_artifacts: z.array(z.string()),
  severity: z.enum(['blocking', 'major', 'minor']), repair_owner: z.string(), repair_proposal: z.string(),
  verification: z.string(), resolution: z.enum(['OPEN', 'RESOLVED']),
}).strict();
export const UcpoSemanticCoverageReportSchema = z.object({
  schema_version: z.literal('amc-ucpo-coverage/v1'), requirements_ref: hash, entries: z.array(UcpoCoverageEntrySchema),
  mandatory_resolved: z.number().int().nonnegative(), mandatory_applicable: z.number().int().nonnegative(),
  coverage: z.union([z.number().min(0).max(1), z.literal('NOT_APPLICABLE')]), debt: z.array(UcpoSemanticDebtEntrySchema),
  release_blocked: z.boolean(),
}).strict();
export type UcpoSemanticCoverageReport = z.infer<typeof UcpoSemanticCoverageReportSchema>;

export const UcpoCheckResultSchema = z.object({
  check: z.string(), route: z.string().nullable(), viewport: z.string().nullable(), result: UcpoCheckResultValueSchema,
  detail: z.string(), req_refs: z.array(z.string()), evidence_ref: z.string().nullable(),
}).strict();
export const UcpoBrowserVerificationSchema = z.object({
  schema_version: z.literal('amc-ucpo-browser-verification/v1'), status: UcpoBrowserStatusSchema,
  build_output_hash: hash.nullable(), browser: z.record(z.string(), z.unknown()), checks: z.array(UcpoCheckResultSchema),
  dom_evidence: z.record(z.string(), z.record(z.string(), z.array(z.string()))), screenshots: z.record(z.string(), hash),
  blocked_requests: z.array(z.string()), note: z.string(),
}).strict();

export const UcpoReleaseProofSchema = z.object({
  schema_version: z.literal('amc-ucpo-release-proof/v1'), project_ref: z.string(), site_id: z.string(),
  revisions: z.record(z.string(), z.string()), artifact_refs: z.record(z.string(), z.string()),
  gates: z.record(z.string(), z.string()), eligible_for_approval: z.boolean(), reasons: z.array(z.string()),
  deployment: z.literal('NOT_AUTHORIZED'),
}).strict();
export type UcpoReleaseProof = z.infer<typeof UcpoReleaseProofSchema>;

const StageEntry = z.object({
  artifact_id: z.string(), version: z.number().int().positive(), action: z.string(), role: z.string(), artifact_type: z.string(),
  invalidated: z.array(z.string()),
}).strict();
export const UcpoCompileResponseSchema = z.object({
  site_id: z.string(), job_id: z.string(), job_state: z.string(), stages: z.record(z.string(), StageEntry),
  compile_coverage: z.object({
    coverage: z.union([z.number(), z.literal('NOT_APPLICABLE')]), mandatory_resolved: z.number().int(),
    mandatory_applicable: z.number().int(), unresolved_until_rendered: z.number().int(),
  }).strict(),
  requirements: z.number().int(), source_files: z.number().int(), source_tree: hash, external_effects: z.literal('none'),
}).strict();
export type UcpoCompileResponse = z.infer<typeof UcpoCompileResponseSchema>;

export const UcpoSiteViewSchema = z.object({
  site_id: z.string(), project_id: z.string(),
  stages: z.record(z.string(), z.object({ artifact_id: z.string(), version: z.number().int(), content_hash: hash,
    status: z.string().nullable() }).strict()),
  job: z.object({ job_id: z.string().nullable(), state: z.string().nullable(), reasons: z.array(z.string()) }).strict(),
  build: z.record(z.string(), z.unknown()).nullable(),
  build_steps: z.array(z.object({ name: z.string(), exit_status: z.number().int(), duration_s: z.number() }).strict()),
  browser_qa: z.object({ status: UcpoBrowserStatusSchema, checks: z.array(UcpoCheckResultSchema),
    browser: z.record(z.string(), z.unknown()), blocked_requests: z.array(z.string()), screenshots: z.record(z.string(), hash),
    note: z.string() }).strict().nullable(),
  coverage: z.object({ coverage: z.union([z.number(), z.literal('NOT_APPLICABLE')]), mandatory_resolved: z.number().int(),
    mandatory_applicable: z.number().int(), release_blocked: z.boolean(), debt: z.array(UcpoSemanticDebtEntrySchema) })
    .strict().nullable(),
  proof: UcpoReleaseProofSchema.nullable(),
  approval: z.object({ approval_id: z.string(), run_id: z.string(), status: z.string() }).strict().nullable(),
  release: z.object({ allowed: z.boolean(), reasons: z.array(z.string()), deployment: z.literal('NOT_AUTHORIZED') }).strict(),
  external_effects: z.literal('none'),
}).strict();
export type UcpoSiteView = z.infer<typeof UcpoSiteViewSchema>;

export const UcpoTraceSchema = z.object({
  requirement: UcpoRequirementSchema, status: UcpoCoverageEntrySchema, ir: z.array(z.string()), source: z.array(z.string()),
  rendered: z.record(z.string(), z.array(z.string())), checks: z.array(UcpoCheckResultSchema),
}).strict();
export type UcpoTrace = z.infer<typeof UcpoTraceSchema>;

export const UcpoSiteListSchema = z.object({
  sites: z.array(z.object({ site_id: z.string(), brief_artifact: z.string(), version: z.number().int() }).strict()),
}).strict();

export const UcpoCapabilitiesSchema = z.object({
  capabilities: z.record(z.string(), z.object({ status: z.string(), blockers: z.array(z.string()) }).strict()),
  disciplines: z.array(z.object({ discipline_id: z.string(), name: z.string(),
    route: z.object({ status: z.enum(['ROUTED', 'CAPABILITY_GAP']) }).passthrough() }).passthrough()),
  presentation_systems: z.array(z.object({ system_id: z.string(), name: z.string() }).passthrough()),
  prompt_modules: z.array(z.object({ module_id: z.string(), name: z.string(),
    preservation: z.object({ missing: z.array(z.string()) }).passthrough() }).passthrough()),
  generation: z.record(z.string(), z.object({ status: z.string(), generated: z.literal(false) }).passthrough()),
  deployment: z.string(),
}).strict();
export type UcpoCapabilities = z.infer<typeof UcpoCapabilitiesSchema>;

export const UcpoBuildTickSchema = z.object({
  tick: z.object({ outcome: z.string(), state: z.string().nullable(), reasons: z.array(z.string()) }).strict(),
  site: UcpoSiteViewSchema,
}).strict();
export type UcpoBuildTick = z.infer<typeof UcpoBuildTickSchema>;
