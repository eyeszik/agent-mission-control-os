import { z } from 'zod';

/**
 * ACE v100 wire contracts. Strict parsing is deliberate: Zod's default
 * z.object() strips unknown keys and would silently lose audit fields.
 * These contracts are opt-in, preserving existing public API behavior.
 */
const digest = z.string().regex(/^[0-9a-f]{64}$/);
const nonempty = z.string().min(1);
const dateTimeWithZone = z.string().datetime({ offset: true });

export const AceRiskTierSchema = z.enum(['R0', 'R1', 'R2', 'R3', 'R4', 'R5']);

export const AceMissionSchema = z.object({
  schema_version: z.literal('ace.mission.v1').default('ace.mission.v1'),
  mission_id: nonempty.max(128),
  tenant_id: nonempty.max(128),
  project_id: nonempty.max(128),
  goal: nonempty.max(10000),
  constraints: z.record(z.string(), z.unknown()).default({}),
  policy_version: nonempty,
}).strict();

export const AceTaskSchema = z.object({
  schema_version: z.literal('ace.task.v1').default('ace.task.v1'),
  task_id: nonempty,
  mission_id: nonempty,
  dependencies: z.array(nonempty).default([]),
  capability: nonempty,
  risk_tier: AceRiskTierSchema.default('R0'),
  deadline: dateTimeWithZone.nullable().optional(),
}).strict().superRefine((value, context) => {
  if (value.dependencies.includes(value.task_id) ||
      new Set(value.dependencies).size !== value.dependencies.length) {
    context.addIssue({ code: z.ZodIssueCode.custom, message: 'self or duplicate dependencies' });
  }
});

export const AceCapabilitySchema = z.object({
  provider_id: nonempty,
  model_id: nonempty,
  capabilities: z.array(nonempty).min(1),
  complexity_ceiling: z.number().int().min(1).max(5),
  available: z.boolean().default(true),
  priority: z.number().int().nonnegative(),
  rate_limit_per_minute: z.number().int().positive(),
  cost_per_million_tokens: z.number().finite().nonnegative(),
}).strict();

export const AceEvidenceItemSchema = z.object({
  claim_id: nonempty,
  source_ref: nonempty,
  observed_at: dateTimeWithZone,
  status: z.enum(['VERIFIED', 'FLAGGED', 'VOID', 'SPECULATIVE']),
  metadata_digest: digest,
}).strict();

export const AceAuditRecordSchema = z.object({
  sequence: z.number().int().positive(),
  previous_hash: digest,
  payload_digest: digest,
  record_hash: digest,
  signature: digest,
}).strict();

export const AceContractSchemas = {
  mission: AceMissionSchema,
  task: AceTaskSchema,
  capability: AceCapabilitySchema,
  evidence: AceEvidenceItemSchema,
  audit: AceAuditRecordSchema,
} as const;
export type AceMission = z.infer<typeof AceMissionSchema>;
export type AceTask = z.infer<typeof AceTaskSchema>;
export type AceCapability = z.infer<typeof AceCapabilitySchema>;
export type AceEvidenceItem = z.infer<typeof AceEvidenceItemSchema>;
export type AceAuditRecord = z.infer<typeof AceAuditRecordSchema>;
