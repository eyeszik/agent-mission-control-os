/**
 * Twin of `agency/design/style_composer.py`: compose style selections into one
 * direction, by dimension. A locked layer beats unlocked ones (two locks on a
 * dimension are blocking); otherwise the strongest layer wins, then the
 * primary, then selection order. Exactly one style supplies identity tokens.
 */
import { z } from 'zod';
import { PyFloat, pyJsonDumps, sha256Hex, type PyJsonValue } from '@amc/kernel';
import { analyzeStyleCompatibility } from './compatibility';
import { InvalidSelectionError } from './errors';
import { compileDesignPrompt, compileNegativePrompt, type DesignBrief } from './prompt';
import {
  STYLE_DIMENSIONS,
  STYLE_LIBRARY_VERSION,
  StyleDimensionSchema,
  StyleIdSchema,
  getStyle,
  type StyleDefinition,
  type StyleDimension,
  type StyleLibrary,
} from './registry';
import { addValueError, parseModel } from './validation';

export const COMPOSER_VERSION = 'style-composer/v1';
export const MAX_SELECTIONS = 8;

export const StyleSelectionSchema = z.strictObject({
  style_id: StyleIdSchema,
  role: z.enum(['primary', 'secondary']).default('secondary'),
  strength: z.number().min(0).max(1).default(0.5),
  dimensions: z.array(StyleDimensionSchema).default([]),
  locked: z.boolean().default(false),
});
export type StyleSelection = z.output<typeof StyleSelectionSchema>;

/** Python `_check_selection_set`'s first failing rule, or null. */
export function selectionSetError(selections: readonly StyleSelection[]): string | null {
  if (selections.length === 0) return 'at least one style selection is required';
  if (selections.length > MAX_SELECTIONS) return `at most ${MAX_SELECTIONS} style selections are allowed`;
  if (selections.filter((s) => s.role === 'primary').length > 1) return 'at most one primary style is allowed';
  const ids = selections.map((s) => s.style_id);
  return new Set(ids).size !== ids.length ? 'a style may appear only once per composition' : null;
}

export const DesignStyleSelectionSchema = z
  .strictObject({
    selections: z.array(StyleSelectionSchema).min(1).max(MAX_SELECTIONS),
    rationale: z.string().default(''),
    catalog_version: z.string().default(STYLE_LIBRARY_VERSION),
  })
  .superRefine((value, ctx) => {
    // Pydantic's after-validator runs only when the field constraints (length) held.
    if (value.selections.length < 1 || value.selections.length > MAX_SELECTIONS) return;
    const error = selectionSetError(value.selections);
    if (error !== null) addValueError(ctx, error);
  });
export type DesignStyleSelection = z.output<typeof DesignStyleSelectionSchema>;

export interface ResolvedStyleToken {
  readonly token: string;
  readonly value: string;
  readonly dimension: StyleDimension;
  readonly strength: number;
}

/** Python `ComposedStyle.model_dump(mode="json")`. */
export interface ComposedStyle {
  readonly composition_id: string;
  readonly catalog_version: string;
  readonly selections: readonly StyleSelection[];
  readonly resolved_dimensions: Readonly<Partial<Record<StyleDimension, string>>>;
  readonly resolved_tokens: readonly ResolvedStyleToken[];
  readonly conflicts: readonly string[];
  readonly warnings: readonly string[];
  readonly blocking: boolean;
  readonly prompt: string;
  readonly negative_prompt: string;
  readonly version: string;
}

/** Python `DesignStyleDirection.model_dump(mode="json")`: what a run persists on its DesignBrief. */
export interface DesignStyleDirection {
  readonly composition_id: string;
  readonly catalog_version: string;
  readonly selections: readonly StyleSelection[];
  readonly resolved_dimensions: Readonly<Partial<Record<StyleDimension, string>>>;
  readonly prompt: string;
  readonly negative_prompt: string;
  readonly conflicts: readonly string[];
  readonly warnings: readonly string[];
  readonly blocking: boolean;
  readonly applied: boolean;
  readonly rationale: string;
}

function normalize(selections: readonly unknown[]): StyleSelection[] {
  const layers = selections.map((item) => parseModel(StyleSelectionSchema, item, 'StyleSelection'));
  const error = selectionSetError(layers);
  if (error !== null) throw new InvalidSelectionError(error);
  return layers;
}

const unique = <T>(values: Iterable<T>): T[] => [...new Set(values)];

function dimensionMaterial(style: StyleDefinition, dimension: StyleDimension): string[] {
  const { physics, typography: typo, palette } = style;
  switch (dimension) {
    case 'lighting': return [...physics.lighting];
    case 'layout': case 'depth': return [...physics.spatial];
    case 'composition': case 'geometry': return [...physics.composition];
    case 'texture': case 'material': case 'surface': return [...physics.material];
    case 'motion': return unique([...physics.motion, ...style.motion_behavior]);
    case 'palette': {
      const roles = Object.entries(palette.semantic_roles).map(([role, value]) => `${role} ${value}`);
      return [...(roles.length > 0 ? roles : palette.colors), ...palette.contrast_notes];
    }
    case 'typography': {
      const parts = [typo.category, ...typo.families];
      if (typo.tracking) parts.push(`${typo.tracking} tracking`);
      if (typo.hierarchy) parts.push(typo.hierarchy);
      return parts;
    }
    case 'imagery': return [...style.prompt_tokens];
  }
}

