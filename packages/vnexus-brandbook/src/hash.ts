import { CanonicalFloat, canonicalBytes, type CanonicalValue } from '@amc/canonical';
import { sha256Hex } from '@amc/kernel';
import { utf8 } from './python';

/**
 * Re-wrap any `CanonicalFloat` built by another copy of `@amc/canonical`. A bundler or test runner can load the
 * package twice (this package's CommonJS build and a consumer's inlined copy); `instanceof` then fails and the float
 * would be refused rather than hashed as a float.
 */
function adoptFloats(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(adoptFloats);
  if (value === null || typeof value !== 'object' || value instanceof Uint8Array || value instanceof Map) return value;
  const foreign = value as { readonly constructor: { readonly name: string }; readonly value?: unknown };
  if (foreign.constructor.name === 'CanonicalFloat' && typeof foreign.value === 'number') return new CanonicalFloat(foreign.value);
  return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, adoptFloats(v)]));
}

function bytesOf(value: unknown): Uint8Array {
  try {
    return canonicalBytes(value as CanonicalValue);
  } catch (error) {
    if (!(error instanceof Error) || error.name !== 'CanonicalizationError' || !error.message.includes('CanonicalFloat')) throw error;
    return canonicalBytes(adoptFloats(value) as CanonicalValue);
  }
}

/**
 * `canonical_hash(value)`, synchronously. Python computes these hashes inline while compiling, so the twin does too:
 * AMC-CANON-1 bytes from `@amc/canonical`, digested by the bundled synchronous SHA-256 in `@amc/kernel`.
 */
export function canonicalHash(value: unknown): string {
  return sha256Hex(bytesOf(value));
}

/** `hashlib.sha256(data).hexdigest()`; a string is hashed as its UTF-8 bytes. */
export function sha256(data: Uint8Array | string): string {
  return sha256Hex(typeof data === 'string' ? utf8(data) : data);
}
