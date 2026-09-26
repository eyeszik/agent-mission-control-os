import { z } from 'zod';

// Mirrors services/langgraph/agency/design/ (style_registry.py for the catalog,
// style_composer.py for selections/composition). The canonical catalog lives at
// packages/shared/style-library/design-styles.json.
//
// Styles are composed *by dimension*: each selection claims dimensions, and each
// dimension resolves to exactly one style. The final prompt is assembled per
// dimension, never by concatenating whole style prompts.

export const STYLE_LIBRARY_VERSION = 'style-library-v1';

export const STYLE_DIMENSIONS = [
  'layout',
  'typography',
  'palette',
  'lighting',
  'texture',
  'surface',
  'composition',
  'motion',
  'imagery',
  'geometry',
  'depth',
  'material',
] as const;
export const StyleDimensionSchema = z.enum(STYLE_DIMENSIONS);
export type StyleDimension = z.infer<typeof StyleDimensionSchema>;

export const STYLE_CATEGORIES = [
  'classical',
  'modernist',
  'experimental',
  'cyber',
  'lifestyle',
  'editorial',
  'illustrative',
  'material',
  'interface',
  'motion',
] as const;
export const StyleCategorySchema = z.enum(STYLE_CATEGORIES);
export type StyleCategory = z.infer<typeof StyleCategorySchema>;

export const STYLE_STATUSES = ['active', 'experimental', 'deprecated', 'disabled'] as const;
export const StyleStatusSchema = z.enum(STYLE_STATUSES);

// Style ids follow a family prefix + two digits (CLS-01, MOD-03, LFS-05, ...).
export const STYLE_ID_PATTERN = /^[A-Z]{3}-\d{2}$/;
export const StyleIdSchema = z.string().regex(STYLE_ID_PATTERN, 'style id must look like ABC-01');

export const StylePhysicsSchema = z.object({
  lighting: z.array(z.string()).default([]),
  spatial: z.array(z.string()).default([]),
  material: z.array(z.string()).default([]),
  composition: z.array(z.string()).default([]),
  motion: z.array(z.string()).default([]),
});

export const StylePaletteSchema = z.object({
  colors: z.array(z.string()).min(1),
  semantic_roles: z.record(z.string(), z.string()).default({}),
  contrast_notes: z.array(z.string()).default([]),
});

export const StyleTypographySchema = z.object({
  families: z.array(z.string()).default([]),
  category: z.string(),
  weights: z.array(z.string()).default([]),
  tracking: z.string().optional(),
  hierarchy: z.string().optional(),
});

export const StyleDefinitionSchema = z
  .object({
    id: StyleIdSchema,
    name: z.string().min(1),
    category: StyleCategorySchema,
    description: z.string().min(1),
    design_dimensions: z.array(StyleDimensionSchema).min(1),
    physics: StylePhysicsSchema,
    palette: StylePaletteSchema,
    typography: StyleTypographySchema,
    prompt_tokens: z.array(z.string()).min(1),
    negative_tokens: z.array(z.string()).default([]),
    // References may name styles not yet migrated into the catalog; they must be
    // well-formed ids, and the registry reports them as pending references.
    compatible_with: z.array(StyleIdSchema).default([]),
    incompatible_with: z.array(StyleIdSchema).default([]),
    recommended_strength: z.number().min(0).max(1),
    suitable_for: z.array(z.string()).default([]),
    unsuitable_for: z.array(z.string()).default([]),
    motion_behavior: z.array(z.string()).default([]),
    production_notes: z.array(z.string()).default([]),
    source_version: z.string().min(1),
    status: StyleStatusSchema,
  })
  .superRefine((style, ctx) => {
    const overlap = style.compatible_with.filter((ref) => style.incompatible_with.includes(ref));
    if (overlap.length > 0) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: `style '${style.id}' is both compatible and incompatible with: ${overlap.join(', ')}`,
      });
    }
    if (style.compatible_with.includes(style.id) || style.incompatible_with.includes(style.id)) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, message: `style '${style.id}' references itself` });
    }
  });

export const StyleLibrarySchema = z
  .object({
    version: z.string().min(1),
    styles: z.array(StyleDefinitionSchema).min(1),
  })
  .superRefine((library, ctx) => {
    const ids = library.styles.map((style) => style.id);
    const duplicates = ids.filter((id, index) => ids.indexOf(id) !== index);
    if (duplicates.length > 0) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: `duplicate style id(s): ${Array.from(new Set(duplicates)).join(', ')}`,
      });
    }
  });

