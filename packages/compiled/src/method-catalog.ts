/**
 * Twin of `agency/compiled/method_catalog.py`: catalog validation and the
 * predicate evaluator. Python's `load_catalog` reads `data/method_catalog.v1.json`
 * from disk (file I/O stays in Python); the twin takes the parsed JSON object.
 *
 * Predicates are a closed, tiny language evaluated against a ProblemSignature:
 * `<field>==<value>`, `<field>!=<value>`, `<field> in a|b|c`,
 * `observed:<fact>`, `not_observed:<fact>`, `family:<ID>`, `domain:<d>`.
 * An unknown (`null`) boolean never satisfies `==true` or `==false`.
 *
 * Divergence: Python's `$` also matches before a trailing newline, so a
 * predicate ending in `\n` is accepted there and refused here. No catalog entry
 * ends that way; the parity fixture pins the case.
 */
import { pyRepr, pyStr } from '@amc/kernel';
import { CatalogError, CompiledAttributeError } from './errors';
import { semanticHash, type HashValue } from './hashing';
import {
  FamilySpecSchema, MethodSpecSchema, type FamilySpec, type MethodSpec, type ProblemSignature,
} from './method-models';
import { sortStrings } from './python';
import { parseModel } from './validate';

export const CATALOG_SCHEMA = 'amc-method-catalog/v1';

const PRED = new RegExp(
  '^(?:(?<field>[a-z_]+)(?<op>==|!=)(?<value>[A-Za-z0-9_\\-]+)'
  + '|(?<infield>[a-z_]+) in (?<choices>[A-Za-z0-9_|\\-]+)'
  + '|(?<kind>observed|not_observed|family|domain):(?<arg>[A-Za-z0-9_\\-]+))$',
);

export interface MethodCatalog {
  readonly families: ReadonlyMap<string, FamilySpec>;
  readonly methods: ReadonlyMap<string, MethodSpec>;
  readonly catalog_hash: string;
}

export function methodsCovering(catalog: MethodCatalog, need: string): MethodSpec[] {
  return [...catalog.methods.values()].filter((m) => m.expected_outputs.includes(need));
}

function checkPredicate(text: string, where: string): void {
  if (!PRED.test(text)) throw new CatalogError(`${where}: unparseable predicate ${pyRepr(text)}`);
}

function literal(raw: string): boolean | string {
  return raw === 'true' ? true : raw === 'false' ? false : raw;
}

function signatureField(signature: ProblemSignature, name: string): unknown {
  if (!Object.prototype.hasOwnProperty.call(signature, name)) {
    throw new CompiledAttributeError(`'ProblemSignature' object has no attribute '${name}'`);
  }
  return (signature as unknown as Readonly<Record<string, unknown>>)[name];
}

function scalarText(value: unknown): string {
  if (Array.isArray(value)) throw new CatalogError('"in" predicates over tuple fields are not reproduced by the twin');
  return pyStr(value);
}

export function evaluatePredicate(predicate: string, signature: ProblemSignature): boolean {
  const g = PRED.exec(predicate)?.groups;
  if (g === undefined) throw new CatalogError(`unparseable predicate ${pyRepr(predicate)}`);
  if (g['kind']) {
    const arg = g['arg'] as string;
    if (g['kind'] === 'observed') return signature.observations.includes(arg);
    if (g['kind'] === 'not_observed') return !signature.observations.includes(arg);
    if (g['kind'] === 'family') return signature.problem_families.includes(arg);
    return signature.domains.includes(arg);
  }
  if (g['infield']) {
    const value = signatureField(signature, g['infield']);
    return value !== null && (g['choices'] as string).split('|').includes(scalarText(value));
  }
  const value = signatureField(signature, g['field'] as string);
  const expected = literal(g['value'] as string);
  return g['op'] === '==' ? value !== null && value === expected : value !== expected;
}

export const allHold = (predicates: readonly string[], signature: ProblemSignature): boolean =>
  predicates.every((p) => evaluatePredicate(p, signature));

export const anyHolds = (predicates: readonly string[], signature: ProblemSignature): boolean =>
  predicates.some((p) => evaluatePredicate(p, signature));

function checkMethod(method: MethodSpec, families: ReadonlyMap<string, FamilySpec>, methods: ReadonlyMap<string, MethodSpec>): void {
  for (const family of [method.family, ...method.secondary_families]) {
    if (!families.has(family)) throw new CatalogError(`${method.method_id}: unknown family ${family}`);
  }
  for (const predicate of [...method.applicability_predicates, ...method.contraindications]) checkPredicate(predicate, method.method_id);
  for (const ref of [...method.composable_with, ...method.conflicts_with]) {
    if (!methods.has(ref)) throw new CatalogError(`${method.method_id}: unknown related method ${ref}`);
  }
  for (const ref of method.conflicts_with) {
    if (!methods.get(ref)?.conflicts_with.includes(method.method_id)) {
      throw new CatalogError(`conflict ${method.method_id}/${ref} is not symmetric`);
    }
  }
  if (method.slot === 'MACRO' && !method.expected_outputs.includes('macro:structured_cycle')) {
    throw new CatalogError(`${method.method_id}: MACRO methods must cover macro:structured_cycle`);
  }
}

function collect<T>(items: unknown, build: (item: unknown) => T, key: (v: T) => string, kind: string): Map<string, T> {
  const out = new Map<string, T>();
  for (const item of Array.isArray(items) && items.length ? items : []) {
    const value = build(item);
    if (out.has(key(value))) throw new CatalogError(`duplicate ${kind} ${key(value)}`);
    out.set(key(value), value);
  }
  return out;
}

/** `parse_catalog(raw)`. `raw` is the JSON object as loaded (integers only; the catalog holds no floats). */
export function parseCatalog(raw: Readonly<Record<string, unknown>>): MethodCatalog {
  if (raw['schema_version'] !== CATALOG_SCHEMA) throw new CatalogError('unsupported catalog schema_version');
  const families = collect(raw['families'], (i) => parseModel(FamilySpecSchema, 'FamilySpec', i), (f) => f.family_id, 'family');
  const methods = collect(raw['methods'], (i) => parseModel(MethodSpecSchema, 'MethodSpec', i), (m) => m.method_id, 'method');
  for (const method of methods.values()) checkMethod(method, families, methods);
  const covered = new Set([...methods.values()].flatMap((m) => m.expected_outputs));
  for (const family of families.values()) {
    const missing = sortStrings(Object.keys(family.needs).filter((n) => !covered.has(n)));
    if (missing.length) {
      throw new CatalogError(`${family.family_id}: needs with no covering method [${missing.map(pyRepr).join(', ')}]`);
    }
  }
  return { families, methods, catalog_hash: semanticHash(raw as unknown as HashValue) };
}
