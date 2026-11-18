/**
 * VNEXUS temporal creative knowledge graph: twin of `vnexus/graph.py`.
 *
 * Typed nodes and edges with validity windows; every edge kind declares the
 * node kinds it may connect; lineage edges stay acyclic among edges valid at
 * the same instant; superseding closes a validity window, it never deletes;
 * `as_of` reads see only what was valid at that instant.
 */
import { compareCodePoints } from '@amc/kernel';
import { GraphError } from './errors';
import { anyData, dictOf, enumOf, model, optional, str, validate, type FieldParser } from './model';
import { canonicalHashSync, sortedStrings, type PyData } from './python';

export { GraphError };

export const NODE_KINDS = [
  'Brand', 'GenomeVersion', 'Campaign', 'Audience', 'Insight', 'DesignDecision', 'CreativeConcept', 'Asset', 'Prompt', 'Experiment',
  'Experience', 'Channel', 'ProviderJob', 'Approval', 'Evidence', 'Branch',
] as const;
export type NodeKind = (typeof NODE_KINDS)[number];

export const EDGE_KINDS = [
  'DERIVED_FROM', 'APPROVED_BY', 'DEPENDS_ON', 'SUPERSEDES', 'IMPLEMENTS', 'GENERATED_BY', 'TESTED_BY', 'TARGETS', 'CONFLICTS_WITH',
  'SUPPORTED_BY',
] as const;
export type EdgeKind = (typeof EDGE_KINDS)[number];

type KindSet = ReadonlySet<NodeKind>;
const kinds = (...items: NodeKind[]): KindSet => new Set(items);
const ANY: KindSet = new Set(NODE_KINDS);
const without = (base: KindSet, ...drop: NodeKind[]): KindSet => new Set(Array.from(base).filter((k) => !drop.includes(k)));
const PRODUCTS = kinds('Asset', 'Experience', 'CreativeConcept', 'Campaign', 'Prompt');
const plus = (base: KindSet, ...add: NodeKind[]): KindSet => new Set([...base, ...add]);

/** edge kind -> [allowed source kinds, allowed destination kinds] */
export const EDGE_RULES: Readonly<Record<EdgeKind, readonly [KindSet, KindSet]>> = {
  DERIVED_FROM: [without(ANY, 'Approval', 'Evidence'), without(ANY, 'Approval')],
  APPROVED_BY: [without(ANY, 'Approval', 'Evidence'), kinds('Approval')],
  DEPENDS_ON: [without(ANY, 'Approval'), without(ANY, 'Approval')],
  SUPERSEDES: [ANY, ANY],
  IMPLEMENTS: [plus(PRODUCTS, 'GenomeVersion'), kinds('DesignDecision', 'CreativeConcept', 'Campaign', 'Insight')],
  GENERATED_BY: [kinds('Asset', 'Experience'), kinds('ProviderJob', 'Prompt')],
  TESTED_BY: [plus(PRODUCTS, 'DesignDecision', 'Insight'), kinds('Experiment')],
  TARGETS: [plus(PRODUCTS, 'Experiment'), kinds('Audience', 'Channel')],
  CONFLICTS_WITH: [without(ANY, 'Approval', 'Evidence'), without(ANY, 'Approval', 'Evidence')],
  SUPPORTED_BY: [without(ANY, 'Evidence'), kinds('Evidence')],
};

export const ACYCLIC: ReadonlySet<EdgeKind> = new Set<EdgeKind>(['DERIVED_FROM', 'DEPENDS_ON', 'SUPERSEDES', 'IMPLEMENTS', 'GENERATED_BY']);
/** Edges whose source is affected when their destination changes. */
export const IMPACT_EDGES: ReadonlySet<EdgeKind> = new Set<EdgeKind>(['DERIVED_FROM', 'DEPENDS_ON', 'IMPLEMENTS', 'GENERATED_BY', 'TESTED_BY']);

