import { describe, expect, it } from 'vitest';
import fixture from './fixtures/instruction-packages.json';
import { InstructionDeliverySchema, InstructionDiffSchema, InstructionPackageSchema } from '../src/schemas/instructions';

describe('Python-owned instruction contracts (fictional inputs)', () => {
  it('accepts all five task packages without granting authority', () => {
    for (const candidate of fixture.packages) {
      const parsed = InstructionPackageSchema.parse(candidate);
      for (const check of parsed.comparisons) {
        expect(check.required.every(capability => check.registered.includes(capability))).toBe(true);
      }
    }
    expect(InstructionDiffSchema.parse(fixture.diff).approval).toBe(false);
  });
  it('preserves unknown measurements and refuses fabricated fields', () => {
    const parsed = InstructionDeliverySchema.parse(fixture.delivery);
    expect(parsed.validation.coverage).toBeNull();
    expect(parsed.execution.remaining_budget).toBeNull();
    expect(InstructionDeliverySchema.safeParse({ ...fixture.delivery, approved: true }).success).toBe(false);
    expect(InstructionPackageSchema.safeParse({ ...fixture.packages[0], permission: 'all' }).success).toBe(false);
    expect(InstructionDiffSchema.safeParse({ ...fixture.diff, approval: true }).success).toBe(false);
  });
});
