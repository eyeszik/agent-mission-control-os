import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  ArtDirectionClaimSchema,
  AuditResponseSchema,
  BranchComparisonSchema,
  BranchSchema,
  BrandSchema,
  CompareResponseSchema,
  GenomeDocumentSchema,
  GenomeVersionSchema,
  GraphViewSchema,
  ImmuneScanSchema,
  ImpactSchema,
  MediaJobSchema,
  PromptInventorySchema,
  ProviderSchema,
  ReadinessSchema,
  ResolveResponseSchema,
  TwinSnapshotSchema,
} from '../src/schemas/vnexus';

// Recorded from the real API by services/langgraph/tests/test_vnexus_contracts.py.
const fixture = JSON.parse(readFileSync(join(__dirname, 'fixtures', 'vnexus.json'), 'utf-8'));

describe('VNEXUS Zod twins parse real backend responses', () => {
  const cases: [string, { parse: (v: unknown) => unknown }, unknown][] = [
    ['brand', BrandSchema, fixture.brand],
    ['genome version', GenomeVersionSchema, fixture.version],
    ['readiness', ReadinessSchema, fixture.readiness],
    ['resolve', ResolveResponseSchema, fixture.resolve],
    ['compare', CompareResponseSchema, fixture.compare],
    ['audit', AuditResponseSchema, fixture.audit],
    ['branch', BranchSchema, fixture.branch],
    ['branch comparison', BranchComparisonSchema, fixture.branch_comparison],
    ['graph', GraphViewSchema, fixture.graph],
    ['impact', ImpactSchema, fixture.impact],
    ['media job', MediaJobSchema, fixture.media_job],
    ['immune scan', ImmuneScanSchema, fixture.immune_scan],
    ['twin', TwinSnapshotSchema, fixture.twin],
    ['prompt inventory', PromptInventorySchema, fixture.prompt_inventory],
  ];
  it.each(cases)('%s', (_name, schema, value) => {
    expect(() => schema.parse(value)).not.toThrow();
  });

  it('every provider and art-direction claim parses', () => {
    for (const p of fixture.providers) ProviderSchema.parse(p);
    for (const c of fixture.art_direction_claims) ArtDirectionClaimSchema.parse(c);
    expect(fixture.providers.some((p: { status: string }) => p.status === 'DISABLED')).toBe(true);
  });

  it('rejects drift: unknown keys and wrong enums fail', () => {
    expect(() => GenomeVersionSchema.parse({ ...fixture.version, tenant_secret: 'x' })).toThrow();
    expect(() => MediaJobSchema.parse({ ...fixture.media_job, state: 'GENERATED' })).toThrow();
    expect(() => GenomeDocumentSchema.parse({ ...fixture.version.document, schema_version: 'v0' })).toThrow();
  });

  it('records what the contract means, not only its shape', () => {
    expect(fixture.media_job.state).toBe('QC_PASSED');
    expect(fixture.media_job.claimable_as_generated).toBe(true);
    expect(fixture.prompt_inventory.expected_originals).toBe(14);
    expect(fixture.audit.verification.intact).toBe(true);
  });
});
