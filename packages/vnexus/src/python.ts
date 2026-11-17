/**
 * The pieces of Python semantics the VNEXUS core depends on: value equality
 * (`1 == 1.0 == True`), `repr()`/`str()` of JSON-shaped data, `round()` and
 * `format()` on the exact binary value, `str.strip()`, code-point ordering and
 * the synchronous AMC-CANON-1 hash.
 *
 * Numbers: an integral `number` is a Python int, a non-integral `number` a
 * float, and a float with an integral value must be a `CanonicalFloat`
 * (the one float marker shared with `@amc/canonical`).
 */
import { CanonicalFloat, canonicalBytes, type CanonicalValue } from '@amc/canonical';
import { compareCodePoints, floatRepr as kernelFloatRepr, pyRepr as reprText, sha256Hex } from '@amc/kernel';
import { PY_SPACE_CHARS } from './python-tables';

export { CanonicalFloat, compareCodePoints };

/** JSON-shaped Python data: what `model_dump(mode="json")` and `dict[str, Any]` fields hold. */
export type PyData =
  | null
  | boolean
  | number
  | string
  | CanonicalFloat
  | readonly PyData[]
  | { readonly [key: string]: PyData };

/** A Python float: a non-integral `number`, or a `CanonicalFloat`. */
export type PyFloatValue = number | CanonicalFloat;

export function isPlainRecord(value: unknown): value is { readonly [key: string]: PyData } {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return false;
  const proto: unknown = Object.getPrototypeOf(value);
  return proto === Object.prototype || proto === null;
}

/** `isinstance(v, float)`. */
export function isFloat(value: unknown): value is PyFloatValue {
  return value instanceof CanonicalFloat || (typeof value === 'number' && !Number.isInteger(value));
}

/** `isinstance(v, int) and not isinstance(v, bool)`. */
export function isInt(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value);
}

/** `isinstance(v, (int, float)) and not isinstance(v, bool)`. */
export function isRealNumber(value: unknown): value is number | CanonicalFloat {
  return typeof value === 'number' || value instanceof CanonicalFloat;
}

/** `isinstance(v, (int, float))`: bool is an int subclass in Python. */
export function isNumberOrBool(value: unknown): value is number | boolean | CanonicalFloat {
  return isRealNumber(value) || typeof value === 'boolean';
}

/** The numeric value of an int, float or bool. */
export function num(value: number | boolean | CanonicalFloat): number {
  if (typeof value === 'boolean') return value ? 1 : 0;
  return value instanceof CanonicalFloat ? value.value : value;
}

/** A Python float result: integral values are wrapped so they still encode as floats. */
export function pyFloat(value: number): PyFloatValue {
  return Number.isInteger(value) ? new CanonicalFloat(value) : value;
}

function listEq(a: readonly unknown[], b: readonly unknown[]): boolean {
  return a.length === b.length && a.every((item, i) => pyEq(item, b[i]));
}

function recordEq(a: { readonly [key: string]: unknown }, b: { readonly [key: string]: unknown }): boolean {
  const keys = Object.keys(a);
  if (keys.length !== Object.keys(b).length) return false;
  return keys.every((k) => Object.prototype.hasOwnProperty.call(b, k) && pyEq(a[k], b[k]));
}

/** Python `==` over JSON-shaped data (numbers compare by value across int/float/bool). */
export function pyEq(a: unknown, b: unknown): boolean {
  if (isNumberOrBool(a) && isNumberOrBool(b)) return num(a) === num(b);
  if (a === null || b === null || typeof a === 'string' || typeof b === 'string') return a === b;
  if (Array.isArray(a) && Array.isArray(b)) return listEq(a, b);
  if (isPlainRecord(a) && isPlainRecord(b)) return recordEq(a, b);
  return false;
}

/** `x in items` (identity, then `==`). */
export function pyIn(value: unknown, items: readonly unknown[]): boolean {
  return items.some((item) => item === value || pyEq(value, item));
}

/** `float.__repr__`, including the non-finite spellings. */
export function floatRepr(value: number): string {
  if (Number.isNaN(value)) return 'nan';
  if (!Number.isFinite(value)) return value > 0 ? 'inf' : '-inf';
  return kernelFloatRepr(value);
}

function reprNumber(value: number): string {
  return Number.isInteger(value) ? String(value) : floatRepr(value);
}

