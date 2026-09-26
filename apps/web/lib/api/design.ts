import {
  ComposedStyleSchema,
  StyleCatalogResponseSchema,
  type ComposedStyle,
  type StyleCatalogResponse,
  type StyleSelection,
} from '@amc/shared';
import { apiFetch } from './client';

// Validated against the shared contract (packages/shared/src/schemas/styleLibrary.ts),
// so a backend/frontend drift fails loudly at the boundary instead of rendering wrong.

export interface DesignComposeBrief {
  objective?: string;
  audience?: string;
  format?: string;
}

export async function getDesignStyleLibrary(): Promise<StyleCatalogResponse> {
  return apiFetch('/design/styles', { method: 'GET' }, StyleCatalogResponseSchema);
}

export async function composeDesignStyle(
  selections: StyleSelection[],
  brief: DesignComposeBrief = {},
): Promise<ComposedStyle> {
  return apiFetch(
    '/design/styles/compose',
    { method: 'POST', body: JSON.stringify({ selections, brief }) },
    ComposedStyleSchema,
  );
}
