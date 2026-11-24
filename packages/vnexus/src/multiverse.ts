/**
 * VNEXUS creative multiverse: twin of `vnexus/multiverse.py`.
 *
 * A branch never edits its base; it records a change set against an immutable
 * base version. Comparison reports what changed and which approved invariants
 * a branch would break. Promotion is not a merge and nothing here decides that
 * a direction is better.
 */
import { BranchTransitionError, PyValueError } from './errors';
import {
  constraintEquals,
  constraintParser,
  documentFromFlat,
  documentHash,
  dumpConstraint,
  dumpDocument,
  enumMember,
  flatten,
  parseLayer,
  valueParser,
  type GenomeConstraint,
  type GenomeDocument,
  type GenomeLayer,
  type GenomeValue,
} from './genome';
import { ModelValueError, dictOf, listOf, model, str, validate, type FieldParser } from './model';
import { canonicalHashSync, compareCodePoints, pyEq, pyRepr, sortedStrings, sortedUnique, type PyData } from './python';
import { diffDocuments, resolve, resolutionHash, type ConstraintFinding } from './resolve';

export const BRANCH_STATES = ['OPEN', 'IN_REVIEW', 'PROMOTED', 'REJECTED', 'ARCHIVED'] as const;
export type BranchState = (typeof BRANCH_STATES)[number];

export const BRANCH_TRANSITIONS: Readonly<Record<string, Readonly<Partial<Record<BranchState, BranchState>>>>> = {
  submit: { OPEN: 'IN_REVIEW' },
  withdraw: { IN_REVIEW: 'OPEN' },
  promote: { IN_REVIEW: 'PROMOTED' },
  reject: { IN_REVIEW: 'REJECTED' },
  archive: { OPEN: 'ARCHIVED' },
};

/** `next_branch_state`. */
export function nextBranchState(current: string, action: string): BranchState {
  const state = enumMember(BRANCH_STATES, 'BranchState', current);
  const known = Object.prototype.hasOwnProperty.call(BRANCH_TRANSITIONS, action);
  const target = known ? BRANCH_TRANSITIONS[action]?.[state] : undefined;
  if (target === undefined) throw new BranchTransitionError(`cannot ${action} a branch in state ${state}`);
  return target;
}

export interface ChangeSet {
  readonly set: Readonly<Record<string, GenomeValue>>;
  readonly unset: readonly string[];
  readonly add_constraints: readonly GenomeConstraint[];
  readonly remove_constraints: readonly string[];
}

function checkDisjoint(cs: ChangeSet): void {
  if (Object.keys(cs.set).some((k) => cs.unset.includes(k))) throw new ModelValueError('a key cannot be both set and unset');
  if (cs.add_constraints.some((c) => cs.remove_constraints.includes(c.constraint_id))) {
    throw new ModelValueError('a constraint cannot be both added and removed');
  }
  if (Object.keys(cs.set).length + cs.unset.length > 400) {
    throw new ModelValueError('a change set touches at most 400 keys');
  }
}

export const changeSetParser: FieldParser<ChangeSet> = model<ChangeSet>(
  {
    set: { parse: dictOf(str(), valueParser), fallback: () => ({}) },
    unset: { parse: listOf(str()), fallback: () => [] },
    add_constraints: { parse: listOf(constraintParser), fallback: () => [] },
    remove_constraints: { parse: listOf(str()), fallback: () => [] },
  },
  { extra: 'forbid', check: checkDisjoint },
);

export function parseChangeSet(input: unknown): ChangeSet {
  return validate('ChangeSet', changeSetParser, input);
}

export function dumpChangeSet(cs: ChangeSet): Record<string, PyData> {
  return {
    set: cs.set as Record<string, PyData>, unset: [...cs.unset], add_constraints: cs.add_constraints.map(dumpConstraint),
    remove_constraints: [...cs.remove_constraints],
  };
}

/** `ChangeSet.changes_hash`. */
export function changesHash(cs: ChangeSet): string {
  return canonicalHashSync(dumpChangeSet(cs));
}

function diffStrings(a: Iterable<string>, b: Iterable<string>): string[] {
  const drop = new Set(b);
  return sortedUnique(Array.from(a).filter((x) => !drop.has(x)));
}

/** `apply_changes`: the branch document is `apply(base, changes)`. */
export function applyChanges(base: GenomeDocument, changes: ChangeSet): GenomeDocument {
  const baseFlat = flatten(base);
  const values = new Map(Array.from(baseFlat).filter(([k]) => !changes.unset.includes(k)));
  const missing = diffStrings(changes.unset, baseFlat.keys());
  if (missing.length > 0) throw new PyValueError(`cannot unset keys the base does not have: ${pyRepr(missing)}`);
  for (const [k, v] of Object.entries(changes.set)) values.set(k, v);
  const known = new Set(base.constraints.map((c) => c.constraint_id));
  const absent = diffStrings(changes.remove_constraints, known);
  if (absent.length > 0) throw new PyValueError(`cannot remove constraints the base does not have: ${pyRepr(absent)}`);
  const adding = changes.add_constraints.map((c) => c.constraint_id);
  const clash = sortedUnique(adding.filter((id) => known.has(id) && !changes.remove_constraints.includes(id)));
  if (clash.length > 0) throw new PyValueError(`constraints already exist in the base: ${pyRepr(clash)}`);
  const kept = base.constraints.filter((c) => !changes.remove_constraints.includes(c.constraint_id));
  return documentFromFlat(values, [...kept, ...changes.add_constraints], base.provenance);
}

