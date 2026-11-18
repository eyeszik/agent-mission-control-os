/**
 * Validation of the records Python builds with Pydantic (`DirectionBrief`, `FindingIn`, `Assessor`).
 *
 * Python raises `pydantic.ValidationError`, whose message embeds a documentation URL and the pydantic version. The
 * twin raises `ValidationError` with the same `issues` (location and error type, as `exc.errors()` reports them),
 * which the fixture records. Pydantic's lax coercions (`"3"` or `2.0` for an int, `True` for a 1) are refused: the
 * fixture lists them as "Python accepts, TS refuses" cases.
 */
import { cpLen, isPlainRecord, type PyValue } from '@amc/vnexus-brandbook';
import {
  ASSET_ROLES, EVIDENCE_CLASSES, EVIDENCE_SOURCES, GATES, NONE, SEVERITIES,
  type AssetRole, type DirectionBrief, type EvidenceClass, type EvidenceSource, type FindingIn, type Gate, type ReferenceIn, type Severity,
} from './records';

export type Loc = ReadonlyArray<string | number>;
export interface Issue {
  readonly loc: Loc;
  readonly type: string;
}

export class ValidationError extends Error {
  override name = 'ValidationError';
  constructor(readonly model: string, readonly issues: readonly Issue[]) {
    super(`${issues.length} validation error${issues.length === 1 ? '' : 's'} for ${model}`);
  }
}

type Source = { readonly [key: string]: unknown };

class Collector {
  readonly issues: Issue[] = [];
  add(loc: Loc, type: string): void {
    this.issues.push({ loc, type });
  }
}

function isInt(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value);
}

function intField(c: Collector, source: Source, key: string, lo: number, hi: number, fallback: number): number {
  const value = source[key];
  if (value === undefined) return fallback;
  if (!isInt(value)) {
    c.add([key], typeof value === 'number' ? 'int_from_float' : (typeof value === 'string' ? 'int_parsing' : 'int_type'));
    return fallback;
  }
  if (value < lo) c.add([key], 'greater_than_equal');
  else if (value > hi) c.add([key], 'less_than_equal');
  return value;
}

function strField(c: Collector, loc: Loc, value: unknown, min: number, max: number): string {
  if (typeof value !== 'string') {
    c.add(loc, 'string_type');
    return '';
  }
  if (cpLen(value) < min) c.add(loc, 'string_too_short');
  else if (cpLen(value) > max) c.add(loc, 'string_too_long');
  return value;
}

function enumField<T extends string>(c: Collector, key: string, value: unknown, members: readonly T[]): T {
  if (typeof value !== 'string' || !(members as readonly string[]).includes(value)) {
    c.add([key], 'enum');
    return members[0] as T;
  }
  return value as T;
}

/** `Union[Literal["@none"], str, None]` with a `max_length` on the str branch. */
function decidedField(c: Collector, source: Source, key: string, max: number): string | null {
  const value = source[key];
  if (value === undefined || value === null) return null;
  if (typeof value !== 'string') {
    c.add([key, "literal['@none']"], 'literal_error');
    c.add([key, 'str'], 'string_type');
    return null;
  }
  if (value !== NONE && cpLen(value) > max) c.add([key], 'too_long');
  return value;
}

/** `Union[Literal["@none"], list[str], None]`. */
function decidedList(c: Collector, source: Source, key: string): '@none' | readonly string[] | null {
  const value = source[key];
  if (value === undefined || value === null || value === NONE) return value ?? null;
  const loc = (extra: ReadonlyArray<string | number>): Loc => [key, ...extra];
  if (!Array.isArray(value)) {
    c.add(loc(["literal['@none']"]), 'literal_error');
    c.add(loc(['list[str]']), 'list_type');
    return null;
  }
  const bad = value.findIndex((item: unknown) => typeof item !== 'string');
  if (bad >= 0) {
    c.add(loc(["literal['@none']"]), 'literal_error');
    c.add(loc(['list[str]', bad]), 'string_type');
    return null;
  }
  return value as string[];
}