export interface Node {
  readonly node_id: string;
  readonly kind: NodeKind;
  readonly label: string;
  readonly attributes: Readonly<Record<string, PyData>>;
  readonly content_hash: string;
  readonly valid_from: string;
  readonly valid_to: string | null;
  readonly superseded_by: string | null;
}

export interface Edge {
  readonly edge_id: string;
  readonly kind: EdgeKind;
  readonly src_node_id: string;
  readonly dst_node_id: string;
  readonly provenance: Readonly<Record<string, PyData>>;
  readonly valid_from: string;
  readonly valid_to: string | null;
}

export const nodeParser: FieldParser<Node> = model<Node>(
  {
    node_id: { parse: str() },
    kind: { parse: enumOf(NODE_KINDS) },
    label: { parse: str() },
    attributes: { parse: dictOf(str(), anyData()), fallback: () => ({}) },
    content_hash: { parse: str(), fallback: () => '' },
    valid_from: { parse: str() },
    valid_to: { parse: optional(str()), fallback: () => null },
    superseded_by: { parse: optional(str()), fallback: () => null },
  },
  { extra: 'ignore' },
);

export const edgeParser: FieldParser<Edge> = model<Edge>(
  {
    edge_id: { parse: str() },
    kind: { parse: enumOf(EDGE_KINDS) },
    src_node_id: { parse: str() },
    dst_node_id: { parse: str() },
    provenance: { parse: dictOf(str(), anyData()), fallback: () => ({}) },
    valid_from: { parse: str() },
    valid_to: { parse: optional(str()), fallback: () => null },
  },
  { extra: 'ignore' },
);

export function parseNode(input: unknown): Node {
  return validate('Node', nodeParser, input);
}

export function parseEdge(input: unknown): Edge {
  return validate('Edge', edgeParser, input);
}

/** `node_hash`. */
export function nodeHash(kind: NodeKind, label: string, attributes: Readonly<Record<string, PyData>>): string {
  return canonicalHashSync({ kind, label, attributes: attributes as Record<string, PyData> });
}

/** `valid_at`: string timestamps compare by code point, as Python compares `str`. */
export function validAt(record: Node | Edge, asOf: string | null): boolean {
  if (asOf === null) return record.valid_to === null;
  const started = compareCodePoints(record.valid_from, asOf) <= 0;
  return started && (record.valid_to === null || compareCodePoints(asOf, record.valid_to) < 0);
}

export interface Snapshot {
  readonly as_of: string | null;
  readonly nodes: Readonly<Record<string, string>>;
  readonly edges: readonly string[];
  readonly snapshot_hash: string;
}

export interface Impact {
  readonly changed: readonly string[];
  readonly affected: ReadonlyArray<{ node_id: string; kind: NodeKind; label: string; path: string[] }>;
}

export interface EvidenceItem {
  readonly via: string;
  readonly node_id: string;
  readonly label: string;
  readonly attributes: Readonly<Record<string, PyData>>;
  readonly edge_provenance: Readonly<Record<string, PyData>>;
}

function byEdgeId(a: Edge, b: Edge): number {
  return compareCodePoints(a.edge_id, b.edge_id);
}

/** An in-memory view of one brand's graph at one instant. */
export class Graph {
  readonly as_of: string | null;
  readonly all_nodes: Map<string, Node>;
  readonly nodes: Map<string, Node>;
  readonly all_edges: Edge[];
  readonly edges: Edge[];

  constructor(nodes: Iterable<Node>, edges: Iterable<Edge>, asOf: string | null = null) {
    this.as_of = asOf;
    this.all_nodes = new Map(Array.from(nodes, (n): [string, Node] => [n.node_id, n]));
    this.nodes = new Map(Array.from(this.all_nodes).filter(([, n]) => validAt(n, asOf)));
    this.all_edges = Array.from(edges).filter((e) => validAt(e, asOf) && this.all_nodes.has(e.src_node_id) && this.all_nodes.has(e.dst_node_id));
    this.edges = this.all_edges.filter((e) => this.nodes.has(e.src_node_id) && this.nodes.has(e.dst_node_id));
  }

