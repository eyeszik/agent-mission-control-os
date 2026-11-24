/**
 * The pieces of Python semantics the compiled planner depends on that JS does
 * differently: string ordering (code points), tuple ordering, `str.strip()`,
 * `str.lower()`, `str.casefold()`, `\s` and `round(x, n)`.
 *
 * Case and whitespace come from tables generated from Python itself
 * (`python-unicode.ts`), so the JS engine's Unicode version never decides a
 * result. `str.lower()` applies a context rule to U+03A3 (final sigma) that a
 * per-character table cannot reproduce; the twin refuses that character
 * instead of guessing.
 */
import { compareCodePoints } from '@amc/kernel';
import { CompiledIndexError, CompiledValueError } from './errors';
import { PY_CASEFOLD, PY_LOWER, PY_SPACE } from './python-unicode';

export { compareCodePoints };

const SPACE = new Set<number>(PY_SPACE);
const LOWER = new Map<number, string>(PY_LOWER);
const CASEFOLD = new Map<number, string>(PY_CASEFOLD);
const CAPITAL_SIGMA = 0x3a3;

/** `sorted()` of strings, by code point. Returns a new array. */
export function sortStrings(values: Iterable<string>): string[] {
  return Array.from(values).sort(compareCodePoints);
}

/** `sorted(set(values))` for strings. */
export function uniqueSorted(values: Iterable<string>): string[] {
  return sortStrings(new Set(values));
}

export type PyScalar = string | number;

/** Python ordering of two scalars of the same kind (str vs str, int vs int). */
export function compareScalars(a: PyScalar, b: PyScalar): number {
  if (typeof a === 'number' && typeof b === 'number') return a < b ? -1 : a > b ? 1 : 0;
  return compareCodePoints(String(a), String(b));
}

/** Python tuple ordering: element-wise, then by length. */
export function compareTuples(a: readonly PyScalar[], b: readonly PyScalar[]): number {
  const shared = Math.min(a.length, b.length);
  for (let i = 0; i < shared; i += 1) {
    const diff = compareScalars(a[i] as PyScalar, b[i] as PyScalar);
    if (diff !== 0) return diff;
  }
  return a.length - b.length;
}

/** Python `text[start:end]` (code points, not UTF-16 units) for non-negative bounds. */
export function pySlice(text: string, start: number, end?: number): string {
  if (/^[\x00-\x7f]*$/.test(text)) return text.slice(start, end);
  return Array.from(text).slice(start, end).join('');
}

/** Python `text.split(":", 1)[1]`; Python raises IndexError when there is no separator. */
export function afterFirst(text: string, separator: string): string {
  const cut = text.indexOf(separator);
  if (cut < 0) throw new CompiledIndexError('list index out of range');
  return text.slice(cut + separator.length);
}

/** Python `str.isspace()` for one code point. */
export function isPySpace(point: number): boolean {
  return SPACE.has(point);
}

/** Python `str.strip()` with no arguments. */
export function pyStrip(text: string): string {
  const points = Array.from(text);
  let start = 0;
  let end = points.length;
  while (start < end && isPySpace(points[start]?.codePointAt(0) ?? 0)) start += 1;
  while (end > start && isPySpace(points[end - 1]?.codePointAt(0) ?? 0)) end -= 1;
  return points.slice(start, end).join('');
}

/** `re.sub(r"\s+", " ", text)` for a str pattern. */
export function collapseWhitespace(text: string): string {
  let out = '';
  let inRun = false;
  for (const ch of text) {
    if (isPySpace(ch.codePointAt(0) ?? 0)) {
      if (!inRun) out += ' ';
      inRun = true;
    } else {
      out += ch;
      inRun = false;
    }
  }
  return out;
}

/** Python `str.lower()`. Refuses U+03A3, whose lowercase depends on context. */
export function pyLower(text: string): string {
  let out = '';
  for (const ch of text) {
    const point = ch.codePointAt(0) ?? 0;
    if (point === CAPITAL_SIGMA) {
      throw new CompiledValueError('str.lower() of U+03A3 (final-sigma context rule) is not reproduced by the twin');
    }
    out += LOWER.get(point) ?? ch;
  }
  return out;
}

/** Python `str.casefold()`: a context-free per-character mapping. */
export function pyCasefold(text: string): string {
  let out = '';
  for (const ch of text) out += CASEFOLD.get(ch.codePointAt(0) ?? 0) ?? ch;
  return out;
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

/** Python `round(value, places)` for a finite float: exact binary value, ties to even. */
export function pyRound(value: number, places: number): number {
  if (!Number.isFinite(value)) throw new CompiledValueError('pyRound takes a finite number');
  const { negative, mantissa, exponent } = decompose(value);
  const scale = 10n ** BigInt(places);
  const units =
    exponent >= 0 ? (mantissa << BigInt(exponent)) * scale : roundedQuotient(mantissa * scale, 1n << BigInt(-exponent));
  const text = units.toString().padStart(places + 1, '0');
  const fixed = `${negative ? '-' : ''}${text.slice(0, -places)}.${text.slice(-places)}`;
  return Number(fixed);
}

/** Python truthiness for a JSON-shaped value. */
export function pyTruthy(value: unknown): boolean {
  if (value === null || value === undefined || value === false || value === '' || value === 0) return false;
  if (typeof value === 'bigint') return value !== 0n;
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === 'object') return Object.keys(value).length > 0;
  return true;
}
