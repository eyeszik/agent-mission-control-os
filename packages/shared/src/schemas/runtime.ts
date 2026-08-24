import { z } from 'zod';

export const RoleOSManifestSchema = z.object({
  tenant_id: z.string(),
  registry_hash: z.string().regex(/^[a-f0-9]{64}$/),
  role_count: z.number().int().nonnegative(),
  phase_count: z.number().int().nonnegative(),
});

export const PolicyDecisionSummarySchema = z.object({
  decision_id: z.string(),
  tenant_id: z.string(),
  project_id: z.string(),
  subject_ref: z.string(),
  action: z.string(),
  target: z.string(),
  policy_version: z.string(),
  input_hash: z.string().regex(/^[a-f0-9]{64}$/),
  effect: z.enum(['ALLOW', 'DENY', 'REQUIRE_APPROVAL']),
  required_authority_refs: z.array(z.string()).default([]),
  evidence_refs: z.array(z.string()).default([]),
  decision_hash: z.string().regex(/^[a-f0-9]{64}$/),
  decided_at: z.string().datetime({ offset: true }),
});

export const OutboxMessageSummarySchema = z.object({
  message_id: z.string(),
  tenant_id: z.string(),
  project_id: z.string(),
  topic: z.string(),
  payload_hash: z.string().regex(/^[a-f0-9]{64}$/),
  payload_ref: z.string(),
  idempotency_key: z.string(),
  status: z.enum(['PENDING', 'CLAIMED', 'DELIVERED', 'FAILED']),
  attempts: z.number().int().nonnegative(),
  claimed_by: z.string().nullable().optional(),
  next_attempt_at: z.string().datetime({ offset: true }).nullable().optional(),
  delivered_at: z.string().datetime({ offset: true }).nullable().optional(),
  last_error: z.string().nullable().optional(),
  created_at: z.string().datetime({ offset: true }),
});

export const RecoveryCaseSummarySchema = z.object({
  recovery_id: z.string(),
  tenant_id: z.string(),
  project_id: z.string(),
  operation_id: z.string(),
  reason: z.enum([
    'EXECUTION_WITHOUT_OBSERVATION',
    'OBSERVATION_MISMATCH',
    'AMBIGUOUS_EXTERNAL_RESULT',
    'IDEMPOTENCY_CONFLICT',
  ]),
  execution_ref: z.string().nullable().optional(),
  observation_ref: z.string().nullable().optional(),
  idempotency_key: z.string().nullable().optional(),
  status: z.enum(['OPEN', 'RECONCILED', 'COMPENSATED', 'ESCALATED']),
  evidence_refs: z.array(z.string()).default([]),
  created_at: z.string().datetime({ offset: true }),
  resolved_at: z.string().datetime({ offset: true }).nullable().optional(),
});

export const AuditCheckpointSummarySchema = z.object({
  seq: z.number().int().positive(),
  tenant_id: z.string(),
  project_id: z.string(),
  event_type: z.string(),
  object_ref: z.string(),
  payload_hash: z.string().regex(/^[a-f0-9]{64}$/),
  previous_hash: z.string().regex(/^[a-f0-9]{64}$/),
  checkpoint_hash: z.string().regex(/^[a-f0-9]{64}$/),
  created_at: z.string().datetime({ offset: true }),
});

export const RecoveryActionResponseSchema = RecoveryCaseSummarySchema;
export const OutboxReplayResponseSchema = z.object({
  message_id: z.string(),
  status: z.string(),
  result_ref: z.string().nullable().optional(),
  error: z.string().nullable().optional(),
});

export const TrustSnapshotSchema = z.object({
  tenant_id: z.string(),
  project_id: z.string(),
  policy_decisions: z.number().int().nonnegative(),
  pending_outbox: z.number().int().nonnegative(),
  delivered_outbox: z.number().int().nonnegative(),
  failed_outbox: z.number().int().nonnegative(),
  open_recovery_cases: z.number().int().nonnegative(),
  resolved_recovery_cases: z.number().int().nonnegative(),
  audit_head_hash: z.string().regex(/^[a-f0-9]{64}$/),
  idempotency_claims: z.number().int().nonnegative(),
  recent_policy_decisions: z.array(PolicyDecisionSummarySchema),
  recent_outbox_messages: z.array(OutboxMessageSummarySchema),
  recent_recovery_cases: z.array(RecoveryCaseSummarySchema),
  recent_audit_events: z.array(AuditCheckpointSummarySchema),
  metadata: z.record(z.unknown()),
  database_backend: z.enum(['sqlite', 'postgres']),
  persistence_mode: z.string(),
});

export type RoleOSManifest = z.infer<typeof RoleOSManifestSchema>;
export type TrustSnapshot = z.infer<typeof TrustSnapshotSchema>;
export type RecoveryActionResponse = z.infer<typeof RecoveryActionResponseSchema>;
export type OutboxReplayResponse = z.infer<typeof OutboxReplayResponseSchema>;
