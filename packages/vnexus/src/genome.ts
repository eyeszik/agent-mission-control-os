/**
 * VNEXUS Brand Genome: twin of `services/langgraph/agency/vnexus/genome.py`.
 *
 * Layers apply in scope order brand -> project -> page -> component -> asset;
 * only APPROVED layers are authoritative (one named draft may be previewed and
 * is then labelled, never authoritative); IMMUTABLE locks a key for every
 * descendant; constraints accumulate and cannot be removed or redefined below.
 * Constraint findings are deterministic checks, never a quality judgement.
 */
import { CanonicalFloat } from '@amc/canonical';
import { pyRepr as reprText } from '@amc/kernel';
import { wcagContrastRatio } from './color';
import { GenomeTransitionError, PyValueError } from './errors';
import {
  INVALID,
  ModelValueError,
  after,
  anyData,
  dictOf,
  enumOf,
  int,
  listOf,
  model,
  optional,
  str,
  validate,
  type FieldParser,
  type Issues,
  type Parsed,
} from './model';
import {
  canonicalHashSync,
  compareCodePoints,
  isFloat,
  isNumberOrBool,
  isRealNumber,
  num,
  pyEq,
  pyIn,
  pyLen,
  pyRepr,
  pyStr,
  pyFloat,
  sortedStrings,
  type PyData,
} from './python';

export const GENOME_SCHEMA = 'amc-vnexus-genome/v1';
export const MAX_KEYS_PER_CHROMOSOME = 200;
export const MAX_CONSTRAINTS = 200;

// Python `re.match` with `$`, which also matches before one trailing "\n".
const KEY_RE = /^[a-z][a-z0-9_]*(\.[a-z0-9_]+){0,5}\n?$/;
const HEX_RE = /^#[0-9a-f]{6}\n?$/;
const SCOPE_PART_RE = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}\n?$/;

export type Scalar = string | number | boolean | null | CanonicalFloat;
export type GenomeValue = Scalar | readonly string[];
export type FlatValues = Readonly<Record<string, GenomeValue>>;

export const CHROMOSOMES = ['strategy', 'visual', 'verbal', 'experience', 'production'] as const;
export type Chromosome = (typeof CHROMOSOMES)[number];

export const CHROMOSOME_DOMAINS: Readonly<Record<Chromosome, readonly string[]>> = {
  strategy: ['positioning', 'audience', 'differentiation', 'promise', 'values', 'competitive_territory'],
  visual: ['color', 'typography', 'grid', 'shape_grammar', 'logo', 'imagery', 'motion'],
  verbal: ['voice', 'tone', 'vocabulary', 'messaging', 'content_rules'],
  experience: ['interaction', 'accessibility', 'navigation', 'responsive'],
  production: ['output', 'media', 'platform', 'licensing', 'delivery'],
};

export const SCOPE_ORDER = ['brand', 'project', 'page', 'component', 'asset'] as const;
export type Scope = (typeof SCOPE_ORDER)[number];

export const VERSION_STATUSES = ['DRAFT', 'EXPERIMENTAL', 'IN_REVIEW', 'APPROVED', 'REJECTED', 'SUPERSEDED'] as const;
export type VersionStatus = (typeof VERSION_STATUSES)[number];
export const EDITABLE_STATUSES: ReadonlySet<VersionStatus> = new Set(['DRAFT', 'EXPERIMENTAL']);
export const FROZEN_STATUSES: ReadonlySet<VersionStatus> = new Set(['IN_REVIEW', 'APPROVED', 'REJECTED', 'SUPERSEDED']);

/** action -> {from: to}. Anything absent is refused. */
export const TRANSITIONS: Readonly<Record<string, Readonly<Partial<Record<VersionStatus, VersionStatus>>>>> = {
  submit: { DRAFT: 'IN_REVIEW' },
  approve: { IN_REVIEW: 'APPROVED' },
  reject: { IN_REVIEW: 'REJECTED' },
  withdraw: { IN_REVIEW: 'DRAFT' },
  supersede: { APPROVED: 'SUPERSEDED' },
};

