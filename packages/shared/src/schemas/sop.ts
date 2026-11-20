import { z } from 'zod';

/**
 * Zod twin of services/langgraph/agency/sop/contracts.py (amc-sop-registry/v1).
 * The canonical bytes are services/langgraph/agency/sop/data/sop_registry.v1.json;
 * tests/fixtures/sop-registry.json is a recorded copy kept equal by
 * services/langgraph/tests/test_sop_contracts.py.
 */
export const SopFailureDispositionSchema = z.enum(['FALLBACK_DEGRADED', 'BLOCKED']);
export const SopStepKindSchema = z.enum(['production', 'measurement', 'gate', 'recovery']);

export const SopGateBindingSchema = z
  .object({
    governance_level: z.enum(['G0', 'G1', 'G2']),
    gates: z.array(z.string()).min(1),
  })
  .strict();

export const SopStepSchema = z
  .object({
    sop_id: z.string().regex(/^SOP-[A-Z]+(-[A-Z]+)?-\d{2}$/),
    stage_name: z.string().min(1),
    kind: SopStepKindSchema,
    owner_role: z.string().min(1),
    roleos_skill: z.string().nullable(),
    entry_preconditions: z.array(z.string()).min(1),
    requires_state: z.array(z.string()),
    input_schema: z.record(z.string(), z.string()),
    output_schema: z.record(z.string(), z.string()),
    exit_postconditions: z.array(z.string()).min(1),
    idempotency_key_formula: z.string().min(1),
    gate_binding: SopGateBindingSchema,
    retry_and_lease_bounds: z.record(z.string(), z.union([z.string(), z.number()])),
    failure_disposition: SopFailureDispositionSchema,
    enforced_by: z.array(z.string()).min(1),
    tests: z.array(z.string()).min(1),
  })
  .strict();

export const SopProcedureSchema = z
  .object({
    procedure_id: z.string().min(1),
    kind: z.enum(['pipeline', 'recovery']),
    workflow_version: z.string().nullable(),
    steps: z.array(z.object({ sequence_index: z.number().int().min(1), sop_id: z.string() }).strict()).min(1),
  })
  .strict();

type SopStep = z.infer<typeof SopStepSchema>;
type SopProcedure = z.infer<typeof SopProcedureSchema>;

/** The same structural rules as `structural_problems` in contracts.py. */
export function sopStructuralProblems(steps: SopStep[], procedures: SopProcedure[]): string[] {
  const byId = new Map<string, SopStep>(steps.map((step) => [step.sop_id, step]));
  const problems: string[] = [];
  if (byId.size !== steps.length) problems.push('duplicate sop_id');
  for (const procedure of procedures) {
    const ordered = [...procedure.steps].sort((a, b) => a.sequence_index - b.sequence_index);
    if (!ordered.every((entry, index) => entry.sequence_index === index + 1)) {
      problems.push(`${procedure.procedure_id}: sequence_index must be contiguous from 1`);
    }
    if (new Set(ordered.map((entry) => entry.sop_id)).size !== ordered.length) {
      problems.push(`${procedure.procedure_id}: a step repeats, so the procedure is cyclic`);
    }
    if (procedure.kind !== 'pipeline') continue;
    const produced = new Set<string>();
    for (const entry of ordered) {
      const step = byId.get(entry.sop_id);
      if (!step) {
        problems.push(`${procedure.procedure_id}: unknown sop_id ${entry.sop_id}`);
        continue;
      }
      for (const key of step.requires_state) {
        if (!produced.has(key)) problems.push(`${procedure.procedure_id}: ${step.sop_id} requires ${key} before any step produces it`);
      }
      Object.keys(step.output_schema).forEach((key) => produced.add(key));
    }
  }
  return problems;
}

export const SopRegistrySchema = z
  .object({
    schema_version: z.literal('amc-sop-registry/v1'),
    description: z.string(),
    owner_principals: z.array(z.string()),
    steps: z.array(SopStepSchema).min(1),
    procedures: z.array(SopProcedureSchema).min(1),
  })
  .strict()
  .superRefine((registry, ctx) => {
    for (const problem of sopStructuralProblems(registry.steps, registry.procedures)) {
      ctx.addIssue({ code: 'custom', message: problem });
    }
  });

export type SopRegistry = z.infer<typeof SopRegistrySchema>;
