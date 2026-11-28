import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  BrandBookBuildSchema,
  BrandBookCompileSchema,
  BrandBookCurrentSchema,
  BrandBookGapsSchema,
  BrandBookIntakeSavedSchema,
  BrandBookIntakeSchema,
  BrandBookTemplateSchema,
} from '../src/schemas/vnexusBrandbook';

// Recorded from the real backend by services/langgraph/tests/test_vnexus_brandbook_contracts.py.
const fixture = JSON.parse(readFileSync(join(__dirname, 'fixtures', 'vnexus-brandbook.json'), 'utf-8'));

describe('VNEXUS brand book Zod twins parse real backend output', () => {
  const cases: [string, { parse: (v: unknown) => unknown }, unknown][] = [
    ['template', BrandBookTemplateSchema, fixture.template],
    ['intake', BrandBookIntakeSchema, fixture.intake],
    ['saved intake', BrandBookIntakeSavedSchema, fixture.intake_saved],
    ['gaps', BrandBookGapsSchema, fixture.gaps],
    ['compile', BrandBookCompileSchema, fixture.compile],
    ['build', BrandBookBuildSchema, fixture.build],
    ['current build', BrandBookCurrentSchema, fixture.current],
  ];
  for (const [name, schema, value] of cases) {
    it(`parses the ${name}`, () => expect(() => schema.parse(value)).not.toThrow());
  }

  it('keeps the template ordered and the build honest about what it did', () => {
    const template = BrandBookTemplateSchema.parse(fixture.template);
    expect(template.manifest.pages.map((p) => p.order)).toEqual(Array.from({ length: 24 }, (_, i) => i + 1));
    const build = BrandBookBuildSchema.parse(fixture.build);
    expect(build.telemetry.model_calls).toBe(0);
    expect(build.states.released).toBe('NOT_RELEASED');
    expect(BrandBookCurrentSchema.parse(fixture.current).freshness.fresh).toBe(true);
  });

  it('accepts a build that reports a missing PDF or page preview, and only in its declared shape', () => {
    const failed = { ...fixture.build, pdf_failure: ['BROWSER_EXIT:1'], capture_failures: { p06: ['CAPTURE_FAILED:p06: Timeout'] } };
    expect(BrandBookBuildSchema.parse(failed).capture_failures).toEqual({ p06: ['CAPTURE_FAILED:p06: Timeout'] });
    expect(() => BrandBookBuildSchema.parse({ ...fixture.build, capture_failures: { p06: [] } })).toThrow();
    expect(() => BrandBookBuildSchema.parse({ ...fixture.build, capture_failures: { 'p06-2': ['x'] } })).toThrow();
    expect(() => BrandBookBuildSchema.parse({ ...fixture.build, pdf_failure: [] })).toThrow();
  });

  it('refuses a build that claims model calls or an unknown status', () => {
    expect(() => BrandBookBuildSchema.parse({ ...fixture.build, telemetry: { ...fixture.build.telemetry, model_calls: 3 } })).toThrow();
    expect(() => BrandBookBuildSchema.parse({ ...fixture.build, status: 'RELEASED' })).toThrow();
  });
});
