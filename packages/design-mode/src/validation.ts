/**
 * Pydantic-shaped validation on top of Zod. Field validators that Python
 * raises as `ValueError` become custom issues tagged `valueError`; model
 * validators run only once every field is valid, as Pydantic's
 * `mode="after"` validators do.
 */
import { z } from 'zod';
import { ValidationError } from './errors';

const VALUE_ERROR = 'valueError';

/** Record a Python `ValueError` raised by a field validator. */
export function addValueError(ctx: z.RefinementCtx, message: string): void {
  ctx.addIssue({ code: 'custom', message, params: { [VALUE_ERROR]: true } });
}

function isValueError(issue: z.core.$ZodIssue): boolean {
  return issue.code === 'custom' && issue.params?.[VALUE_ERROR] === true;
}

function describe(issue: z.core.$ZodIssue): string {
  return `${issue.path.map(String).join('.') || '(root)'}: ${issue.message}`;
}

/** The issues of one failed parse, split into value errors and everything else. */
export interface IssueSplit {
  readonly valueErrors: string[];
  readonly details: string[];
}

export function splitIssues(issues: readonly z.core.$ZodIssue[], prefix: readonly PropertyKey[] = []): IssueSplit {
  const located = issues.map((issue) => ({ ...issue, path: [...prefix, ...issue.path] }));
  return {
    valueErrors: located.filter(isValueError).map((issue) => issue.message),
    details: located.filter((issue) => !isValueError(issue)).map(describe),
  };
}

/** Parse or throw a `ValidationError` named after the Python model. */
export function parseModel<T extends z.ZodType>(schema: T, input: unknown, model: string): z.output<T> {
  const result = schema.safeParse(input);
  if (result.success) return result.data;
  const split = splitIssues(result.error.issues);
  throw new ValidationError(model, split.valueErrors, split.details);
}

/** Python strings that look like array indices reorder inside a JS object, so they are refused. */
export function hasIndexLikeKey(record: Readonly<Record<string, string>>): boolean {
  return Object.keys(record).some((key) => /^(0|[1-9]\d*)$/.test(key) && Number(key) < 2 ** 32 - 1);
}
