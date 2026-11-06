import { z } from 'zod';

export const RenderEngineIdSchema = z.enum(['paper_js', 'svg_js', 'rough_js', 'p5_js', 'pixi_js', 'react_three_fiber', 'remotion', 'motion_canvas']);
export type RenderEngineId = z.infer<typeof RenderEngineIdSchema>;
const hash = z.string().regex(/^[a-f0-9]{64}$/);
export const RenderCapabilitySchema = z.object({
  engine: RenderEngineIdSchema, adapter_version: z.string().nullable(), available: z.boolean(),
  profiles: z.array(z.string()), blockers: z.array(z.string()), arbitrary_code: z.literal(false),
  remote_storage: z.literal(false), isolation_profile: z.string(),
});
export const RenderCapabilitiesSchema = z.object({ engines: z.array(RenderCapabilitySchema), external_effects: z.literal('none') });
export const RenderJobSchema = z.object({
  job_id: z.string(), run_id: z.string(), spec_hash: hash, engine: RenderEngineIdSchema,
  workflow_status: z.enum(['queued', 'executing', 'blocked', 'awaiting_approval', 'completed', 'cancelled']),
  job_status: z.string(), artifact_status: z.enum(['pending_verification', 'verified', 'rejected', 'stale']),
  approval_status: z.enum(['not_requested', 'pending', 'approved', 'rejected', 'invalidated']),
  blockers: z.array(z.string()), artifact_id: z.string().nullable(), artifact_version: z.number().int().nullable(),
  content_hash: hash.nullable(), approval_id: z.string().nullable(),
  verification: z.object({ status: z.enum(['PASSED', 'FAILED', 'INCONCLUSIVE']), content_hash: hash,
    spec_hash: hash, byte_count: z.number().int().nonnegative(), checks: z.array(z.string()), findings: z.array(z.string()), verifier: z.string() }).nullable(),
  release: z.object({ allowed: z.boolean(), reasons: z.array(z.string()) }).passthrough(),
  external_effects: z.literal('none'),
});
export type RenderJob = z.infer<typeof RenderJobSchema>;
export type RenderCapability = z.infer<typeof RenderCapabilitySchema>;
