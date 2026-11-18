/**
 * Twin of `agency/compiled/execution.py` (T16/T17): MissionCells and the
 * execution-wave scheduler. Planning-time only: nothing here runs a node.
 * Independent PURE/DRAFT work runs in parallel; mutation collisions,
 * exclusive resources and consequential external actions are serialized;
 * anything gated on a human decision, missing evidence or authority is held
 * out with explicit reasons.
 */
import { pyRepr } from '@amc/kernel';
import type { BackchainNode, CausalWorkGraph } from './backchain';
import { CellTransitionError } from './errors';
import { semanticHash, type HashValue } from './hashing';
import { afterFirst, compareTuples, sortStrings, uniqueSorted } from './python';

export const CELL_STATUSES = [
  'FORMED', 'READY', 'EXECUTING', 'VALIDATING', 'ACCEPTED', 'BLOCKED', 'REVISION', 'ESCALATED', 'DISSOLVED',
] as const;
export type CellStatus = (typeof CELL_STATUSES)[number];

export const CELL_TRANSITIONS: Readonly<Record<CellStatus, readonly CellStatus[]>> = {
  FORMED: ['READY', 'BLOCKED'],
  READY: ['EXECUTING', 'BLOCKED'],
  EXECUTING: ['VALIDATING', 'BLOCKED', 'ESCALATED'],
  VALIDATING: ['ACCEPTED', 'BLOCKED', 'REVISION', 'ESCALATED'],
  REVISION: ['EXECUTING', 'ESCALATED'],
  BLOCKED: ['READY', 'ESCALATED', 'DISSOLVED'],
  ESCALATED: ['READY', 'DISSOLVED'],
  ACCEPTED: ['DISSOLVED'],
  DISSOLVED: [],
};

export interface MissionCell {
  readonly cell_id: string;
  readonly objective: string;
  readonly node_refs: readonly string[];
  readonly accountable_specialist: string | null;
  readonly contributor_specialists: readonly string[];
  readonly runtime_authority_binding: string;
  readonly work_order_refs: readonly string[];
  readonly context_capsule_ref: string | null;
  readonly input_refs: readonly (readonly [string, string])[];
  readonly output_contracts: readonly string[];
  readonly validators: readonly string[];
  readonly mutation_targets: readonly string[];
  readonly resource_locks: readonly string[];
  readonly risk_class: string;
  readonly side_effect_class: string;
  readonly approval_refs: readonly string[];
  readonly status: CellStatus;
  readonly blockers: readonly string[];
}

/** `cell_hash`: every field except the (mutable) status. */
export function cellHash(cell: MissionCell): string {
  return semanticHash(cell as unknown as HashValue, ['status']);
}

export function advanceCell(cell: MissionCell, to: CellStatus): MissionCell {
  if (!CELL_TRANSITIONS[cell.status].includes(to)) {
    throw new CellTransitionError(`${cell.cell_id}: ${cell.status} -> ${to} is not permitted`);
  }
  if (to === 'READY' && cell.blockers.length) {
    throw new CellTransitionError(`${cell.cell_id}: cannot become READY with blockers [${cell.blockers.map(pyRepr).join(', ')}]`);
  }
  return { ...cell, status: to };
}

export interface Wave {
  readonly index: number;
  readonly cells: readonly string[];
  readonly serialized_reason: string | null;
}

export interface WavePlan {
  readonly waves: readonly Wave[];
  readonly held: ReadonlyMap<string, readonly string[]>;
  readonly wave_hash: string;
}

const WORK_TYPES: ReadonlySet<string> = new Set(['EXECUTABLE_WORK', 'EXTERNAL_ACTION']);

/** Longest downstream path length to any root (higher = more critical). */
function criticalPath(graph: CausalWorkGraph): Map<string, number> {
  const forward = graph.dependents();
  const memo = new Map<string, number>();
  for (const nid of [...graph.topological_order].reverse()) {
    const next = [...(forward.get(nid) ?? [])].map((d) => memo.get(d) ?? 0);
    memo.set(nid, 1 + Math.max(0, ...next));
  }
  return memo;
}

/** Earlier lifecycle stages reduce more uncertainty downstream. */
function informationGain(stage: string | null): number {
  return stage ? 30 - Number(stage.slice(1)) : 0;
}