export const PROVENANCE_KINDS = ['USER_SUPPLIED', 'IMPORTED', 'INFERRED', 'DEFAULTED', 'UNRESOLVED'] as const;
export type ProvenanceKind = (typeof PROVENANCE_KINDS)[number];
export const CONSTRAINT_KINDS = ['IMMUTABLE', 'REQUIRED', 'ALLOWED_VALUES', 'RANGE', 'HEX_COLOR', 'MIN_CONTRAST'] as const;
export type ConstraintKind = (typeof CONSTRAINT_KINDS)[number];
export const SEVERITIES = ['INFO', 'WARNING', 'ERROR', 'BLOCKING'] as const;
export type Severity = (typeof SEVERITIES)[number];
export const CONFLICT_REASONS = ['SCOPE_ORDER', 'UNAPPROVED_OVERRIDE', 'IMMUTABLE_OVERRIDE', 'CONSTRAINT_VIOLATION'] as const;
export type ConflictReason = (typeof CONFLICT_REASONS)[number];

/** Python `Enum(value)`: the member, or `ValueError("'x' is not a valid Name")`. */
export function enumMember<T extends string>(values: readonly T[], name: string, value: unknown): T {
  const found = values.find((v) => v === value);
  if (found === undefined) throw new PyValueError(`${pyRepr(value)} is not a valid ${name}`);
  return found;
}

/** `next_status`: the target status of a lifecycle action, or `GenomeTransitionError`. */
export function nextStatus(current: string, action: string): VersionStatus {
  const status = enumMember(VERSION_STATUSES, 'VersionStatus', current);
  const target = Object.prototype.hasOwnProperty.call(TRANSITIONS, action) ? TRANSITIONS[action]?.[status] : undefined;
  if (target === undefined) throw new GenomeTransitionError(`cannot ${action} a genome version in status ${status}`);
  return target;
}

// -- records -------------------------------------------------------------------

export interface GenomeConstraint {
  readonly constraint_id: string;
  readonly key: string;
  readonly kind: ConstraintKind;
  readonly params: Readonly<Record<string, PyData>>;
  readonly severity: Severity;
  readonly rationale: string;
}

export interface GenomeProvenance {
  readonly key: string;
  readonly kind: ProvenanceKind;
  readonly source_ref: string;
  readonly note: string;
}

export type Chromosomes = Readonly<Partial<Record<Chromosome, Readonly<Record<string, GenomeValue>>>>>;

export interface GenomeDocument {
  readonly schema_version: string;
  readonly chromosomes: Chromosomes;
  readonly constraints: readonly GenomeConstraint[];
  readonly provenance: readonly GenomeProvenance[];
}

export interface GenomeLayer {
  readonly scope: Scope;
  readonly scope_ref: string;
  readonly status: VersionStatus;
  readonly document: GenomeDocument;
  readonly version_id: string | null;
  readonly version: number | null;
}

// -- validation ----------------------------------------------------------------

function fail(message: string): never {
  throw new ModelValueError(message);
}

function checkConstraintKey(value: string): void {
  const dot = value.indexOf('.');
  const head = dot < 0 ? value : value.slice(0, dot);
  const rest = dot < 0 ? '' : value.slice(dot + 1);
  if (!(CHROMOSOMES as readonly string[]).includes(head) || !rest || !KEY_RE.test(rest)) {
    fail(`constraint key ${reprText(value)} must be '<chromosome>.<key>'`);
  }
}

function checkRange(p: Readonly<Record<string, PyData>>): void {
  const lo = p['min'];
  const hi = p['max'];
  if (!isRealNumber(lo) || !isRealNumber(hi) || num(lo) > num(hi)) fail('RANGE needs numeric params.min <= params.max');
}

function checkContrast(p: Readonly<Record<string, PyData>>): void {
  const ratio = p['ratio'];
  if (typeof p['against'] !== 'string' || !isNumberOrBool(ratio) || !(num(ratio) >= 1 && num(ratio) <= 21)) {
    fail('MIN_CONTRAST needs params.against (a key) and params.ratio in [1, 21]');
  }
}

