/**
 * Twin of `agency/compiled/hashing.py`: every structural hash goes through the
 * N4 `content_fingerprint` (sorted keys, compact separators, SHA-256).
 *
 * Python canonicalizes enums to their values, tuples to lists, Pydantic models
 * to `model_dump(mode="json")` and sets to a list sorted by each member's
 * fingerprint. Here enums are already strings, records are already plain
 * objects (built by each module exactly as Pydantic dumps them, float fields
 * as `PyFloat`), and a `Set` is sorted the same way. Anything else is refused
 * by `pyJsonDumps`, never guessed.
 */
import { contentFingerprint, type PyJsonValue } from '@amc/kernel';
import { compareCodePoints, compareTuples } from './python';

export type HashValue =
  | PyJsonValue
  | ReadonlySet<HashValue>
  | ReadonlyMap<string, HashValue>
  | readonly HashValue[]
  | { readonly [key: string]: HashValue };

function isRecord(value: unknown): value is Readonly<Record<string, HashValue>> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return false;
  const proto: unknown = Object.getPrototypeOf(value);
  return proto === Object.prototype || proto === null;
}

function canonicalSet(values: ReadonlySet<HashValue>): PyJsonValue[] {
  const members = Array.from(values, (v) => canonical(v));
  return members
    .map((member) => ({ member, key: contentFingerprint(member) }))
    .sort((a, b) => compareCodePoints(a.key, b.key))
    .map(({ member }) => member);
}

function canonicalRecord(entries: Iterable<[string, HashValue]>): { [key: string]: PyJsonValue } {
  const out: { [key: string]: PyJsonValue } = {};
  for (const [key, value] of entries) out[key] = canonical(value);
  return out;
}

/** `_canonical(value)`. */
export function canonical(value: HashValue): PyJsonValue {
  if (value instanceof Set) return canonicalSet(value as ReadonlySet<HashValue>);
  if (value instanceof Map) return canonicalRecord((value as ReadonlyMap<string, HashValue>).entries());
  if (Array.isArray(value)) return (value as readonly HashValue[]).map((v) => canonical(v));
  if (isRecord(value)) return canonicalRecord(Object.entries(value));
  return value as PyJsonValue;
}

/** `semantic_hash(payload, exclude=...)`: drops top-level `exclude` keys of a mapping. */
export function semanticHash(payload: HashValue, exclude: Iterable<string> = []): string {
  const value = canonical(payload);
  if (!isRecord(value)) return contentFingerprint(value);
  const skip = new Set(exclude);
  const kept: { [key: string]: PyJsonValue } = {};
  for (const [key, item] of Object.entries(value)) if (!skip.has(key)) kept[key] = item as PyJsonValue;
  return contentFingerprint(kept);
}

/** `closure_hash(pairs)`: order-independent hash over `(ref, hash)` pairs. */
export function closureHash(pairs: Iterable<readonly [string, string]>): string {
  const sorted = Array.from(pairs, ([ref, digest]) => [ref, digest]).sort(compareTuples);
  return contentFingerprint(sorted);
}
