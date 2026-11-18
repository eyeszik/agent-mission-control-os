/**
 * `PyValue`: the JSON-shaped values both Python subsystems hash and render, plus
 * the two renderings that matter:
 *
 * - `canonicalJson`: `json.dumps(v, sort_keys=True, separators=(",", ":"),
 *   ensure_ascii=True)`, the text every hash in this area is taken over;
 * - `pyStr`: `str(v)`/`repr(v)` of a dict/list tree. The router measures its
 *   context budget with `len(str(payload))`, so the exact text matters.
 *
 * A JS `number` cannot say whether it was an int or a float: integral `number`s
 * are ints, every Python float is a `CanonicalFloat`, and a non-integral bare
 * `number` is refused rather than guessed. Dicts are `Map`s (insertion order is
 * observable in `str(dict)`) or plain records (order only matters after sorting).
 */
import { CanonicalFloat } from '@amc/canonical';
import { floatRepr, pyRepr } from '@amc/kernel';
import { PyValueError } from './errors';
import { compareCodePoints, sha256Text } from './pytext';

export type PyValue =
  | null
  | boolean
  | number
  | bigint
  | string
  | CanonicalFloat
  | readonly PyValue[]
  | ReadonlyMap<string, PyValue>
  | { readonly [key: string]: PyValue };

const SHORT: Readonly<Record<number, string>> = { 0x22: '\\"', 0x5c: '\\\\', 0x08: '\\b', 0x0c: '\\f', 0x0a: '\\n', 0x0d: '\\r', 0x09: '\\t' };

/** `json.dumps(str)` with `ensure_ascii=True`. */
export function jsonString(text: string): string {
  let out = '"';
  for (let i = 0; i < text.length; i += 1) {
    const unit = text.charCodeAt(i);
    const short = SHORT[unit];
    if (short !== undefined) out += short;
    else if (unit >= 0x20 && unit <= 0x7e) out += text[i];
    else out += `\\u${unit.toString(16).padStart(4, '0')}`;
  }
  return `${out}"`;
}

function floatText(value: number): string {
  if (Number.isNaN(value)) return 'NaN';
  if (!Number.isFinite(value)) return value > 0 ? 'Infinity' : '-Infinity';
  return floatRepr(value);
}

function intText(value: number): string {
  if (!Number.isInteger(value)) throw new PyValueError(`non-integral number ${value} must be wrapped in CanonicalFloat`);
  if (!Number.isSafeInteger(value)) throw new PyValueError(`integral number ${value} is outside the safe range; pass a bigint`);
  return String(value);
}

/** Entries of a dict-like `PyValue`, or `null` when the value is not one. */
export function dictEntries(value: unknown): ReadonlyMap<string, unknown> | null {
  if (value instanceof Map) return value as ReadonlyMap<string, unknown>;
  if (value === null || typeof value !== 'object' || Array.isArray(value) || value instanceof CanonicalFloat) return null;
  const proto: unknown = Object.getPrototypeOf(value);
  if (proto !== Object.prototype && proto !== null) return null;
  return new Map(Object.entries(value as Record<string, unknown>));
}

function encodeDict(entries: ReadonlyMap<string, unknown>): string {
  const keys = Array.from(entries.keys()).sort(compareCodePoints);
  return `{${keys.map((key) => `${jsonString(key)}:${encode(entries.get(key))}`).join(',')}}`;
}

function encode(value: unknown): string {
  if (value === null) return 'null';
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'number') return intText(value);
  if (typeof value === 'bigint') return value.toString();
  if (typeof value === 'string') return jsonString(value);
  if (value instanceof CanonicalFloat) return floatText(value.value);
  if (Array.isArray(value)) return `[${value.map((item: unknown) => encode(item)).join(',')}]`;
  const entries = dictEntries(value);
  if (entries === null) throw new PyValueError(`Object of type ${typeof value} is not JSON serializable`);
  return encodeDict(entries);
}

export function canonicalJson(value: unknown): string {
  return encode(value);
}

/** `stable_hash` / `stable_guidance_hash`: SHA-256 of the canonical JSON. */
export function stableHash(value: unknown): string {
  return sha256Text(canonicalJson(value));
}

function floatStr(value: number): string {
  if (Number.isNaN(value)) return 'nan';
  if (!Number.isFinite(value)) return value > 0 ? 'inf' : '-inf';
  return floatRepr(value);
}

function reprDict(entries: ReadonlyMap<string, unknown>): string {
  return `{${Array.from(entries, ([key, item]) => `${pyRepr(key)}: ${pyReprValue(item)}`).join(', ')}}`;
}

/** `repr(v)` of a `PyValue`. */
export function pyReprValue(value: unknown): string {
  if (value === null || value === undefined) return 'None';
  if (typeof value === 'boolean') return value ? 'True' : 'False';
  if (typeof value === 'number') return intText(value);
  if (typeof value === 'bigint') return value.toString();
  if (typeof value === 'string') return pyRepr(value);
  if (value instanceof CanonicalFloat) return floatStr(value.value);
  if (Array.isArray(value)) return `[${value.map((item: unknown) => pyReprValue(item)).join(', ')}]`;
  const entries = dictEntries(value);
  if (entries === null) throw new PyValueError(`cannot render ${typeof value} as Python text`);
  return reprDict(entries);
}

/** Build a `Map` in the given order. */
export function orderedMap(entries: ReadonlyArray<readonly [string, PyValue]>): Map<string, PyValue> {
  return new Map(entries);
}
