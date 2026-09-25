import { z } from 'zod';

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
] as const;

export const StyleCategorySchema = z.enum([
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
]);

export const StyleDimensionSchema = z.enum(STYLE_DIMENSIONS);

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

export const StyleDefinitionSchema = z.object({
  id: z.string().min(1),
  name: z.string().min(1),
  category: StyleCategorySchema,
  description: z.string().min(1),
  design_dimensions: z.array(StyleDimensionSchema).min(1),
  physics: StylePhysicsSchema,
  palette: StylePaletteSchema,
  typography: StyleTypographySchema,
  prompt_tokens: z.array(z.string()).min(1),
  negative_tokens: z.array(z.string()).default([]),
  compatible_with: z.array(z.string()).default([]),
  incompatible_with: z.array(z.string()).default([]),
  recommended_strength: z.number().min(0).max(1),
  suitable_for: z.array(z.string()).default([]),
  unsuitable_for: z.array(z.string()).default([]),
  motion_behavior: z.array(z.string()).default([]),
  production_notes: z.array(z.string()).default([]),
  source_version: z.string().min(1),
  status: z.enum(['active', 'experimental', 'deprecated', 'disabled']),
});

export const StyleLibrarySchema = z.object({
  version: z.string().min(1),
  styles: z.array(StyleDefinitionSchema),
});

export const StyleSelectionSchema = z.object({
  style_id: z.string().min(1),
  strength: z.number().min(0).max(1).default(0.5),
  dimensions: z.array(StyleDimensionSchema).default([]),
  locked: z.boolean().default(false),
});

export const ResolvedStyleTokenSchema = z.object({
  token: z.string(),
  value: z.string(),
  dimension: StyleDimensionSchema,
  strength: z.number().min(0).max(1),
});

export const ComposedStyleSchema = z.object({
  composition_id: z.string().min(1),
  selections: z.array(StyleSelectionSchema).min(1),
  resolved_tokens: z.array(ResolvedStyleTokenSchema).default([]),
  conflicts: z.array(z.string()).default([]),
  warnings: z.array(z.string()).default([]),
  prompt: z.string().min(1),
  negative_prompt: z.string().default(''),
  version: z.string().min(1),
});

export const DesignStyleSelectionSchema = z.object({
  primary_style_id: z.string().nullable().optional(),
  secondary_style_ids: z.array(z.string()).default([]),
  locked_dimensions: z.record(z.string(), z.string()).default({}),
  style_strengths: z.record(z.string(), z.number().min(0).max(1)).default({}),
  composed_style_version: z.string().default('style-library-v1'),
  rationale: z.string().default(''),
});

export type StyleCategory = z.infer<typeof StyleCategorySchema>;
export type StyleDimension = z.infer<typeof StyleDimensionSchema>;
export type StyleDefinition = z.infer<typeof StyleDefinitionSchema>;
export type StyleLibrary = z.infer<typeof StyleLibrarySchema>;
export type StyleSelection = z.infer<typeof StyleSelectionSchema>;
export type ComposedStyle = z.infer<typeof ComposedStyleSchema>;
export type DesignStyleSelection = z.infer<typeof DesignStyleSelectionSchema>;