/** Python `repr()` of JSON-shaped data (dicts in insertion order). */
export function pyRepr(value: unknown): string {
  if (value === null || value === undefined) return 'None';
  if (typeof value === 'boolean') return value ? 'True' : 'False';
  if (typeof value === 'number') return reprNumber(value);
  if (value instanceof CanonicalFloat) return floatRepr(value.value);
  if (typeof value === 'string') return reprText(value);
  if (Array.isArray(value)) return `[${value.map(pyRepr).join(', ')}]`;
  if (isPlainRecord(value)) {
    return `{${Object.entries(value).map(([k, v]) => `${reprText(k)}: ${pyRepr(v)}`).join(', ')}}`;
  }
  throw new TypeError(`cannot render ${Object.prototype.toString.call(value)} as Python text`);
}

/** Python `str()` (what an f-string renders): strings bare, everything else as `repr()`. */
export function pyStr(value: unknown): string {
  return typeof value === 'string' ? value : pyRepr(value);
}

/** Python truthiness for JSON-shaped data. */
export function pyTruthy(value: unknown): boolean {
  if (value === null || value === undefined || value === '' || value === false) return false;
  if (isNumberOrBool(value)) return num(value) !== 0;
  if (Array.isArray(value)) return value.length > 0;
  if (isPlainRecord(value)) return Object.keys(value).length > 0;
  return true;
}

/** `sorted()` for strings (code-point order). */
export function sortedStrings(values: Iterable<string>): string[] {
  return Array.from(values).sort(compareCodePoints);
}

/** `sorted(set(values))`. */
export function sortedUnique(values: Iterable<string>): string[] {
  return sortedStrings(new Set(values));
}

/** Python `a < b` for two strings. */
export function strLess(a: string, b: string): boolean {
  return compareCodePoints(a, b) < 0;
}

/** Python's code-point length of a string. */
export function pyLen(text: string): number {
  let n = 0;
  for (const _ of text) n += 1;
  return n;
}

/** `str.strip()` with no arguments (Python's `isspace()` set). */
export function pyStrip(text: string, chars: string = PY_SPACE_CHARS): string {
  const points = Array.from(text);
  let start = 0;
  let end = points.length;
  while (start < end && chars.includes(points[start] ?? '')) start += 1;
  while (end > start && chars.includes(points[end - 1] ?? '')) end -= 1;
  return points.slice(start, end).join('');
}

/** `canonical_hash(value)`: AMC-CANON-1 bytes, synchronous SHA-256 (Python's hash is synchronous). */
export function canonicalHashSync(value: CanonicalValue): string {
  return sha256Hex(canonicalBytes(value));
}

// -- round() and format() on the exact binary value -------------------------------

function decompose(value: number): { negative: boolean; mantissa: bigint; exponent: number } {
  const view = new DataView(new ArrayBuffer(8));
  view.setFloat64(0, value);
  const hi = view.getUint32(0);
  const biased = (hi >>> 20) & 0x7ff;
  const fraction = (BigInt(hi & 0xfffff) << 32n) | BigInt(view.getUint32(4));
  const mantissa = biased === 0 ? fraction : fraction | (1n << 52n);
  return { negative: hi >>> 31 === 1, mantissa, exponent: (biased === 0 ? 1 : biased) - 1075 };
}

function roundedQuotient(numerator: bigint, denominator: bigint): bigint {
  const quotient = numerator / denominator;
  const twice = (numerator % denominator) * 2n;
  const up = twice > denominator || (twice === denominator && quotient % 2n === 1n);
  return up ? quotient + 1n : quotient;
}

/** Python `f"{value:.{places}f}"`: exact binary value, round half to even, sign kept on zero. */
export function formatFixed(value: number, places: number): string {
  if (Number.isNaN(value)) return 'nan';
  if (!Number.isFinite(value)) return value > 0 ? 'inf' : '-inf';
  const { negative, mantissa, exponent } = decompose(value);
  const scale = 10n ** BigInt(places);
  const units = exponent >= 0
    ? (mantissa << BigInt(exponent)) * scale
    : roundedQuotient(mantissa * scale, 1n << BigInt(-exponent));
  const text = units.toString().padStart(places + 1, '0');
  const fraction = places > 0 ? `.${text.slice(-places)}` : '';
  return `${negative ? '-' : ''}${places > 0 ? text.slice(0, -places) : text}${fraction}`;
}

/** Python `round(value, places)` for a float: correctly rounded, back to a float. */
export function roundTo(value: number, places: number): number {
  if (!Number.isFinite(value)) return value;
  return Number(formatFixed(value, places));
}

/** Python `round(value)` for a float: nearest integer, ties to even. */
export function roundHalfEven(value: number): number {
  const floor = Math.floor(value);
  const diff = value - floor;
  if (diff > 0.5) return floor + 1;
  if (diff < 0.5) return floor;
  return floor % 2 === 0 ? floor : floor + 1;
}

/** Python `f"{value:.0%}"`: the value is multiplied by 100 in float arithmetic first. */
export function formatPercent0(value: number): string {
  return `${formatFixed(value * 100, 0)}%`;
}