  checkEdge(kind: EdgeKind, src: string, dst: string): void {
    if (src === dst) throw new GraphError('an edge cannot connect a node to itself');
    const a = this.nodes.get(src);
    const b = this.nodes.get(dst);
    if (a === undefined || b === undefined) throw new GraphError('both endpoints must exist and be currently valid');
    const [sources, targets] = EDGE_RULES[kind];
    if (!sources.has(a.kind) || !targets.has(b.kind)) throw new GraphError(`${kind} may not connect ${a.kind} -> ${b.kind}`);
    if (kind === 'SUPERSEDES' && a.kind !== b.kind) throw new GraphError('SUPERSEDES connects two nodes of the same kind');
    if (this.edges.some((e) => e.kind === kind && e.src_node_id === src && e.dst_node_id === dst)) {
      throw new GraphError(`${kind} ${src} -> ${dst} already exists`);
    }
    if (ACYCLIC.has(kind) && this.reaches(dst, src, ACYCLIC)) throw new GraphError(`${kind} ${src} -> ${dst} would create a lineage cycle`);
  }

  reaches(start: string, goal: string, allowed: ReadonlySet<EdgeKind>): boolean {
    const seen = new Set([start]);
    const queue = [start];
    for (let head = 0; head < queue.length; head += 1) {
      const cur = queue[head] as string;
      if (cur === goal) return true;
      for (const e of this.edges) {
        if (allowed.has(e.kind) && e.src_node_id === cur && !seen.has(e.dst_node_id)) {
          seen.add(e.dst_node_id);
          queue.push(e.dst_node_id);
        }
      }
    }
    return false;
  }

  /** Lineage cycles in the stored data (should be none; detects rows written around the API). */
  findCycles(): string[][] {
    const adj = new Map<string, string[]>();
    for (const e of this.edges) if (ACYCLIC.has(e.kind)) adj.set(e.src_node_id, [...(adj.get(e.src_node_id) ?? []), e.dst_node_id]);
    const cycles: string[][] = [];
    const state = new Map<string, number>();
    const stack: string[] = [];
    const visit = (n: string): void => {
      state.set(n, 1);
      stack.push(n);
      for (const m of sortedStrings(adj.get(n) ?? [])) {
        if (state.get(m) === 1) cycles.push([...stack.slice(stack.indexOf(m)), m]);
        else if (!state.has(m)) visit(m);
      }
      stack.pop();
      state.set(n, 2);
    };
    for (const n of sortedStrings(adj.keys())) if (!state.has(n)) visit(n);
    return cycles;
  }

  upstream(nodeId: string, allowed: ReadonlySet<EdgeKind> = IMPACT_EDGES): string[] {
    const out: string[] = [];
    const seen = new Set([nodeId]);
    const queue = [nodeId];
    const ordered = [...this.edges].sort(byEdgeId);
    for (let head = 0; head < queue.length; head += 1) {
      for (const e of ordered) {
        if (allowed.has(e.kind) && e.src_node_id === queue[head] && !seen.has(e.dst_node_id)) {
          seen.add(e.dst_node_id);
          out.push(e.dst_node_id);
          queue.push(e.dst_node_id);
        }
      }
    }
    return out;
  }

  /** Everything downstream of the changed nodes, with the shortest dependency path to each. */
  impact(changed: Iterable<string>): Impact {
    const start = Array.from(changed).filter((c) => this.nodes.has(c));
    const paths = new Map<string, string[]>(start.map((c): [string, string[]] => [c, [c]]));
    const queue = [...start];
    const ordered = [...this.edges].sort(byEdgeId);
    for (let head = 0; head < queue.length; head += 1) {
      const cur = queue[head] as string;
      for (const e of ordered) {
        if (IMPACT_EDGES.has(e.kind) && e.dst_node_id === cur && !paths.has(e.src_node_id)) {
          paths.set(e.src_node_id, [...(paths.get(cur) as string[]), `<-${e.kind}-`, e.src_node_id]);
          queue.push(e.src_node_id);
        }
      }
    }
    const length = (n: string): number => (paths.get(n) as string[]).length;
    const affected = Array.from(paths.keys()).filter((n) => !start.includes(n))
      .sort((a, b) => length(a) - length(b) || compareCodePoints(a, b));
    return {
      changed: sortedStrings(start),
      affected: affected.map((n) => {
        const node = this.nodes.get(n) as Node;
        return { node_id: n, kind: node.kind, label: node.label, path: paths.get(n) as string[] };
      }),
    };
  }

