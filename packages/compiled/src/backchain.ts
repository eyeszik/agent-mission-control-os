/**
 * Twin of `agency/compiled/backchain.py` (T10): the DeliverableBackchain that
 * compiles DeliverableSpecs into the Causal Work Graph, expanded from N3
 * `produces`/`consumes`. Every leaf resolves to VALID_EXISTING_REF,
 * EXECUTABLE_WORK, HUMAN_DECISION or EXPLICIT_BLOCKER; nothing is invented.
 */
import { ARTIFACT_TYPES, ROLE_REGISTRY, pyRepr, type ArtifactType, type RoleContract } from '@amc/kernel';
import { BackchainCycleError, CompiledKeyError, CompiledValueError } from './errors';
import { semanticHash, type HashValue } from './hashing';
import { ARTIFACT_STAGE, STAGES_BY_ID } from './ontology';
import { compareCodePoints, pySlice, sortStrings, uniqueSorted } from './python';
import { obligationsFor } from './validation';

export const NODE_TYPES = [
  'DELIVERABLE', 'ACCEPTED_ARTIFACT', 'VALIDATION_OBLIGATION', 'EXECUTABLE_WORK', 'MATERIAL_DECISION',
  'EVIDENCE_REQUIREMENT', 'EXISTING_REF', 'EXTERNAL_ACTION', 'BLOCKER',
] as const;
export type NodeType = (typeof NODE_TYPES)[number];

export const RESOLUTIONS = ['VALID_EXISTING_REF', 'EXECUTABLE_WORK', 'HUMAN_DECISION', 'EXPLICIT_BLOCKER', 'DERIVED'] as const;
export type Resolution = (typeof RESOLUTIONS)[number];

export const NODE_STATUSES = ['SATISFIED', 'PLANNED', 'AWAITING_HUMAN', 'BLOCKED'] as const;
export type NodeStatus = (typeof NODE_STATUSES)[number];

export const DECISION_KINDS = [
  'scope', 'commercial_constraint', 'strategy', 'positioning', 'audience', 'brand_platform', 'creative_direction',
  'architecture', 'material_budget', 'legal_security_policy', 'release_go_no_go',
] as const;
export type DecisionKind = (typeof DECISION_KINDS)[number];

/** Only material choices enter the DecisionSpine (spec §26). */
export const MATERIAL_DECISIONS: ReadonlyMap<string, DecisionKind> = new Map<string, DecisionKind>([
  ['positioning_statement', 'positioning'],
  ['business_model_spec', 'commercial_constraint'],
  ['brand_platform', 'brand_platform'],
  ['creative_concept', 'creative_direction'],
  ['implementation_plan', 'architecture'],
  ['product_spec', 'scope'],
  ['media_plan', 'material_budget'],
  ['release_record', 'release_go_no_go'],
]);

export const EXTERNAL_ACTIONS = [
  'publish', 'deploy', 'distribute', 'send', 'pay', 'purchase', 'media_spend', 'production_migration', 'delete',
  'credential_mutation', 'client_binding_commitment',
] as const;
export type ExternalAction = (typeof EXTERNAL_ACTIONS)[number];

export const RESEARCH_ARTIFACTS: readonly ArtifactType[] = ['research_brief', 'market_analysis'];
export const REVERSIBLE_ACTIONS: ReadonlySet<ExternalAction> = new Set(['deploy']);
export const SPEND_ACTIONS: ReadonlySet<ExternalAction> = new Set(['pay', 'purchase', 'media_spend']);

/** N3 role whose contract declares `external_side_effect` for the action. */
export function externalActionRole(action: ExternalAction): string {
  return SPEND_ACTIONS.has(action) ? 'media_planner' : 'release_manager';
}

export interface DeliverableSpec {
  readonly id: string;
  readonly requested_outcome: string;
  readonly output_contract: string;
  readonly acceptance_criteria: readonly string[];
  readonly required_approvals: readonly string[];
  readonly constraints: readonly string[];
  readonly priority: number | null;
  readonly source_refs: readonly string[];
  readonly domains: readonly string[];
  readonly external_action: ExternalAction | null;
  readonly live_service: boolean;
}