function checkConstraintParams(c: GenomeConstraint): void {
  const p = c.params;
  if (c.kind === 'ALLOWED_VALUES') {
    const values = p['values'];
    if (!Array.isArray(values) || values.length === 0 || values.length > 100) {
      fail('ALLOWED_VALUES needs params.values: a non-empty list (<= 100)');
    }
  } else if (c.kind === 'RANGE') checkRange(p);
  else if (c.kind === 'MIN_CONTRAST') checkContrast(p);
  else if (Object.keys(p).length > 0) fail(`${c.kind} takes no params`);
}

export const constraintParser: FieldParser<GenomeConstraint> = model<GenomeConstraint>(
  {
    constraint_id: { parse: str({ pattern: /^[a-z0-9][a-z0-9_.-]{0,79}$/ }) },
    key: { parse: after(str(), checkConstraintKey) },
    kind: { parse: enumOf(CONSTRAINT_KINDS) },
    params: { parse: dictOf(str(), anyData()), fallback: () => ({}) },
    severity: { parse: enumOf(SEVERITIES), fallback: () => 'BLOCKING' },
    rationale: { parse: str({ max: 500 }), fallback: () => '' },
  },
  { extra: 'forbid', check: checkConstraintParams },
);

export const provenanceParser: FieldParser<GenomeProvenance> = model<GenomeProvenance>(
  {
    key: { parse: str() },
    kind: { parse: enumOf(PROVENANCE_KINDS) },
    source_ref: { parse: str({ max: 300 }), fallback: () => '' },
    note: { parse: str({ max: 300 }), fallback: () => '' },
  },
  { extra: 'forbid' },
);

/** The `Value` union: str | int | float | bool | None | list[str]. */
export const valueParser: FieldParser<GenomeValue> = (value, loc, issues) => {
  if (value === null || typeof value === 'string' || typeof value === 'boolean' || value instanceof CanonicalFloat) return value;
  if (typeof value === 'number') return Number.isInteger(value) && !Number.isSafeInteger(value) ? issues.add(loc, 'integers beyond 2^53 are refused') : value;
  if (Array.isArray(value) && value.every((x: unknown) => typeof x === 'string')) return value as string[];
  return issues.add(loc, 'Input should be a str, int, float, bool, None or list of str');
};

function checkEntry(chromosome: string, key: string, item: GenomeValue): void {
  if (!KEY_RE.test(key)) fail(`${chromosome}.${key}: keys are lower-case dotted identifiers`);
  if (isFloat(item) && Number.isNaN(num(item))) fail(`${chromosome}.${key}: NaN is not a value`);
  if (typeof item === 'string' && pyLen(item) > 2000) fail(`${chromosome}.${key}: value longer than 2000 characters`);
  if (Array.isArray(item) && (item.length > 50 || !item.every((x: string) => pyLen(x) <= 300))) {
    fail(`${chromosome}.${key}: lists hold <= 50 strings of <= 300 characters`);
  }
}

function checkChromosomes(value: Chromosomes): void {
  for (const [chromosome, entries] of Object.entries(value)) {
    const items = Object.entries(entries ?? {});
    if (items.length > MAX_KEYS_PER_CHROMOSOME) fail(`${chromosome}: more than ${MAX_KEYS_PER_CHROMOSOME} keys`);
    for (const [key, item] of items) checkEntry(chromosome, key, item);
  }
}

function checkSchema(value: string): void {
  if (value !== GENOME_SCHEMA) fail(`unsupported genome schema ${reprText(value)}`);
}

function checkDocument(doc: GenomeDocument): void {
  if (doc.constraints.length > MAX_CONSTRAINTS) fail(`more than ${MAX_CONSTRAINTS} constraints`);
  const ids = doc.constraints.map((c) => c.constraint_id);
  if (new Set(ids).size !== ids.length) fail('constraint ids must be unique within a document');
}

export const documentParser: FieldParser<GenomeDocument> = model<GenomeDocument>(
  {
    schema_version: { parse: after(str(), checkSchema), fallback: () => GENOME_SCHEMA },
    chromosomes: { parse: after(dictOf(enumOf(CHROMOSOMES), dictOf(str(), valueParser)), checkChromosomes), fallback: () => ({}) },
    constraints: { parse: listOf(constraintParser), fallback: () => [] },
    provenance: { parse: listOf(provenanceParser), fallback: () => [] },
  },
  { extra: 'forbid', check: checkDocument },
);

