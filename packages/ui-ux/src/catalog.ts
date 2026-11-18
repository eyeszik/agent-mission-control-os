/**
 * Accessors over the catalog tables, plus the pure helpers the compiler and the
 * evaluator share (twin of the module-level helpers in `ui_ux/compiler.py`).
 */
import { COMPONENT_TEMPLATES, STATE_TABLE, SURFACE_TEMPLATES, TERRITORY_TEMPLATES } from './catalog-data';
import { uniqueInOrder } from './python';
import type { ComponentTemplate, StateRow, SurfaceMode, SurfaceTemplate, UIState } from './types';

export { COMPONENT_TEMPLATES, STATE_TABLE, SURFACE_TEMPLATES, TERRITORY_TEMPLATES };

/** The state table row for a state (Python `_STATE_TABLE[state]`). */
export function stateRow(state: UIState): StateRow {
  const row = STATE_TABLE[state];
  if (row === undefined) throw new Error(`no state table row for ${state}`);
  return row;
}

/** A component template by name (Python `_COMPONENTS[name]`). */
export function componentTemplate(name: string): ComponentTemplate {
  const template = COMPONENT_TEMPLATES[name];
  if (template === undefined) throw new Error(`unknown component ${name}`);
  return template;
}

/** A fresh, mutable copy of the surface template: the compiler edits component lists in place. */
export function surfaceTemplate(mode: SurfaceMode): SurfaceTemplate {
  const template = SURFACE_TEMPLATES[mode];
  if (template === undefined) throw new Error(`no template for ${mode}`);
  return structuredClone(template);
}

/** Python `str.strip("-")`, in a linear scan (no regex, so no backtracking on long runs of `-`). */
function trimDashes(text: string): string {
  let start = 0;
  let end = text.length;
  while (start < end && text.charCodeAt(start) === 45) start += 1;
  while (end > start && text.charCodeAt(end - 1) === 45) end -= 1;
  return text.slice(start, end);
}

/** Python `_slug`: lowercase, runs of non `[a-z0-9]` become `-`, edges trimmed, `item` if empty. */
export function slug(text: string): string {
  return trimDashes(text.toLowerCase().replace(/[^a-z0-9]+/g, '-')) || 'item';
}

/** Python `_add_unique`: append and report whether anything changed. */
export function addUnique(items: string[], value: string): boolean {
  if (items.includes(value)) return false;
  items.push(value);
  return true;
}

/** Python `_component_tokens`: the token paths a component with these tags references. */
export function componentTokens(tags: readonly string[]): string[] {
  const has = (...wanted: string[]): boolean => wanted.some((tag) => tags.includes(tag));
  const tokens = ['semantic.color.foreground', 'semantic.color.surface', 'semantic.space.stack'];
  if (has('action', 'cta')) {
    tokens.push('component.button.primary.background', 'component.button.primary.foreground', 'component.focus.ring');
  }
  if (has('field', 'filter', 'nav')) tokens.push('semantic.color.border-strong', 'component.focus.ring');
  if (has('ai')) tokens.push('component.ai-trust.border', 'component.ai-trust.label', 'component.ai-trust.degraded');
  if (has('metric')) tokens.push('component.metric.value', 'component.metric.truth-label');
  if (has('status')) {
    tokens.push('semantic.color.status.success', 'semantic.color.status.warning', 'semantic.color.status.danger');
  }
  return uniqueInOrder(tokens);
}
