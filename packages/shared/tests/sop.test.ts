import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { AGENCY_PIPELINE_STAGES } from '../src/schemas/agency';
import { SopRegistrySchema } from '../src/schemas/sop';

// Recorded copy of services/langgraph/agency/sop/data/sop_registry.v1.json,
// kept byte-equal by services/langgraph/tests/test_sop_contracts.py.
const fixture: unknown = JSON.parse(readFileSync(join(__dirname, 'fixtures', 'sop-registry.json'), 'utf-8'));

function clone(): { procedures: { steps: { sequence_index: number; sop_id: string }[] }[] } {
  return JSON.parse(JSON.stringify(fixture));
}

describe('SOP registry Zod twin', () => {
  it('parses the canonical registry', () => {
    expect(() => SopRegistrySchema.parse(fixture)).not.toThrow();
  });

  it('orders the legacy pipeline exactly like the shared stage list', () => {
    const registry = SopRegistrySchema.parse(fixture);
    const legacy = registry.procedures.find((p) => p.procedure_id === 'PIPELINE.agency/v1-legacy');
    const stages = (legacy?.steps ?? [])
      .slice()
      .sort((a, b) => a.sequence_index - b.sequence_index)
      .map((entry) => registry.steps.find((step) => step.sop_id === entry.sop_id)?.stage_name);
    expect(stages).toEqual([...AGENCY_PIPELINE_STAGES]);
  });

  it('rejects a gap in sequence_index', () => {
    const broken = clone();
    broken.procedures[0].steps[3].sequence_index = 7;
    expect(SopRegistrySchema.safeParse(broken).success).toBe(false);
  });

  it('rejects a step that reads state no earlier step produced', () => {
    const broken = clone();
    const steps = broken.procedures[0].steps;
    [steps[1].sop_id, steps[3].sop_id] = [steps[3].sop_id, steps[1].sop_id];
    const result = SopRegistrySchema.safeParse(broken);
    expect(result.success).toBe(false);
    expect(JSON.stringify(result.error?.issues)).toContain('requires brand_strategy before');
  });
});