function gatesFor(
  graph: CausalWorkGraph, cell: MissionCell, cellForNode: ReadonlyMap<string, string>, held: ReadonlyMap<string, readonly string[]>,
): Set<string> {
  const reasons = new Set<string>();
  for (const anc of graph.ancestors(cell.node_refs[0] ?? '')) {
    const node = graph.node(anc);
    const upstream = cellForNode.get(anc);
    if (node.type === 'MATERIAL_DECISION' && node.status === 'AWAITING_HUMAN') reasons.add(`WAIT_HUMAN_DECISION:${anc}`);
    else if (node.status === 'BLOCKED') reasons.add(`UPSTREAM_BLOCKED:${anc}`);
    else if (WORK_TYPES.has(node.type) && upstream !== undefined && held.has(upstream)) reasons.add(`UPSTREAM_HELD:${upstream}`);
  }
  return reasons;
}

/** Hold anything downstream of a held cell or of a non-work gate, to a fixed point. */
function holdGated(
  graph: CausalWorkGraph, cells: ReadonlyMap<string, MissionCell>, cellForNode: ReadonlyMap<string, string>,
): Map<string, string[]> {
  const held = new Map<string, string[]>();
  for (const c of cells.values()) if (c.blockers.length) held.set(c.cell_id, [...c.blockers]);
  const ordered = [...cells.values()].sort((a, b) => compareTuples([a.cell_id], [b.cell_id]));
  for (let changed = true; changed;) {
    changed = false;
    for (const cell of ordered) {
      if (held.has(cell.cell_id)) continue;
      const reasons = gatesFor(graph, cell, cellForNode, held);
      if (reasons.size) {
        held.set(cell.cell_id, sortStrings(reasons));
        changed = true;
      }
    }
  }
  return held;
}

function cellDepths(
  graph: CausalWorkGraph, runnable: ReadonlyMap<string, MissionCell>, cellForNode: ReadonlyMap<string, string>,
): Map<string, number> {
  const depth = new Map<string, number>();
  for (const nid of graph.topological_order) {
    const cid = cellForNode.get(nid);
    if (cid === undefined || !runnable.has(cid) || !WORK_TYPES.has(graph.node(nid).type)) continue;
    const upstream: string[] = [];
    for (const a of graph.ancestors(nid)) {
      const ac = cellForNode.get(a);
      if (ac !== undefined && runnable.has(ac) && ac !== cid && WORK_TYPES.has(graph.node(a).type)) upstream.push(ac);
    }
    depth.set(cid, 1 + Math.max(-1, ...upstream.map((u) => depth.get(u) ?? 0)));
  }
  return depth;
}

function layerWaves(
  level: readonly string[], runnable: ReadonlyMap<string, MissionCell>, waves: Wave[],
): void {
  const buckets: string[][] = [[]];
  const serial: string[] = [];
  for (const cid of level) {
    const cell = runnable.get(cid) as MissionCell;
    if (cell.side_effect_class !== 'PURE' && cell.side_effect_class !== 'DRAFT') {
      serial.push(cid);
      continue;
    }
    const target = buckets.find((bucket) => {
      const locks = new Set(bucket.flatMap((o) => runnable.get(o)?.resource_locks ?? []));
      return !cell.resource_locks.some((l) => locks.has(l));
    });
    if (target) target.push(cid);
    else buckets.push([cid]);
  }
  buckets.filter((b) => b.length).forEach((bucket, i) => {
    waves.push({ index: waves.length, cells: bucket, serialized_reason: i ? 'RESOURCE_OR_MUTATION_COLLISION' : null });
  });
  for (const cid of serial) waves.push({ index: waves.length, cells: [cid], serialized_reason: 'CONSEQUENTIAL_EXTERNAL_ACTION' });
}

function sortedHeld(held: ReadonlyMap<string, readonly string[]>): Map<string, readonly string[]> {
  return new Map(sortStrings(held.keys()).map((k) => [k, held.get(k) ?? []]));
}

