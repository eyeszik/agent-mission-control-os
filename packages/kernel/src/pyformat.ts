/**
 * The few pieces of Python's text formatting the kernel's messages and
 * fingerprints depend on: `repr(str)`, `str()` of a primitive, `float.__repr__`,
 * and `sorted()` order for strings (code points, not UTF-16 code units).
 */
import { KernelTypeError } from './errors';

/** An explicit Python float. A JS `number` cannot say whether `2` was `2` or `2.0`. */
export class PyFloat {
  constructor(readonly value: number) {}
}

function codePoints(text: string): number[] {
  return Array.from(text, (ch) => ch.codePointAt(0) ?? 0);
}

/** Python `str` ordering: by code point. JS `<` compares UTF-16 units, which differs above U+FFFF. */
export function compareCodePoints(a: string, b: string): number {
  const left = codePoints(a);
  const right = codePoints(b);
  const shared = Math.min(left.length, right.length);
  for (let i = 0; i < shared; i += 1) {
    const diff = (left[i] ?? 0) - (right[i] ?? 0);
    if (diff !== 0) return diff;
  }
  return left.length - right.length;
}

/** `sorted(values)` for strings. Returns a new array. */
export function pySorted<T extends string>(values: Iterable<T>): T[] {
  return Array.from(values).sort(compareCodePoints);
}

function shortestDigits(magnitude: number): { digits: string; exponent: number } {
  const [mantissa = '0', exponent = '0'] = magnitude.toExponential().split('e');
  return { digits: mantissa.replace('.', ''), exponent: Number(exponent) };
}

function fixedNotation(digits: string, exponent: number): string {
  if (exponent < 0) return `0.${'0'.repeat(-exponent - 1)}${digits}`;
  const integer = digits.slice(0, exponent + 1).padEnd(exponent + 1, '0');
  return `${integer}.${digits.slice(exponent + 1) || '0'}`;
}

function scientificNotation(digits: string, exponent: number): string {
  const mantissa = digits.length > 1 ? `${digits[0]}.${digits.slice(1)}` : digits;
  const sign = exponent < 0 ? '-' : '+';
  return `${mantissa}e${sign}${String(Math.abs(exponent)).padStart(2, '0')}`;
}

/**
 * `float.__repr__` for a finite value: shortest round-trip digits, fixed
 * notation for decimal exponents in [-4, 16), scientific otherwise.
 */
export function floatRepr(value: number): string {
  if (!Number.isFinite(value)) throw new KernelTypeError('floatRepr takes a finite number');
  if (value === 0) return Object.is(value, -0) ? '-0.0' : '0.0';
  const sign = value < 0 ? '-' : '';
  const { digits, exponent } = shortestDigits(Math.abs(value));
  const body = exponent >= -4 && exponent < 16 ? fixedNotation(digits, exponent) : scientificNotation(digits, exponent);
  return sign + body;
}

// Python's str.isprintable() is false for these general categories (space excepted).
const NON_PRINTABLE = /[\p{Cc}\p{Cf}\p{Cs}\p{Co}\p{Cn}\p{Zl}\p{Zp}\p{Zs}]/u;
const SHORT_ESCAPES: Readonly<Record<string, string>> = { '\t': '\\t', '\n': '\\n', '\r': '\\r', '\\': '\\\\' };

function hexEscape(point: number): string {
  if (point <= 0xff) return `\\x${point.toString(16).padStart(2, '0')}`;
  if (point <= 0xffff) return `\\u${point.toString(16).padStart(4, '0')}`;
  return `\\U${point.toString(16).padStart(8, '0')}`;
}

function reprChar(ch: string, quote: string): string {
  const short = SHORT_ESCAPES[ch];
  if (short !== undefined) return short;
  if (ch === quote) return `\\${quote}`;
  if (ch !== ' ' && NON_PRINTABLE.test(ch)) return hexEscape(ch.codePointAt(0) ?? 0);
  return ch;
}

/** `repr(text)` for a Python `str`. */
export function pyRepr(text: string): string {
  const quote = text.includes("'") && !text.includes('"') ? '"' : "'";
  return quote + Array.from(text, (ch) => reprChar(ch, quote)).join('') + quote;
}

function reprAny(value: unknown): string {
  if (typeof value === 'string') return pyRepr(value);
  if (Array.isArray(value)) return `[${value.map(reprAny).join(', ')}]`;
  if (isPlainObject(value)) {
    return `{${Object.entries(value).map(([k, v]) => `${pyRepr(k)}: ${reprAny(v)}`).join(', ')}}`;
  }
  return pyStr(value);
}

function numberStr(value: number): string {
  if (Number.isNaN(value)) return 'nan';
  if (!Number.isFinite(value)) return value > 0 ? 'inf' : '-inf';
  return Number.isInteger(value) && !Object.is(value, -0) ? String(value) : floatRepr(value);
}

/**
 * `str(value)` as an f-string renders it. Integral numbers render as ints;
 * pass `PyFloat` for a Python float with an integral value.
 */
export function pyStr(value: unknown): string {
  if (value === null || value === undefined) return 'None';
  if (typeof value === 'string') return value;
  if (typeof value === 'boolean') return value ? 'True' : 'False';
  if (typeof value === 'number') return numberStr(value);
  if (typeof value === 'bigint') return value.toString();
  if (value instanceof PyFloat) return Number.isFinite(value.value) ? floatRepr(value.value) : numberStr(value.value);
  if (Array.isArray(value) || isPlainObject(value)) return reprAny(value);
  throw new KernelTypeError(`cannot render ${Object.prototype.toString.call(value)} as Python text`);
}

/** Python's type name for a JSON-shaped value, as `int()` reports it. */
export function pyTypeName(value: unknown): string {
  if (value === null || value === undefined) return 'NoneType';
  if (typeof value === 'string') return 'str';
  if (typeof value === 'boolean') return 'bool';
  if (typeof value === 'bigint') return 'int';
  if (typeof value === 'number') return Number.isInteger(value) ? 'int' : 'float';
  if (value instanceof PyFloat) return 'float';
  return Array.isArray(value) ? 'list' : 'dict';
}

/** A plain `{}` record: not an array, not a class instance. */
export function isPlainObject(value: unknown): value is Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return false;
  const proto: unknown = Object.getPrototypeOf(value);
  return proto === Object.prototype || proto === null;
}

/** Python truthiness for a JSON-shaped value. */
export function pyTruthy(value: unknown): boolean {
  if (value === null || value === undefined || value === false || value === '' || value === 0) return false;
  if (typeof value === 'bigint') return value !== 0n;
  if (value instanceof PyFloat) return value.value !== 0;
  if (Array.isArray(value)) return value.length > 0;
  if (isPlainObject(value)) return Object.keys(value).length > 0;
  return true;
}