function stringList(c: Collector, source: Source, key: string, max: number): readonly string[] {
  const value = source[key];
  if (value === undefined) return [];
  if (!Array.isArray(value)) {
    c.add([key], 'list_type');
    return [];
  }
  if (value.length > max) {
    c.add([key], 'too_long'); // pydantic checks the length before the items
    return [];
  }
  value.forEach((item: unknown, i) => {
    if (typeof item !== 'string') c.add([key, i], 'string_type');
  });
  return value as string[];
}

function referenceList(c: Collector, source: Source): readonly ReferenceIn[] {
  const value = source['references'];
  if (value === undefined) return [];
  if (!Array.isArray(value)) {
    c.add(['references'], 'list_type');
    return [];
  }
  if (value.length > 12) {
    c.add(['references'], 'too_long');
    return [];
  }
  return value.map((item: unknown, i) => reference(c, item, i));
}

function reference(c: Collector, item: unknown, i: number): ReferenceIn {
  if (!isPlainRecord(item as PyValue)) {
    c.add(['references', i], 'model_type');
    return { ref_id: '', role: 'principle_only', rights: 'unknown' };
  }
  const r = item as Source;
  const ref_id = strField(c, ['references', i, 'ref_id'], r['ref_id'], 1, 200);
  const role = literal(c, ['references', i, 'role'], r['role'] ?? 'principle_only', ['principle_only', 'approved_asset']);
  const rights = literal(c, ['references', i, 'rights'], r['rights'] ?? 'unknown', ['owned', 'licensed', 'unknown']);
  for (const k of Object.keys(r)) if (!['ref_id', 'role', 'rights'].includes(k)) c.add(['references', i, k], 'extra_forbidden');
  return { ref_id, role, rights };
}

function literal<T extends string>(c: Collector, loc: Loc, value: unknown, members: readonly T[]): T {
  if (typeof value !== 'string' || !(members as readonly string[]).includes(value)) {
    c.add(loc, 'literal_error');
    return members[0] as T;
  }
  return value as T;
}

const BRIEF_KEYS = ['asset_role', 'objective', 'audience', 'category', 'exact_text', 'references', 'rights_constraints', 'privacy_constraints',
  'applications', 'emotional_targets', 'directions', 'candidate_count', 'budget_minor', 'width', 'height'];

function required(c: Collector, source: Source, keys: readonly string[]): void {
  for (const k of keys) if (source[k] === undefined) c.add([k], 'missing');
}

/** `DirectionBrief(**input)`: defaults applied, every constraint checked, extra keys forbidden. */
export function parseBrief(input: unknown): DirectionBrief {
  const c = new Collector();
  const s = (isPlainRecord(input as PyValue) ? input : {}) as Source;
  required(c, s, ['asset_role', 'objective']);
  const asset_role: AssetRole = s['asset_role'] === undefined ? 'LOGO_MARK' : enumField(c, 'asset_role', s['asset_role'], ASSET_ROLES);
  const objective = s['objective'] === undefined ? '' : strField(c, ['objective'], s['objective'], 1, 1000);
  const brief: DirectionBrief = { asset_role, objective, audience: decidedField(c, s, 'audience', 300), category: decidedField(c, s, 'category', 200),
    exact_text: decidedList(c, s, 'exact_text'), references: referenceList(c, s), rights_constraints: decidedField(c, s, 'rights_constraints', 1000),
    privacy_constraints: decidedField(c, s, 'privacy_constraints', 1000), applications: decidedList(c, s, 'applications'),
    emotional_targets: stringList(c, s, 'emotional_targets', 6), directions: stringList(c, s, 'directions', 4),
    candidate_count: intField(c, s, 'candidate_count', 1, 4, 3), budget_minor: intField(c, s, 'budget_minor', 0, 10_000_000, 0),
    width: intField(c, s, 'width', 64, 4096, 1024), height: intField(c, s, 'height', 64, 4096, 1024) };
  for (const k of Object.keys(s)) if (!BRIEF_KEYS.includes(k)) c.add([k], 'extra_forbidden');
  if (c.issues.length > 0) throw new ValidationError('DirectionBrief', c.issues);
  return brief;
}

