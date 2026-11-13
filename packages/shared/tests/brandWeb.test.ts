import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { BrandSiteRequestSchema, BrandSiteResponseSchema } from '../src/schemas/brandWeb';

const fixture: unknown = JSON.parse(readFileSync(join(__dirname, 'fixtures', 'brand-web.json'), 'utf-8'));

describe('approved-brand to UCPO contracts', () => {
  it('parses Python request and real API response', () => {
    const f = fixture as { request: unknown; response: unknown };
    expect(BrandSiteRequestSchema.parse(f.request).mapping.pages).toHaveLength(7);
    const output = BrandSiteResponseSchema.parse(f.response);
    expect(output.external_effects).toBe('none');
    expect(output.brand.layers).not.toHaveLength(0);
  });
  it('accepts the same omitted request defaults as Pydantic', () => {
    const request = BrandSiteRequestSchema.parse({ site_id: 'example', brand_id: 'brand-example', mapping: {
      cta_target: 'index', pages: [{ slug: 'index', title_key: 'verbal.messaging.title',
        description_key: 'verbal.messaging.description', sections: [{ kind: 'hero', heading_key: 'verbal.messaging.title' }] }],
    } });
    expect(request.mapping.locale).toBe('en');
    expect(request.mapping.pages[0].sections[0].cta).toBe(false);
    expect(request.mapping.pages[0].sections[0].body_key).toBeNull();
    expect(request.mapping.images).toEqual([]);
  });
  it('rejects smuggled authority and duplicate pages', () => {
    const f = fixture as { request: Record<string, unknown> };
    const request = BrandSiteRequestSchema.parse(f.request);
    expect(() => BrandSiteRequestSchema.parse({ ...request, tenant_id: 'other' })).toThrow();
    expect(() => BrandSiteRequestSchema.parse({ ...request,
      mapping: { ...request.mapping, pages: [request.mapping.pages[0], request.mapping.pages[0]] } })).toThrow();
  });
});
