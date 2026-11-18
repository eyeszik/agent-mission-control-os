/**
 * Twin of `agency/compiled/decisions.py` (T15): the DecisionSpine of
 * versioned material decisions. Accepted versions are immutable; a revision
 * appends a new version that supersedes the old hash and names the CWG
 * descendants it makes stale.
 */
import { pyRepr, type PyFloat } from '@amc/kernel';
import { DECISION_KINDS, type CausalWorkGraph, type DecisionKind } from './backchain';
import { CompiledAttributeError, DecisionError } from './errors';
import { semanticHash, type HashValue } from './hashing';
import { compareTuples, sortStrings } from './python';

export const DECISION_STATUSES = [
  'PROPOSED', 'AWAITING_EVIDENCE', 'AWAITING_APPROVAL', 'ACCEPTED', 'REJECTED', 'SUPERSEDED', 'INVALIDATED',
] as const;
export type DecisionStatus = (typeof DECISION_STATUSES)[number];

export interface DecisionNode {
  readonly id: string;
  readonly kind: DecisionKind;
  readonly version: number;
  readonly question: string;
  readonly alternatives: readonly string[];
  readonly evidence_refs: readonly string[];
  readonly assumptions: readonly string[];
  readonly selected_option: string | null;
  readonly owner: string;
  readonly required_approver: string | null;
  readonly approved_by: string | null;
  readonly affected_nodes: readonly string[];
  readonly status: DecisionStatus;
  readonly confidence: PyFloat | null;
  readonly supersedes: string | null;
  readonly created_at: string | null;
}

/** `created_at` is provenance, not semantics. */
export function decisionHash(node: DecisionNode): string {
  return semanticHash(node as unknown as HashValue, ['created_at']);
}

export interface DecisionDiff {
  readonly kind: DecisionKind;
  readonly old_hash: string;
  readonly new_hash: string;
  readonly changed_fields: readonly string[];
  readonly stale_nodes: readonly string[];
}

/** Fields a revision may change (`id`, `kind`, `version`, `supersedes`, `status`, `approved_by` are refused). */
export type DecisionChanges = { readonly [K in keyof DecisionNode]?: DecisionNode[K] };

export const DECISION_FIELDS = [
  'id', 'kind', 'version', 'question', 'alternatives', 'evidence_refs', 'assumptions', 'selected_option', 'owner',
  'required_approver', 'approved_by', 'affected_nodes', 'status', 'confidence', 'supersedes', 'created_at',
];

const FORBIDDEN_REVISION_FIELDS = ['id', 'kind', 'version', 'supersedes', 'status', 'approved_by'];

function sameValue(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

export class DecisionSpine {
  private readonly log: DecisionNode[] = [];
  private readonly superseded = new Set<string>();

  constructor(versions: Iterable<DecisionNode> = []) {
    for (const v of versions) this.append(v);
  }

  private append(node: DecisionNode): DecisionNode {
    if (node.supersedes) this.superseded.add(node.supersedes);
    this.log.push(node);
    return node;
  }

  get versions(): readonly DecisionNode[] {
    return [...this.log];
  }

  current(kind: DecisionKind): DecisionNode | null {
    const live = this.log.filter((v) => v.kind === kind && !this.superseded.has(decisionHash(v)));
    return live[live.length - 1] ?? null;
  }

  effectiveStatus(node: DecisionNode): DecisionStatus {
    return this.superseded.has(decisionHash(node)) ? 'SUPERSEDED' : node.status;
  }

  propose(node: DecisionNode): DecisionNode {
    if (node.status !== 'PROPOSED') throw new DecisionError('new decisions enter the spine as PROPOSED');
    if (this.current(node.kind) !== null) throw new DecisionError(`${node.kind} already has a live version; use revise()`);
    return this.append(node);
  }

  private live(kind: DecisionKind): DecisionNode {
    const current = this.current(kind);
    if (current === null) throw new DecisionError(`no live ${kind} decision`);
    return current;
  }

  accept(kind: DecisionKind, selectedOption: string, approverRef: string): DecisionNode {
    const current = this.live(kind);
    if (current.status === 'ACCEPTED') throw new DecisionError('accepted decision versions are immutable; use revise()');
    if (!current.alternatives.includes(selectedOption)) {
      throw new DecisionError('selected option must be one of the declared alternatives');
    }
    if (!approverRef || approverRef === current.owner) {
      throw new DecisionError('acceptance needs an approver distinct from the decision owner');
    }
    if (current.required_approver && approverRef !== current.required_approver) {
      throw new DecisionError('approver does not match the required approver');
    }
    return this.append({
      ...current, status: 'ACCEPTED', selected_option: selectedOption, approved_by: approverRef,
      version: current.version + 1, supersedes: decisionHash(current),
    });
  }

  /** New version → supersedes → causal invalidation of CWG descendants. */
  revise(kind: DecisionKind, graph: CausalWorkGraph, changes: DecisionChanges): [DecisionNode, DecisionDiff] {
    const current = this.live(kind);
    const forbidden = sortStrings(Object.keys(changes).filter((k) => FORBIDDEN_REVISION_FIELDS.includes(k)));
    if (forbidden.length) throw new DecisionError(`cannot set [${forbidden.map(pyRepr).join(', ')}] on a revision`);
    const revised: DecisionNode = {
      ...current, ...changes, version: current.version + 1, supersedes: decisionHash(current), status: 'PROPOSED',
      approved_by: null,
    };
    for (const k of Object.keys(changes)) {
      if (!DECISION_FIELDS.includes(k)) throw new CompiledAttributeError(`'DecisionNode' object has no attribute '${k}'`);
    }
    const changed = sortStrings(Object.keys(changes).filter(
      (k) => !sameValue(current[k as keyof DecisionNode], revised[k as keyof DecisionNode]),
    ));
    const stale = sortStrings(graph.descendants([`decision:${kind}`]));
    this.append(revised);
    return [revised, {
      kind, old_hash: decisionHash(current), new_hash: decisionHash(revised), changed_fields: changed, stale_nodes: stale,
    }];
  }

  acceptedByKind(): Map<string, string> {
    const out = new Map<string, string>();
    for (const kind of DECISION_KINDS) {
      const node = this.current(kind);
      if (node !== null && node.status === 'ACCEPTED') out.set(kind, decisionHash(node));
    }
    return out;
  }
}

/** Unresolved decisions ranked by the downstream topology they could reshape. */
export function uncertaintyPriority(graph: CausalWorkGraph): [string, number][] {
  const pending = [...graph.nodes.values()]
    .filter((n) => n.id.startsWith('decision:') && n.status === 'AWAITING_HUMAN').map((n) => n.id);
  return pending.map((d): [string, number] => [d, graph.descendants([d]).size])
    .sort((a, b) => compareTuples([-a[1], a[0]], [-b[1], b[0]]));
}