export const layerParser: FieldParser<GenomeLayer> = model<GenomeLayer>(
  {
    scope: { parse: enumOf(SCOPE_ORDER) },
    scope_ref: { parse: str({ min: 1, max: 300 }) },
    status: { parse: enumOf(VERSION_STATUSES) },
    document: { parse: documentParser },
    version_id: { parse: optional(str()), fallback: () => null },
    version: { parse: optional(int()), fallback: () => null },
  },
  { extra: 'forbid' },
);

export function parseConstraint(input: unknown): GenomeConstraint {
  return validate('GenomeConstraint', constraintParser, input);
}

export function parseProvenance(input: unknown): GenomeProvenance {
  return validate('GenomeProvenance', provenanceParser, input);
}

export function parseDocument(input: unknown): GenomeDocument {
  return validate('GenomeDocument', documentParser, input);
}

export function parseLayer(input: unknown): GenomeLayer {
  return validate('GenomeLayer', layerParser, input);
}

/** Parses an already-typed value as a `GenomeValue` (used where Python constructs models from values). */
export function asParsed<T>(parsed: Parsed<T>, issues: Issues, title: string): T {
  if (parsed === INVALID) throw new PyValueError(`${title}: ${issues.list.map((i) => i.msg).join('; ')}`);
  return parsed;
}

// -- dumps and hashes ------------------------------------------------------------

export function dumpConstraint(c: GenomeConstraint): Record<string, PyData> {
  return { constraint_id: c.constraint_id, key: c.key, kind: c.kind, params: c.params, severity: c.severity, rationale: c.rationale };
}

export function dumpDocument(doc: GenomeDocument): Record<string, PyData> {
  return {
    schema_version: doc.schema_version,
    chromosomes: doc.chromosomes as Record<string, Record<string, PyData>>,
    constraints: doc.constraints.map(dumpConstraint),
    provenance: doc.provenance.map((p) => ({ key: p.key, kind: p.kind, source_ref: p.source_ref, note: p.note })),
  };
}

/** `GenomeDocument.content_hash`. */
export function documentHash(doc: GenomeDocument): string {
  return canonicalHashSync(dumpDocument(doc));
}

/** `GenomeDocument.flatten()`: `chromosome.key` -> value, sorted by chromosome then key. */
export function flatten(doc: GenomeDocument): Map<string, GenomeValue> {
  const out = new Map<string, GenomeValue>();
  for (const chromosome of sortedStrings(Object.keys(doc.chromosomes))) {
    const entries = doc.chromosomes[chromosome as Chromosome] ?? {};
    for (const key of sortedStrings(Object.keys(entries))) out.set(`${chromosome}.${key}`, entries[key] ?? null);
  }
  return out;
}

/** Python `str.partition(".")`. */
export function partition(text: string): [string, string] {
  const dot = text.indexOf('.');
  return dot < 0 ? [text, ''] : [text.slice(0, dot), text.slice(dot + 1)];
}

/** `document_from_flat`. Keys are read in the map's insertion order, as Python iterates a dict. */
export function documentFromFlat(
  values: ReadonlyMap<string, GenomeValue>,
  constraints: readonly GenomeConstraint[] = [],
  provenance: readonly GenomeProvenance[] = [],
): GenomeDocument {
  const chromosomes: Record<string, Record<string, GenomeValue>> = {};
  for (const [key, value] of values) {
    const [head, rest] = partition(key);
    const chromosome = enumMember(CHROMOSOMES, 'Chromosome', head);
    (chromosomes[chromosome] ??= {})[rest] = value;
  }
  return parseDocument({ chromosomes, constraints: constraints.map(dumpConstraint), provenance: provenance.map((p) => ({ ...p })) });
}

/** Pydantic model equality for two constraints (`==` on every field). */
export function constraintEquals(a: GenomeConstraint, b: GenomeConstraint): boolean {
  return a.constraint_id === b.constraint_id && a.key === b.key && a.kind === b.kind && a.severity === b.severity
    && a.rationale === b.rationale && pyEq(a.params, b.params);
}

export { pyFloat, compareCodePoints };
