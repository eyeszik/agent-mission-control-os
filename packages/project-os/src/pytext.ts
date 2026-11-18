/**
 * Python text semantics the Project OS policies depend on: code-point
 * slicing, `str.strip()` / `str.split()`, `str.lower()` (as far as it can
 * change an ASCII comparison), `float(str)` and `round(float, n)`.
 *
 * Whitespace, digit values and lowercase come from `python-casefold.ts`
 * (generated from Python itself), never from the JS engine's Unicode tables.
 */
import { CanonicalFloat } from '@amc/canonical';
import { PyFloat, pyStr } from '@amc/kernel';
import { DECIMAL_ZEROS, FULL_LOWER_ASCII, SPACE_RANGES } from './python-casefold';

export type Ranges = readonly (readonly [number, number])[];

export function inRanges(ranges: Ranges, cp: number): boolean {
  let lo = 0;
  let hi = ranges.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const [a, b] = ranges[mid] as readonly [number, number];
    if (cp < a) hi = mid - 1;
    else if (cp > b) lo = mid + 1;
    else return true;
  }
  return false;
}

/** `text[:count]` for a Python str (code points, not UTF-16 units). */
export function sliceCodePoints(text: string, count: number): string {
  return Array.from(text).slice(0, count).join('');
}

export function isPySpace(cp: number): boolean {
  return inRanges(SPACE_RANGES, cp);
}

/** `str.strip()` with no argument. */
export function pyStrip(text: string): string {
  const chars = Array.from(text);
  let start = 0;
  let end = chars.length;
  while (start < end && isPySpace(chars[start]?.codePointAt(0) ?? 0)) start += 1;
  while (end > start && isPySpace(chars[end - 1]?.codePointAt(0) ?? 0)) end -= 1;
  return chars.slice(start, end).join('');
}

/** `str.split()` with no argument: runs of whitespace separate, empty pieces dropped. */
export function pySplitWhitespace(text: string): string[] {
  const words: string[] = [];
  let current = '';
  for (const ch of text) {
    if (isPySpace(ch.codePointAt(0) ?? 0)) {
      if (current) words.push(current);
      current = '';
    } else current += ch;
  }
  if (current) words.push(current);
  return words;
}

/**
 * `str.lower()` for every code point that can lower to ASCII (U+0130, U+212A).
 * Other non-ASCII characters are left as they are: lowercasing them never
 * produces an ASCII character, so ASCII comparisons are unaffected.
 */
export function lowerView(text: string): string {
  let out = '';
  for (const ch of text) {
    const cp = ch.codePointAt(0) ?? 0;
    if (cp < 0x80) out += ch.toLowerCase();
    else out += FULL_LOWER_ASCII.get(cp) ?? ch;
  }
  return out;
}

/** Python truthiness for a JSON-shaped value (the twin's `x or default`). */
export function truthy(value: unknown): boolean {
  if (value === null || value === undefined || value === false || value === '' || value === 0) return false;
  if (typeof value === 'bigint') return value !== 0n;
  if (value instanceof CanonicalFloat || value instanceof PyFloat) return value.value !== 0;
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === 'object') return Object.keys(value).length > 0;
  return true;
}

/** `str(value)` for a JSON-shaped value; either float marker renders as a Python float. */
export function strOf(value: unknown): string {
  if (value instanceof CanonicalFloat) return pyStr(new PyFloat(value.value));
  return pyStr(value);
}

// -- float(str) -----------------------------------------------------------------

function decimalValue(cp: number): number | undefined {
  for (const zero of DECIMAL_ZEROS) {
    if (cp >= zero && cp < zero + 10) return cp - zero;
  }
  return undefined;
}

const FLOAT_SHAPE = /^[+-]?(?:\d(?:_?\d)*(?:\.(?:\d(?:_?\d)*)?)?|\.\d(?:_?\d)*)(?:[eE][+-]?\d(?:_?\d)*)?$/;
const FLOAT_SPECIAL = /^([+-]?)(inf|infinity|nan)$/i;

function asciiDigits(text: string): string {
  return Array.from(text, (ch) => {
    const value = decimalValue(ch.codePointAt(0) ?? 0);
    return value === undefined ? ch : String(value);
  }).join('');
}

/** Python `float(text)`; `undefined` where Python raises ValueError. */
export function pyFloat(text: string): number | undefined {
  const stripped = pyStrip(text);
  const special = FLOAT_SPECIAL.exec(stripped);
  if (special) {
    if (/nan/i.test(special[2] ?? '')) return Number.NaN;
    return special[1] === '-' ? -Infinity : Infinity;
  }
  const normalized = asciiDigits(stripped);
  if (!FLOAT_SHAPE.test(normalized)) return undefined;
  return Number(normalized.replaceAll('_', ''));
}

// -- round(float, places) ---------------------------------------------------------

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

/** Python `round(value, places)` for a float: the exact binary value rounded half to even. */
export function roundTo(value: number, places: number): number {
  if (!Number.isFinite(value)) return value;
  const { negative, mantissa, exponent } = decompose(value);
  const scale = 10n ** BigInt(places);
  const units = exponent >= 0 ? (mantissa << BigInt(exponent)) * scale : roundedQuotient(mantissa * scale, 1n << BigInt(-exponent));
  const text = units.toString().padStart(places + 1, '0');
  const result = Number(`${text.slice(0, text.length - places)}.${text.slice(text.length - places)}`);
  return negative ? -result : result;
}
