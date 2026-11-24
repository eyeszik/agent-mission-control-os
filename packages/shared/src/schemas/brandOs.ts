import { z } from 'zod';

/**
 * Zod twin of services/langgraph/agency/sop/brand_os_contracts.py (the /brand-os API).
 * tests/fixtures/brand-os.json is recorded by services/langgraph/tests/test_brand_os_api.py
 * (regenerate with AMC_REGENERATE_FIXTURES=1).
 *
 * F01-F08 are newly written Brand OS 4.0 drafts, never recovered originals; adoption is a
 * per-project decision made on /approvals/{id}/decide and grants no runtime authority.
 */
const SopIdSchema = z.string().regex(/^F(0[1-9]|[1-5][0-9]|60)$/);
const Sha256Schema = z.string().regex(/^[0-9a-f]{64}$/);

export const BrandOsProcedureStatusSchema = z.enum(['NEWLY_AUTHORED_DRAFT', 'SOURCE_UNAVAILABLE']);
export const BrandOsAdoptionStateSchema = z.enum([
  'NOT_STAGED',
  'STAGED_NO_APPROVAL',
  'PENDING',
  'ADOPTED',
  'REJECTED',
  'STALE',
  'REVISION_CHANGED',
]);

export const BrandOsSopListItemSchema = z
  .object({
    sop_id: SopIdSchema,
    name: z.string(),
    department_id: z.string(),
    department_name: z.string(),
    batch: z.enum(['BATCH_1', 'INDEX_ONLY']),
    procedure_status: BrandOsProcedureStatusSchema,
    origin: z.literal('NEWLY_AUTHORED_SOP').nullable(),
    draft_version: z.string().nullable(),
    source_sha256: Sha256Schema.nullable(),
    step_count: z.number().int().min(0),
  })
  .strict();

export const BrandOsSopStepViewSchema = z
  .object({
    step_ref: z.string(),
    sequence: z.number().int().min(1),
    line: z.number().int().min(1),
    text: z.string(),
    agm_disposition: z.string(),
    agm_task_ids: z.array(z.string()),
  })
  .strict();

export const BrandOsSopDetailSchema = z
  .object({
    sop: BrandOsSopListItemSchema,
    steps: z.array(BrandOsSopStepViewSchema),
    companion_scope: z.literal('ADVISORY'),
    original_authenticated: z.literal(false),
  })
  .strict();

export const BrandOsAdoptionStatusSchema = z
  .object({
    project_id: z.string(),
    sop_id: SopIdSchema,
    name: z.string(),
    origin: z.literal('NEWLY_AUTHORED_SOP'),
    draft_version: z.string(),
    source_sha256: Sha256Schema,
    state: BrandOsAdoptionStateSchema,
    decision_covers: z.string(),
    artifact_id: z.string().nullable(),
    artifact_version: z.number().int().nullable(),
    artifact_hash: z.string().nullable(),
    approval_id: z.string().nullable(),
    decision_route: z.string().nullable(),
    reasons: z.array(z.string()),
    grants_runtime_authority: z.literal(false),
    external_effects: z.literal('none'),
  })
  .strict();

export type BrandOsSopListItem = z.infer<typeof BrandOsSopListItemSchema>;
export type BrandOsSopDetail = z.infer<typeof BrandOsSopDetailSchema>;
export type BrandOsAdoptionStatus = z.infer<typeof BrandOsAdoptionStatusSchema>;
