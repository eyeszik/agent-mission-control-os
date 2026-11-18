/**
 * Layer resolution, constraint evaluation, document diff and scope helpers:
 * twin of the rest of `services/langgraph/agency/vnexus/genome.py`.
 */
import { CanonicalFloat } from '@amc/canonical';
import { pyRepr as reprText } from '@amc/kernel';
import { wcagContrastRatio } from './color';
import {
  SCOPE_ORDER,
  constraintEquals,
  documentHash,
  dumpConstraint,
  flatten,
  type ConflictReason,
  type ConstraintKind,
  type GenomeConstraint,
  type GenomeDocument,
  type GenomeLayer,
  type GenomeValue,
  type Scope,
  type Severity,
} from './genome';
import { PyValueError } from './errors';
import {
  canonicalHashSync,
  floatRepr,
  num,
  pyEq,
  pyIn,
  pyRepr,
  pyStr,
  sortedStrings,
  sortedUnique,
  type PyData,
} from './python';
import { compareCodePoints } from '@amc/kernel';

const HEX_RE = /^#[0-9a-f]{6}\n?$/;

export interface GenomeConflict {
  readonly key: string;
  readonly reason: ConflictReason;
  readonly scope_ref: string;
  readonly detail: string;
  readonly constraint_id: string | null;
}

export interface ConstraintFinding {
  readonly constraint_id: string;
  readonly key: string;
  readonly kind: ConstraintKind;
  readonly severity: Severity;
  readonly passed: boolean;
  readonly detail: string;
  readonly declared_by: string;
}

export interface Resolution {
  readonly values: Readonly<Record<string, GenomeValue>>;
  readonly sources: Readonly<Record<string, string>>;
  readonly constraints: readonly GenomeConstraint[];
  readonly constraint_owner: Readonly<Record<string, string>>;
  readonly conflicts: readonly GenomeConflict[];
  readonly findings: readonly ConstraintFinding[];
  readonly applied_scopes: readonly string[];
  readonly preview_scope: string | null;
  readonly authoritative: boolean;
}

type ValueMap = ReadonlyMap<string, GenomeValue>;

function isHex(value: unknown): value is string {
  return typeof value === 'string' && HEX_RE.test(value);
}

function byConstraintId(a: GenomeConstraint, b: GenomeConstraint): number {
  return compareCodePoints(a.constraint_id, b.constraint_id);
}

function isNumeric(value: unknown): value is number | CanonicalFloat {
  return typeof value === 'number' || value instanceof CanonicalFloat;
}

function checkAllowed(value: GenomeValue, allowed: readonly PyData[]): string | null {
  if (Array.isArray(value)) {
    const outside = (value as readonly string[]).filter((v) => !pyIn(v, allowed));
    return outside.length > 0 ? `${pyRepr(outside)} not in allowed values` : null;
  }
  return pyIn(value, allowed) ? null : `${pyRepr(value)} not in allowed values ${pyRepr(allowed)}`;
}

function checkRangeValue(value: GenomeValue, p: Readonly<Record<string, PyData>>): string | null {
  if (typeof value === 'boolean' || !isNumeric(value)) return `${pyRepr(value)} is not numeric`;
  const n = num(value);
  const lo = num(p['min'] as number);
  const hi = num(p['max'] as number);
  return lo <= n && n <= hi ? null : `${pyStr(value)} outside [${pyStr(p['min'])}, ${pyStr(p['max'])}]`;
}

function checkContrastValue(c: GenomeConstraint, value: GenomeValue, values: ValueMap): string | null {
  const against = c.params['against'] as string;
  const other = values.get(against);
  if (!(isHex(value) && isHex(other))) return null; // evaluated on the resolved genome
  const ratio = wcagContrastRatio(value, other);
  const floor = num(c.params['ratio'] as number);
  return ratio >= floor ? null : `contrast ${floatRepr(ratio)}:1 against ${against} is below ${pyStr(c.params['ratio'])}:1`;
}

/** `_check_value`: null when the value satisfies the constraint, else a reason. */
export function checkValue(c: GenomeConstraint, value: GenomeValue, values: ValueMap): string | null {
  switch (c.kind) {
    case 'ALLOWED_VALUES':
      return checkAllowed(value, c.params['values'] as readonly PyData[]);
    case 'RANGE':
      return checkRangeValue(value, c.params);
    case 'HEX_COLOR':
      return isHex(value) ? null : `${pyRepr(value)} is not a #rrggbb colour`;
    case 'MIN_CONTRAST':
      return checkContrastValue(c, value, values);
    default:
      return null;
  }
}

function constraintReason(c: GenomeConstraint, values: ValueMap): string | null {
  const present = values.get(c.key) !== undefined && values.get(c.key) !== null;
  if (c.kind === 'IMMUTABLE') return null;
  if (c.kind === 'REQUIRED' || !present) return present ? null : 'no value resolved for a constrained key';
  if (c.kind === 'MIN_CONTRAST') {
    const against = c.params['against'] as string;
    if (!isHex(values.get(c.key)) || !isHex(values.get(against))) return `contrast pair ${c.key}/${against} is not two colours`;
  }
  return checkValue(c, values.get(c.key) as GenomeValue, values);
}

