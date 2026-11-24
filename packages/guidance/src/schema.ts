/**
 * A small strict validation layer that reproduces what Pydantic reports: the
 * `loc` path and `type` of every issue (`extra_forbidden`, `missing`,
 * `string_too_short`, `enum`, ...), field order, defaults that are not
 * re-validated, field validators and model `after` validators that only run
 * when every field passed. Pydantic's lax coercions are refused, never guessed:
 * a numeric string is not an int, `1`/`"yes"` are not booleans, and a float is
 * not an int, even when Python would accept them. Those are recorded as
 * "Python accepts, TS refuses" cases in the fixtures.
 */
import { CanonicalFloat } from '@amc/canonical';
import { ValidationError, type Loc, type ValidationIssue } from './errors';
import { pyLen } from './pytext';
import { dictEntries } from './pyvalue';

export const INVALID: unique symbol = Symbol('invalid');
export type Invalid = typeof INVALID;
export type Issues = ValidationIssue[];
export type Parser<T> = (value: unknown, loc: Loc, issues: Issues) => T | Invalid;

function fail(issues: Issues, loc: Loc, type: string, msg: string): Invalid {
  issues.push({ loc, type, msg });
  return INVALID;
}

export interface Bounds {
  readonly ge?: number;
  readonly le?: number;
  readonly gt?: number;
}

function checkBounds(value: number, bounds: Bounds, loc: Loc, issues: Issues): boolean {
  if (bounds.ge !== undefined && !(value >= bounds.ge)) {
    fail(issues, loc, 'greater_than_equal', `Input should be greater than or equal to ${bounds.ge}`);
  } else if (bounds.le !== undefined && !(value <= bounds.le)) {
    fail(issues, loc, 'less_than_equal', `Input should be less than or equal to ${bounds.le}`);
  } else if (bounds.gt !== undefined && !(value > bounds.gt)) {
    fail(issues, loc, 'greater_than', `Input should be greater than ${bounds.gt}`);
  } else return true;
  return false;
}

export function str(options: { readonly min?: number; readonly pattern?: RegExp } = {}): Parser<string> {
  return (value, loc, issues) => {
    if (typeof value !== 'string') return fail(issues, loc, 'string_type', 'Input should be a valid string');
    if (options.min !== undefined && pyLen(value) < options.min) {
      return fail(issues, loc, 'string_too_short', `String should have at least ${options.min} character`);
    }
    if (options.pattern !== undefined && !options.pattern.test(value)) {
      return fail(issues, loc, 'string_pattern_mismatch', `String should match pattern '${options.pattern.source}'`);
    }
    return value;
  };
}

export function int(bounds: Bounds = {}): Parser<number> {
  return (value, loc, issues) => {
    if (typeof value !== 'number' || !Number.isInteger(value)) return fail(issues, loc, 'int_type', 'Input should be a valid integer');
    return checkBounds(value, bounds, loc, issues) ? value : INVALID;
  };
}

/** A float field: ints are accepted (Pydantic stores `1` as `1.0`), everything else non-numeric is refused. */
export function float(bounds: Bounds = {}): Parser<CanonicalFloat> {
  return (value, loc, issues) => {
    const raw = value instanceof CanonicalFloat ? value.value : value;
    if (typeof raw !== 'number') return fail(issues, loc, 'float_type', 'Input should be a valid number');
    return checkBounds(raw, bounds, loc, issues) ? new CanonicalFloat(raw) : INVALID;
  };
}

export const bool: Parser<boolean> = (value, loc, issues) =>
  typeof value === 'boolean' ? value : fail(issues, loc, 'bool_type', 'Input should be a valid boolean');

export const anyValue: Parser<unknown> = (value) => value;

export function enumOf<T extends string>(values: readonly T[]): Parser<T> {
  return (value, loc, issues) => {
    const found = values.find((item) => item === value);
    return found ?? fail(issues, loc, 'enum', `Input should be ${values.map((item) => `'${item}'`).join(', ')}`);
  };
}

export function literal<T extends string | boolean>(expected: T): Parser<T> {
  return (value, loc, issues) =>
    value === expected ? expected : fail(issues, loc, 'literal_error', `Input should be ${String(expected)}`);
}

