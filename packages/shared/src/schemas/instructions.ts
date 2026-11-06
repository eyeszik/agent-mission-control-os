import { z } from 'zod';

const hash = z.string().regex(/^[a-f0-9]{64}$/);
export const InstructionTaskSchema = z.enum(['research', 'architecture', 'implementation', 'validation', 'delivery']);
const modelRoute = z.strictObject({
  provider: z.enum(['openai', 'anthropic', 'gemini', 'ollama']),
  model: z.string().min(1).max(128).regex(/^[A-Za-z0-9][A-Za-z0-9._:/-]*$/)
    .refine(value => !value.includes('..') && !value.includes('//')),
});
export const InstructionSelectionSchema = z.strictObject({
  task_type: InstructionTaskSchema.default('implementation'),
  max_sections: z.number().int().min(9).max(16).default(16),
  max_bytes: z.number().int().min(256).max(32768).default(32768),
  model_profile: z.strictObject({
    schema_version: z.literal('amc.model-profile/v1').default('amc.model-profile/v1'),
    source: z.enum(['run', 'project', 'tenant', 'deployment']), primary: modelRoute,
    fallbacks: z.array(modelRoute).default([]),
  }).nullable().default(null),
});
export const InstructionSectionSchema = z.strictObject({
  section_id: z.string(), text: z.string(),
  authority: z.enum(['RUNTIME_CONSTRAINT', 'TASK_DATA', 'ADVISORY']),
  requirement_refs: z.array(z.string()), source_refs: z.array(z.string()), mandatory: z.boolean(),
});
const comparison = z.strictObject({
  namespace: z.enum(['N3', 'ROLEOS']), required: z.array(z.string()), registered: z.array(z.string()),
});
export const InstructionPackageSchema = z.strictObject({
  schema_version: z.literal('amc.instruction-package/v1'),
  compiler_version: z.literal('amc.instruction-compiler/v1'),
  tenant_id: z.string().min(1), project_id: z.string().min(1), work_order_id: z.string().min(1),
  contract_hash: hash, context_hash: hash, dependency_hash: hash,
  task_type: InstructionTaskSchema, role_id: z.string(), specialist_role_id: z.string(),
  policy_hash: hash, guidance_hash: hash, adapter_id: z.string(), adapter_version: z.literal('1'),
  model_profile_ref: z.string().nullable(), sections: z.array(InstructionSectionSchema).min(9).max(16),
  comparisons: z.array(comparison), provenance: z.array(z.string()), content_hash: hash,
});
export const InstructionDiffSchema = z.strictObject({
  added: z.array(z.string()), removed: z.array(z.string()), modified: z.array(z.string()),
  affected_requirements: z.array(z.string()), affected_capabilities: z.array(z.string()),
  security_critical: z.array(z.string()), expected_evaluation: z.array(z.string()), approval: z.literal(false),
});
export const InstructionCompilationSchema = z.strictObject({
  package: InstructionPackageSchema.nullable(), blockers: z.array(z.string()),
  rejected: z.array(z.strictObject({ section_id: z.string(), reason: z.string() })),
  bytes_used: z.number().int().nonnegative(), sections_used: z.number().int().nonnegative(),
});
export const InstructionDeliverySchema = z.strictObject({
  status: z.enum(['COMPLETE', 'PARTIAL', 'BLOCKED', 'WAITING_APPROVAL']),
  operation: z.enum(['EXECUTE', 'PROMPT', 'AUDIT', 'PATCH']), artifact: z.string(),
  changes: z.array(z.string()), assumptions: z.array(z.string()),
  evidence: z.array(z.strictObject({
    id: z.string(), claim: z.string(), source: z.string(),
    status: z.enum(['VERIFIED', 'REVIEWED', 'UNVERIFIED']), limitations: z.string(),
  })),
  validation: z.strictObject({
    result: z.enum(['PASS', 'PARTIAL', 'FAIL', 'NOT_APPLICABLE']), checks: z.array(z.string()),
    coverage: z.number().min(0).max(1).nullable(), regressions: z.number().int().nonnegative().nullable(),
    blockers: z.array(z.string()),
  }),
  execution: z.strictObject({
    performed: z.array(z.string()), proposed: z.array(z.string()), pending_approval: z.array(z.string()),
    checkpoint: z.string().nullable(), remaining_budget: z.number().int().nonnegative().nullable(),
  }),
  human_review: z.string().nullable(), next_action: z.string().nullable(),
});
export type InstructionPackage = z.infer<typeof InstructionPackageSchema>;
