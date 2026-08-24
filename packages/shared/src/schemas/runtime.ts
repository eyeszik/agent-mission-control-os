import { z } from 'zod';

export const RoleOSManifestSchema = z.object({
  tenant_id: z.string(),
  registry_hash: z.string().regex(/^[a-f0-9]{64}$/),
  role_count: z.number().int().nonnegative(),
  phase_count: z.number().int().nonnegative(),
});

export const TrustSnapshotSchema = z.object({
  tenant_id: z.string(),
  project_id: z.string(),
  policy_decisions: z.number().int().nonnegative(),
  pending_outbox: z.number().int().nonnegative(),
  open_recovery_cases: z.number().int().nonnegative(),
  audit_head_hash: z.string().regex(/^[a-f0-9]{64}$/),
  idempotency_claims: z.number().int().nonnegative(),
  metadata: z.record(z.unknown()),
  database_backend: z.enum(['sqlite', 'postgres']),
  persistence_mode: z.string(),
});

export type RoleOSManifest = z.infer<typeof RoleOSManifestSchema>;
export type TrustSnapshot = z.infer<typeof TrustSnapshotSchema>;