const FINDING_KEYS = ['candidate', 'criterion', 'seat', 'region_or_element', 'evidence_class', 'evidence_source', 'observation', 'severity',
  'rationale', 'proposed_change', 'acceptance_check', 'uncertainty', 'score', 'gate', 'gate_status', 'trait', 'cue'];

function optionalString(c: Collector, s: Source, key: string, max: number): string | null {
  const v = s[key];
  if (v === undefined || v === null) return null;
  return strField(c, [key], v, 0, max);
}

function defaultedString(c: Collector, s: Source, key: string, fallback: string, max: number): string {
  return s[key] === undefined ? fallback : strField(c, [key], s[key], 0, max);
}

function gateFields(c: Collector, s: Source): [Gate | null, 'PASS' | 'FAIL' | null] {
  const gate = s['gate'] === undefined || s['gate'] === null ? null : enumField(c, 'gate', s['gate'], GATES);
  const gs = s['gate_status'];
  const status = gs === undefined || gs === null ? null : literal(c, ['gate_status'], gs, ['PASS', 'FAIL'] as const);
  return [gate, status];
}

function seatField(c: Collector, s: Source): string {
  const seat = s['seat'];
  if (seat === undefined) return '';
  if (typeof seat !== 'string') {
    c.add(['seat'], 'string_type');
    return '';
  }
  if (!/^(0[1-9]|1[0-4])$/.test(seat)) c.add(['seat'], 'string_pattern_mismatch');
  return seat;
}

function scoreField(c: Collector, s: Source): number | null {
  if (s['score'] === undefined || s['score'] === null) return null;
  return intField(c, s, 'score', 0, 10, 0);
}

/** `FindingIn(**input)`. */
export function parseFinding(input: unknown): FindingIn {
  const c = new Collector();
  const s = (isPlainRecord(input as PyValue) ? input : {}) as Source;
  required(c, s, ['candidate', 'criterion', 'seat', 'evidence_class', 'observation']);
  const [gate, gate_status] = gateFields(c, s);
  const finding: FindingIn = {
    candidate: s['candidate'] === undefined ? '' : strField(c, ['candidate'], s['candidate'], 1, 120),
    criterion: s['criterion'] === undefined ? '' : strField(c, ['criterion'], s['criterion'], 1, 80), seat: seatField(c, s),
    region_or_element: defaultedString(c, s, 'region_or_element', 'whole asset', 200),
    evidence_class: s['evidence_class'] === undefined ? 'OBSERVED' : enumField<EvidenceClass>(c, 'evidence_class', s['evidence_class'], EVIDENCE_CLASSES),
    evidence_source: s['evidence_source'] === undefined ? 'PIXELS' : enumField<EvidenceSource>(c, 'evidence_source', s['evidence_source'], EVIDENCE_SOURCES),
    observation: s['observation'] === undefined ? '' : strField(c, ['observation'], s['observation'], 1, 2000),
    severity: s['severity'] === undefined ? 'NOTE' : enumField<Severity>(c, 'severity', s['severity'], SEVERITIES),
    rationale: defaultedString(c, s, 'rationale', '', 2000), proposed_change: optionalString(c, s, 'proposed_change', 2000),
    acceptance_check: optionalString(c, s, 'acceptance_check', 1000), uncertainty: defaultedString(c, s, 'uncertainty', '', 500),
    score: scoreField(c, s), gate, gate_status, trait: optionalString(c, s, 'trait', 80), cue: optionalString(c, s, 'cue', 300),
  };
  for (const k of Object.keys(s)) if (!FINDING_KEYS.includes(k)) c.add([k], 'extra_forbidden');
  if (c.issues.length > 0) throw new ValidationError('FindingIn', c.issues);
  return finding;
}

/** `Assessor(kind=HUMAN, id=reviewer)`: the id must be 1..200 characters. */
export function checkAssessorId(id: string): void {
  const c = new Collector();
  strField(c, ['id'], id, 1, 200);
  if (c.issues.length > 0) throw new ValidationError('Assessor', c.issues);
}