/** Layer strength controls how much of a style's material is used. */
function take(values: readonly string[], strength: number): string[] {
  return values.length === 0 ? [] : values.slice(0, Math.max(1, Math.ceil(strength * values.length)));
}

function selectionJson(selection: StyleSelection): PyJsonValue {
  return { ...selection, strength: new PyFloat(selection.strength) };
}

/** `"cmp-" + sha256(json.dumps({...}, sort_keys=True, separators=(",", ":")))[:16]`. */
export function compositionId(catalogVersion: string, selections: readonly StyleSelection[]): string {
  const canonical = pyJsonDumps({ catalog_version: catalogVersion, selections: selections.map(selectionJson) });
  return `cmp-${sha256Hex(new TextEncoder().encode(canonical)).slice(0, 16)}`;
}

interface Layering {
  readonly layers: readonly StyleSelection[];
  readonly styles: ReadonlyMap<string, StyleDefinition>;
  readonly order: ReadonlyMap<string, number>;
}

function styleOf(layering: Layering, layer: StyleSelection): StyleDefinition {
  const style = layering.styles.get(layer.style_id);
  if (style === undefined) throw new InvalidSelectionError(`unresolved style ${layer.style_id}`);
  return style;
}

function claimDimensions(layering: Layering, warnings: string[]): Map<StyleDimension, StyleSelection[]> {
  const claims = new Map<StyleDimension, StyleSelection[]>();
  for (const layer of layering.layers) {
    const style = styleOf(layering, layer);
    const claimed = layer.dimensions.length > 0 ? layer.dimensions : style.design_dimensions;
    for (const dimension of claimed) {
      if (!style.design_dimensions.includes(dimension)) {
        warnings.push(
          `'${style.name}' is assigned to ${dimension}, which it does not declare; ` +
            'its contribution there may be thin',
        );
      }
      claims.set(dimension, [...(claims.get(dimension) ?? []), layer]);
    }
  }
  return claims;
}

/** Python `max(pool, key=(strength, role == "primary", -order))`: the first maximal layer. */
function strongest(pool: readonly StyleSelection[], order: ReadonlyMap<string, number>): StyleSelection {
  const rank = (layer: StyleSelection): [number, number, number] => [
    layer.strength, layer.role === 'primary' ? 1 : 0, -(order.get(layer.style_id) ?? 0),
  ];
  let best = pool[0] as StyleSelection;
  for (const layer of pool.slice(1)) {
    const [a, b] = [rank(layer), rank(best)];
    if (a[0] > b[0] || (a[0] === b[0] && (a[1] > b[1] || (a[1] === b[1] && a[2] > b[2])))) best = layer;
  }
  return best;
}

function precedenceWarning(layering: Layering, dimension: string, winner: StyleSelection, other: StyleSelection): string {
  const [winning, losing] = [styleOf(layering, winner), styleOf(layering, other)];
  const declared = winning.compatible_with.includes(other.style_id) || losing.compatible_with.includes(winner.style_id);
  if (winner.locked && !other.locked) {
    // Locks claim every dimension of their layer; an overridden assignment stays visible.
    return (
      `${dimension}: locked '${winning.name}' overrides the assignment to '${losing.name}'; ` +
      `unassign ${dimension} from '${winning.name}' to hand it over`
    );
  }
  return declared ? '' : `${dimension}: '${winning.name}' takes precedence over '${losing.name}' (no declared compatibility between them)`;
}

interface Resolution {
  readonly resolved: Map<StyleDimension, string>;
  readonly conflicts: string[];
  readonly warnings: string[];
}

function resolveDimension(layering: Layering, dimension: StyleDimension, candidates: readonly StyleSelection[], out: Resolution): void {
  const locked = candidates.filter((layer) => layer.locked);
  if (locked.length > 1) {
    const names = locked.map((layer) => styleOf(layering, layer).name).join(', ');
    out.conflicts.push(`${dimension} is locked by more than one style: ${names}`);
  }
  const winner = strongest(locked.length > 0 ? locked : candidates, layering.order);
  out.resolved.set(dimension, winner.style_id);
  for (const other of candidates) {
    if (other === winner) continue;
    const warning = precedenceWarning(layering, dimension, winner, other);
    if (warning) out.warnings.push(warning);
  }
}

function resolveTokens(layering: Layering, resolved: ReadonlyMap<StyleDimension, string>): ResolvedStyleToken[] {
  const strengthOf = new Map(layering.layers.map((layer) => [layer.style_id, layer.strength]));
  const tokens: ResolvedStyleToken[] = [];
  for (const [dimension, styleId] of resolved) {
    const style = layering.styles.get(styleId) as StyleDefinition;
    const strength = strengthOf.get(styleId) ?? 0;
    for (const value of take(dimensionMaterial(style, dimension), strength)) {
      tokens.push({ token: style.name, value, dimension, strength });
    }
  }
  return tokens;
}