export function list<T>(item: Parser<T>, options: { readonly min?: number } = {}): Parser<readonly T[]> {
  return (value, loc, issues) => {
    if (!Array.isArray(value)) return fail(issues, loc, 'list_type', 'Input should be a valid list');
    const before = issues.length;
    const out = value.map((entry: unknown, index) => item(entry, [...loc, index], issues));
    if (issues.length > before) return INVALID;
    if (options.min !== undefined && out.length < options.min) {
      return fail(issues, loc, 'too_short', `List should have at least ${options.min} item after validation, not ${out.length}`);
    }
    return out as T[];
  };
}

export function dict<T>(valueParser: Parser<T>): Parser<ReadonlyMap<string, T>> {
  return (value, loc, issues) => {
    const entries = dictEntries(value);
    if (entries === null) return fail(issues, loc, 'dict_type', 'Input should be a valid dictionary');
    const before = issues.length;
    const out = new Map<string, T | Invalid>();
    for (const [key, raw] of entries) out.set(key, valueParser(raw, [...loc, key], issues));
    return issues.length > before ? INVALID : (out as Map<string, T>);
  };
}

export function nullable<T>(parser: Parser<T>): Parser<T | null> {
  return (value, loc, issues) => (value === null ? null : parser(value, loc, issues));
}

export interface Field<T> {
  readonly parse: Parser<T>;
  readonly default?: () => T;
  /** Field validator: returns the error message, or null when the value is fine. */
  check?(value: T): string | null;
}

type Shape = Readonly<Record<string, Field<unknown>>>;
export type Out<S extends Shape> = { readonly [K in keyof S]: S[K] extends Field<infer T> ? T : never };

export interface ModelOptions {
  readonly extra?: 'forbid' | 'ignore';
}

function runField(spec: Field<unknown>, raw: unknown, loc: Loc, issues: Issues): unknown {
  const value = spec.parse(raw, loc, issues);
  if (value === INVALID || spec.check === undefined) return value;
  const message = spec.check(value);
  return message === null ? value : fail(issues, loc, 'value_error', `Value error, ${message}`);
}

function collectFields(shape: Shape, entries: ReadonlyMap<string, unknown>, loc: Loc, issues: Issues, forbid: boolean): Map<string, unknown> {
  const out = new Map<string, unknown>();
  for (const [key, raw] of entries) {
    const spec = Object.hasOwn(shape, key) ? shape[key] : undefined;
    if (spec !== undefined) out.set(key, runField(spec, raw, [...loc, key], issues));
    else if (forbid) fail(issues, [...loc, key], 'extra_forbidden', 'Extra inputs are not permitted');
  }
  for (const [name, spec] of Object.entries(shape)) {
    if (out.has(name)) continue;
    if (spec.default === undefined) fail(issues, [...loc, name], 'missing', 'Field required');
    else out.set(name, spec.default());
  }
  return out;
}

export function model<S extends Shape>(shape: S, options: ModelOptions = {}): Parser<Out<S>> {
  return (value, loc, issues) => {
    const entries = dictEntries(value);
    if (entries === null) return fail(issues, loc, 'model_type', 'Input should be a valid dictionary or instance of model');
    const before = issues.length;
    const fields = collectFields(shape, entries, loc, issues, options.extra !== 'ignore');
    if (issues.length > before) return INVALID;
    return Object.fromEntries(Object.keys(shape).map((name) => [name, fields.get(name)])) as Out<S>;
  };
}

/** Model `after` validators: run in order once every field passed; the first message wins. */
export function refine<T>(parser: Parser<T>, rules: ReadonlyArray<(value: NoInfer<T>) => string | null>): Parser<T> {
  return (value, loc, issues) => {
    const result = parser(value, loc, issues);
    if (result === INVALID) return INVALID;
    for (const rule of rules) {
      const message = rule(result);
      if (message !== null) return fail(issues, loc, 'value_error', `Value error, ${message}`);
    }
    return result;
  };
}

/** Parse `value` with `parser`, throwing `ValidationError` with every issue found. */
export function parse<T>(parser: Parser<T>, value: unknown): T {
  const issues: Issues = [];
  const result = parser(value, [], issues);
  if (result === INVALID || issues.length > 0) throw new ValidationError(issues);
  return result;
}

/** The value a model produces from `{}`: its defaults. Throws if a field is required. */
export function defaultsOf<T>(parser: Parser<T>): () => T {
  return () => parse(parser, new Map());
}