export interface EvidenceItem {
  readonly ref: string;
  readonly supports: readonly string[];
  readonly verified: boolean;
}

export interface BackchainNode {
  readonly id: string;
  readonly type: NodeType;
  readonly purpose: string;
  readonly satisfies: readonly string[];
  readonly dependencies: readonly string[];
  readonly hard_dependencies: readonly string[];
  readonly soft_dependencies: readonly string[];
  readonly phase_compatibility: readonly string[];
  readonly required_capabilities: readonly string[];
  readonly validation_obligations: readonly string[];
  readonly side_effect_class: string;
  readonly mutation_targets: readonly string[];
  readonly status: NodeStatus;
  readonly resolution: Resolution;
  readonly artifact_type: string | null;
  readonly runtime_role_id: string | null;
  readonly stage: string | null;
  readonly domains: readonly string[];
  readonly blockers: readonly string[];
  readonly semantic_hash: string;
}

/** The fields a node was built with; the semantic hash covers exactly these (minus `purpose`). */
export interface RawNode {
  id?: string;
  type?: NodeType;
  purpose?: string;
  satisfies?: readonly string[];
  hard_dependencies?: readonly string[];
  soft_dependencies?: readonly string[];
  phase_compatibility?: readonly string[];
  required_capabilities?: readonly string[];
  validation_obligations?: readonly string[];
  side_effect_class?: string;
  mutation_targets?: readonly string[];
  status?: NodeStatus;
  resolution?: Resolution;
  artifact_type?: string | null;
  runtime_role_id?: string | null;
  stage?: string | null;
  domains?: readonly string[];
  blockers?: readonly string[];
}

export class CausalWorkGraph {
  constructor(
    readonly nodes: ReadonlyMap<string, BackchainNode>,
    readonly roots: readonly string[],
    readonly topological_order: readonly string[],
    readonly eliminated: readonly string[],
    readonly redundant_candidates: readonly string[],
    readonly dedup_hits: number,
    readonly graph_hash: string,
  ) {}

  /** Node → the nodes that depend on it. */
  dependents(): Map<string, Set<string>> {
    const out = new Map<string, Set<string>>();
    for (const id of this.nodes.keys()) out.set(id, new Set());
    for (const node of this.nodes.values()) {
      for (const dep of node.dependencies) {
        const set = out.get(dep) ?? new Set<string>();
        set.add(node.id);
        out.set(dep, set);
      }
    }
    return out;
  }

  /** Causal closure downstream of `refs`. */
  descendants(refs: Iterable<string>): Set<string> {
    const forward = this.dependents();
    const seen = new Set<string>();
    const queue = [...refs].filter((r) => this.nodes.has(r));
    while (queue.length) {
      const current = queue.shift() as string;
      for (const next of forward.get(current) ?? []) {
        if (!seen.has(next)) {
          seen.add(next);
          queue.push(next);
        }
      }
    }
    return seen;
  }

  ancestors(ref: string): Set<string> {
    const seen = new Set<string>();
    const queue = [ref];
    while (queue.length) {
      const node = this.nodes.get(queue.shift() as string);
      if (node === undefined) continue;
      for (const dep of node.dependencies) {
        if (!seen.has(dep)) {
          seen.add(dep);
          queue.push(dep);
        }
      }
    }
    return seen;
  }

  workNodes(): BackchainNode[] {
    return this.topological_order.map((id) => this.node(id)).filter((n) => n.type === 'EXECUTABLE_WORK');
  }

  node(id: string): BackchainNode {
    const found = this.nodes.get(id);
    if (found === undefined) throw new CompiledKeyError(pyRepr(id));
    return found;
  }
}

export function producerFor(artifactType: ArtifactType): RoleContract | null {
  const producers = [...ROLE_REGISTRY.values()].filter((r) => r.produces.has(artifactType))
    .sort((a, b) => compareCodePoints(a.role_id, b.role_id));
  return producers[0] ?? null;
}

const unionSorted = (a: readonly string[] | undefined, b: readonly string[] | undefined): string[] =>
  uniqueSorted([...(a ?? []), ...(b ?? [])]);

