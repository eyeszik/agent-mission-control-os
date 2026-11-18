/**
 * Python text behaviour the guidance registry and prompt compiler depend on:
 * code-point length, `str.strip()`, `str.casefold()`, `str.encode('utf-8')`,
 * `f"{x:.Nf}"` and `round(x, n)`. The Unicode tables come from
 * `python-unicode.ts`, generated from Python itself.
 */
import { sha256Hex } from '@amc/kernel';
import { UnicodeEncodeError } from './errors';
import { CASEFOLD_TABLE, SPACE_RANGES } from './python-unicode';

const SPACE_CODE_POINTS: ReadonlySet<number> = new Set(
  SPACE_RANGES.flatMap(([lo, hi]) => Array.from({ length: hi - lo + 1 }, (_, i) => lo + i)),
);
const CASEFOLD: ReadonlyMap<number, string> = new Map(
  CASEFOLD_TABLE.map(([cp, folded]) => [cp, String.fromCodePoint(...folded)]),
);

/** `len(text)`: code points, not UTF-16 units. */
export function pyLen(text: string): number {
  return Array.from(text).length;
}

/** `text.strip()` with no arguments: Python's `isspace()` set. */
export function pyStrip(text: string): string {
  const chars = Array.from(text);
  let start = 0;
  let end = chars.length;
  while (start < end && SPACE_CODE_POINTS.has(chars[start]?.codePointAt(0) ?? -1)) start += 1;
  while (end > start && SPACE_CODE_POINTS.has(chars[end - 1]?.codePointAt(0) ?? -1)) end -= 1;
  return chars.slice(start, end).join('');
}

/** `text.casefold()`. */
export function pyCasefold(text: string): string {
  return Array.from(text, (ch) => CASEFOLD.get(ch.codePointAt(0) ?? -1) ?? ch).join('');
}

/** `text.encode('utf-8')`; a lone surrogate raises as in Python (TextEncoder would substitute U+FFFD). */
export function utf8Bytes(text: string): Uint8Array {
  if (/\p{Cs}/u.test(text)) throw new UnicodeEncodeError("'utf-8' codec can't encode character: surrogates not allowed");
  return new TextEncoder().encode(text);
}

/** `hashlib.sha256(text.encode('utf-8')).hexdigest()`. */
export function sha256Text(text: string): string {
  return sha256Hex(utf8Bytes(text));
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

/** `f"{value:.{places}f}"` for a finite float: exact binary value, round half to even. */
export function formatFixed(value: number, places: number): string {
  const { negative, mantissa, exponent } = decompose(value);
  const scale = 10n ** BigInt(places);
  const units =
    exponent >= 0 ? (mantissa << BigInt(exponent)) * scale : roundedQuotient(mantissa * scale, 1n << BigInt(-exponent));
  const text = units.toString().padStart(places + 1, '0');
  const fraction = places > 0 ? `.${text.slice(-places)}` : '';
  return `${negative ? '-' : ''}${places > 0 ? text.slice(0, -places) : text}${fraction}`;
}

/** `round(value, places)` for a finite float. */
export function roundTo(value: number, places: number): number {
  return Number(formatFixed(value, places));
}

/** `sorted(strings)` order: by code point, not UTF-16 unit. */
export function compareCodePoints(a: string, b: string): number {
  const left = Array.from(a, (ch) => ch.codePointAt(0) ?? 0);
  const right = Array.from(b, (ch) => ch.codePointAt(0) ?? 0);
  const shared = Math.min(left.length, right.length);
  for (let i = 0; i < shared; i += 1) {
    const diff = (left[i] ?? 0) - (right[i] ?? 0);
    if (diff !== 0) return diff;
  }
  return left.length - right.length;
}

export function sortedStrings(values: Iterable<string>): string[] {
  return Array.from(values).sort(compareCodePoints);
}