  /** Evidence and approvals supporting a node, directly or through what it implements or derives from. */
  evidenceFor(nodeId: string): { node_id: string; considered: string[]; evidence: EvidenceItem[]; approvals: EvidenceItem[]; unsupported: boolean } {
    if (!this.nodes.has(nodeId)) throw new GraphError(`node ${nodeId} is not valid at this instant`);
    const chain = [nodeId, ...this.upstream(nodeId, new Set<EdgeKind>(['IMPLEMENTS', 'DERIVED_FROM']))];
    const evidence: EvidenceItem[] = [];
    const approvals: EvidenceItem[] = [];
    for (const n of chain) {
      for (const e of this.edges.filter((edge) => edge.src_node_id === n)) {
        const target = this.nodes.get(e.dst_node_id) as Node;
        const item: EvidenceItem = { via: n, node_id: target.node_id, label: target.label, attributes: target.attributes, edge_provenance: e.provenance };
        if (e.kind === 'SUPPORTED_BY') evidence.push(item);
        else if (e.kind === 'APPROVED_BY') approvals.push(item);
      }
    }
    return { node_id: nodeId, considered: chain, evidence, approvals, unsupported: evidence.length === 0 && approvals.length === 0 };
  }

  /**
   * The supersession chain through `nodeId`, oldest first. Python loops forever on a
   * supersession cycle; this twin refuses it with a `GraphError` instead.
   */
  history(nodeId: string): string[] {
    const older = new Map<string, string>();
    for (const n of this.all_nodes.values()) if (n.superseded_by) older.set(n.superseded_by, n.node_id);
    let first = nodeId;
    const seen = new Set([first]);
    while (older.has(first)) {
      first = older.get(first) as string;
      if (seen.has(first)) throw new GraphError('supersession cycle');
      seen.add(first);
    }
    const chain = [first];
    for (let next = this.all_nodes.get(first)?.superseded_by; next; next = this.all_nodes.get(next)?.superseded_by) {
      if (chain.includes(next)) throw new GraphError('supersession cycle');
      chain.push(next);
    }
    return chain;
  }

  snapshot(): Snapshot {
    const nodes: Record<string, string> = {};
    for (const n of this.nodes.values()) nodes[n.node_id] = n.content_hash;
    const edges = sortedStrings(this.edges.map((e) => `${e.src_node_id}|${e.kind}|${e.dst_node_id}`));
    const sorted = Object.fromEntries(Object.entries(nodes).sort(([a], [b]) => compareCodePoints(a, b)));
    return { as_of: this.as_of, nodes: sorted, edges, snapshot_hash: canonicalHashSync({ nodes, edges }) };
  }
}

function minus(a: Iterable<string>, b: ReadonlySet<string>): string[] {
  return sortedStrings(Array.from(a).filter((x) => !b.has(x)));
}

/** `diff_snapshots`. */
export function diffSnapshots(a: Snapshot, b: Snapshot): Record<string, PyData> {
  const na = new Set(Object.keys(a.nodes));
  const nb = new Set(Object.keys(b.nodes));
  const ea = new Set(a.edges);
  const eb = new Set(b.edges);
  return {
    from: a.as_of, to: b.as_of, nodes_added: minus(nb, na), nodes_removed: minus(na, nb),
    nodes_changed: sortedStrings(Array.from(na).filter((k) => nb.has(k) && a.nodes[k] !== b.nodes[k])),
    edges_added: minus(eb, ea), edges_removed: minus(ea, eb), identical: a.snapshot_hash === b.snapshot_hash,
  };
}
