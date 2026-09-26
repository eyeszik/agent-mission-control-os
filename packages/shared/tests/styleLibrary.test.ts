import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import {
  STYLE_DIMENSIONS,
  STYLE_ID_PATTERN,
  StyleLibrarySchema,
  StyleDefinitionSchema,
  StyleComposeRequestSchema,
  StyleSelectionSchema,
  DesignStyleSelectionSchema,
  DesignStyleDirectionSchema,
  StyleCatalogResponseSchema,
} from '../src/schemas/styleLibrary';

const catalog = JSON.parse(
  readFileSync(join(__dirname, '../style-library/design-styles.json'), 'utf-8'),
);

describe('canonical style catalog', () => {
  it('validates against the shared schema', () => {
    const result = StyleLibrarySchema.safeParse(catalog);
    if (!result.success) throw new Error(JSON.stringify(result.error.issues, null, 2));
    expect(result.success).toBe(true);
  });

  it('contains the initial named entries', () => {
    const names = catalog.styles.map((s: { name: string }) => s.name);
    for (const name of ['Tenebrism', 'Coquette', 'Bauhaus', 'Glassmorphism', 'Modular Typography', 'Bento Box']) {
      expect(names).toContain(name);
    }
  });

  it('uses only dimensions from the shared vocabulary', () => {
    const vocabulary = new Set<string>(STYLE_DIMENSIONS);
    for (const style of catalog.styles) {
      for (const dimension of style.design_dimensions) expect(vocabulary.has(dimension)).toBe(true);
    }
  });

  it('references only well-formed style ids (pending migrations allowed)', () => {
    for (const style of catalog.styles) {
      for (const ref of [...style.compatible_with, ...style.incompatible_with]) {
        expect(STYLE_ID_PATTERN.test(ref)).toBe(true);
      }
    }
  });

  it('rejects duplicate ids, self references, and compat/incompat overlap', () => {
    const style = catalog.styles[0];
    expect(StyleLibrarySchema.safeParse({ ...catalog, styles: [style, style] }).success).toBe(false);
    expect(StyleDefinitionSchema.safeParse({ ...style, compatible_with: [style.id] }).success).toBe(false);
    expect(
      StyleDefinitionSchema.safeParse({ ...style, compatible_with: ['MOD-03'], incompatible_with: ['MOD-03'] }).success,
    ).toBe(false);
  });

  it('parses the catalog API response shape', () => {
    const response = { ...catalog, pending_references: ['LFS-05'] };
    expect(StyleCatalogResponseSchema.safeParse(response).success).toBe(true);
  });
});

describe('style selections', () => {
  it('applies layer defaults', () => {
    const parsed = StyleSelectionSchema.parse({ style_id: 'MOD-03' });
    expect(parsed).toEqual({ style_id: 'MOD-03', role: 'secondary', strength: 0.5, dimensions: [], locked: false });
  });

  it('rejects out-of-range strength and unknown dimensions', () => {
    expect(StyleSelectionSchema.safeParse({ style_id: 'MOD-03', strength: 1.2 }).success).toBe(false);
    expect(StyleSelectionSchema.safeParse({ style_id: 'MOD-03', dimensions: ['vibes'] }).success).toBe(false);
  });

  it('enforces one primary and unique styles per compose request', () => {
    const twoPrimaries = {
      selections: [
        { style_id: 'MOD-03', role: 'primary' },
        { style_id: 'MOD-04', role: 'primary' },
      ],
    };
    expect(StyleComposeRequestSchema.safeParse(twoPrimaries).success).toBe(false);
    const duplicate = { selections: [{ style_id: 'MOD-03' }, { style_id: 'MOD-03' }] };
    expect(StyleComposeRequestSchema.safeParse(duplicate).success).toBe(false);
    expect(StyleComposeRequestSchema.safeParse({ selections: [{ style_id: 'MOD-03' }] }).success).toBe(true);
  });

  it('models the run-level selection and the persisted direction', () => {
    const selection = DesignStyleSelectionSchema.parse({ selections: [{ style_id: 'CLS-01', role: 'primary' }] });
    expect(selection.catalog_version).toBe('style-library-v1');
    const direction = {
      composition_id: 'cmp-0123456789abcdef',
      catalog_version: 'style-library-v1',
      selections: selection.selections,
      resolved_dimensions: { lighting: 'CLS-01' },
      prompt: 'Objective: x.',
      blocking: false,
      applied: true,
    };
    expect(DesignStyleDirectionSchema.safeParse(direction).success).toBe(true);
  });
});
