import {
  STYLE_DIMENSIONS,
  STYLE_LIBRARY_VERSION,
  type DesignStyleSelection,
  type StyleDefinition,
  type StyleDimension,
  type StyleSelection,
  type StyleSelectionRole,
} from '@amc/shared';

// Pure Design Mode logic, kept out of the component so it is unit-testable.
// These prechecks mirror the server's rules for fast feedback only; the
// backend composition (POST /design/styles/compose) remains authoritative.

export const MAX_LAYERS = 8;

export type StyleIndex = ReadonlyMap<string, StyleDefinition>;

export function indexStyles(styles: readonly StyleDefinition[]): Map<string, StyleDefinition> {
  const index = new Map<string, StyleDefinition>();
  for (const style of styles) index.set(style.id, style);
  return index;
}

export function layerFromStyle(style: StyleDefinition, role: StyleSelectionRole): StyleSelection {
  return {
    style_id: style.id,
    role,
    strength: style.recommended_strength,
    dimensions: [...style.design_dimensions],
    locked: false,
  };
}

function demoteOtherPrimaries(layers: StyleSelection[], keepId: string): StyleSelection[] {
  return layers.map((layer) =>
    layer.style_id !== keepId && layer.role === 'primary' ? { ...layer, role: 'secondary' } : layer,
  );
}

export function addLayer(
  layers: StyleSelection[],
  style: StyleDefinition,
  role: StyleSelectionRole,
): StyleSelection[] {
  const existing = layers.find((layer) => layer.style_id === style.id);
  if (existing) return setRole(layers, style.id, role);
  if (layers.length >= MAX_LAYERS) return layers;
  const next = [...layers, layerFromStyle(style, role)];
  return role === 'primary' ? demoteOtherPrimaries(next, style.id) : next;
}

export function removeLayer(layers: StyleSelection[], styleId: string): StyleSelection[] {
  return layers.filter((layer) => layer.style_id !== styleId);
}

export function setRole(layers: StyleSelection[], styleId: string, role: StyleSelectionRole): StyleSelection[] {
  const next = layers.map((layer) => (layer.style_id === styleId ? { ...layer, role } : layer));
  return role === 'primary' ? demoteOtherPrimaries(next, styleId) : next;
}

export function setStrength(layers: StyleSelection[], styleId: string, strength: number): StyleSelection[] {
  const clamped = Math.round(Math.min(1, Math.max(0, Number.isFinite(strength) ? strength : 0)) * 100) / 100;
  return layers.map((layer) => (layer.style_id === styleId ? { ...layer, strength: clamped } : layer));
}

export function toggleDimension(
  layers: StyleSelection[],
  styleId: string,
  dimension: StyleDimension,
): StyleSelection[] {
  return layers.map((layer) => {
    if (layer.style_id !== styleId) return layer;
    const has = layer.dimensions.includes(dimension);
    const dimensions = has
      ? layer.dimensions.filter((item) => item !== dimension)
      : STYLE_DIMENSIONS.filter((item) => item === dimension || layer.dimensions.includes(item));
    return { ...layer, dimensions };
  });
}

export function toggleLock(layers: StyleSelection[], styleId: string): StyleSelection[] {
  return layers.map((layer) => (layer.style_id === styleId ? { ...layer, locked: !layer.locked } : layer));
}

export interface Precheck {
  conflicts: string[];
  warnings: string[];
}

export function precheck(layers: readonly StyleSelection[], index: StyleIndex): Precheck {
  const conflicts: string[] = [];
  const warnings: string[] = [];
  const nameOf = (id: string) => index.get(id)?.name ?? id;

  if (layers.filter((layer) => layer.role === 'primary').length > 1) {
    conflicts.push('Only one primary style is allowed.');
  }
  if (layers.length > MAX_LAYERS) conflicts.push(`At most ${MAX_LAYERS} styles can be layered.`);

  for (let i = 0; i < layers.length; i += 1) {
    const left = index.get(layers[i].style_id);
    if (!left) {
      conflicts.push(`Unknown style ${layers[i].style_id}.`);
      continue;
    }
    if (left.status === 'disabled') conflicts.push(`${left.name} is disabled.`);
    for (let j = i + 1; j < layers.length; j += 1) {
      const right = index.get(layers[j].style_id);
      if (!right) continue;
      if (left.incompatible_with.includes(right.id) || right.incompatible_with.includes(left.id)) {
        conflicts.push(`${left.name} is incompatible with ${right.name}.`);
      }
    }
  }

  const lockedBy = new Map<StyleDimension, string[]>();
  for (const layer of layers) {
    const style = index.get(layer.style_id);
    if (!style) continue;
    const claimed = layer.dimensions.length > 0 ? layer.dimensions : style.design_dimensions;
    for (const dimension of claimed) {
      if (!style.design_dimensions.includes(dimension)) {
        warnings.push(`${style.name} is assigned to ${dimension}, which it does not declare.`);
      }
      if (layer.locked) lockedBy.set(dimension, [...(lockedBy.get(dimension) ?? []), style.name]);
    }
  }
  lockedBy.forEach((owners, dimension) => {
    if (owners.length > 1) conflicts.push(`${dimension} is locked by more than one style: ${owners.join(', ')}.`);
  });

  return { conflicts, warnings };
}

// Stable identity for a layer set, used to detect a composition that no longer
// matches the current layers (so a stale direction cannot be attached).
export function selectionKey(layers: readonly StyleSelection[]): string {
  return JSON.stringify(
    layers.map((layer) => [layer.style_id, layer.role, layer.strength, [...layer.dimensions], layer.locked]),
  );
}

export interface StyleFilter {
  query: string;
  category: string;
  hideDisabled: boolean;
}

export function filterStyles(styles: readonly StyleDefinition[], filter: StyleFilter): StyleDefinition[] {
  const needle = filter.query.trim().toLowerCase();
  return styles.filter((style) => {
    if (filter.hideDisabled && style.status === 'disabled') return false;
    if (filter.category && style.category !== filter.category) return false;
    if (!needle) return true;
    const haystack = [
      style.id,
      style.name,
      style.description,
      style.category,
      ...style.design_dimensions,
      ...style.prompt_tokens,
      ...style.suitable_for,
    ]
      .join(' ')
      .toLowerCase();
    return haystack.includes(needle);
  });
}

export function toDesignStyleSelection(layers: readonly StyleSelection[], rationale: string): DesignStyleSelection {
  return {
    selections: layers.map((layer) => ({ ...layer, dimensions: [...layer.dimensions] })),
    rationale: rationale.trim(),
    catalog_version: STYLE_LIBRARY_VERSION,
  };
}
