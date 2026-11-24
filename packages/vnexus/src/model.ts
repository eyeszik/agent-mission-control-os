/**
 * A small Pydantic-shaped validator: fields in declaration order, every issue
 * collected, a field's own "after" validator only when its type check passed,
 * and a model's "after" validator only when every field passed.
 *
 * It is strict where Pydantic's lax mode coerces (numeric strings, bool as a
 * number, integral floats for int fields, unix timestamps for dates). Those
 * inputs are refused, and the parity fixture records each one as an explicit
 * "Python accepts, TypeScript refuses" case.
 */
import { CanonicalFloat } from '@amc/canonical';
import { ValidationError, type ValidationIssue } from './errors';
import { isPlainRecord, pyFloat, pyLen, type PyData, type PyFloatValue } from './python';

export const INVALID: unique symbol = Symbol('invalid');
export type Parsed<T> = T | typeof INVALID;

export class Issues {
  readonly list: ValidationIssue[] = [];

  add(loc: string, msg: string, custom = false): typeof INVALID {
    this.list.push({ loc, msg, custom });
    return INVALID;
  }
}

/** Raised inside an "after" validator; becomes a custom issue at that location. */
export class ModelValueError extends Error {
  override name = 'ValueError';
}

export type FieldParser<T> = (value: unknown, loc: string, issues: Issues) => Parsed<T>;

export interface FieldSpec {
  readonly parse: FieldParser<unknown>;
  /** Produces the default when the key is absent; absent means the field is required. */
  readonly fallback?: () => unknown;
}

export type ModelSpec = Readonly<Record<string, FieldSpec>>;

function join(loc: string, key: string): string {
  return loc ? `${loc}.${key}` : key;
}

export interface StrOptions {
  readonly min?: number;
  readonly max?: number;
  readonly pattern?: RegExp;
}

export function str(options: StrOptions = {}): FieldParser<string> {
  return (value, loc, issues) => {
    if (typeof value !== 'string') return issues.add(loc, 'Input should be a valid string');
    const length = pyLen(value);
    if (options.min !== undefined && length < options.min) return issues.add(loc, `String should have at least ${options.min} characters`);
    if (options.max !== undefined && length > options.max) return issues.add(loc, `String should have at most ${options.max} characters`);
    if (options.pattern && !options.pattern.test(value)) return issues.add(loc, `String should match pattern '${options.pattern.source}'`);
    return value;
  };
}

export interface NumberOptions {
  readonly gt?: number;
  readonly ge?: number;
  readonly lt?: number;
  readonly le?: number;
}

function boundsIssue(value: number, o: NumberOptions): string | null {
  if (o.gt !== undefined && !(value > o.gt)) return `Input should be greater than ${o.gt}`;
  if (o.ge !== undefined && !(value >= o.ge)) return `Input should be greater than or equal to ${o.ge}`;
  if (o.lt !== undefined && !(value < o.lt)) return `Input should be less than ${o.lt}`;
  if (o.le !== undefined && !(value <= o.le)) return `Input should be less than or equal to ${o.le}`;
  return null;
}

/** A Pydantic `int` field, strictly: an integral `number` only (no bool, no float, no string). */
export function int(options: NumberOptions = {}): FieldParser<number> {
  return (value, loc, issues) => {
    if (typeof value !== 'number' || !Number.isInteger(value)) return issues.add(loc, 'Input should be a valid integer');
    if (!Number.isSafeInteger(value)) return issues.add(loc, 'integers beyond 2^53 are refused');
    const problem = boundsIssue(value, options);
    return problem ? issues.add(loc, problem) : value;
  };
}

/** A Pydantic `float` field: an int or float (no bool, no string); an int becomes a float, as in Pydantic. */
export function float(options: NumberOptions = {}): FieldParser<PyFloatValue> {
  return (value, loc, issues) => {
    if (typeof value !== 'number' && !(value instanceof CanonicalFloat)) return issues.add(loc, 'Input should be a valid number');
    const n = value instanceof CanonicalFloat ? value.value : value;
    const problem = boundsIssue(n, options);
    return problem ? issues.add(loc, problem) : pyFloat(n);
  };
}

export function bool(): FieldParser<boolean> {
  return (value, loc, issues) => (typeof value === 'boolean' ? value : issues.add(loc, 'Input should be a valid boolean'));
}

export function enumOf<T extends string>(values: readonly T[]): FieldParser<T> {
  return (value, loc, issues) => {
    const found = values.find((v) => v === value);
    return found ?? issues.add(loc, `Input should be ${values.map((v) => `'${v}'`).join(', ')}`);
  };
}

