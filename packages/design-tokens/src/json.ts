/**
 * Python `json` behaviour the compiler depends on: `canonical_json` (sort_keys,
 * compact separators, ensure_ascii), `source_hash`, and a reader that keeps the
 * int/float distinction `json.loads` keeps.
 */
import { CanonicalFloat } from '@amc/canonical';
import { TokenAmbiguityError } from './errors';
import { PythonRuntimeError, floatRepr, isMapping, pyTypeName, sortedStrings, type Mapping } from './python';
import { sha256Hex } from './sha256';

const SHORT_ESCAPES: Readonly<Record<string, string>> = {
  '"': '\\"',
  '\\': '\\\\',
  '\n': '\\n',
  '\r': '\\r',
  '\t': '\\t',
  '\b': '\\b',
  '\f': '\\f',
};

/** `json.dumps(str, ensure_ascii=True)`: everything outside ' '..'~' escaped, UTF-16 units for astral. */
function jsonString(text: string): string {
  const body = text.replace(
    /[\\"]|[^ -~]/g,
    (ch) => SHORT_ESCAPES[ch] ?? `\\u${ch.charCodeAt(0).toString(16).padStart(4, '0')}`,
  );
  return `"${body}"`;
}

function jsonFloat(value: number): string {
  if (Number.isNaN(value)) return 'NaN';
  if (!Number.isFinite(value)) return value > 0 ? 'Infinity' : '-Infinity';
  return floatRepr(value);
}

function jsonNumber(value: number): string {
  if (!Number.isInteger(value)) return jsonFloat(value);
  if (!Number.isSafeInteger(value)) {
    throw new TokenAmbiguityError(
      'integral number beyond 2^53 cannot be hashed unambiguously; pass a bigint (int) or CanonicalFloat (float)',
    );
  }
  return value === 0 ? '0' : String(value);
}

function jsonMapping(value: Mapping): string {
  const keys = sortedStrings(Object.keys(value));
  return `{${keys.map((key) => `${jsonString(key)}:${encodeJson(value[key])}`).join(',')}}`;
}

function encodeJson(value: unknown): string {
  if (value === null) return 'null';
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'bigint') return value.toString();
  if (typeof value === 'number') return jsonNumber(value);
  if (typeof value === 'string') return jsonString(value);
  if (value instanceof CanonicalFloat) return jsonFloat(value.value);
  if (Array.isArray(value)) return `[${value.map((item: unknown) => encodeJson(item)).join(',')}]`;
  if (isMapping(value)) return jsonMapping(value);
  throw new PythonRuntimeError('TypeError', `Object of type ${pyTypeName(value)} is not JSON serializable`);
}

/** Python `canonical_json`: `json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)`. */
export function canonicalJson(value: unknown): string {
  return encodeJson(value);
}

/** Python `source_hash`: SHA-256 hex of the canonical JSON. */
export function sourceHash(document: unknown): string {
  return sha256Hex(new TextEncoder().encode(canonicalJson(document)));
}

interface SourceContext {
  readonly source?: string;
}

function reviveNumber(value: number, source: string): number | bigint | CanonicalFloat {
  if (/[.eE]/.test(source)) {
    return Number.isInteger(value) || !Number.isFinite(value) ? new CanonicalFloat(value) : value;
  }
  if (Number.isSafeInteger(value)) return value === 0 ? 0 : value;
  return BigInt(source);
}

function revive(_key: string, value: unknown, context?: SourceContext): unknown {
  if (typeof value !== 'number') return value;
  const source = context?.source;
  if (source === undefined) {
    throw new TokenAmbiguityError('JSON.parse source-text access is unavailable; cannot tell int from float');
  }
  return reviveNumber(value, source);
}

/**
 * `json.loads` for token sources: a number written with `.`/`e` is a float
 * (integral ones become `CanonicalFloat`), any other number an int (`bigint`
 * beyond 2^53). Plain `JSON.parse` would turn `1.0` into the int `1` and change
 * `source-sha256`. Needs JSON.parse source-text access (Node 21+, current browsers).
 */
export function parseTokenJson(text: string): unknown {
  return JSON.parse(text, revive);
}
