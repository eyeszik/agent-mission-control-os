import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  AvicApprovalResponseSchema,
  AvicAssetListSchema,
  AvicAssetViewSchema,
  AvicCapabilitiesSchema,
  AvicCompileResponseSchema,
  AvicConflictSchema,
  AvicEditResponseSchema,
  AvicRecompileResponseSchema,
  AvicReleaseResponseSchema,
} from '../src/schemas/avic';

// Recorded from the real backend by services/langgraph/tests/test_avic_contracts.py.
const fixture = JSON.parse(readFileSync(join(__dirname, 'fixtures', 'avic.json'), 'utf-8'));

describe('AVIC Zod twins parse real backend output', () => {
  const cases: [string, { parse: (v: unknown) => unknown }, unknown][] = [
    ['capabilities', AvicCapabilitiesSchema, fixture.capabilities],
    ['asset list', AvicAssetListSchema, fixture.asset_list],
    ['compile response', AvicCompileResponseSchema, fixture.compile_response],
    ['asset view', AvicAssetViewSchema, fixture.asset_view],
    ['asset view after release attempt', AvicAssetViewSchema, fixture.asset_view_after],
    ['edit response', AvicEditResponseSchema, fixture.edit_response],
    ['conflict', AvicConflictSchema, fixture.conflict],
    ['recompile response', AvicRecompileResponseSchema, fixture.recompile_response],
    ['approval response', AvicApprovalResponseSchema, fixture.approval_response],
    ['release response', AvicReleaseResponseSchema, fixture.release_response],
  ];
  for (const [name, schema, value] of cases) {
    it(`parses the ${name}`, () => expect(() => schema.parse(value)).not.toThrow());
  }

  it('keeps an unapproved release blocked and effect-free', () => {
    const release = AvicReleaseResponseSchema.parse(fixture.release_response);
    expect(release.status).toBe('BLOCKED');
    expect(release.manifest?.external_effects).toBe('none');
    expect(AvicAssetViewSchema.parse(fixture.asset_view_after).release?.release_allowed).toBe(false);
  });

  it('refuses a release manifest that claims an external effect', () => {
    expect(() => AvicReleaseResponseSchema.parse({
      ...fixture.release_response, manifest: { ...fixture.release_response.manifest, external_effects: 'published' },
    })).toThrow();
  });
});
