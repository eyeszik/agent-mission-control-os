import { BrandBookPackageSchema, BrandBookTemplateSchema } from '@amc/shared';
import { describe, expect, it } from 'vitest';
import { DEFAULT_MANIFEST, bookContext, compileBook, manifestHash, markAsset } from '../src/index';

// The twin's output must satisfy the Zod twins already shipped in @amc/shared (vnexusBrandbook.ts).
describe('@amc/shared brand book schemas', () => {
  it('accepts the template and a compiled package', () => {
    const template = { manifest: DEFAULT_MANIFEST, manifest_hash: manifestHash(DEFAULT_MANIFEST),
      modes: ['SYSTEM_SPEC_ONLY', 'PROMPTS_ONLY', 'PREVIEW', 'PRODUCTION'] };
    expect(BrandBookTemplateSchema.safeParse(template).success).toBe(true);
    const mark = markAsset({ kind: 'MISSING', source: 'none' });
    const ctx = bookContext({ brand_id: 'b', brand_name: 'B', genome_ref: 'g', resolution_hash: 'ab'.repeat(32), approved: {}, mode: 'PREVIEW', mark });
    const parsed = BrandBookPackageSchema.safeParse(JSON.parse(JSON.stringify(compileBook(ctx))));
    expect(parsed.success, JSON.stringify(parsed.error?.issues.slice(0, 3))).toBe(true);
  });
});