export function optional<T>(parse: FieldParser<T>): FieldParser<T | null> {
  return (value, loc, issues) => (value === null ? null : parse(value, loc, issues));
}

export interface ListOptions {
  readonly min?: number;
  readonly max?: number;
}

/** A `tuple[X, ...]`/`list[X]` field (arrays only). */
export function listOf<T>(parse: FieldParser<T>, options: ListOptions = {}): FieldParser<T[]> {
  return (value, loc, issues) => {
    if (!Array.isArray(value)) return issues.add(loc, 'Input should be a valid list');
    const before = issues.list.length;
    const items = value.map((item: unknown, i) => parse(item, join(loc, String(i)), issues));
    if (options.max !== undefined && value.length > options.max) issues.add(loc, `List should have at most ${options.max} items`);
    if (options.min !== undefined && value.length < options.min) issues.add(loc, `List should have at least ${options.min} items`);
    return issues.list.length > before ? INVALID : (items as T[]);
  };
}

/** A `dict[K, V]` field: a plain object; keys are validated by `parseKey`. */
export function dictOf<K extends string, V>(parseKey: FieldParser<K>, parseValue: FieldParser<V>): FieldParser<Record<K, V>> {
  return (value, loc, issues) => {
    if (!isPlainRecord(value)) return issues.add(loc, 'Input should be a valid dictionary');
    const before = issues.list.length;
    const out: Record<string, V> = {};
    for (const [key, item] of Object.entries(value)) {
      const k = parseKey(key, join(loc, `${key}[key]`), issues);
      const v = parseValue(item, join(loc, key), issues);
      if (k !== INVALID && v !== INVALID) out[k] = v;
    }
    return issues.list.length > before ? INVALID : (out as Record<K, V>);
  };
}

function isPyData(value: unknown): value is PyData {
  if (value === null || typeof value === 'boolean' || typeof value === 'string' || value instanceof CanonicalFloat) return true;
  if (typeof value === 'number') return true;
  if (Array.isArray(value)) return value.every(isPyData);
  return isPlainRecord(value) && Object.values(value).every(isPyData);
}

/** An `Any` field: JSON-shaped data only. */
export function anyData(): FieldParser<PyData> {
  return (value, loc, issues) => (isPyData(value) ? value : issues.add(loc, 'only JSON-shaped data is accepted'));
}

/** Adds a field "after" validator: runs only on a value that passed `parse`. */
export function after<T>(parse: FieldParser<T>, check: (value: T) => void): FieldParser<T> {
  return (value, loc, issues) => {
    const parsed = parse(value, loc, issues);
    if (parsed === INVALID) return INVALID;
    try {
      check(parsed);
    } catch (error) {
      if (error instanceof ModelValueError) return issues.add(loc, error.message, true);
      throw error;
    }
    return parsed;
  };
}

function readFields(input: { readonly [key: string]: unknown }, spec: ModelSpec, loc: string, issues: Issues): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [name, field] of Object.entries(spec)) {
    if (!Object.prototype.hasOwnProperty.call(input, name)) {
      if (field.fallback) out[name] = field.fallback();
      else issues.add(join(loc, name), 'Field required');
      continue;
    }
    const parsed = field.parse(input[name], join(loc, name), issues);
    if (parsed !== INVALID) out[name] = parsed;
  }
  return out;
}

export interface ModelOptions<T> {
  readonly extra: 'forbid' | 'ignore';
  readonly check?: (model: T) => void;
}

/** A nested model field. `check` is the model's "after" validator. */
export function model<T>(spec: ModelSpec, options: ModelOptions<T>): FieldParser<T> {
  return (value, loc, issues) => {
    if (!isPlainRecord(value)) return issues.add(loc, 'Input should be a valid dictionary');
    const before = issues.list.length;
    const out = readFields(value, spec, loc, issues);
    if (options.extra === 'forbid') {
      for (const key of Object.keys(value)) if (!(key in spec)) issues.add(join(loc, key), 'Extra inputs are not permitted');
    }
    if (issues.list.length > before) return INVALID;
    const built = out as T;
    return after<T>(() => built, (m) => options.check?.(m))(value, loc, issues);
  };
}

/** Validates `input` with `parse` and throws a `ValidationError` naming `title` on any issue. */
export function validate<T>(title: string, parse: FieldParser<T>, input: unknown): T {
  const issues = new Issues();
  const parsed = parse(input, '', issues);
  if (parsed === INVALID || issues.list.length > 0) throw new ValidationError(title, issues.list);
  return parsed;
}
