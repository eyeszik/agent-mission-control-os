/**
 * The pieces of Python's text and number semantics the brand book (and the creative-direction twin, which imports
 * these) depend on: code-point lengths and slices, `str.strip()`, `str()`/`repr()` of genome values, `html.escape`,
 * exact half-even number formatting (`round`, `:.Nf`, `:g`, `:.0%`) and `json.dumps` with an indent.
 *
 * Unicode classes come from `python-unicode.ts`, generated from Python's own `re` engine and `str` methods by the
 * parity test, so the JS engine's Unicode tables never decide a match.
 */
import { CanonicalFloat } from '@amc/canonical';
import { compareCodePoints, floatRepr, pyRepr as reprText } from '@amc/kernel';
import { DECIMAL_RANGES, ISDIGIT_RANGES, SPACE_RANGES, WORD_RANGES, type CodePointRange } from './python-unicode';

/** A genome / record value as Python holds it. `CanonicalFloat` marks a float whose value is integral. */
export type PyValue =
  | null
  | boolean
  | number
  | string
  | CanonicalFloat
  | readonly PyValue[]
  | { readonly [key: string]: PyValue };

function hex(point: number): string {
  return `\\u{${point.toString(16)}}`;
}

/** A regex character-class body (for a `u`-flag pattern) covering the given code-point ranges. */
export function classBody(ranges: readonly CodePointRange[]): string {
  return ranges.map(([lo, hi]) => (lo === hi ? hex(lo) : `${hex(lo)}-${hex(hi)}`)).join('');
}

/** Python `\s` / `str.isspace()`. */
export const PY_SPACE = classBody(SPACE_RANGES);
/** Python `\w` in a str pattern. */
export const PY_WORD = classBody(WORD_RANGES);
/** Python `\d` in a str pattern (Unicode decimal digits). */
export const PY_DECIMAL = classBody(DECIMAL_RANGES);

const SPACE_ONE = new RegExp(`^[${PY_SPACE}]$`, 'u');
const ISDIGIT_ONE = new RegExp(`^[${classBody(ISDIGIT_RANGES)}]$`, 'u');

export function isPySpace(ch: string): boolean {
  return SPACE_ONE.test(ch);
}

/** `str.isdigit()` for one character. */
export function isPyDigit(ch: string): boolean {
  return ISDIGIT_ONE.test(ch);
}

/** `len(text)`: code points, not UTF-16 units. */
export function cpLen(text: string): number {
  return Array.from(text).length;
}

/** `text[start:end]` by code points (non-negative bounds). */
export function cpSlice(text: string, start: number, end?: number): string {
  return Array.from(text).slice(start, end).join('');
}

/** `str.strip()` / `rstrip()` with Python's whitespace set. */
export function pyStrip(text: string): string {
  return pyRstrip(pyLstrip(text));
}

export function pyLstrip(text: string): string {
  const chars = Array.from(text);
  let i = 0;
  while (i < chars.length && isPySpace(chars[i] ?? '')) i += 1;
  return chars.slice(i).join('');
}

export function pyRstrip(text: string): string {
  const chars = Array.from(text);
  let n = chars.length;
  while (n > 0 && isPySpace(chars[n - 1] ?? '')) n -= 1;
  return chars.slice(0, n).join('');
}

/** `str.split()` with no separator: runs of Python whitespace, no empty parts. */
export function pySplitWs(text: string): string[] {
  return text.split(new RegExp(`[${PY_SPACE}]+`, 'u')).filter((part) => part.length > 0);
}

export function isPlainRecord(value: unknown): value is { readonly [key: string]: PyValue } {
  if (value === null || typeof value !== 'object' || Array.isArray(value) || value instanceof CanonicalFloat) return false;
  const proto: unknown = Object.getPrototypeOf(value);
  return proto === Object.prototype || proto === null;
}

function numberText(value: number): string {
  if (Number.isNaN(value)) return 'nan';
  if (!Number.isFinite(value)) return value > 0 ? 'inf' : '-inf';
  return Number.isInteger(value) && !Object.is(value, -0) ? String(value) : floatRepr(value);
}

/** `repr(value)` for a JSON-shaped Python value (dict order = insertion order). */
export function pyRepr(value: unknown): string {
  if (typeof value === 'string') return reprText(value);
  if (Array.isArray(value)) return `[${value.map(pyRepr).join(', ')}]`;
  if (isPlainRecord(value)) return `{${Object.entries(value).map(([k, v]) => `${reprText(k)}: ${pyRepr(v)}`).join(', ')}}`;
  return pyStr(value);
}

