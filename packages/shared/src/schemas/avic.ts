import { z } from 'zod';

// Zod twins of the /avic route responses (services/langgraph/api/routes/avic.py) over
// services/langgraph/agency/avic. Parity is proven by packages/shared/tests/fixtures/avic.json,
// recorded by services/langgraph/tests/test_avic_contracts.py from a real render.

const hash = z.string().regex(/^[a-f0-9]{64}$/);
const assetId = z.string().regex(/^[a-z0-9][a-z0-9-]{0,39}$/);

export const AvicCheckResultSchema = z.enum(['PASS', 'FAIL', 'BLOCKED', 'NOT_MEASURED']);
export const AvicCapabilityStateSchema = z.enum(['IMPLEMENTED_VERIFIED', 'PARTIAL', 'PROPOSED', 'BLOCKED', 'PROVIDER_GAP', 'NOT_ADDED']);
export const AvicProfileStateSchema = z.enum([
  'IMPLEMENTED_VERIFIED', 'IMPLEMENTED_UNTESTED', 'PARTIAL', 'PROPOSED', 'BLOCKED', 'DEPRECATED', 'UNKNOWN',
]);
export const AvicEditOpSchema = z.enum(['recolor', 'change_text', 'set_geometry']);
export type AvicEditOp = z.infer<typeof AvicEditOpSchema>;

export const AvicCheckSchema = z.object({
  check: z.string(), level: z.string(), result: AvicCheckResultSchema, detail: z.string(),
}).strict();
export type AvicCheck = z.infer<typeof AvicCheckSchema>;

const StageEntry = z.object({
  artifact_id: z.string(), version: z.number().int(), action: z.enum(['created', 'revised', 'reused_unchanged']),
  sha256: hash.nullable(), role: z.string().optional(), file: z.string().optional(),
}).strict();

const EvaluationReport = z.object({
  schema_version: z.string(), scene_hash: hash, svg_sha256: hash, png_sha256: hash.nullable(), renderer: z.string(),
  renderer_version: z.string().nullable(), checks: z.array(AvicCheckSchema), metrics: z.record(z.string(), z.unknown()),
}).strict();

export const AvicCapabilitiesSchema = z.object({
  capabilities: z.array(z.object({ name: z.string(), state: AvicCapabilityStateSchema, limit: z.string(),
    tests: z.array(z.string()) }).strict()),
  style_profiles: z.array(z.object({ profile_id: z.string(), name: z.string(), state: AvicProfileStateSchema,
    notes: z.array(z.string()) }).strict()),
  renderer: z.object({ name: z.string(), state: AvicProfileStateSchema, blockers: z.array(z.string()),
    concurrency: z.number().int().min(1) }).strict(),
  brand: z.object({ source: z.string(), palette: z.record(z.string(), z.string()) }).strict(),
}).strict();
export type AvicCapabilities = z.infer<typeof AvicCapabilitiesSchema>;

export const AvicAssetListSchema = z.object({
  assets: z.array(z.object({ asset_id: assetId, scene_artifact: z.string(), version: z.number().int() }).strict()),
}).strict();

export const AvicAssetViewSchema = z.object({
  project_id: z.string(), asset_id: assetId, svg_sha256: hash, scene_hash: hash, style_profile: z.string(),
  output_profile: z.string(), width: z.number().int(), height: z.number().int(), exact_text: z.array(z.string()),
  stages: z.record(z.string(), z.object({ artifact_id: z.string(), version: z.number().int(), content_hash: hash.nullable() }).strict()),
  consistency: z.object({ consistent: z.boolean(), stale: z.array(z.string()) }).strict(),
  evaluation: z.object({ passed: z.boolean(), renderer: z.string().nullable(), renderer_version: z.string().nullable(),
    svg_sha256: hash.nullable(), png_sha256: hash.nullable(), checks: z.array(AvicCheckSchema) }).strict(),
  objects: z.array(z.object({ object_id: z.string(), semantic_role: z.string(), protected: z.boolean(), text: z.string().nullable(),
    fill: z.string().nullable(), stroke: z.string().nullable(), operations: z.array(AvicEditOpSchema) }).strict()),
  palette: z.record(z.string(), z.string()), brand_source: z.string(), brand_approved: z.boolean(),
  approvals: z.array(z.object({ approval_id: z.string(), status: z.string(), decision: z.string().nullable(),
    reviewer: z.string().nullable(), subject_hash: z.string().nullable(), current: z.boolean(), created_at: z.string() }).strict()),
  release: z.object({ release_allowed: z.boolean(), reasons: z.array(z.string()), approval_id: z.string().nullable(),
    svg_sha256: z.string().nullable(), external_effects: z.literal('none') }).strict().nullable(),
}).strict();
export type AvicAssetView = z.infer<typeof AvicAssetViewSchema>;

