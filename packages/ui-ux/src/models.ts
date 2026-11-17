/**
 * Request contracts of the compiler (Python `UIUXRequest`, `BrandContext`,
 * `SourceRef`; strict, `extra="forbid"`). The IR contracts live in `@amc/shared`.
 *
 * Pydantic lax coercions are refused rather than guessed: `"yes"`/`1` for a
 * bool and the like. The parity fixture lists them as `lax_divergences`.
 */
import { z } from 'zod';
import { SurfaceModeSchema, UIPlatformSchema, UISourceKindSchema } from '@amc/shared';
import type { SourceKind } from './types';

export const UIUX_SCHEMA_VERSION = 'amc-uiux-ir/v1';
export const UIUX_COMPILER_VERSION = 'amc-uiux-compiler/v1';
/** The compiler's success terminal. There is deliberately no generated/deployed value. */
export const UIUX_SPEC_READY = 'UIUX_SPEC_READY';

/** Pydantic `ValidationError` for a request the compiler cannot read. */
export class ValidationError extends Error {
  override name = 'ValidationError';

  constructor(
    readonly model: string,
    readonly details: readonly string[],
  ) {
    super(`validation failed for ${model}: ${details.join('; ')}`);
  }
}

const nonEmpty = z.string().min(1);
const texts = z.array(z.string()).default([]);
const optionalText = z.string().nullable().default(null);

export const SourceRefSchema = z.strictObject({
  kind: UISourceKindSchema,
  ref: nonEmpty,
  detail: z.string().default(''),
});

export const BrandContextSchema = z.strictObject({
  brand_name: nonEmpty,
  positioning: optionalText,
  tone_attributes: texts,
  typography_direction: optionalText,
  imagery_style: optionalText,
  motion_pace: optionalText,
  reduced_motion_fallback: optionalText,
  palette_hex: texts,
  palette_source: UISourceKindSchema.default('COMPILER_DEFAULT' satisfies SourceKind),
});

export const UIUXRequestSchema = z.strictObject({
  project_ref: nonEmpty,
  surface: SurfaceModeSchema.nullable().default(null),
  surface_hint: z.string().default(''),
  platform: UIPlatformSchema.nullable().default(null),
  purpose: z.string().default(''),
  primary_user: z.string().default(''),
  primary_task: z.string().default(''),
  business_goal: z.string().default(''),
  content_requirements: texts,
  constraints: texts,
  negative_constraints: texts,
  ai_features: z.boolean().nullable().default(null),
  ai_provider_known: z.boolean().default(false),
  existing_components: texts,
  locale_rtl: z.boolean().default(false),
  brand: BrandContextSchema.nullable().default(null),
  sources: z.array(SourceRefSchema).default([]),
});

export type BrandContext = z.output<typeof BrandContextSchema>;
export type UIUXRequest = z.output<typeof UIUXRequestSchema>;

/** Python `UIUXRequest.model_validate(data)`. */
export function parseUiuxRequest(data: unknown): UIUXRequest {
  const result = UIUXRequestSchema.safeParse(data);
  if (result.success) return result.data;
  throw new ValidationError(
    'UIUXRequest',
    result.error.issues.map((issue) => `${issue.path.map(String).join('.') || '(root)'}: ${issue.message}`),
  );
}
