/**
 * A JSON-comparable view of a twin result, shaped as Python's
 * `model_dump(mode="json")`: `PyFloat` becomes its number, `Map` an object,
 * `Set` a code-point-sorted array, class instances their own fields.
 */
import { PyFloat } from '@amc/kernel';
import { compareCodePoints } from './python';

export type Plain = null | boolean | number | string | Plain[] | { [key: string]: Plain };

export function toPlain(value: unknown): Plain {
  if (value === null || value === undefined) return null;
  if (value instanceof PyFloat) return value.value;
  if (typeof value === 'bigint') return value.toString();
  if (typeof value !== 'object') return value as Plain;
  if (Array.isArray(value)) return value.map(toPlain);
  if (value instanceof Set) return [...value].map(toPlain).sort((a, b) => compareCodePoints(JSON.stringify(a), JSON.stringify(b)));
  if (value instanceof Map) return Object.fromEntries([...value].map(([k, v]) => [String(k), toPlain(v)]));
  return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, toPlain(v)]));
}
