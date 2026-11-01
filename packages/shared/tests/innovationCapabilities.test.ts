import computationFixture from './fixtures/innovation-local-computation.json';
import { describe, expect, it } from 'vitest';
import generationFixture from './fixtures/innovation-generation.json';
import { InnovationGenerationStageSchema, InnovationGenerationResultSchema, InnovationGenerationSpecSchema, InnovationLocalExperimentSchema } from '../src/schemas/innovationCapabilities';

describe('UNBOUND independent capability boundaries', () => {
  it('parses actual fabric receipt IDs without assuming agency UUIDs', () => {
    const result = InnovationLocalExperimentSchema.parse(computationFixture);
    expect(result.status).toBe('COMPLETED');
    if (result.status !== 'COMPLETED') throw new Error('Expected local computation');
    expect(result.proof.execution_receipts[0].run_id).toBe(result.fabric_run_id);
    expect(result.measurements.baseline_redundant_items).toBe(4);
    expect(result.measurements.candidate_redundant_items).toBe(0);
  });
  it('parses a generation-stage fixture emitted by the Python model', () => {
    const stage = InnovationGenerationStageSchema.parse(generationFixture);
    expect(stage.output).toBeNull();
    expect(stage.reasons).toContain('CREDENTIALS_UNAVAILABLE_OR_PROVIDER_REVOKED');
    expect(stage.spec.max_calls).toBe(1);
    expect(stage.spec.max_cost_usd).toBe(0);
  });
  it('rejects fabricated experiment observations and release authority', () => {
    expect(InnovationLocalExperimentSchema.safeParse({ schema_version: 'innovation.local-experiment/v1', status: 'COMPLETED', release_authorized: true, measurements: {} }).success).toBe(false);
    expect(InnovationLocalExperimentSchema.safeParse({ schema_version: 'innovation.local-experiment/v1', status: 'BLOCKED', report: {}, limitations: ['No receipt committed'] }).success).toBe(true);
  });
  it('keeps generated claims as hypotheses and refuses fabricated verification', () => {
    const output = { schema_version: 'unbound.generation-result/v1', state: 'FAILED', ideas: [], coverage: [], duplicate_groups: [], limitations: ['Invalid provider output'], receipt: null, evidence_class: 'HYPOTHESIS' };
    expect(InnovationGenerationResultSchema.safeParse(output).success).toBe(true);
    expect(InnovationGenerationResultSchema.safeParse({ ...output, evidence_class: 'MEASURED' }).success).toBe(false);
    expect(InnovationGenerationResultSchema.safeParse({ ...output, approved: true }).success).toBe(false);
  });
  it('refuses source identity, provider permissions and resource ceilings missing from a plan', () => {
    expect(InnovationGenerationSpecSchema.safeParse({ run_id: 'r', authorized: true }).success).toBe(false);
  });
});
