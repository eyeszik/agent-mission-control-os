import { describe, expect, it } from 'vitest';
import fixture from './fixtures/innovation.json';
import { InnovationBriefSchema, InnovationRunSchema } from '../src/schemas/innovation';

describe('UNBOUND shared wire contract', () => {
  it('parses the full cohort emitted by the Python offline compiler', () => {
    const run = InnovationRunSchema.parse(fixture);
    expect(run.ideas).toHaveLength(35);
    expect(run.hybrids).toHaveLength(4);
    expect(run.meta_hybrids).toHaveLength(2);
    expect(run.experiments.every((e) => e.execution_state === 'NOT_RUN')).toBe(true);
  });
  it('refuses undeclared authority and fabricated execution states', () => {
    expect(InnovationRunSchema.safeParse({ ...fixture, approved: true }).success).toBe(false);
    const experiments = fixture.experiments.map((e) => ({ ...e, execution_state: 'SUCCEEDED' }));
    expect(InnovationRunSchema.safeParse({ ...fixture, experiments }).success).toBe(false);
  });
  it('accepts bounded retry exhaustion and rejects incompatible status/phase pairs', () => {
    const run = { ...fixture, status: 'BLOCKED', phase: 'RETRY_EXHAUSTED', ideas: [], wildcards: [], hybrids: [], meta_hybrids: [], lineage: [], shortlist: [], evaluations: [], experiments: [] };
    expect(InnovationRunSchema.safeParse(run).success).toBe(true);
    expect(InnovationRunSchema.safeParse({ ...run, status: 'RECEIVED' }).success).toBe(false);
    expect(InnovationRunSchema.safeParse({ ...run, phase: 'COMPLETED' }).success).toBe(false);
  });
  it('rejects blank, oversized and authority-bearing briefs', () => {
    expect(InnovationBriefSchema.safeParse({ objective: ' '.repeat(20) }).success).toBe(false);
    expect(InnovationBriefSchema.safeParse({ objective: 'x'.repeat(4001) }).success).toBe(false);
    expect(InnovationBriefSchema.safeParse({ objective: 'A fictional brief', tenant_id: 'forged' }).success).toBe(false);
  });
});