export const AvicCompileResponseSchema = z.object({
  asset_id: assetId, status: z.enum(['EVALUATED', 'REJECTED', 'BLOCKED']),
  candidate: z.record(z.string(), z.unknown()).optional(), evaluation: EvaluationReport.optional(),
  coverage: z.object({ coverage: z.number(), rows: z.array(z.record(z.string(), z.unknown())), unmapped: z.array(z.string()) })
    .strict().optional(),
  repairs: z.array(z.record(z.string(), z.unknown())).optional(), metrics: z.record(z.string(), z.unknown()).optional(),
  artifacts: z.record(z.string(), StageEntry).optional(), reasons: z.array(z.string()).optional(),
  intent: z.record(z.string(), z.unknown()).optional(), parent_kept: z.boolean().optional(),
}).strict();
export type AvicCompileResponse = z.infer<typeof AvicCompileResponseSchema>;

export const AvicEditResponseSchema = z.object({
  status: z.enum(['EVALUATED', 'REJECTED']), reasons: z.array(z.string()).optional(),
  transformations: z.array(z.object({ object_id: z.string(), field: z.string(), before: z.unknown(), after: z.unknown() }).passthrough())
    .optional(),
  metrics: z.record(z.string(), z.unknown()).optional(), artifacts: z.record(z.string(), StageEntry).optional(),
  evaluation: EvaluationReport.optional(), repairs: z.array(z.record(z.string(), z.unknown())).optional(),
  parent_kept: z.boolean().optional(),
}).strict();
export type AvicEditResponse = z.infer<typeof AvicEditResponseSchema>;

/** Body of a 409: the edit was made against an SVG that is no longer the head. Reload and re-apply. */
export const AvicConflictSchema = z.object({
  detail: z.object({ status: z.literal('CONFLICT'), reasons: z.array(z.string()) }).strict(),
}).strict();

export const AvicRecompileResponseSchema = z.object({
  status: z.enum(['EVALUATED', 'REJECTED']), already_consistent: z.boolean().optional(),
  metrics: z.record(z.string(), z.unknown()).optional(), artifacts: z.record(z.string(), StageEntry).optional(),
  reasons: z.array(z.string()).optional(), evaluation: EvaluationReport.optional(),
  repairs: z.array(z.record(z.string(), z.unknown())).optional(),
}).strict();
export type AvicRecompileResponse = z.infer<typeof AvicRecompileResponseSchema>;

export const AvicApprovalResponseSchema = z.union([
  z.object({ status: z.literal('PENDING'), approval_id: z.string(), approval_status: z.string(), subject_hash: hash })
    .passthrough(),
  z.object({ status: z.literal('BLOCKED'), reasons: z.array(z.string()) }).strict(),
]);
export type AvicApprovalResponse = z.infer<typeof AvicApprovalResponseSchema>;

export const AvicReleaseResponseSchema = z.object({
  status: z.enum(['RELEASED_LOCAL', 'BLOCKED']), reasons: z.array(z.string()),
  manifest: z.object({ release_allowed: z.boolean(), external_effects: z.literal('none'), approval_id: z.string().nullable(),
    source_hashes: z.record(z.string(), z.string()), quality: z.record(z.string(), z.string()) }).passthrough().nullable(),
  artifact: z.object({ artifact_id: z.string(), version: z.number().int(), sha256: hash }).strict().optional(),
}).strict();
export type AvicReleaseResponse = z.infer<typeof AvicReleaseResponseSchema>;