class Builder {
  readonly nodes = new Map<string, RawNode>();
  dedupHits = 0;
  private readonly expanding = new Set<string>();

  constructor(
    private readonly existing: ReadonlyMap<string, string>,
    private readonly acceptedDecisions: ReadonlyMap<string, string>,
    private readonly evidence: readonly EvidenceItem[],
  ) {}

  add(nodeId: string, fields: RawNode): string {
    const current = this.nodes.get(nodeId);
    if (current !== undefined) {
      this.dedupHits += 1;
      current.satisfies = unionSorted(current.satisfies, fields.satisfies);
      current.domains = unionSorted(current.domains, fields.domains);
      return nodeId;
    }
    const raw: RawNode = { soft_dependencies: [], domains: [], ...fields, id: nodeId };
    raw.hard_dependencies = uniqueSorted(fields.hard_dependencies ?? []);
    this.nodes.set(nodeId, raw);
    return nodeId;
  }

  accepted(artifact: ArtifactType, satisfies: string, domains: readonly string[], live: boolean): string {
    const existingHash = this.existing.get(artifact);
    if (existingHash !== undefined) return this.existingRef(artifact, existingHash, satisfies, domains);
    const producer = producerFor(artifact);
    if (producer === null) return this.blocker('NO_N3_PRODUCER', artifact, satisfies);
    const acceptId = `accept:${artifact}`;
    if (this.nodes.has(acceptId)) return this.add(acceptId, { satisfies: [satisfies], domains });
    if (this.expanding.has(artifact)) throw new BackchainCycleError(`N3 consumes/produces cycle through ${artifact}`);
    this.expanding.add(artifact);
    const inputs = [...producer.consumes].sort(compareCodePoints)
      .map((c) => this.accepted(c, `work:${artifact}`, domains, live));
    this.expanding.delete(artifact);
    const stage = ARTIFACT_STAGE.get(artifact);
    if (stage === undefined) return this.blocker('ARTIFACT_STAGE_UNMODELED', artifact, satisfies);
    const workId = this.workNode(artifact, producer, inputs, stage, domains);
    const validateId = this.validateNode(artifact, producer, workId, stage, domains, live);
    const acceptDeps = [validateId];
    const kind = MATERIAL_DECISIONS.get(artifact);
    if (kind !== undefined) acceptDeps.push(this.decisionNode(kind, workId, acceptId, domains));
    return this.add(acceptId, {
      type: 'ACCEPTED_ARTIFACT', purpose: `Accepted ${artifact}`, satisfies: [satisfies], hard_dependencies: acceptDeps,
      status: 'PLANNED', resolution: 'DERIVED', artifact_type: artifact, runtime_role_id: producer.role_id, domains,
    });
  }

  private existingRef(key: string, digest: string, satisfies: string, domains: readonly string[]): string {
    return this.add(`ref:${key}`, {
      type: 'EXISTING_REF', purpose: `Existing accepted ${key} (content hash ${pySlice(digest, 0, 12)})`,
      satisfies: [satisfies], hard_dependencies: [], status: 'SATISFIED', resolution: 'VALID_EXISTING_REF',
      artifact_type: key, domains,
    });
  }

  private workNode(
    artifact: ArtifactType, producer: RoleContract, inputs: readonly string[], stage: string, domains: readonly string[],
  ): string {
    const phase = STAGES_BY_ID.get(stage)?.roleos_phase ?? '';
    return this.add(`work:${artifact}`, {
      type: 'EXECUTABLE_WORK', purpose: `Produce ${artifact} (${producer.mandate})`, satisfies: [`validate:${artifact}`],
      hard_dependencies: inputs, phase_compatibility: [phase], required_capabilities: sortStrings(producer.capabilities),
      side_effect_class: 'DRAFT', mutation_targets: [`artifact:${artifact}`], status: 'PLANNED',
      resolution: 'EXECUTABLE_WORK', artifact_type: artifact, runtime_role_id: producer.role_id, stage, domains,
    });
  }