/** `evaluate_constraints`: deterministic findings for every constraint over a resolved value map. */
export function evaluateConstraints(
  values: ValueMap,
  constraints: Iterable<GenomeConstraint>,
  owner: Readonly<Record<string, string>> = {},
): ConstraintFinding[] {
  return Array.from(constraints).sort(byConstraintId).map((c): ConstraintFinding => {
    const reason = constraintReason(c, values);
    const detail = c.kind === 'IMMUTABLE' ? 'locked for descendant scopes' : (reason ?? 'satisfied');
    return {
      constraint_id: c.constraint_id, key: c.key, kind: c.kind, severity: c.severity, passed: reason === null, detail,
      declared_by: owner[c.constraint_id] ?? '',
    };
  });
}

interface ResolveState {
  values: Map<string, GenomeValue>;
  sources: Map<string, string>;
  constraints: Map<string, GenomeConstraint>;
  owner: Map<string, string>;
  conflicts: GenomeConflict[];
  applied: string[];
  last: number;
  previewed: string | null;
}

function conflict(key: string, reason: ConflictReason, scopeRef: string, detail: string, constraintId: string | null = null): GenomeConflict {
  return { key, reason, scope_ref: scopeRef, detail, constraint_id: constraintId };
}

function applyValue(state: ResolveState, layer: GenomeLayer, inherited: ReadonlyMap<string, GenomeConstraint>, key: string, value: GenomeValue): void {
  const locked = Array.from(inherited.values()).find((c) => c.key === key && c.kind === 'IMMUTABLE');
  const current = state.values.get(key);
  if (locked !== undefined && state.values.has(key) && !pyEq(current, value)) {
    state.conflicts.push(conflict(key, 'IMMUTABLE_OVERRIDE', layer.scope_ref, `locked by ${state.owner.get(locked.constraint_id)}`, locked.constraint_id));
    return;
  }
  const trial = new Map(state.values).set(key, value);
  for (const c of Array.from(inherited.values()).sort(byConstraintId)) {
    const reason = c.key === key ? checkValue(c, value, trial) : null;
    if (reason) {
      state.conflicts.push(conflict(key, 'CONSTRAINT_VIOLATION', layer.scope_ref, reason, c.constraint_id));
      return;
    }
  }
  state.values.set(key, value);
  state.sources.set(key, layer.scope_ref);
}

function addConstraint(state: ResolveState, layer: GenomeLayer, c: GenomeConstraint): void {
  const existing = state.constraints.get(c.constraint_id);
  if (existing !== undefined && !constraintEquals(existing, c)) {
    const detail = `cannot redefine constraint declared by ${state.owner.get(c.constraint_id)}`;
    state.conflicts.push(conflict(c.key, 'CONSTRAINT_VIOLATION', layer.scope_ref, detail, c.constraint_id));
    return;
  }
  if (existing === undefined) {
    state.constraints.set(c.constraint_id, c);
    state.owner.set(c.constraint_id, layer.scope_ref);
  }
}

function applyLayer(state: ResolveState, layer: GenomeLayer): void {
  state.applied.push(layer.scope_ref);
  const inherited = new Map(state.constraints);
  for (const [key, value] of flatten(layer.document)) applyValue(state, layer, inherited, key, value);
  for (const c of layer.document.constraints) addConstraint(state, layer, c);
}

function skipUnapproved(state: ResolveState, layer: GenomeLayer): void {
  for (const key of flatten(layer.document).keys()) {
    state.conflicts.push(conflict(key, 'UNAPPROVED_OVERRIDE', layer.scope_ref, `${layer.status} layers are not authoritative`));
  }
}

function visit(state: ResolveState, layer: GenomeLayer, previewRef: string | null): void {
  const order = SCOPE_ORDER.indexOf(layer.scope);
  if (order < state.last) {
    state.conflicts.push(conflict('*', 'SCOPE_ORDER', layer.scope_ref, `${layer.scope} layer after a narrower scope`));
    return;
  }
  state.last = order;
  const isPreview = previewRef !== null && layer.scope_ref === previewRef && layer.status !== 'APPROVED';
  if (layer.status !== 'APPROVED' && !isPreview) return skipUnapproved(state, layer);
  if (isPreview) state.previewed = layer.scope_ref;
  applyLayer(state, layer);
}

function recordOf<V>(map: ReadonlyMap<string, V>): Record<string, V> {
  return Object.fromEntries(Array.from(map.entries()).sort(([a], [b]) => compareCodePoints(a, b)));
}

/** `resolve`: layers into one value map; `previewRef` names a non-approved layer applied as a preview. */
export function resolve(layers: readonly GenomeLayer[], previewRef: string | null = null): Resolution {
  const state: ResolveState = {
    values: new Map(), sources: new Map(), constraints: new Map(), owner: new Map(), conflicts: [], applied: [], last: -1, previewed: null,
  };
  for (const layer of layers) visit(state, layer, previewRef);
  const ordered = Array.from(state.constraints.values()).sort(byConstraintId);
  const owner = recordOf(state.owner);
  return {
    values: recordOf(state.values), sources: recordOf(state.sources), constraints: ordered, constraint_owner: owner,
    conflicts: state.conflicts, findings: evaluateConstraints(state.values, ordered, owner), applied_scopes: state.applied,
    preview_scope: state.previewed, authoritative: state.previewed === null,
  };
}

