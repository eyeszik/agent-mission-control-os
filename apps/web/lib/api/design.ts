import { z } from 'zod';
import { apiFetch } from './client';

const StyleDefinitionSchema = z.object({
  id: z.string(),
  name: z.string(),
  category: z.string(),
  description: z.string(),
  design_dimensions: z.array(z.string()),
  physics: z.record(z.array(z.string())),
  palette: z.object({ colors: z.array(z.string()), semantic_roles: z.record(z.string()), contrast_notes: z.array(z.string()) }),
  typography: z.object({ families: z.array(z.string()), category: z.string(), weights: z.array(z.string()), tracking: z.string().optional(), hierarchy: z.string().optional() }),
  prompt_tokens: z.array(z.string()),
  negative_tokens: z.array(z.string()),
  compatible_with: z.array(z.string()),
  incompatible_with: z.array(z.string()),
  recommended_strength: z.number(),
  suitable_for: z.array(z.string()),
  unsuitable_for: z.array(z.string()),
  motion_behavior: z.array(z.string()),
  production_notes: z.array(z.string()),
  source_version: z.string(),
  status: z.string(),
});

export const DesignStyleLibrarySchema = z.object({ version: z.string(), styles: z.array(StyleDefinitionSchema) });
export type DesignStyle = z.infer<typeof StyleDefinitionSchema>;
export type DesignStyleLibrary = z.infer<typeof DesignStyleLibrarySchema>;

export const ComposedStyleSchema = z.object({
  composition_id: z.string(),
  selections: z.array(z.object({ style_id: z.string(), strength: z.number(), dimensions: z.array(z.string()), locked: z.boolean() })),
  resolved_tokens: z.array(z.object({ token: z.string(), value: z.string(), dimension: z.string(), strength: z.number() })),
  conflicts: z.array(z.string()),
  warnings: z.array(z.string()),
  blocking: z.boolean().optional(),
  prompt: z.string(),
  negative_prompt: z.string(),
  version: z.string(),
});
export type ComposedDesignStyle = z.infer<typeof ComposedStyleSchema>;

export async function getDesignStyleLibrary(): Promise<DesignStyleLibrary> {
  return apiFetch('/design/styles', { method: 'GET' }, DesignStyleLibrarySchema);
}

export async function composeDesignStyle(
  selections: Array<{ style_id: string; strength: number; dimensions: string[]; locked: boolean }>,
  brief: { objective?: string; audience?: string; format?: string },
): Promise<ComposedDesignStyle> {
  return apiFetch('/design/styles/compose', { method: 'POST', body: JSON.stringify({ selections, brief }) }, ComposedStyleSchema);
}