// Catalog as served by GET /design/styles: the library plus the references
// that name styles not yet present (pending migration), so the UI can show them.
export const StyleCatalogResponseSchema = z.object({
  version: z.string().min(1),
  styles: z.array(StyleDefinitionSchema),
  pending_references: z.array(StyleIdSchema).default([]),
});

export const STYLE_SELECTION_ROLES = ['primary', 'secondary'] as const;
export const StyleSelectionRoleSchema = z.enum(STYLE_SELECTION_ROLES);

// One layer of a composition: which style, how strongly, which dimensions it
// claims (empty = the style's own design_dimensions), and whether those
// dimensions are locked against being taken by another layer.
export const StyleSelectionSchema = z.object({
  style_id: StyleIdSchema,
  role: StyleSelectionRoleSchema.default('secondary'),
  strength: z.number().min(0).max(1).default(0.5),
  dimensions: z.array(StyleDimensionSchema).default([]),
  locked: z.boolean().default(false),
});

export const StyleComposeRequestSchema = z
  .object({
    selections: z.array(StyleSelectionSchema).min(1).max(8),
    brief: z
      .object({
        objective: z.string().optional(),
        audience: z.string().optional(),
        format: z.string().optional(),
      })
      .default({}),
  })
  .superRefine((request, ctx) => {
    const primaries = request.selections.filter((s) => s.role === 'primary').length;
    if (primaries > 1) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, message: 'at most one primary style is allowed' });
    }
    const ids = request.selections.map((s) => s.style_id);
    if (new Set(ids).size !== ids.length) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, message: 'a style may appear only once per composition' });
    }
  });

export const ResolvedStyleTokenSchema = z.object({
  token: z.string(),
  value: z.string(),
  dimension: StyleDimensionSchema,
  strength: z.number().min(0).max(1),
});

export const ComposedStyleSchema = z.object({
  composition_id: z.string().min(1),
  catalog_version: z.string().min(1),
  selections: z.array(StyleSelectionSchema).min(1),
  // dimension -> style id that owns it after resolution
  resolved_dimensions: z.record(StyleDimensionSchema, StyleIdSchema).default({}),
  resolved_tokens: z.array(ResolvedStyleTokenSchema).default([]),
  conflicts: z.array(z.string()).default([]),
  warnings: z.array(z.string()).default([]),
  blocking: z.boolean(),
  prompt: z.string().min(1),
  negative_prompt: z.string().default(''),
  version: z.string().min(1),
});

// What a run carries in: the selection the designer composed in Design Mode.
export const DesignStyleSelectionSchema = z.object({
  selections: z.array(StyleSelectionSchema).min(1).max(8),
  rationale: z.string().default(''),
  catalog_version: z.string().default(STYLE_LIBRARY_VERSION),
});

// What a run persists on its DesignBrief: the resolved direction, so the
// artifact's lineage records exactly which styles shaped it.
export const DesignStyleDirectionSchema = z.object({
  composition_id: z.string().min(1),
  catalog_version: z.string().min(1),
  selections: z.array(StyleSelectionSchema).min(1),
  resolved_dimensions: z.record(StyleDimensionSchema, StyleIdSchema).default({}),
  prompt: z.string(),
  negative_prompt: z.string().default(''),
  conflicts: z.array(z.string()).default([]),
  warnings: z.array(z.string()).default([]),
  blocking: z.boolean(),
  applied: z.boolean(),
  rationale: z.string().default(''),
});

export type StyleDefinition = z.infer<typeof StyleDefinitionSchema>;
export type StyleLibrary = z.infer<typeof StyleLibrarySchema>;
export type StyleCatalogResponse = z.infer<typeof StyleCatalogResponseSchema>;
export type StyleSelectionRole = z.infer<typeof StyleSelectionRoleSchema>;
export type StyleSelection = z.infer<typeof StyleSelectionSchema>;
export type StyleComposeRequest = z.infer<typeof StyleComposeRequestSchema>;
export type ResolvedStyleToken = z.infer<typeof ResolvedStyleTokenSchema>;
export type ComposedStyle = z.infer<typeof ComposedStyleSchema>;
export type DesignStyleSelection = z.infer<typeof DesignStyleSelectionSchema>;
export type DesignStyleDirection = z.infer<typeof DesignStyleDirectionSchema>;