/** `compose`: a sub-branch's effective change set relative to the shared base, parent first. */
export function compose(parent: ChangeSet, child: ChangeSet): ChangeSet {
  const values = new Map(Object.entries(parent.set).filter(([k]) => !child.unset.includes(k)));
  for (const [k, v] of Object.entries(child.set)) values.set(k, v);
  const unset = sortedUnique([...parent.unset.filter((k) => !(k in child.set)), ...child.unset]);
  const adds = new Map(parent.add_constraints.filter((c) => !child.remove_constraints.includes(c.constraint_id)).map((c): [string, GenomeConstraint] => [c.constraint_id, c]));
  for (const c of child.add_constraints) adds.set(c.constraint_id, c);
  const parentAdds = new Set(parent.add_constraints.map((c) => c.constraint_id));
  const removes = sortedUnique([...parent.remove_constraints.filter((k) => !adds.has(k)), ...child.remove_constraints.filter((k) => !parentAdds.has(k))]);
  return parseChangeSet({
    set: Object.fromEntries(values), unset: unset.filter((k) => !values.has(k)), add_constraints: Array.from(adds.values()).map(dumpConstraint),
    remove_constraints: removes,
  });
}

interface Violation {
  kind: string;
  key: string;
  constraint_id: string | null;
  detail: string;
}

function invariantViolations(base: GenomeDocument, changes: ChangeSet): Violation[] {
  const out: Violation[] = [];
  const immutable = new Map(base.constraints.filter((c) => c.kind === 'IMMUTABLE').map((c): [string, GenomeConstraint] => [c.constraint_id, c]));
  for (const id of sortedStrings(changes.remove_constraints.filter((x) => immutable.has(x)))) {
    out.push({ kind: 'INVARIANT_REMOVED', key: (immutable.get(id) as GenomeConstraint).key, constraint_id: id, detail: 'removes an approved immutable constraint' });
  }
  const flat = flatten(base);
  for (const c of immutable.values()) {
    if (c.key in changes.set && !pyEq(flat.get(c.key) ?? null, changes.set[c.key])) {
      out.push({ kind: 'INVARIANT_CHANGED', key: c.key, constraint_id: c.constraint_id, detail: 'changes a value the approved version declares immutable' });
    }
    if (changes.unset.includes(c.key)) {
      out.push({ kind: 'INVARIANT_CHANGED', key: c.key, constraint_id: c.constraint_id, detail: 'unsets a value the approved version declares immutable' });
    }
  }
  return out;
}

function dumpFinding(f: ConstraintFinding): Record<string, PyData> {
  return { ...f };
}

/** `compare_with_base`: what a branch changes relative to its base, and which approved invariants it would break. */
export function compareWithBase(
  base: GenomeDocument, changes: ChangeSet, ancestors: readonly GenomeLayer[], scopeRef: string, scope: string,
): Record<string, PyData> {
  const branchDoc = applyChanges(base, changes);
  const diff = diffDocuments(base, branchDoc);
  const layer = parseLayer({ scope, scope_ref: scopeRef, status: 'DRAFT', document: branchDoc });
  const resolution = resolve([...ancestors, layer], scopeRef);
  const violations: Violation[] = resolution.conflicts
    .filter((c) => c.scope_ref === scopeRef && c.reason !== 'UNAPPROVED_OVERRIDE')
    .map((c) => ({ kind: c.reason, key: c.key, constraint_id: c.constraint_id, detail: c.detail }));
  violations.push(...invariantViolations(base, changes));
  const inherited = resolution.constraints.filter((c) => resolution.constraint_owner[c.constraint_id] !== scopeRef).map((c) => c.constraint_id);
  const failed = resolution.findings.filter((f) => !f.passed).map(dumpFinding);
  const baseIds = base.constraints.map((c) => c.constraint_id);
  const dumpChange = (c: { key: string; before: GenomeValue; after: GenomeValue }): Record<string, PyData> => ({ ...c }) as Record<string, PyData>;
  return {
    branch_document_hash: documentHash(branchDoc), base_document_hash: documentHash(base),
    values: {
      added: diff.added.map(dumpChange), removed: diff.removed.map(dumpChange), modified: diff.modified.map(dumpChange), unchanged: [...diff.unchanged],
    },
    constraints: {
      added: [...diff.constraints_added], removed: [...diff.constraints_removed], modified: [...diff.constraints_modified],
      unchanged_own: diffStrings(baseIds, [...diff.constraints_removed, ...diff.constraints_modified]), unchanged_inherited: sortedStrings(inherited),
    },
    invariant_violations: violations as unknown as PyData[], failed_findings: failed, resolution_hash: resolutionHash(resolution),
    promotable: violations.length === 0 && !failed.some((f) => f['severity'] === 'BLOCKING'),
  };
}