  private validateNode(
    artifact: ArtifactType, producer: RoleContract, workId: string, stage: string, domains: readonly string[], live: boolean,
  ): string {
    const deps = [workId];
    if (producer.min_evidence) {
      const ancestors = this.rawAncestors(workId);
      const researchUpstream = RESEARCH_ARTIFACTS.includes(artifact)
        || RESEARCH_ARTIFACTS.some((r) => ancestors.has(`work:${r}`));
      deps.push(this.evidenceNode(artifact, producer.min_evidence, domains, researchUpstream));
    }
    return this.add(`validate:${artifact}`, {
      type: 'VALIDATION_OBLIGATION', purpose: `Validate ${artifact} against its obligations`,
      satisfies: [`accept:${artifact}`], hard_dependencies: deps,
      validation_obligations: obligationsFor(artifact, domains, { liveService: live }), status: 'PLANNED',
      resolution: 'DERIVED', artifact_type: artifact, stage: compareCodePoints(stage, 'S17') < 0 ? 'S17' : stage, domains,
    });
  }

  rawAncestors(nodeId: string): Set<string> {
    const seen = new Set<string>();
    const stack = [nodeId];
    while (stack.length) {
      const raw = this.nodes.get(stack.pop() as string);
      for (const dep of raw?.hard_dependencies ?? []) {
        if (!seen.has(dep)) {
          seen.add(dep);
          stack.push(dep);
        }
      }
    }
    return seen;
  }

  private evidenceNode(artifact: ArtifactType, floor: number, domains: readonly string[], researchUpstream: boolean): string {
    const have = this.evidence.filter((e) => e.verified && e.supports.includes(artifact)).length;
    let fields: RawNode = { status: 'SATISFIED', resolution: 'VALID_EXISTING_REF', blockers: [] };
    if (have < floor) {
      fields = researchUpstream
        ? { status: 'PLANNED', resolution: 'EXECUTABLE_WORK', blockers: [`AWAITING_EVIDENCE:${artifact}:${have}/${floor}`] }
        : { status: 'BLOCKED', resolution: 'EXPLICIT_BLOCKER', blockers: [`EVIDENCE_DEFICIT:${artifact}:${have}/${floor}`] };
    }
    return this.add(`evidence:${artifact}`, {
      type: 'EVIDENCE_REQUIREMENT', purpose: `At least ${floor} verified evidence items supporting ${artifact} (have ${have})`,
      satisfies: [`validate:${artifact}`], hard_dependencies: [], ...fields, artifact_type: artifact, domains,
    });
  }

  private decisionNode(kind: DecisionKind, workId: string, acceptId: string, domains: readonly string[]): string {
    const accepted = this.acceptedDecisions.has(kind);
    return this.add(`decision:${kind}`, {
      type: 'MATERIAL_DECISION', purpose: `Material ${kind} decision over produced options`, satisfies: [acceptId],
      hard_dependencies: [workId], status: accepted ? 'SATISFIED' : 'AWAITING_HUMAN',
      resolution: accepted ? 'VALID_EXISTING_REF' : 'HUMAN_DECISION', domains,
    });
  }

  blocker(code: string, subject: string, satisfies: string): string {
    return this.add(`blocker:${code}:${subject}`, {
      type: 'BLOCKER', purpose: `${code} for ${subject}`, satisfies: [satisfies], hard_dependencies: [],
      status: 'BLOCKED', resolution: 'EXPLICIT_BLOCKER', blockers: [`${code}:${subject}`],
    });
  }

  deliverable(spec: DeliverableSpec): string {
    const root = `deliverable:${spec.id}`;
    const domains = sortStrings(spec.domains);
    const known = (ARTIFACT_TYPES as readonly string[]).includes(spec.output_contract);
    const dep = known
      ? this.accepted(spec.output_contract as ArtifactType, root, domains, spec.live_service)
      : this.blocker('ARTIFACT_TYPE_UNMODELED', spec.output_contract, root);
    const deps = spec.external_action === null ? [dep] : [this.externalNode(spec, spec.external_action, dep, domains)];
    return this.add(root, {
      type: 'DELIVERABLE', purpose: spec.requested_outcome, satisfies: [], hard_dependencies: deps, status: 'PLANNED',
      resolution: 'DERIVED', artifact_type: spec.output_contract, domains,
    });
  }