/** `str(value)` as an f-string renders it. */
export function pyStr(value: unknown): string {
  if (value === null || value === undefined) return 'None';
  if (typeof value === 'string') return value;
  if (typeof value === 'boolean') return value ? 'True' : 'False';
  if (typeof value === 'number') return numberText(value);
  if (value instanceof CanonicalFloat) return Number.isFinite(value.value) ? floatRepr(value.value) : numberText(value.value);
  return pyRepr(value);
}

/** A float as Python formats it in an f-string (`f"{x}"`), whether integral or not. */
export function pyFloatStr(value: number): string {
  return Number.isFinite(value) ? floatRepr(value) : numberText(value);
}

/** Python `==` against `None`, `""` and `[]` (the brand book's emptiness test). */
export function isPyEmpty(value: unknown): boolean {
  return value === null || value === undefined || value === '' || (Array.isArray(value) && value.length === 0);
}

const HTML_ESCAPES: Readonly<Record<string, string>> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#x27;' };

/** `html.escape(text)` (quote=True). */
export function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (ch) => HTML_ESCAPES[ch] ?? ch);
}

/** Python's type name for a JSON-shaped value. */
export function pyTypeName(value: unknown): string {
  if (value === null || value === undefined) return 'NoneType';
  if (typeof value === 'boolean') return 'bool';
  if (typeof value === 'string') return 'str';
  if (typeof value === 'number') return Number.isInteger(value) ? 'int' : 'float';
  if (value instanceof CanonicalFloat) return 'float';
  return Array.isArray(value) ? 'list' : 'dict';
}

export class PyAttributeError extends Error {
  override name = 'AttributeError';
}

/** `html.escape(value)` where Python passes the value straight in: a non-str has no `.replace`. */
export function escapeStrict(value: unknown): string {
  if (typeof value !== 'string') throw new PyAttributeError(`'${pyTypeName(value)}' object has no attribute 'replace'`);
  return escapeHtml(value);
}

/** `xml.sax.saxutils.escape(text)`: only `&`, `<` and `>`. */
export function escapeXml(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// ------------------------------------------------------------------ exact decimal formatting (half-even, like CPython)

interface Exact {
  readonly negative: boolean;
  readonly digits: bigint; // value = digits / 10**scale exactly
  readonly scale: number;
}

function exact(value: number): Exact {
  const view = new DataView(new ArrayBuffer(8));
  view.setFloat64(0, value);
  const high = view.getUint32(0);
  const low = view.getUint32(4);
  const biased = (high >>> 20) & 0x7ff;
  const fraction = (BigInt(high & 0xfffff) << 32n) | BigInt(low);
  const mantissa = biased === 0 ? fraction : fraction | (1n << 52n);
  const exponent = (biased === 0 ? 1 : biased) - 1075;
  const negative = (high >>> 31) === 1;
  if (exponent >= 0) return { negative, digits: mantissa << BigInt(exponent), scale: 0 };
  return { negative, digits: mantissa * 5n ** BigInt(-exponent), scale: -exponent };
}

function divRoundHalfEven(n: bigint, d: bigint): bigint {
  const q = n / d;
  const r = n - q * d;
  if (r * 2n > d || (r * 2n === d && q % 2n === 1n)) return q + 1n;
  return q;
}

/** Round the exact value to an integer count of 10**-places units. */
function scaled(e: Exact, places: number): bigint {
  const shift = e.scale - places;
  if (shift <= 0) return e.digits * 10n ** BigInt(-shift);
  return divRoundHalfEven(e.digits, 10n ** BigInt(shift));
}

function pointed(units: bigint, places: number): string {
  const text = units.toString().padStart(places + 1, '0');
  return places > 0 ? `${text.slice(0, text.length - places)}.${text.slice(text.length - places)}` : text;
}

function assertFinite(value: number): void {
  if (!Number.isFinite(value)) throw new RangeError('only finite numbers are formatted');
}

/** `f"{value:.{places}f}"`: exact binary value, rounded half to even. */
export function formatFixed(value: number, places: number): string {
  assertFinite(value);
  const e = exact(value);
  return (e.negative ? '-' : '') + pointed(scaled(e, places), places);
}

/** `round(value, places)` for a float. */
export function pyRound(value: number, places: number): number {
  return Number(formatFixed(value, places));
}

/** `round(value)` for a float: the nearest integer, ties to even. */
export function pyRoundInt(value: number): number {
  return Number(formatFixed(value, 0)) + 0; // `round(-0.4)` is the int 0: never -0
}

/** `f"{value:.0%}"`. */
export function formatPercent0(value: number): string {
  return `${formatFixed(value * 100, 0)}%`;
}

function stripZeros(text: string): string {
  if (!text.includes('.')) return text;
  let end = text.length;
  while (end > 0 && text[end - 1] === '0') end -= 1;
  if (end > 0 && text[end - 1] === '.') end -= 1;
  return text.slice(0, end);
}

/** `f"{value:g}"` (precision 6). */
export function formatG(value: number, precision = 6): string {
  assertFinite(value);
  const e = exact(value);
  const sign = e.negative ? '-' : '';
  if (e.digits === 0n) return `${sign}0`;
  let exp10 = e.digits.toString().length - 1 - e.scale;
  let units = scaled(e, precision - 1 - exp10);
  if (units.toString().length > precision) {
    exp10 += 1;
    units /= 10n;
  }
  if (exp10 >= -4 && exp10 < precision) return sign + stripZeros(pointed(units, precision - 1 - exp10));
  const mantissa = stripZeros(pointed(units, precision - 1));
  const expText = String(Math.abs(exp10)).padStart(2, '0');
  return `${sign}${mantissa}e${exp10 < 0 ? '-' : '+'}${expText}`;
}

// ------------------------------------------------------------------ json.dumps

export interface JsonDumpOptions {
  readonly indent?: number;
  readonly sortKeys?: boolean;
  readonly ensureAscii?: boolean;
}

const JSON_SHORT: Readonly<Record<number, string>> = { 0x22: '\\"', 0x5c: '\\\\', 0x08: '\\b', 0x0c: '\\f', 0x0a: '\\n', 0x0d: '\\r', 0x09: '\\t' };

function jsonString(text: string, ensureAscii: boolean): string {
  let out = '"';
  for (let i = 0; i < text.length; i += 1) {
    const unit = text.charCodeAt(i);
    const short = JSON_SHORT[unit];
    if (short !== undefined) out += short;
    else if (unit < 0x20 || (ensureAscii && unit > 0x7e)) out += `\\u${unit.toString(16).padStart(4, '0')}`;
    else out += text[i];
  }
  return `${out}"`;
}

function jsonFloat(value: number): string {
  if (Number.isNaN(value)) return 'NaN';
  if (!Number.isFinite(value)) return value > 0 ? 'Infinity' : '-Infinity';
  return floatRepr(value);
}

function jsonScalar(value: unknown, ensureAscii: boolean): string | undefined {
  if (value === null || value === undefined) return 'null';
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'number') return Number.isInteger(value) && !Object.is(value, -0) ? String(value) : jsonFloat(value);
  if (value instanceof CanonicalFloat) return jsonFloat(value.value);
  if (typeof value === 'string') return jsonString(value, ensureAscii);
  return undefined;
}

