/**
 * The small slice of Python semantics the reference compiler leans on, rebuilt
 * exactly: code-point string ordering, `str.strip()`, `repr()`, `float` repr,
 * `f"{x:.4f}"` (exact, round-half-even), `round()` (banker's), `float(int)`.
 *
 * Numbers follow the `@amc/canonical` convention: an integral `number` (or a
 * `bigint`) is a Python int, a non-integral or non-finite `number` is a Python
 * float, and an integral float (Python `1.0`) is a `CanonicalFloat`.
 */
import { CanonicalFloat } from '@amc/canonical';

export type PythonErrorType = 'TypeError' | 'OverflowError' | 'AttributeError' | 'KeyError';

/** A Python builtin exception the reference raises outside the TokenError hierarchy. */
export class PythonRuntimeError extends Error {
  override name = 'PythonRuntimeError';

  constructor(
    readonly pythonType: PythonErrorType,
    message: string,
  ) {
    super(message);
  }
}

/** A JSON number as Python sees it. */
export type PyNumber = number | bigint | CanonicalFloat;

/** A JSON object (Python `Mapping`): a plain object, never an array or a wrapper. */
export type Mapping = Readonly<Record<string, unknown>>;

export function isMapping(value: unknown): value is Mapping {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const proto: unknown = Object.getPrototypeOf(value);
  return proto === Object.prototype || proto === null;
}

/** Python `mapping.get(key, default)`: own keys only. */
export function pyGet(mapping: Mapping, key: string, fallback: unknown = null): unknown {
  return Object.hasOwn(mapping, key) ? mapping[key] : fallback;
}

/** Python `isinstance(v, (int, float)) and not isinstance(v, bool)`. */
export function isNumber(value: unknown): value is PyNumber {
  return typeof value === 'number' || typeof value === 'bigint' || value instanceof CanonicalFloat;
}

/** The exact numeric value, for comparisons (JS compares number and bigint exactly). */
export function numeric(value: PyNumber): number | bigint {
  return value instanceof CanonicalFloat ? value.value : value;
}

/** Python `float(value)`, including its OverflowError for huge ints. */
export function toFloat(value: PyNumber): number {
  if (typeof value !== 'bigint') return Number(numeric(value));
  const converted = Number(value);
  if (!Number.isFinite(converted)) {
    throw new PythonRuntimeError('OverflowError', 'int too large to convert to float');
  }
  return converted;
}

/** Python's name for the type of a JSON value, as used in builtin error messages. */
export function pyTypeName(value: unknown): string {
  if (value === null || value === undefined) return 'NoneType';
  if (typeof value === 'boolean') return 'bool';
  if (typeof value === 'bigint') return 'int';
  if (typeof value === 'number') return Number.isInteger(value) ? 'int' : 'float';
  if (value instanceof CanonicalFloat) return 'float';
  if (typeof value === 'string') return 'str';
  if (Array.isArray(value)) return 'list';
  return isMapping(value) ? 'dict' : typeof value;
}

/** Python `value in frozenset_of_str`, including the TypeError for unhashable values. */
export function inStringSet(set: ReadonlySet<string>, value: unknown): boolean {
  if (Array.isArray(value) || isMapping(value)) {
    throw new PythonRuntimeError('TypeError', `unhashable type: '${pyTypeName(value)}'`);
  }
  return typeof value === 'string' && set.has(value);
}

/** Python `str` ordering: by code point (JS's default sort is by UTF-16 unit). */
export function compareCodePoints(a: string, b: string): number {
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    const ca = a.codePointAt(i) ?? 0;
    const cb = b.codePointAt(j) ?? 0;
    if (ca !== cb) return ca - cb;
    i += ca > 0xffff ? 2 : 1;
    j += cb > 0xffff ? 2 : 1;
  }
  return a.length - i - (b.length - j);
}

/** Python `sorted(strings)`. */
export function sortedStrings(values: Iterable<string>): string[] {
  return [...values].sort(compareCodePoints);
}

// Python str.isspace(): JS trim() minus U+FEFF, plus U+001C..U+001F and U+0085.
const PY_SPACE = '\\t\\n\\v\\f\\r\\x1c-\\x20\\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000';
const PY_STRIP = new RegExp(`^[${PY_SPACE}]+|[${PY_SPACE}]+$`, 'g');

/** Python `str.strip()` with no arguments. */
export function pyStrip(text: string): string {
  return text.replace(PY_STRIP, '');
}

function sciRepr(digits: string, exponent: number): string {
  const mantissa = digits.length > 1 ? `${digits[0]}.${digits.slice(1)}` : digits;
  const sign = exponent < 0 ? '-' : '+';
  return `${mantissa}e${sign}${String(Math.abs(exponent)).padStart(2, '0')}`;
}

