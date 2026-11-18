/**
 * Pydantic-style validation on top of Zod. Pydantic's rendered message embeds
 * a version URL, so the twin reports the model name and the error locations
 * (`CompiledValidationError.issues`), which is what a caller can act on and
 * what the parity suite compares.
 *
 * Pydantic lax coercions (`"2"` for an int, `"yes"` for a bool, a float for an
 * int, ...) are refused: the parity fixture records them as "Python accepts,
 * TS refuses". JSON lists are accepted for tuple fields, as Pydantic does.
 */
import { z } from 'zod';
import { CompiledValidationError, type ValidationIssue } from './errors';

/** Length in code points, as Python's `len(str)` (Zod counts UTF-16 units). */
export function cpLength(text: string): number {
  return Array.from(text).length;
}

/** A string with Pydantic `min_length`/`max_length` semantics. */
export function bounded(min = 0, max = Number.POSITIVE_INFINITY) {
  return z.string().refine((s) => cpLength(s) >= min && cpLength(s) <= max, {
    message: `string length must be between ${min} and ${max}`,
  });
}

function toLoc(path: readonly PropertyKey[]): (string | number)[] {
  return path.map((p) => (typeof p === 'number' ? p : String(p)));
}

function issuesOf(error: z.ZodError): ValidationIssue[] {
  const out: ValidationIssue[] = [];
  for (const issue of error.issues) {
    if (issue.code === 'unrecognized_keys') {
      for (const key of issue.keys) out.push({ loc: [...toLoc(issue.path), key], message: 'extra_forbidden' });
    } else {
      out.push({ loc: toLoc(issue.path), message: issue.message });
    }
  }
  return out;
}

/** `Model.model_validate(value)`. */
export function parseModel<S extends z.ZodType>(schema: S, model: string, value: unknown): z.output<S> {
  const result = schema.safeParse(value);
  if (!result.success) throw new CompiledValidationError(model, issuesOf(result.error));
  return result.data;
}

/** Stable text for an error location list, as the fixture stores it. */
export function locKey(loc: readonly (string | number)[]): string {
  return loc.join('.');
}

/**
 * A Pydantic `tuple[X, ...]` field with `min_length`/`max_length`. Pydantic validates every item first and
 * then checks the length of what survived, so an invalid item can also yield `too_short` at the field.
 */
export function pyArray<S extends z.ZodType>(item: S, min = 0, max = Number.POSITIVE_INFINITY) {
  return z.unknown().transform((value, ctx): z.output<S>[] => {
    if (!Array.isArray(value)) {
      ctx.addIssue({ code: 'custom', message: 'Input should be a valid tuple' });
      return z.NEVER;
    }
    const kept: z.output<S>[] = [];
    value.forEach((v: unknown, index: number) => {
      const result = item.safeParse(v);
      if (result.success) kept.push(result.data);
      else for (const issue of result.error.issues) ctx.addIssue({ ...issue, path: [index, ...issue.path] } as never);
    });
    if (kept.length < min) ctx.addIssue({ code: 'custom', message: 'too_short' });
    if (value.length > max) ctx.addIssue({ code: 'custom', message: 'too_long' });
    return kept;
  });
}