/** Python's `WavePlan` hash body: waves as dumped, held as lists, sorted by cell id. */
export function waveHash(waves: readonly Wave[], held: ReadonlyMap<string, readonly string[]>): string {
  const heldBody: Record<string, HashValue> = {};
  for (const [k, v] of sortedHeld(held)) heldBody[k] = [...v];
  return semanticHash({ waves: waves as unknown as HashValue, held: heldBody });
}

/** `schedule_waves`: layer READY cells into waves; hold gated cells with reasons. */
export function scheduleWaves(
  graph: CausalWorkGraph, cells: ReadonlyMap<string, MissionCell>, cellForNode: ReadonlyMap<string, string>,
): WavePlan {
  const held = holdGated(graph, cells, cellForNode);
  const critical = criticalPath(graph);
  const descendants = new Map([...graph.nodes.keys()].map((n) => [n, graph.descendants([n]).size]));
  const runnable = new Map([...cells].filter(([cid]) => !held.has(cid)));
  const depth = cellDepths(graph, runnable, cellForNode);
  const priority = (cid: string): (string | number)[] => {
    const cell = runnable.get(cid) as MissionCell;
    const work = cell.node_refs[0] ?? '';
    return [-(critical.get(work) ?? 0), -(descendants.get(work) ?? 0), -informationGain(graph.node(work).stage),
      cell.side_effect_class === 'PURE' || cell.side_effect_class === 'DRAFT' ? 0 : 1, cid];
  };
  const waves: Wave[] = [];
  for (const level of [...new Set(depth.values())].sort((a, b) => a - b)) {
    const members = [...depth].filter(([, d]) => d === level).map(([cid]) => cid)
      .sort((a, b) => compareTuples(priority(a), priority(b)));
    layerWaves(members, runnable, waves);
  }
  return { waves, held: sortedHeld(held), wave_hash: waveHash(waves, held) };
}

export interface BuildCellInputs {
  readonly graph: CausalWorkGraph;
  readonly work_node_id: string;
  readonly accountable_specialist: string | null;
  readonly contributor_specialists: Iterable<string>;
  readonly binding_hash: string;
  readonly work_order_ids: Iterable<string>;
  readonly capsule_hash: string | null;
  readonly validators: Iterable<string>;
  readonly resource_locks: Iterable<string>;
  readonly risk_class: string;
  readonly approval_refs: Iterable<string>;
  readonly blockers: Iterable<string>;
}

function cellRefs(graph: CausalWorkGraph, node: BackchainNode, workId: string): string[] {
  const refs = [workId];
  for (const suffix of ['validate', 'accept']) {
    const candidate = `${suffix}:${node.artifact_type}`;
    if (node.artifact_type && graph.nodes.has(candidate) && node.type === 'EXECUTABLE_WORK') refs.push(candidate);
  }
  return refs;
}

export function buildCell(inputs: BuildCellInputs): MissionCell {
  const { graph } = inputs;
  const node = graph.node(inputs.work_node_id);
  const artifact = node.artifact_type;
  const blockers = uniqueSorted(inputs.blockers);
  const inputRefs = node.hard_dependencies.map((d): [string, string] => [d, graph.node(d).semantic_hash]).sort(compareTuples);
  return {
    cell_id: node.type === 'EXECUTABLE_WORK' ? `cell:${afterFirst(inputs.work_node_id, ':')}` : `cell:${inputs.work_node_id}`,
    objective: node.purpose,
    node_refs: cellRefs(graph, node, inputs.work_node_id),
    accountable_specialist: inputs.accountable_specialist,
    contributor_specialists: uniqueSorted(inputs.contributor_specialists),
    runtime_authority_binding: inputs.binding_hash,
    work_order_refs: sortStrings(inputs.work_order_ids),
    context_capsule_ref: inputs.capsule_hash,
    input_refs: inputRefs,
    output_contracts: artifact ? [artifact] : [],
    validators: uniqueSorted(inputs.validators),
    mutation_targets: node.mutation_targets,
    resource_locks: uniqueSorted(inputs.resource_locks),
    risk_class: inputs.risk_class,
    side_effect_class: node.side_effect_class,
    approval_refs: uniqueSorted(inputs.approval_refs),
    status: blockers.length ? 'BLOCKED' : 'FORMED',
    blockers,
  };
}
