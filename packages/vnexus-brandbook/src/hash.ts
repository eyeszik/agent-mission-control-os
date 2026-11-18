import { canonicalBytes, type CanonicalValue } from '@amc/canonical';
import { sha256Hex } from '@amc/kernel';
import { utf8 } from './python';

/**
 * `canonical_hash(value)`, synchronously. Python computes these hashes inline while compiling, so the twin does too:
 * AMC-CANON-1 bytes from `@amc/canonical`, digested by the bundled synchronous SHA-256 in `@amc/kernel`.
 */
export function canonicalHash(value: unknown): string {
  return sha256Hex(canonicalBytes(value as CanonicalValue));
}

/** `hashlib.sha256(data).hexdigest()`; a string is hashed as its UTF-8 bytes. */
export function sha256(data: Uint8Array | string): string {
  return sha256Hex(typeof data === 'string' ? utf8(data) : data);
}