type Effect = readonly ['SET', GenomeValue] | readonly ['UNSET', null];

function effectOf(cs: ChangeSet): Map<string, Effect> {
  const out = new Map<string, Effect>(Object.entries(cs.set).map(([k, v]): [string, Effect] => [k, ['SET', v]]));
  for (const k of cs.unset) out.set(k, ['UNSET', null]);
  return out;
}

function constraintById(cs: ChangeSet): Map<string, GenomeConstraint> {
  return new Map(cs.add_constraints.map((c): [string, GenomeConstraint] => [c.constraint_id, c]));
}

function effectsEqual(a: Effect, b: Effect): boolean {
  return a[0] === b[0] && pyEq(a[1], b[1]);
}

/** `compare_branches`: two branches from the same base. */
export function compareBranches(a: ChangeSet, b: ChangeSet): Record<string, PyData> {
  const ea = effectOf(a);
  const eb = effectOf(b);
  const keys = sortedUnique([...ea.keys(), ...eb.keys()]);
  const both = keys.filter((k) => ea.has(k) && eb.has(k));
  const conflicts = both.filter((k) => !effectsEqual(ea.get(k) as Effect, eb.get(k) as Effect))
    .map((k) => ({ key: k, a: [...(ea.get(k) as Effect)], b: [...(eb.get(k) as Effect)] }));
  const ca = constraintById(a);
  const cb = constraintById(b);
  const constraintConflicts = sortedStrings(Array.from(ca.keys()).filter((k) => cb.has(k) && !constraintEquals(ca.get(k) as GenomeConstraint, cb.get(k) as GenomeConstraint)));
  const cross = new Set([...a.remove_constraints.filter((k) => cb.has(k)), ...b.remove_constraints.filter((k) => ca.has(k))]);
  constraintConflicts.push(...sortedStrings(cross));
  return {
    only_a: keys.filter((k) => ea.has(k) && !eb.has(k)), only_b: keys.filter((k) => eb.has(k) && !ea.has(k)),
    agree: both.filter((k) => effectsEqual(ea.get(k) as Effect, eb.get(k) as Effect)), conflicts: conflicts as unknown as PyData[],
    constraint_conflicts: constraintConflicts, mergeable: conflicts.length === 0 && constraintConflicts.length === 0,
  };
}

/** `merge_change_sets`: deterministic; `[null, report]` when anything conflicts, never picks a side. */
export function mergeChangeSets(a: ChangeSet, b: ChangeSet): [ChangeSet | null, Record<string, PyData>] {
  const report = compareBranches(a, b);
  if (report['mergeable'] !== true) return [null, report];
  const adds = new Map([...a.add_constraints, ...b.add_constraints].map((c): [string, GenomeConstraint] => [c.constraint_id, c]));
  const merged = parseChangeSet({
    set: { ...a.set, ...b.set }, unset: sortedUnique([...a.unset, ...b.unset]),
    add_constraints: sortedStrings(adds.keys()).map((k) => dumpConstraint(adds.get(k) as GenomeConstraint)),
    remove_constraints: sortedUnique([...a.remove_constraints, ...b.remove_constraints]),
  });
  return [merged, report];
}

/**
 * `rebase`: carry a change set onto a newer approved base. On an apply failure the
 * report's conflict text is this twin's message (Python embeds `str(exc)`, which for a
 * Pydantic ValidationError is Pydantic's own multi-line rendering).
 */
export function rebase(oldBase: GenomeDocument, newBase: GenomeDocument, changes: ChangeSet): [ChangeSet | null, Record<string, PyData>] {
  const diff = diffDocuments(oldBase, newBase);
  const touched = new Set([...diff.added, ...diff.removed, ...diff.modified].map((c) => c.key));
  const branchTouched = new Set([...Object.keys(changes.set), ...changes.unset]);
  const conflicts = sortedStrings(Array.from(touched).filter((k) => branchTouched.has(k)));
  const changedConstraints = new Set([...diff.constraints_added, ...diff.constraints_removed, ...diff.constraints_modified]);
  const own = new Set([...changes.add_constraints.map((c) => c.constraint_id), ...changes.remove_constraints]);
  const constraintConflicts = sortedStrings(Array.from(changedConstraints).filter((k) => own.has(k)));
  const report: Record<string, PyData> = { base_changed_keys: sortedStrings(touched), conflicts, constraint_conflicts: constraintConflicts };
  if (conflicts.length > 0 || constraintConflicts.length > 0) return [null, report];
  try {
    applyChanges(newBase, changes);
  } catch (error) {
    if (!(error instanceof PyValueError)) throw error;
    report['conflicts'] = [error.message];
    return [null, report];
  }
  return [changes, report];
}

export { compareCodePoints, dumpDocument };