  private externalNode(spec: DeliverableSpec, action: ExternalAction, acceptedId: string, domains: readonly string[]): string {
    const nodeId = `external:${action}:${spec.id}`;
    const deps = [acceptedId];
    if (!SPEND_ACTIONS.has(action)) deps.push(this.accepted('release_record', nodeId, domains, spec.live_service));
    const role = ROLE_REGISTRY.get(externalActionRole(action)) as RoleContract;
    return this.add(nodeId, {
      type: 'EXTERNAL_ACTION', purpose: `${action} ${spec.output_contract} externally (P12, distinct from P11 acceptance)`,
      satisfies: [`deliverable:${spec.id}`], hard_dependencies: deps, phase_compatibility: ['P12'],
      required_capabilities: sortStrings(role.capabilities),
      validation_obligations: obligationsFor('release_record', domains, { externalAction: true, liveService: spec.live_service }),
      side_effect_class: REVERSIBLE_ACTIONS.has(action) ? 'REVERSIBLE_WRITE' : 'IRREVERSIBLE_WRITE',
      mutation_targets: [`external:${action}`], status: 'PLANNED', resolution: 'EXECUTABLE_WORK',
      runtime_role_id: role.role_id, stage: 'S18', domains,
    });
  }
}

/** `_finalize`: fill model defaults; the semantic hash covers the raw fields except `purpose`. */
export function finalizeNode(raw: RawNode): BackchainNode {
  const hard = raw.hard_dependencies ?? [];
  const body: RawNode & { dependencies: string[] } = {
    ...raw, dependencies: uniqueSorted([...hard, ...(raw.soft_dependencies ?? [])]), blockers: raw.blockers ?? [],
  };
  const semantic: Record<string, HashValue> = {};
  for (const [key, value] of Object.entries(body)) if (key !== 'purpose') semantic[key] = value as HashValue;
  return {
    id: body.id ?? '', type: body.type ?? 'BLOCKER', purpose: body.purpose ?? '', satisfies: body.satisfies ?? [],
    dependencies: body.dependencies, hard_dependencies: hard, soft_dependencies: body.soft_dependencies ?? [],
    phase_compatibility: body.phase_compatibility ?? [], required_capabilities: body.required_capabilities ?? [],
    validation_obligations: body.validation_obligations ?? [], side_effect_class: body.side_effect_class ?? 'PURE',
    mutation_targets: body.mutation_targets ?? [], status: body.status ?? 'BLOCKED', resolution: body.resolution ?? 'DERIVED',
    artifact_type: body.artifact_type ?? null, runtime_role_id: body.runtime_role_id ?? null, stage: body.stage ?? null,
    domains: body.domains ?? [], blockers: body.blockers ?? [], semantic_hash: semanticHash(semantic),
  };
}

function indegrees(nodes: ReadonlyMap<string, BackchainNode>) {
  const indegree = new Map<string, number>();
  const forward = new Map<string, string[]>();
  for (const id of nodes.keys()) {
    indegree.set(id, 0);
    forward.set(id, []);
  }
  for (const node of nodes.values()) {
    for (const dep of node.dependencies) {
      if (!nodes.has(dep)) throw new BackchainCycleError(`${node.id} depends on unknown node ${dep}`);
      indegree.set(node.id, (indegree.get(node.id) ?? 0) + 1);
      forward.get(dep)?.push(node.id);
    }
  }
  return { indegree, forward };
}

/** `_topological`: Kahn's algorithm with a sorted ready list; refuses cycles and dangling edges. */
export function topological(nodes: ReadonlyMap<string, BackchainNode>): string[] {
  const { indegree, forward } = indegrees(nodes);
  const ready = sortStrings([...indegree].filter(([, d]) => d === 0).map(([id]) => id));
  const order: string[] = [];
  while (ready.length) {
    const current = ready.shift() as string;
    order.push(current);
    for (const next of sortStrings(forward.get(current) ?? [])) {
      const left = (indegree.get(next) ?? 0) - 1;
      indegree.set(next, left);
      if (left === 0) ready.push(next);
    }
    ready.sort(compareCodePoints);
  }
  if (order.length !== nodes.size) {
    const done = new Set(order);
    const rest = sortStrings([...nodes.keys()].filter((id) => !done.has(id)));
    throw new BackchainCycleError(`causal work graph contains a cycle: ${rest.join(', ')}`);
  }
  return order;
}

