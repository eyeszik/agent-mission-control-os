import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { StyleLibrarySchema, type StyleDefinition, type StyleSelection } from '@amc/shared';
import {
  MAX_LAYERS,
  addLayer,
  filterStyles,
  indexStyles,
  precheck,
  removeLayer,
  selectionKey,
  setRole,
  setStrength,
  toDesignStyleSelection,
  toggleDimension,
  toggleLock,
} from '../lib/design/composer';
import { useDesignStore } from '../lib/stores/designStore';
import { composeDesignStyle, getDesignStyleLibrary } from '../lib/api/design';

const catalog = StyleLibrarySchema.parse(
  JSON.parse(readFileSync(join(__dirname, '../../../packages/shared/style-library/design-styles.json'), 'utf-8')),
);
const index = indexStyles(catalog.styles);
const style = (id: string): StyleDefinition => {
  const found = index.get(id);
  if (!found) throw new Error(`fixture missing ${id}`);
  return found;
};

describe('layer operations', () => {
  it('adds a layer with the style defaults', () => {
    const layers = addLayer([], style('MOD-03'), 'primary');
    expect(layers).toEqual([
      {
        style_id: 'MOD-03',
        role: 'primary',
        strength: style('MOD-03').recommended_strength,
        dimensions: style('MOD-03').design_dimensions,
        locked: false,
      },
    ]);
  });

  it('keeps at most one primary', () => {
    let layers = addLayer([], style('MOD-03'), 'primary');
    layers = addLayer(layers, style('CLS-01'), 'primary');
    expect(layers.filter((l) => l.role === 'primary').map((l) => l.style_id)).toEqual(['CLS-01']);
    layers = setRole(layers, 'MOD-03', 'primary');
    expect(layers.filter((l) => l.role === 'primary').map((l) => l.style_id)).toEqual(['MOD-03']);
  });

  it('re-adding a style changes its role instead of duplicating it', () => {
    let layers = addLayer([], style('MOD-03'), 'secondary');
    layers = addLayer(layers, style('MOD-03'), 'primary');
    expect(layers).toHaveLength(1);
    expect(layers[0].role).toBe('primary');
  });

  it(`caps the stack at ${MAX_LAYERS} layers`, () => {
    let layers: StyleSelection[] = [];
    for (const item of catalog.styles) layers = addLayer(layers, item, 'secondary');
    expect(layers.length).toBeLessThanOrEqual(MAX_LAYERS);
  });

  it('clamps and rounds strength', () => {
    let layers = addLayer([], style('MOD-03'), 'primary');
    expect(setStrength(layers, 'MOD-03', 1.7)[0].strength).toBe(1);
    expect(setStrength(layers, 'MOD-03', -2)[0].strength).toBe(0);
    layers = setStrength(layers, 'MOD-03', 0.333333);
    expect(layers[0].strength).toBe(0.33);
  });

  it('toggles dimensions in canonical order and toggles locks', () => {
    let layers = addLayer([], style('CLS-01'), 'primary');
    layers = toggleDimension(layers, 'CLS-01', 'lighting');
    expect(layers[0].dimensions).not.toContain('lighting');
    layers = toggleDimension(layers, 'CLS-01', 'lighting');
    expect(layers[0].dimensions).toContain('lighting');
    layers = toggleLock(layers, 'CLS-01');
    expect(layers[0].locked).toBe(true);
    expect(removeLayer(layers, 'CLS-01')).toEqual([]);
  });
});

describe('precheck', () => {
  it('flags declared incompatibility', () => {
    const layers = addLayer(addLayer([], style('CLS-02'), 'primary'), style('MOD-01'), 'secondary');
    expect(precheck(layers, index).conflicts.join(' ')).toMatch(/incompatible/);
  });

  it('flags two locks on one dimension', () => {
    let layers = addLayer([], style('MOD-03'), 'primary');
    layers = addLayer(layers, style('MOD-04'), 'secondary');
    layers = toggleLock(toggleLock(layers, 'MOD-03'), 'MOD-04');
    expect(precheck(layers, index).conflicts.join(' ')).toMatch(/layout is locked by more than one style/);
  });

  it('warns when a style is assigned outside its declared dimensions', () => {
    let layers = addLayer([], style('MOD-07'), 'primary');
    layers = toggleDimension(layers, 'MOD-07', 'lighting');
    expect(precheck(layers, index).warnings.join(' ')).toMatch(/does not declare/);
    expect(precheck(layers, index).conflicts).toEqual([]);
  });
});

describe('selection helpers', () => {
  it('filters by text, category, and status', () => {
    expect(filterStyles(catalog.styles, { query: 'chiaroscuro', category: '', hideDisabled: true }).map((s) => s.id)).toContain('CLS-01');
    const modernist = filterStyles(catalog.styles, { query: '', category: 'modernist', hideDisabled: true });
    expect(modernist.every((s) => s.category === 'modernist')).toBe(true);
  });

  it('changes the selection key whenever a layer changes', () => {
    const layers = addLayer([], style('MOD-03'), 'primary');
    expect(selectionKey(setStrength(layers, 'MOD-03', 0.1))).not.toBe(selectionKey(layers));
    expect(selectionKey(toggleLock(layers, 'MOD-03'))).not.toBe(selectionKey(layers));
  });

  it('builds a run-level selection', () => {
    const selection = toDesignStyleSelection(addLayer([], style('MOD-03'), 'primary'), '  editorial  ');
    expect(selection.rationale).toBe('editorial');
    expect(selection.catalog_version).toBe('style-library-v1');
  });
});

describe('design store', () => {
  beforeEach(() => useDesignStore.setState({ attached: null }));

  it('attaches and detaches a direction', () => {
    const selection = toDesignStyleSelection(addLayer([], style('MOD-03'), 'primary'), '');
    useDesignStore.getState().attach({ selection, compositionId: 'cmp-0123456789abcdef', label: 'Bauhaus' });
    expect(useDesignStore.getState().attached?.compositionId).toBe('cmp-0123456789abcdef');
    useDesignStore.getState().detach();
    expect(useDesignStore.getState().attached).toBeNull();
  });
});

describe('design API client', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('validates the catalog response against the shared contract', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ...catalog, pending_references: ['LFS-05'] }), {
        status: 200, headers: { 'Content-Type': 'application/json' },
      }),
    ));
    const result = await getDesignStyleLibrary();
    expect(result.pending_references).toEqual(['LFS-05']);
  });

  it('rejects a compose response that drifts from the contract', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ composition_id: 'x', prompt: 'p' }), {
        status: 200, headers: { 'Content-Type': 'application/json' },
      }),
    ));
    await expect(composeDesignStyle(addLayer([], style('MOD-03'), 'primary'))).rejects.toThrow();
  });
});