function identityTokens(layering: Layering): ResolvedStyleToken[] {
  const primary = layering.layers.find((layer) => layer.role === 'primary');
  const identity =
    primary ?? strongest(layering.layers.map((layer) => ({ ...layer, role: 'secondary' as const })), layering.order);
  const style = styleOf(layering, identity);
  return take(style.prompt_tokens, identity.strength).map((value) => ({
    token: style.name, value, dimension: 'imagery' as const, strength: identity.strength,
  }));
}

function layeringOf(layers: readonly StyleSelection[], library: StyleLibrary): Layering {
  return {
    layers,
    styles: new Map(layers.map((layer) => [layer.style_id, getStyle(layer.style_id, library)])),
    order: new Map(layers.map((layer, index) => [layer.style_id, index])),
  };
}

function briefText(brief: DesignBrief): string {
  const text = (key: string): string => {
    if (!Object.hasOwn(brief, key) || brief[key] === undefined) return '';
    return brief[key] ?? 'None';
  };
  return ['objective', 'audience', 'format'].map(text).join(' ');
}

function resolve(layering: Layering, brief: DesignBrief, library: StyleLibrary): Resolution {
  const compatibility = analyzeStyleCompatibility(layering.layers.map((l) => l.style_id), {
    briefText: briefText(brief), dimensionOverlap: false, library,
  });
  const out: Resolution = { resolved: new Map(), conflicts: [...compatibility.conflicts], warnings: [...compatibility.warnings] };
  const claims = claimDimensions(layering, out.warnings);
  for (const dimension of STYLE_DIMENSIONS) {
    const candidates = claims.get(dimension);
    if (candidates !== undefined) resolveDimension(layering, dimension, candidates, out);
  }
  return out;
}

export interface ComposeOptions {
  readonly library: StyleLibrary;
}

/** Python `compose_style_selection`; selections are validated like Python's dicts. */
export function composeStyleSelection(selections: readonly unknown[], brief: DesignBrief | null | undefined, options: ComposeOptions): ComposedStyle {
  const chosenBrief = brief ?? {};
  const layering = layeringOf(normalize(selections), options.library);
  const { resolved, conflicts, warnings } = resolve(layering, chosenBrief, options.library);
  const tokens = resolveTokens(layering, resolved);
  if (!resolved.has('imagery')) tokens.push(...identityTokens(layering));
  const owners = unique(resolved.values()).map((id) => layering.styles.get(id) as StyleDefinition);
  const productionNotes = unique(owners.flatMap((style) => style.production_notes)).filter((note) => note);
  return {
    composition_id: compositionId(options.library.version, layering.layers),
    catalog_version: options.library.version,
    selections: layering.layers,
    resolved_dimensions: Object.fromEntries(resolved),
    resolved_tokens: tokens,
    conflicts,
    warnings: unique(warnings),
    blocking: conflicts.length > 0,
    prompt: compileDesignPrompt(chosenBrief, { resolved_tokens: tokens, conflicts, production_notes: productionNotes }),
    negative_prompt: compileNegativePrompt(unique(owners.flatMap((style) => style.negative_tokens))),
    version: COMPOSER_VERSION,
  };
}

/** Python `DesignStyleSelection.model_validate(data)`. */
export function parseDesignStyleSelection(data: unknown): DesignStyleSelection {
  return parseModel(DesignStyleSelectionSchema, data, 'DesignStyleSelection');
}

/**
 * Compose a run's selection into the direction persisted on its DesignBrief.
 * A blocking direction is recorded for lineage and review but never applied.
 */
export function directionFromSelection(selection: unknown, brief: DesignBrief | null | undefined, options: ComposeOptions): DesignStyleDirection {
  const chosen = parseDesignStyleSelection(selection);
  const composed = composeStyleSelection(chosen.selections, brief, options);
  return {
    composition_id: composed.composition_id,
    catalog_version: composed.catalog_version,
    selections: composed.selections,
    resolved_dimensions: composed.resolved_dimensions,
    prompt: composed.prompt,
    negative_prompt: composed.negative_prompt,
    conflicts: composed.conflicts,
    warnings: composed.warnings,
    blocking: composed.blocking,
    applied: !composed.blocking,
    rationale: chosen.rationale,
  };
}

/** A direction that could not be composed: recorded for lineage, never applied. */
export function unresolvedDirection(selection: DesignStyleSelection, reason: string, catalogVersion?: string | null): DesignStyleDirection {
  const version = catalogVersion || selection.catalog_version;
  return {
    composition_id: compositionId(version, selection.selections),
    catalog_version: version,
    selections: selection.selections,
    resolved_dimensions: {},
    prompt: '',
    negative_prompt: '',
    conflicts: [reason],
    warnings: [],
    blocking: true,
    applied: false,
    rationale: selection.rationale,
  };
}