function jsonContainer(items: string[], open: string, close: string, indent: number | undefined, depth: number): string {
  if (items.length === 0) return open + close;
  if (indent === undefined) return open + items.join(', ') + close;
  const pad = '\n' + ' '.repeat(indent * (depth + 1));
  return open + pad + items.join(',' + pad) + '\n' + ' '.repeat(indent * depth) + close;
}

function jsonNode(value: unknown, options: JsonDumpOptions, depth: number): string {
  const ensureAscii = options.ensureAscii ?? true;
  const scalar = jsonScalar(value, ensureAscii);
  if (scalar !== undefined) return scalar;
  if (Array.isArray(value)) {
    return jsonContainer(value.map((v: unknown) => jsonNode(v, options, depth + 1)), '[', ']', options.indent, depth);
  }
  if (isPlainRecord(value)) {
    const entries = Object.entries(value);
    if (options.sortKeys) entries.sort(([a], [b]) => compareCodePoints(a, b));
    const items = entries.map(([k, v]) => `${jsonString(k, ensureAscii)}: ${jsonNode(v, options, depth + 1)}`);
    return jsonContainer(items, '{', '}', options.indent, depth);
  }
  throw new TypeError(`Object of type ${typeof value} is not JSON serializable`);
}

/** `json.dumps(value, indent=..., sort_keys=..., ensure_ascii=...)` with Python's default separators. */
export function pyJsonDumps(value: unknown, options: JsonDumpOptions = {}): string {
  return jsonNode(value, options, 0);
}

/** UTF-8 bytes of a string (Python `str.encode()`). */
export function utf8(text: string): Uint8Array {
  return new TextEncoder().encode(text);
}

/** `bytes.decode("utf-8", errors="replace")`; a leading BOM is kept as U+FEFF, as Python does. */
export function decodeReplace(data: Uint8Array): string {
  return new TextDecoder('utf-8', { fatal: false, ignoreBOM: true }).decode(data);
}

/** Standard base64 (`base64.b64encode(...).decode()`). */
export function base64(data: Uint8Array): string {
  let binary = '';
  for (const byte of data) binary += String.fromCharCode(byte);
  return btoa(binary);
}

export { compareCodePoints, floatRepr };
