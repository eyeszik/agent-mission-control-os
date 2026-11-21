import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  BrandOsAdoptionStatusSchema,
  BrandOsSopDetailSchema,
  BrandOsSopListItemSchema,
} from '../src/schemas/brandOs';

// Recorded by services/langgraph/tests/test_brand_os_api.py from the Python contracts.
const fixture = JSON.parse(readFileSync(join(__dirname, 'fixtures', 'brand-os.json'), 'utf-8')) as {
  sops: unknown[];
  detail: unknown;
  status: Record<string, unknown>;
};

describe('Brand OS API Zod twin', () => {
  it('parses the recorded index, detail and status payloads', () => {
    expect(() => fixture.sops.map((item) => BrandOsSopListItemSchema.parse(item))).not.toThrow();
    expect(BrandOsSopDetailSchema.parse(fixture.detail).steps).toHaveLength(7);
    expect(BrandOsAdoptionStatusSchema.parse(fixture.status).state).toBe('PENDING');
  });

  it('never accepts runtime authority, an original label or extra fields', () => {
    expect(() => BrandOsAdoptionStatusSchema.parse({ ...fixture.status, grants_runtime_authority: true })).toThrow();
    expect(() => BrandOsAdoptionStatusSchema.parse({ ...fixture.status, origin: 'ORIGINAL_CANONICAL_SOP' })).toThrow();
    expect(() => BrandOsAdoptionStatusSchema.parse({ ...fixture.status, extra: 1 })).toThrow();
    expect(() => BrandOsAdoptionStatusSchema.parse({ ...fixture.status, state: 'APPROVED' })).toThrow();
  });
});
