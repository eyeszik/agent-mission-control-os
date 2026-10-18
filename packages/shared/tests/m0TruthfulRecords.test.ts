import { describe, it, expect } from 'vitest';
import { CompletionEvaluationSchema, GenerationProvenanceSchema } from '../src/schemas/agency';

const base = {
  terminal_candidate: 'BLOCKED' as const,
  criteria: [{ criterion_ref: 'execution', status: 'SATISFIED' }],
  proof_coverage: 0.5,
  confidence: 0.5,
};

describe('completion scores are measured or NOT_MEASURED', () => {
  it('accepts NOT_MEASURED for evidence and quality', () => {
    const parsed = CompletionEvaluationSchema.parse({ ...base, evidence_score: 'NOT_MEASURED', quality_score: 'NOT_MEASURED' });
    expect(parsed.evidence_score).toBe('NOT_MEASURED');
    expect(parsed.quality_score).toBe('NOT_MEASURED');
  });

  it('accepts a bounded numeric measurement', () => {
    expect(CompletionEvaluationSchema.parse({ ...base, evidence_score: 0.8, quality_score: 0.9 }).quality_score).toBe(0.9);
  });

  it('rejects any other string or an out-of-range number', () => {
    expect(() => CompletionEvaluationSchema.parse({ ...base, quality_score: 'UNKNOWN' })).toThrow();
    expect(() => CompletionEvaluationSchema.parse({ ...base, evidence_score: 1.5, quality_score: 0.5 })).toThrow();
  });
});

describe('generation provenance carries the fields the backend writes', () => {
  const full = {
    task: 'brand_strategy',
    mode: 'PROVIDER_SUCCESS' as const,
    provider: 'gemini',
    model: 'fixture-model',
    schema_version: 'brand-strategy-v1',
    prompt_version: 'agency-v1',
    prompt_hash: 'a'.repeat(64),
    attempts: 1,
    started_at: '2026-10-18T00:00:00+00:00',
    completed_at: '2026-10-18T00:00:01+00:00',
    fallback_used: false,
    error_class: null,
    route: ['gemini'],
    profile_hash: 'b'.repeat(64),
    usage: { input_tokens: 4, output_tokens: 2, total_tokens: 6 },
    usage_reported: true,
    unreported_token_estimate: 0,
  };

  it('keeps route, profile, usage and usage-reporting fields', () => {
    const parsed = GenerationProvenanceSchema.parse(full);
    expect(parsed.route).toEqual(['gemini']);
    expect(parsed.profile_hash).toBe('b'.repeat(64));
    expect(parsed.usage.total_tokens).toBe(6);
    expect(parsed.usage_reported).toBe(true);
  });

  it('still parses rows stored before those fields existed', () => {
    const legacy = Object.fromEntries(Object.entries(full).filter(([k]) =>
      !['route', 'profile_hash', 'usage', 'usage_reported', 'unreported_token_estimate'].includes(k)));
    const parsed = GenerationProvenanceSchema.parse(legacy);
    expect(parsed.route).toEqual([]);
    expect(parsed.profile_hash).toBeNull();
    expect(parsed.usage_reported).toBe(true);
    expect(parsed.unreported_token_estimate).toBe(0);
  });
});
