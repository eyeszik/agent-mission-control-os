/**
 * `workspace.canonical_json`: `json.dumps(payload, sort_keys=True,
 * separators=(",", ":"), ensure_ascii=False).encode("utf-8")`, and the
 * SHA-256 every Project OS hash is taken over.
 *
 * (Not the AMC-CANON-1 encoding in `@amc/canonical`: that one is a different
 * protocol. This one is plain `json.dumps`, so non-ASCII text stays literal.)
 *
 * A JS `number` cannot say whether `2` was an int or a float. Integral
 * numbers encode as ints; wrap an integral float in `CanonicalFloat` (from
 * `@amc/canonical`) or `PyFloat` (from `@amc/kernel`) so it encodes as `2.0`.
 * An integral number beyond 2^53 must be a `bigint`.
 */
import { CanonicalFloat } from '@amc/canonical';
import { PyFloat, compareCodePoints, floatRepr, sha256Hex } from '@amc/kernel';
import { PyTypeError, PyUnicodeEncodeError, PyValueError } from './errors';

export type PyJson =
  | null
  | boolean
  | number
  | bigint
  | string
  | CanonicalFloat
  | PyFloat
  | readonly PyJson[]
  | { readonly [key: string]: PyJson };

const SHORT: Readonly<Record<string, string>> = { '"': '\\"', '\\': '\\\\', '\b': '\\b', '\f': '\\f', '\n': '\\n', '\r': '\\r', '\t': '\\t' };

function encodeString(text: string): string {
  const body = text.replace(/[\u0000-\u001f"\\]/g, (ch) => SHORT[ch] ?? `\\u${ch.charCodeAt(0).toString(16).padStart(4, '0')}`);
  return `"${body}"`;
}

function encodeFloat(value: number): string {
  if (Number.isNaN(value)) return 'NaN';
  if (!Number.isFinite(value)) return value > 0 ? 'Infinity' : '-Infinity';
  return floatRepr(value);
}

function encodeNumber(value: number): string {
  if (!Number.isInteger(value)) return encodeFloat(value);
  if (!Number.isSafeInteger(value)) {
    throw new PyValueError(`integral number ${value} is beyond 2^53; pass a bigint (int) or a CanonicalFloat (float)`);
  }
  return String(value);
}

function encodeScalar(value: PyJson): string | undefined {
  if (value === null) return 'null';
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'number') return encodeNumber(value);
  if (typeof value === 'bigint') return value.toString();
  if (typeof value === 'string') return encodeString(value);
  if (value instanceof CanonicalFloat || value instanceof PyFloat) return encodeFloat(value.value);
  return undefined;
}

function encode(value: PyJson): string {
  const scalar = encodeScalar(value);
  if (scalar !== undefined) return scalar;
  if (Array.isArray(value)) return `[${(value as readonly PyJson[]).map(encode).join(',')}]`;
  if (typeof value !== 'object') throw new PyTypeError(`Object of type ${typeof value} is not JSON serializable`);
  const record = value as { readonly [key: string]: PyJson };
  const keys = Object.keys(record).sort(compareCodePoints);
  return `{${keys.map((key) => `${encodeString(key)}:${encode(record[key] as PyJson)}`).join(',')}}`;
}

function isLoneSurrogate(char: string): boolean {
  const code = char.codePointAt(0) ?? 0;
  return char.length === 1 && code >= 0xd800 && code <= 0xdfff;
}

function assertEncodable(text: string): void {
  const chars = Array.from(text);
  const first = chars.findIndex(isLoneSurrogate);
  if (first < 0) return;
  let last = first;
  while (last + 1 < chars.length && isLoneSurrogate(chars[last + 1] as string)) last += 1;
  const code = (chars[first] as string).charCodeAt(0).toString(16);
  const where =
    last === first ? `character '\\u${code}' in position ${first}` : `characters in position ${first}-${last}`;
  throw new PyUnicodeEncodeError(`'utf-8' codec can't encode ${where}: surrogates not allowed`);
}

/** `canonical_json(payload)`: UTF-8 bytes; lone surrogates raise `UnicodeEncodeError` as in Python. */
export function canonicalJsonBytes(payload: PyJson): Uint8Array {
  const text = encode(payload);
  assertEncodable(text);
  return new TextEncoder().encode(text);
}

/** `sha256_bytes(canonical_json(payload))`. */
export function canonicalSha256(payload: PyJson): string {
  return sha256Hex(canonicalJsonBytes(payload));
}

/** `hashlib.sha256(data).hexdigest()`. */
export function sha256Bytes(data: Uint8Array): string {
  return sha256Hex(data);
}
