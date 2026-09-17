import { z } from 'zod';
import { AgencyRunSchema } from './agency';

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

export const LineageRemediationSummarySchema = z.object({
  remediation_id: z.string(),
  tenant_id: z.string(),
  project_id: z.string(),
  run_id: z.string(),
  approval_id: z.string().nullable().optional(),
  artifact_id: z.string(),
  artifact_version_ref: z.string(),
  changed_artifact_id: z.string(),
  changed_version_ref: z.string(),
  reason: z.string(),
  status: z.enum(['OPEN', 'REGENERATED', 'RETRIED', 'RESOLVED']),
  payload: z.record(z.unknown()),
  created_at: z.string().datetime({ offset: true }),
  resolved_at: z.string().datetime({ offset: true }).nullable().optional(),
});

export const InvalidationObligationSummarySchema = z.object({
  obligation_id: z.string(),
  tenant_id: z.string(),
  project_id: z.string(),
  run_id: z.string(),
  artifact_branch: z.string(),
  node_id: z.string(),
  event_class: z.enum([
    'SPEC_CHANGE',
    'MODEL_PARAM_CHANGE',
    'TOOL_RESULT_CHANGE',
    'SCHEMA_CHANGE',
    'ACL_SECRET_CHANGE',
    'MEMORY_WRITE',
    'CLOCK_WINDOW_ADVANCE',
    'HOOK_GAP',
  ]),
  state: z.enum(['OPEN', 'DISCHARGED_RECOMPUTE', 'DISCHARGED_CUTOFF', 'HOOK_GAP']),
  demanded: z.union([z.boolean(), z.number().int().nonnegative()]).transform((value) => Boolean(value)),
  cause_k: z.string().regex(/^[a-f0-9]{64}$/),
  payload: z.record(z.unknown()),
  created_at: z.string().datetime({ offset: true }),
  updated_at: z.string().datetime({ offset: true }),
  discharged_at: z.string().datetime({ offset: true }).nullable().optional(),
});

export const RecoveryActionResponseSchema = RecoveryCaseSummarySchema;
export const OutboxReplayResponseSchema = z.object({
  message_id: z.string(),
  status: z.string(),
  result_ref: z.string().nullable().optional(),
  error: z.string().nullable().optional(),
});

export const RunRemediationActionSchema = z.enum([
  'retry_blocked_execution',
  'compensate_ambiguous_result',
  'regenerate_approval',
]);

export const RunRemediationResponseSchema = z.object({
  action: RunRemediationActionSchema,
  run: AgencyRunSchema,
  recovery_case: RecoveryCaseSummarySchema.nullable().optional(),
  pending_approval: z.record(z.unknown()).nullable().optional(),
});

export const TrustSnapshotSchema = z.object({
  tenant_id: z.string(),
  project_id: z.string(),
  policy_decisions: z.number().int().nonnegative(),
  compile_blocked: z.boolean(),
  pending_outbox: z.number().int().nonnegative(),
  delivered_outbox: z.number().int().nonnegative(),
  failed_outbox: z.number().int().nonnegative(),
  open_recovery_cases: z.number().int().nonnegative(),
  resolved_recovery_cases: z.number().int().nonnegative(),
  open_invalidation_obligations: z.number().int().nonnegative(),
  hook_gap_count: z.number().int().nonnegative(),
  open_lineage_remediations: z.number().int().nonnegative(),
  resolved_lineage_remediations: z.number().int().nonnegative(),
  audit_head_hash: z.string().regex(/^[a-f0-9]{64}$/),
  idempotency_claims: z.number().int().nonnegative(),
  recent_invalidation_obligations: z.array(InvalidationObligationSummarySchema),
  recent_policy_decisions: z.array(PolicyDecisionSummarySchema),
  recent_outbox_messages: z.array(OutboxMessageSummarySchema),
  recent_recovery_cases: z.array(RecoveryCaseSummarySchema),
  recent_lineage_remediations: z.array(LineageRemediationSummarySchema),
  recent_audit_events: z.array(AuditCheckpointSummarySchema),
  metadata: z.record(z.unknown()),
  database_backend: z.enum(['sqlite', 'postgres']),
  persistence_mode: z.string(),
});

export type RoleOSManifest = z.infer<typeof RoleOSManifestSchema>;
export type TrustSnapshot = z.infer<typeof TrustSnapshotSchema>;
export type RecoveryActionResponse = z.infer<typeof RecoveryActionResponseSchema>;
export type OutboxReplayResponse = z.infer<typeof OutboxReplayResponseSchema>;
export type RunRemediationAction = z.infer<typeof RunRemediationActionSchema>;
export type RunRemediationResponse = z.infer<typeof RunRemediationResponseSchema>;
export type LineageRemediationSummary = z.infer<typeof LineageRemediationSummarySchema>;
