/**
 * Twin of `agency/design/style_registry.py`: validate an already-loaded style
 * catalog, look styles up, and report pending references. Reading the catalog
 * file stays in Python (`load_style_library`); callers pass the parsed JSON.
 */
import { z } from 'zod';
import { pyRepr, pySorted, pyStr } from '@amc/kernel';
import { STYLE_CATEGORIES, STYLE_DIMENSIONS, STYLE_LIBRARY_VERSION, STYLE_STATUSES } from '@amc/shared';
import { UnknownStyleError, ValidationError } from './errors';
import { PY_DIGIT } from './python';
import { addValueError, hasIndexLikeKey, splitIssues, type IssueSplit } from './validation';

export { STYLE_CATEGORIES, STYLE_DIMENSIONS, STYLE_LIBRARY_VERSION };
export type StyleDimension = (typeof STYLE_DIMENSIONS)[number];

/** Python `re.compile(r"^[A-Z]{3}-\d{2}$")`: Unicode `\d`, and `$` also before a final "\n". */
export const STYLE_ID_PATTERN = new RegExp(`^[A-Z]{3}-${PY_DIGIT}{2}\\n?$`, 'u');

/** Python `_check_id`'s error text. */
export function styleIdError(value: string): string {
  return `style id must look like ABC-01, got ${pyRepr(value)}`;
}

/** A str field validated by `_check_id`. */
export const StyleIdSchema = z.string().superRefine((value, ctx) => {
  if (!STYLE_ID_PATTERN.test(value)) addValueError(ctx, styleIdError(value));
});

// `[_check_id(v) for v in values]`: the first bad reference raises, once per field.
const StyleRefsSchema = z.array(z.string()).superRefine((values, ctx) => {
  const bad = values.find((value) => !STYLE_ID_PATTERN.test(value));
  if (bad !== undefined) addValueError(ctx, styleIdError(bad));
});

const strings = z.array(z.string()).default([]);
export const StyleDimensionSchema = z.enum(STYLE_DIMENSIONS);
const unit = z.number().min(0).max(1);

export const StylePhysicsSchema = z.strictObject({
  lighting: strings, spatial: strings, material: strings, composition: strings, motion: strings,
});

export const StylePaletteSchema = z.strictObject({
  colors: z.array(z.string()).min(1),
  semantic_roles: z.record(z.string(), z.string()).default({}).refine((roles) => !hasIndexLikeKey(roles), {
    message: 'semantic_roles keys that look like array indices would be reordered by a JS object; refused',
  }),
  contrast_notes: strings,
});

export const StyleTypographySchema = z.strictObject({
  families: strings,
  category: z.string(),
  weights: strings,
  tracking: z.string().nullable().default(null),
  hierarchy: z.string().nullable().default(null),
});

export const StyleDefinitionSchema = z.strictObject({
  id: StyleIdSchema,
  name: z.string().min(1),
  category: z.enum(STYLE_CATEGORIES),
  description: z.string().min(1),
  design_dimensions: z.array(StyleDimensionSchema).min(1),
  physics: StylePhysicsSchema,
  palette: StylePaletteSchema,
  typography: StyleTypographySchema,
  prompt_tokens: z.array(z.string()).min(1),
  negative_tokens: strings,
  compatible_with: StyleRefsSchema.default([]),
  incompatible_with: StyleRefsSchema.default([]),
  recommended_strength: unit,
  suitable_for: strings,
  unsuitable_for: strings,
  motion_behavior: strings,
  production_notes: strings,
  source_version: z.string().min(1),
  status: z.enum(STYLE_STATUSES),
});

export type StyleDefinition = z.output<typeof StyleDefinitionSchema>;

/** A validated catalog (Python `StyleLibrary`). Build one with `parseStyleLibrary`. */
export interface StyleLibrary {
  readonly version: string;
  readonly styles: readonly StyleDefinition[];
}

const LibraryShapeSchema = z.strictObject({ version: z.string().min(1), styles: z.array(z.unknown()).min(1) });

/** `StyleDefinition._consistent_relations`, run only on a style whose fields are valid. */
function relationError(style: StyleDefinition): string | null {
  const overlap = pySorted(new Set(style.compatible_with.filter((ref) => style.incompatible_with.includes(ref))));
  if (overlap.length > 0) return `${style.id} is both compatible and incompatible with ${pyStr(overlap)}`;
  if (style.compatible_with.includes(style.id) || style.incompatible_with.includes(style.id)) {
    return `${style.id} references itself`;
  }
  return null;
}

function validateStyle(raw: unknown, index: number, errors: IssueSplit): StyleDefinition | null {
  const parsed = StyleDefinitionSchema.safeParse(raw);
  if (!parsed.success) {
    const split = splitIssues(parsed.error.issues, ['styles', index]);
    errors.valueErrors.push(...split.valueErrors);
    errors.details.push(...split.details);
    return null;
  }
  const relation = relationError(parsed.data);
  if (relation !== null) errors.valueErrors.push(relation);
  return relation === null ? parsed.data : null;
}

function duplicateIds(styles: readonly StyleDefinition[]): string[] {
  const seen = new Set<string>();
  const duplicates = new Set<string>();
  for (const style of styles) {
    if (seen.has(style.id)) duplicates.add(style.id);
    seen.add(style.id);
  }
  return pySorted(duplicates);
}

/** Python `StyleLibrary.model_validate(data)` for already-parsed catalog JSON. */
export function parseStyleLibrary(data: unknown): StyleLibrary {
  const errors: IssueSplit = { valueErrors: [], details: [] };
  const shape = LibraryShapeSchema.safeParse(data);
  if (!shape.success) errors.details.push(...splitIssues(shape.error.issues).details);
  const items: readonly unknown[] = Array.isArray((data as { styles?: unknown } | null)?.styles)
    ? ((data as { styles: unknown[] }).styles)
    : [];
  const styles = items.map((raw, index) => validateStyle(raw, index, errors));
  if (!shape.success || errors.valueErrors.length > 0 || errors.details.length > 0) {
    throw new ValidationError('StyleLibrary', errors.valueErrors, errors.details);
  }
  const valid = styles.filter((style): style is StyleDefinition => style !== null);
  const duplicates = duplicateIds(valid);
  if (duplicates.length > 0) {
    throw new ValidationError('StyleLibrary', [`duplicate style id(s): ${pyStr(duplicates)}`], []);
  }
  return { version: shape.data.version, styles: valid };
}

/** Python `get_style`. */
export function getStyle(styleId: string, library: StyleLibrary): StyleDefinition {
  const found = library.styles.find((style) => style.id === styleId);
  if (found === undefined) throw new UnknownStyleError(styleId);
  return found;
}

/** Referenced style ids that are not in the catalog yet (awaiting migration). */
export function pendingReferences(library: StyleLibrary): string[] {
  const known = new Set(library.styles.map((style) => style.id));
  const referenced = library.styles.flatMap((style) => [...style.compatible_with, ...style.incompatible_with]);
  return pySorted(new Set(referenced.filter((ref) => !known.has(ref))));
}

/** JSON-safe catalog payload for the API (Python `style_catalog_snapshot`). */
export interface StyleCatalogSnapshot {
  readonly version: string;
  readonly styles: readonly StyleDefinition[];
  readonly pending_references: readonly string[];
}

export function styleCatalogSnapshot(library: StyleLibrary): StyleCatalogSnapshot {
  return { version: library.version, styles: library.styles, pending_references: pendingReferences(library) };
}