function positionalRepr(digits: string, exponent: number): string {
  const pointAt = exponent + 1;
  if (pointAt <= 0) return `0.${'0'.repeat(-pointAt)}${digits}`;
  if (pointAt >= digits.length) return `${digits}${'0'.repeat(pointAt - digits.length)}.0`;
  return `${digits.slice(0, pointAt)}.${digits.slice(pointAt)}`;
}

/** Python `repr(float)`: shortest round-trip digits, exponent form outside [1e-4, 1e16). */
export function floatRepr(value: number): string {
  if (Number.isNaN(value)) return 'nan';
  if (!Number.isFinite(value)) return value > 0 ? 'inf' : '-inf';
  if (value === 0) return Object.is(value, -0) ? '-0.0' : '0.0';
  const [mantissa = '', exp = '0'] = Math.abs(value).toExponential().split('e');
  const digits = mantissa.replace('.', '');
  const exponent = Number(exp);
  const body = exponent < -4 || exponent >= 16 ? sciRepr(digits, exponent) : positionalRepr(digits, exponent);
  return (value < 0 ? '-' : '') + body;
}

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

/** Python `f"{value:.{places}f}"`: exact binary value, round-half-even, sign kept on zero. */
export function formatFixed(value: number, places: number): string {
  if (Number.isNaN(value)) return 'nan';
  if (!Number.isFinite(value)) return value > 0 ? 'inf' : '-inf';
  const { negative, mantissa, exponent } = decompose(value);
  const scale = 10n ** BigInt(places);
  const units =
    exponent >= 0
      ? (mantissa << BigInt(exponent)) * scale
      : roundedQuotient(mantissa * scale, 1n << BigInt(-exponent));
  const text = units.toString().padStart(places + 1, '0');
  const fraction = places > 0 ? `.${text.slice(-places)}` : '';
  return `${negative ? '-' : ''}${places > 0 ? text.slice(0, -places) : text}${fraction}`;
}

/** Python `round(value)` for a float: nearest int, ties to even. */
export function roundHalfEven(value: number): number {
  const floor = Math.floor(value);
  const diff = value - floor;
  if (diff > 0.5) return floor + 1;
  if (diff < 0.5) return floor;
  return floor % 2 === 0 ? floor : floor + 1;
}

/** Python `round(value, places)` for a float: correctly rounded, back to a float. */
export function roundTo(value: number, places: number): number {
  return Number(formatFixed(value, places));
}

// Python str.isprintable() is false for these categories (space excepted).
const NON_PRINTABLE = /[\p{Cc}\p{Cf}\p{Cs}\p{Co}\p{Cn}\p{Zl}\p{Zp}\p{Zs}]/u;
const SHORT_ESCAPES: Readonly<Record<string, string>> = { '\\': '\\\\', '\t': '\\t', '\n': '\\n', '\r': '\\r' };

function escapeReprChar(ch: string, quote: string): string {
  if (ch === quote) return `\\${quote}`;
  const short = SHORT_ESCAPES[ch];
  if (short !== undefined) return short;
  if (ch === ' ' || !NON_PRINTABLE.test(ch)) return ch;
  const cp = ch.codePointAt(0) ?? 0;
  if (cp < 0x100) return `\\x${cp.toString(16).padStart(2, '0')}`;
  if (cp < 0x10000) return `\\u${cp.toString(16).padStart(4, '0')}`;
  return `\\U${cp.toString(16).padStart(8, '0')}`;
}

/** Python `repr(str)`. */
export function reprString(text: string): string {
  const quote = text.includes("'") && !text.includes('"') ? '"' : "'";
  return quote + Array.from(text, (ch) => escapeReprChar(ch, quote)).join('') + quote;
}

function reprMapping(value: Mapping): string {
  return `{${Object.entries(value)
    .map(([key, item]) => `${reprString(key)}: ${pyRepr(item)}`)
    .join(', ')}}`;
}

/** Python `repr()` of a JSON value (dict order is JS object order; see the index.ts notes). */
export function pyRepr(value: unknown): string {
  if (value === null || value === undefined) return 'None';
  if (typeof value === 'boolean') return value ? 'True' : 'False';
  if (typeof value === 'bigint') return value.toString();
  if (typeof value === 'number') return Number.isInteger(value) ? BigInt(value).toString() : floatRepr(value);
  if (typeof value === 'string') return reprString(value);
  if (value instanceof CanonicalFloat) return floatRepr(value.value);
  if (Array.isArray(value)) return `[${value.map((item: unknown) => pyRepr(item)).join(', ')}]`;
  if (isMapping(value)) return reprMapping(value);
  return `<${typeof value}>`;
}
