import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  UcpoBrowserVerificationSchema,
  UcpoCompileResponseSchema,
  UcpoReleaseProofSchema,
  UcpoRequirementsPackageSchema,
  UcpoSemanticCoverageReportSchema,
  UcpoSiteListSchema,
  UcpoSiteViewSchema,
  UcpoTraceSchema,
  UcpoWebsiteBriefSchema,
} from '../src/schemas/ucpo';

// Recorded from the real backend by services/langgraph/tests/test_ucpo_contracts.py.
const fixture = JSON.parse(readFileSync(join(__dirname, 'fixtures', 'ucpo.json'), 'utf-8'));

describe('UCPO Zod twins parse real backend output', () => {
  const cases: [string, { parse: (v: unknown) => unknown }, unknown][] = [
    ['brief', UcpoWebsiteBriefSchema, fixture.brief],
    ['requirements', UcpoRequirementsPackageSchema, fixture.requirements],
    ['coverage', UcpoSemanticCoverageReportSchema, fixture.coverage],
    ['browser verification', UcpoBrowserVerificationSchema, fixture.browser_verification],
    ['release proof', UcpoReleaseProofSchema, fixture.release_proof],
    ['compile response', UcpoCompileResponseSchema, fixture.compile_response],
    ['site view', UcpoSiteViewSchema, fixture.site_view],
    ['site list', UcpoSiteListSchema, fixture.site_list],
    ['trace', UcpoTraceSchema, fixture.trace],
  ];
  for (const [name, schema, value] of cases) {
    it(`parses the ${name}`, () => expect(() => schema.parse(value)).not.toThrow());
  }

  it('never authorizes deployment and keeps an unbuilt site blocked', () => {
    expect(UcpoReleaseProofSchema.parse(fixture.release_proof).deployment).toBe('NOT_AUTHORIZED');
    const view = UcpoSiteViewSchema.parse(fixture.site_view);
    expect(view.release.allowed).toBe(false);
    expect(view.proof).toBeNull();
    const trace = UcpoTraceSchema.parse(fixture.trace);
    expect(trace.status.status).toBe('UNRESOLVED');
  });

  it('refuses a proof that claims deployment authority', () => {
    expect(() => UcpoReleaseProofSchema.parse({ ...fixture.release_proof, deployment: 'AUTHORIZED' })).toThrow();
  });
});