/** `Resolution.blocking`. */
export function blockingFindings(resolution: Resolution): ConstraintFinding[] {
  return resolution.findings.filter((f) => !f.passed && f.severity === 'BLOCKING');
}

/** `Resolution.resolution_hash`. */
export function resolutionHash(resolution: Resolution): string {
  return canonicalHashSync({
    values: resolution.values as Record<string, PyData>,
    constraints: resolution.constraints.map(dumpConstraint),
    applied: [...resolution.applied_scopes],
    preview: resolution.preview_scope,
  });
}

// -- diff -------------------------------------------------------------------------

export interface ValueChange {
  readonly key: string;
  readonly before: GenomeValue;
  readonly after: GenomeValue;
}

export interface DocumentDiff {
  readonly added: readonly ValueChange[];
  readonly removed: readonly ValueChange[];
  readonly modified: readonly ValueChange[];
  readonly unchanged: readonly string[];
  readonly constraints_added: readonly string[];
  readonly constraints_removed: readonly string[];
  readonly constraints_modified: readonly string[];
}

function constraintMap(doc: GenomeDocument): Map<string, GenomeConstraint> {
  return new Map(doc.constraints.map((c): [string, GenomeConstraint] => [c.constraint_id, c]));
}

function onlyIn(a: ReadonlyMap<string, unknown>, b: ReadonlyMap<string, unknown>): string[] {
  return sortedStrings(Array.from(a.keys()).filter((k) => !b.has(k)));
}

/** `diff_documents`. */
export function diffDocuments(before: GenomeDocument, after: GenomeDocument): DocumentDiff {
  const a = flatten(before);
  const b = flatten(after);
  const both = sortedStrings(Array.from(a.keys()).filter((k) => b.has(k)));
  const get = (m: ValueMap, k: string): GenomeValue => m.get(k) ?? null;
  const ca = constraintMap(before);
  const cb = constraintMap(after);
  const bothC = sortedStrings(Array.from(ca.keys()).filter((k) => cb.has(k)));
  return {
    added: onlyIn(b, a).map((k) => ({ key: k, before: null, after: get(b, k) })),
    removed: onlyIn(a, b).map((k) => ({ key: k, before: get(a, k), after: null })),
    modified: both.filter((k) => !pyEq(get(a, k), get(b, k))).map((k) => ({ key: k, before: get(a, k), after: get(b, k) })),
    unchanged: both.filter((k) => pyEq(get(a, k), get(b, k))),
    constraints_added: onlyIn(cb, ca),
    constraints_removed: onlyIn(ca, cb),
    constraints_modified: bothC.filter((k) => !constraintEquals(ca.get(k) as GenomeConstraint, cb.get(k) as GenomeConstraint)),
  };
}

/** `DocumentDiff.is_empty`. */
export function diffIsEmpty(diff: DocumentDiff): boolean {
  return !(diff.added.length || diff.removed.length || diff.modified.length || diff.constraints_added.length
    || diff.constraints_removed.length || diff.constraints_modified.length);
}

/** `self_check`: a document's own values against its own constraints (REQUIRED is checked only after resolution). */
export function selfCheck(document: GenomeDocument): ConstraintFinding[] {
  const values = flatten(document);
  const own = document.constraints.filter((c) => c.kind !== 'REQUIRED' && values.has(c.key));
  return evaluateConstraints(values, own).filter((f) => !f.passed);
}

// -- scope helpers ------------------------------------------------------------------

const SCOPE_PART_RE = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}\n?$/;

/** `scope_ref_project`: the project that authorizes a scope. */
export function scopeRefProject(scope: Scope, scopeRef: string, brandOwnerProject: string): string {
  if (scope === 'brand') return brandOwnerProject;
  const parts = scopeRef.split('/');
  const depth = SCOPE_ORDER.indexOf(scope);
  if (parts.length !== depth || !parts.every((p) => SCOPE_PART_RE.test(p))) {
    throw new PyValueError(`a ${scope} scope_ref has ${depth} '/'-separated segment(s), starting with the project id`);
  }
  return parts[0] as string;
}

/** `ancestor_refs`: the scope chain for a target, outermost first. */
export function ancestorRefs(scope: Scope, scopeRef: string, brandId: string): Array<[Scope, string]> {
  const chain: Array<[Scope, string]> = [['brand', brandId]];
  if (scope === 'brand') return chain;
  const parts = scopeRef.split('/');
  for (let i = 1; i <= SCOPE_ORDER.indexOf(scope); i += 1) chain.push([SCOPE_ORDER[i] as Scope, parts.slice(0, i).join('/')]);
  return chain;
}

export { documentHash, reprText, sortedUnique };
