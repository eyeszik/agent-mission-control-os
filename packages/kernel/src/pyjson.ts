/**
 * `json.dumps(value, sort_keys=True, separators=(",", ":"))` with Python's
 * defaults otherwise (`ensure_ascii=True`, `allow_nan=True`), the encoding
 * `content_fingerprint` hashes.
 *
 * Python passes unknown objects through `default=str`. That cannot be
 * reproduced for JS objects (their `str()` is a Python-side notion), so
 * anything outside the JSON-shaped `PyJsonValue` is refused, never guessed.
 */
import { KernelTypeError, KernelValueError } from './errors';
import { compareCodePoints, floatRepr, isPlainObject, PyFloat } from './pyformat';

export type PyJsonValue =
  | null
  | boolean
  | number
  | bigint
  | string
  | PyFloat
  | readonly PyJsonValue[]
  | { readonly [key: string]: PyJsonValue };

const SHORT: Readonly<Record<number, string>> = { 0x22: '\\"', 0x5c: '\\\\', 0x08: '\\b', 0x0c: '\\f', 0x0a: '\\n', 0x0d: '\\r', 0x09: '\\t' };

/** ensure_ascii string encoding: every unit outside ' '..'~' is escaped, astral as a surrogate pair. */
export function encodeString(text: string): string {
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

function encodeFloat(value: number): string {
  if (Number.isNaN(value)) return 'NaN';
  if (!Number.isFinite(value)) return value > 0 ? 'Infinity' : '-Infinity';
  return floatRepr(value);
}

function encodeNumber(value: number): string {
  if (!Number.isInteger(value)) return encodeFloat(value);
  if (!Number.isSafeInteger(value)) {
    throw new KernelValueError(`integral number ${value} is outside the safe range; pass a bigint or a PyFloat`);
  }
  return String(value);
}

function encodeScalar(value: PyJsonValue): string | undefined {
  if (value === null) return 'null';
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'number') return encodeNumber(value);
  if (typeof value === 'bigint') return value.toString();
  if (typeof value === 'string') return encodeString(value);
  if (value instanceof PyFloat) return encodeFloat(value.value);
  return undefined;
}

function encodeObject(value: Readonly<Record<string, PyJsonValue>>, seen: Set<object>): string {
  const keys = Object.keys(value).sort(compareCodePoints);
  return `{${keys.map((key) => `${encodeString(key)}:${encode(value[key] as PyJsonValue, seen)}`).join(',')}}`;
}

function encodeContainer(value: object, seen: Set<object>): string {
  if (seen.has(value)) throw new KernelValueError('Circular reference detected');
  seen.add(value);
  try {
    if (Array.isArray(value)) return `[${value.map((item: PyJsonValue) => encode(item, seen)).join(',')}]`;
    if (isPlainObject(value)) return encodeObject(value as Readonly<Record<string, PyJsonValue>>, seen);
  } finally {
    seen.delete(value);
  }
  throw new KernelTypeError(`Object of type ${Object.prototype.toString.call(value)} is not JSON serializable here`);
}

function encode(value: PyJsonValue, seen: Set<object>): string {
  const scalar = encodeScalar(value);
  if (scalar !== undefined) return scalar;
  if (typeof value !== 'object' || value === null) {
    throw new KernelTypeError(`Object of type ${typeof value} is not JSON serializable`);
  }
  return encodeContainer(value, seen);
}

/** Python `json.dumps(value, sort_keys=True, separators=(",", ":"))`. Output is pure ASCII. */
export function pyJsonDumps(value: PyJsonValue): string {
  return encode(value, new Set<object>());
}