function reachable(nodes: ReadonlyMap<string, BackchainNode>, roots: Iterable<string>, hardOnly: boolean): Set<string> {
  const seen = new Set<string>();
  const queue = [...roots];
  while (queue.length) {
    const current = queue.shift() as string;
    const node = nodes.get(current);
    if (seen.has(current) || node === undefined) continue;
    seen.add(current);
    queue.push(...(hardOnly ? node.hard_dependencies : node.dependencies));
  }
  return seen;
}

export interface BackchainInputs {
  readonly existing_artifacts?: ReadonlyMap<string, string>;
  readonly accepted_decisions?: ReadonlyMap<string, string>;
  readonly evidence?: readonly EvidenceItem[];
}

function normalizeSpecs(deliverables: Iterable<DeliverableSpec>): DeliverableSpec[] {
  const specs = [...deliverables].sort((a, b) => compareCodePoints(a.id, b.id));
  if (!specs.length) throw new CompiledValueError('at least one DeliverableSpec is required');
  if (new Set(specs.map((s) => s.id)).size !== specs.length) throw new CompiledValueError('deliverable ids must be unique');
  return specs;
}

/** `compile_backchain`: NORMALIZE → EXPAND(+CSE) → DEDUP → DEAD/ORPHAN ELIMINATION → CYCLE CHECK → NECESSITY. */
export function compileBackchain(deliverables: Iterable<DeliverableSpec>, inputs: BackchainInputs = {}): CausalWorkGraph {
  const specs = normalizeSpecs(deliverables);
  const builder = new Builder(inputs.existing_artifacts ?? new Map(), inputs.accepted_decisions ?? new Map(), inputs.evidence ?? []);
  const roots = specs.map((spec) => builder.deliverable(spec));
  const finalized = new Map<string, BackchainNode>();
  for (const [id, raw] of builder.nodes) finalized.set(id, finalizeNode(raw));
  const live = reachable(finalized, roots, false);
  const eliminated = sortStrings([...finalized.keys()].filter((id) => !live.has(id)));
  const kept = new Map<string, BackchainNode>();
  for (const id of sortStrings(live)) kept.set(id, finalized.get(id) as BackchainNode);
  const order = topological(kept);
  const hardLive = reachable(kept, roots, true);
  const redundant = sortStrings([...kept.keys()].filter((id) => !hardLive.has(id)));
  const nodeHashes: Record<string, HashValue> = {};
  for (const [id, n] of kept) nodeHashes[id] = n.semantic_hash;
  const graphHash = semanticHash({ roots, nodes: nodeHashes });
  return new CausalWorkGraph(kept, roots, order, eliminated, redundant, builder.dedupHits, graphHash);
}

/** Leaves must resolve to one of the four terminal resolutions. */
export function unresolvedLeaves(graph: CausalWorkGraph): string[] {
  const allowed = new Set<Resolution>(['VALID_EXISTING_REF', 'EXECUTABLE_WORK', 'HUMAN_DECISION', 'EXPLICIT_BLOCKER']);
  return sortStrings([...graph.nodes.values()].filter((n) => !n.dependencies.length && !allowed.has(n.resolution)).map((n) => n.id));
}

/** Plain-JSON view of a graph, shaped as Python's `CausalWorkGraph.model_dump(mode="json")`. */
export function dumpGraph(graph: CausalWorkGraph): Record<string, HashValue> {
  const nodes: Record<string, HashValue> = {};
  for (const [id, n] of graph.nodes) nodes[id] = n as unknown as HashValue;
  return {
    nodes, roots: graph.roots, topological_order: graph.topological_order, eliminated: graph.eliminated,
    redundant_candidates: graph.redundant_candidates, dedup_hits: graph.dedup_hits, graph_hash: graph.graph_hash,
  };
}
