/**
 * Twin of `agency/compiled/planner.py`: composes every T04-T19 projection into
 * one plan. `compileAgencyPlan` is pure (no LLM call, no database, no network,
 * no wall clock: `as_of` is an input) and deterministic: the same canonical
 * request, registry and policy give the same `plan_hash`.
 *
 * It plans consequential actions but can never make one executable on its own:
 * external actions need a verified provider, an authority grant, an exact
 * approval and the N2 release guards.
 *
 * Left in Python: `JITSkillLoader` (reads archive files). `compileAgencyPlan`
 * takes an optional `jitStatusFor` callback instead, called once with the
 * activated specialists, and `source_hashes` as an already-built map.
 */
import { pyRepr } from '@amc/kernel';
import {
  AuthorityBridge, N3_SPECIALISTS, type AuthorityGrant, type BindingStatus, type SpecialistBinding,
} from './authority';
import { classify, suitabilityForNode, type AutonomyDecision } from './autonomy';
import {
  compileBackchain, unresolvedLeaves, type BackchainNode, type CausalWorkGraph, type DeliverableSpec, type EvidenceItem,
} from './backchain';
import {
  dependencyClosureHash, evaluateScope, scopeHash, type ApprovalScope,
} from './change-control';
import {
  capsuleFreshness, hoistSharedRefs, projectCapsule, projectGenome, type ContextCapsule, type GenomeAssertion,
} from './context';
import { DecisionSpine, uncertaintyPriority, type DecisionNode } from './decisions';
import { CompiledKeyError, CompiledValueError } from './errors';
import { volatileReleaseBlockers, type VolatileConstraint } from './evidence';
import { buildCell, cellHash, scheduleWaves, type MissionCell, type WavePlan } from './execution';
import { semanticHash, type HashValue } from './hashing';
import { selectOverlays } from './ontology';
import { afterFirst, compareCodePoints, pySlice, sortStrings, uniqueSorted } from './python';
import type { RoleOSRegistry } from './roleos';
import {
  evaluateValidation, PROFILES_BY_ID, releaseBlockers, volatileKeysFor, type ValidationResult,
} from './validation';
import { compilePcwo, riskLevelFor, type PCWO } from './work-orders';

export const COMPILED_AGENCY_VERSION = 'amc-compiled-agency/v1';
export const DEFAULT_POLICY_VERSION = 'amc-approval/v1';
export const NODE_INVARIANT_DIMENSIONS = [
  'WHO', 'WHY', 'TRIGGER', 'INPUT', 'SOURCE', 'EVIDENCE', 'ACTION', 'TOOL', 'OUTPUT', 'NEXT', 'DEPENDENCY', 'DECISION',
  'AUTHORITY', 'AUTONOMY', 'VALIDATION', 'APPROVAL', 'FAILURE', 'RECOVERY', 'PROVENANCE',
] as const;

export interface CompiledAgencyRequest {
  readonly project_id: string;
  readonly as_of: string;
  readonly deliverables: readonly DeliverableSpec[];
  readonly genome: readonly GenomeAssertion[];
  readonly evidence: readonly EvidenceItem[];
  readonly existing_artifacts: ReadonlyMap<string, string>;
  readonly decisions: readonly DecisionNode[];
  readonly approvals: readonly ApprovalScope[];
  readonly grants: readonly AuthorityGrant[];
  readonly volatile_constraints: readonly VolatileConstraint[];
  readonly validation_results: readonly ValidationResult[];
  readonly generation_modes: ReadonlyMap<string, string>;
  /** action → "VERIFIED" only when a real provider adapter is installed and verified. */
  readonly provider_status: ReadonlyMap<string, string>;
  readonly artifact_hashes: ReadonlyMap<string, string>;
  readonly policy_version: string;
}

export interface NodeCard {
  readonly node_id: string;
  readonly dimensions: Readonly<Record<string, HashValue>>;
  readonly unresolved: readonly string[];
}

export interface CompiledAgencyPlan {
  readonly version: string;
  readonly project_id: string;
  readonly as_of: string;
  readonly registry_hash: string;
  readonly overlays: readonly string[];
  readonly genome_hash: string;
  readonly graph: CausalWorkGraph;
  readonly bindings: ReadonlyMap<string, SpecialistBinding>;
  readonly capsules: ReadonlyMap<string, ContextCapsule>;
  readonly shared_genome_refs: readonly string[];
  readonly work_orders: ReadonlyMap<string, PCWO>;
  readonly cells: ReadonlyMap<string, MissionCell>;
  readonly waves: WavePlan;
  readonly autonomy: ReadonlyMap<string, AutonomyDecision>;
  readonly executable: ReadonlyMap<string, boolean>;
  readonly blocked: ReadonlyMap<string, readonly string[]>;
  readonly human_gates: readonly string[];
  readonly release_readiness: ReadonlyMap<string, readonly string[]>;
  readonly uncertainty_first: readonly (readonly [string, number])[];
  readonly activated_specialists: readonly string[];
  readonly dormant_specialist_count: number;
  readonly jit_skills: ReadonlyMap<string, string>;
  readonly node_cards: ReadonlyMap<string, NodeCard>;
  readonly plan_hash: string;
}

export interface PlanOptions {
  /** role_id → source hash, from the (Python-built) RoleSourceIndex. Absent = no source index. */
  readonly sourceHashes?: ReadonlyMap<string, string> | null;
  /** Python's `JITSkillLoader.load_selected`, injected: role_id → status value for the activated roles. */
  readonly jitStatusFor?: ((activated: readonly string[]) => ReadonlyMap<string, string>) | null;
}

/** Counts and ids a caller shows first; mirrors `CompiledAgencyPlan.summary()`. */
export function planSummary(plan: CompiledAgencyPlan) {
  const byLevel = new Map<string, number>();
  for (const d of plan.autonomy.values()) byLevel.set(d.level, (byLevel.get(d.level) ?? 0) + 1);
  return {
    plan_hash: plan.plan_hash, nodes: plan.graph.nodes.size, work_nodes: plan.work_orders.size, cells: plan.cells.size,
    waves: plan.waves.waves.length, held_cells: plan.waves.held.size, dedup_hits: plan.graph.dedup_hits,
    activated_specialists: plan.activated_specialists.length, dormant_specialists: plan.dormant_specialist_count,
    human_gates: [...plan.human_gates],
    by_autonomy_level: Object.fromEntries(sortStrings(byLevel.keys()).map((k) => [k, byLevel.get(k) ?? 0])),
    blocked_nodes: plan.blocked.size,
    release_ready: sortStrings([...plan.release_readiness].filter(([, b]) => !b.length).map(([d]) => d)),
  };
}

function validatorsFor(obligations: readonly string[], bridge: AuthorityBridge): string[] {
  const out: string[] = [];
  for (const ob of obligations) {
    if (!ob.startsWith('PROFILE:')) continue;
    const profile = PROFILES_BY_ID.get(afterFirst(ob, ':'));
    if (profile === undefined) throw new CompiledKeyError(pyRepr(afterFirst(ob, ':')));
    const roleId = bridge.resolveSpecialist({ skill_name: profile.validator_skill, department: profile.validator_department });
    out.push(roleId || `CAPABILITY_GAP:${profile.validator_skill}`);
  }
  return uniqueSorted(out);
}

const isGap = (v: string): boolean => v.startsWith('CAPABILITY_GAP');

function buildBridge(registry: RoleOSRegistry, options: PlanOptions): [AuthorityBridge, Map<string, string>] {
  const sourceHashes = new Map<string, string>();
  const plain = new AuthorityBridge(registry);
  if (!options.sourceHashes) return [plain, sourceHashes];
  for (const query of N3_SPECIALISTS.values()) {
    const roleId = plain.resolveSpecialist(query);
    const digest = roleId ? options.sourceHashes.get(roleId) : undefined;
    if (roleId && digest !== undefined) sourceHashes.set(roleId, digest);
  }
  return [new AuthorityBridge(registry, sourceHashes), sourceHashes];
}

interface Context {
  readonly request: CompiledAgencyRequest;
  readonly registry: RoleOSRegistry;
  readonly graph: CausalWorkGraph;
  readonly bridge: AuthorityBridge;
  readonly sourceHashes: ReadonlyMap<string, string>;
  readonly missionId: string;
  readonly currentHashes: ReadonlyMap<string, string>;
  readonly acceptedDecisions: ReadonlyMap<string, string>;
  readonly genome: ReturnType<typeof projectGenome>;
  readonly forward: ReadonlyMap<string, ReadonlySet<string>>;
  readonly rootsFor: ReadonlyMap<string, ReadonlySet<string>>;
  readonly specByRoot: ReadonlyMap<string, DeliverableSpec>;
}

function validApprovals(ctx: Context, matches: (s: ApprovalScope) => boolean): ApprovalScope[] {
  const { request, graph } = ctx;
  return request.approvals.filter((s) => matches(s) && evaluateScope(s, {
    current_subject_hashes: ctx.currentHashes,
    current_closure_hash: dependencyClosureHash(graph, s.subject_refs, request.artifact_hashes),
    current_policy_version: request.policy_version,
  }) === 'VALID');
}

function nodeExtras(
  ctx: Context, isExternal: boolean, action: string, obligations: readonly string[], validators: readonly string[],
): string[] {
  const { request } = ctx;
  const keys = new Set(volatileKeysFor(obligations));
  const extra = validators.filter(isGap);
  extra.push(...volatileReleaseBlockers(request.volatile_constraints.filter((c) => keys.has(c.key)), request.as_of));
  const have = new Set(request.volatile_constraints.map((c) => c.key));
  extra.push(...sortStrings([...keys].filter((k) => !have.has(k))).map((k) => `VOLATILE_UNVERIFIED:${k}`));
  if (isExternal && request.provider_status.get(action) !== 'VERIFIED') extra.push(`PROVIDER_UNAVAILABLE:${action}`);
  return extra;
}

function nodeCapsule(ctx: Context, node: BackchainNode, deliverableRefs: readonly string[], binding: SpecialistBinding): ContextCapsule {
  const specs = deliverableRefs.map((r) => ctx.specByRoot.get(r)).filter((s): s is DeliverableSpec => s !== undefined);
  const depHashes = new Map(node.hard_dependencies.map((d) => [d, ctx.currentHashes.get(d) as string]));
  return projectCapsule(ctx.genome, {
    objective: node.purpose, acceptance_criteria: specs.flatMap((s) => s.acceptance_criteria), domains: node.domains,
    approved_decision_refs: [...ctx.acceptedDecisions].map(([k, h]) => `${k}@${pySlice(h, 0, 16)}`),
    artifact_refs: node.hard_dependencies.filter((d) => d.startsWith('ref:') || d.startsWith('accept:')),
    dependency_hashes: depHashes, hard_constraints: specs.flatMap((s) => s.constraints), authority_refs: [binding.binding_hash],
    tool_permissions: binding.permitted_tools,
  });
}

const isEmptyDim = (v: HashValue | undefined): boolean => v === undefined || v === null || v === '' || (Array.isArray(v) && v.length === 0);

function nodeCard(
  ctx: Context, node: BackchainNode, binding: SpecialistBinding, pcwo: PCWO | null, capsule: ContextCapsule,
  autonomy: AutonomyDecision, obligations: readonly string[], decisionRefs: readonly string[], evidenceReqs: readonly string[],
): NodeCard {
  const specialist = binding.specialist_role_id;
  const dims: Record<string, HashValue> = {
    WHO: specialist, WHY: [...node.satisfies],
    TRIGGER: node.hard_dependencies.length ? 'all hard dependencies accepted' : 'plan admitted',
    INPUT: node.hard_dependencies.length ? [...node.hard_dependencies] : [`capsule:${pySlice(capsule.capsule_hash, 0, 16)}`],
    SOURCE: ctx.sourceHashes.get(specialist ?? '') ?? `roleos:${ctx.registry.registry_hash}`,
    EVIDENCE: evidenceReqs.length ? [...evidenceReqs] : ['none required'], ACTION: node.purpose,
    TOOL: pcwo ? [...pcwo.tool_plan] : [],
    OUTPUT: node.artifact_type || (node.mutation_targets.length ? (node.mutation_targets[0] as string) : null),
    NEXT: sortStrings(ctx.forward.get(node.id) ?? []),
    DEPENDENCY: node.dependencies.length ? [...node.dependencies] : ['none (leaf)'],
    DECISION: decisionRefs.length ? [...decisionRefs] : ['none material'],
    AUTHORITY: binding.status === 'RESOLVED' ? binding.binding_hash : null, AUTONOMY: autonomy.level,
    VALIDATION: [...obligations],
    APPROVAL: binding.approval_requirements.length ? [...binding.approval_requirements] : ['none'],
    FAILURE: 'route to smallest causal producer', RECOVERY: pcwo ? pcwo.idempotency_class : null,
    PROVENANCE: pcwo ? pcwo.work_order_id : null,
  };
  const unresolved = NODE_INVARIANT_DIMENSIONS.filter((d) => isEmptyDim(dims[d]));
  return { node_id: node.id, dimensions: dims, unresolved };
}

interface NodeResult {
  readonly binding: SpecialistBinding;
  readonly capsule: ContextCapsule;
  readonly pcwo: PCWO | null;
  readonly autonomy: AutonomyDecision;
  readonly card: NodeCard;
  readonly cell: MissionCell;
  readonly blockers: string[];
}

function ancestryExtras(ctx: Context, node: BackchainNode) {
  const ancestry = ctx.graph.ancestors(node.id);
  const withEvidence = new Set([...ancestry, `evidence:${node.artifact_type}`]);
  const present = [...withEvidence].filter((a) => ctx.graph.nodes.has(a));
  const decisionRefs = sortStrings([...new Set([...ancestry, ...(ctx.forward.get(node.id) ?? [])])].filter((a) => a.startsWith('decision:')));
  const evidenceReqs = sortStrings(present.flatMap((a) => ctx.graph.node(a).blockers));
  const evidenceOk = !present.some((a) => ctx.graph.node(a).type === 'EVIDENCE_REQUIREMENT' && ctx.graph.node(a).status === 'BLOCKED');
  return { ancestry, decisionRefs, evidenceReqs, evidenceOk };
}

function planNode(ctx: Context, node: BackchainNode): NodeResult {
  const { request, graph } = ctx;
  const nid = node.id;
  const deliverableRefs = sortStrings(ctx.rootsFor.get(nid) ?? []);
  const isExternal = node.type === 'EXTERNAL_ACTION';
  const action = isExternal ? (nid.split(':')[1] as string) : 'produce';
  const target = node.mutation_targets[0] ?? nid;
  const scope = new Set([nid, ...deliverableRefs]);
  const approvalRefs = sortStrings(validApprovals(ctx, (s) => s.subject_refs.some((r) => scope.has(r))).map((s) => s.approval_id));
  const binding = ctx.bridge.bind({
    runtime_role_id: node.runtime_role_id ?? '', side_effect_class: node.side_effect_class, operation: action, target,
    grants: request.grants, approval_refs: approvalRefs, as_of: request.as_of,
  });
  const validateId = `validate:${node.artifact_type}`;
  const obligations = graph.nodes.has(validateId) && !isExternal ? graph.node(validateId).validation_obligations : node.validation_obligations;
  const validators = validatorsFor(obligations, ctx.bridge);
  const extra = nodeExtras(ctx, isExternal, action, obligations, validators);
  const capsule = nodeCapsule(ctx, node, deliverableRefs, binding);
  if (capsuleFreshness(capsule, ctx.currentHashes) !== 'FRESH') extra.push('INVALIDATED_CONTEXT');
  const anc = ancestryExtras(ctx, node);
  const [pcwo, pcwoBlockers] = compilePcwo(ctx.registry, {
    project_id: request.project_id, mission_id: ctx.missionId, node, binding, deliverable_refs: deliverableRefs,
    acceptance_criteria: capsule.acceptance_criteria, validation_obligations: obligations, evidence_requirements: anc.evidenceReqs,
    decision_refs: anc.decisionRefs, contributor_specialists: validators.filter((v) => !isGap(v)),
    context_capsule_hash: capsule.capsule_hash, authority_refs: request.grants.filter((g) => g.target === target).map((g) => g.grant_id),
    approval_refs: approvalRefs,
    approval_scope_hash: ((s) => (s === undefined ? null : scopeHash(s)))(request.approvals.find((s) => approvalRefs.includes(s.approval_id))),
    extra_blockers: extra,
  });
  const autonomy = classify(suitabilityForNode({
    artifactType: node.artifact_type, sideEffectClass: node.side_effect_class, evidenceSufficient: anc.evidenceOk,
    rightsUncertain: validators.some(isGap),
  }));
  if (graph.nodes.has(validateId) && !isExternal) {
    const verdict = evaluateValidation(validateId, obligations, request.validation_results, {
      creatorRef: binding.specialist_role_id ?? '', riskLevel: riskLevelFor(node), graphNodes: new Set(graph.nodes.keys()),
    });
    if (verdict.escalation) pcwoBlockers.push(verdict.escalation);
    pcwoBlockers.push(...verdict.independence_violations);
  }
  const gating = [...anc.ancestry].filter((a) => ['AWAITING_HUMAN', 'BLOCKED'].includes(graph.node(a).status))
    .map((a) => (graph.node(a).type === 'MATERIAL_DECISION' ? `WAIT_HUMAN_DECISION:${a}` : `UPSTREAM_BLOCKED:${a}`));
  const blockers = uniqueSorted([...pcwoBlockers, ...gating, ...(pcwo === null ? ['NO_VALID_PCWO'] : [])]);
  const card = nodeCard(ctx, node, binding, pcwo, capsule, autonomy, obligations, anc.decisionRefs, anc.evidenceReqs);
  const all = uniqueSorted([...blockers, ...card.unresolved.map((d) => `NODE_INVARIANT_UNRESOLVED:${d}`)]);
  const contributors = validators.filter((v) => !isGap(v));
  const cell = buildCell({
    graph, work_node_id: nid, accountable_specialist: binding.specialist_role_id, contributor_specialists: contributors,
    binding_hash: binding.binding_hash, work_order_ids: pcwo ? [pcwo.work_order_id] : [], capsule_hash: capsule.capsule_hash,
    validators, resource_locks: pcwo ? pcwo.resource_locks : node.mutation_targets, risk_class: riskLevelFor(node),
    approval_refs: approvalRefs,
    // Waiting on a human decision is scheduling state, not a cell defect.
    blockers: all.filter((b) => !b.startsWith('WAIT_HUMAN_DECISION') && !b.startsWith('UPSTREAM_BLOCKED')),
  });
  return { binding, capsule, pcwo, autonomy, card, cell, blockers: all };
}

function releaseFor(ctx: Context, root: string, blocked: ReadonlyMap<string, readonly string[]>): string[] {
  const { request, graph } = ctx;
  const spec = ctx.specByRoot.get(root) as DeliverableSpec;
  const ancestry = graph.ancestors(root);
  const modes = new Set([...ancestry, root].map((a) => request.generation_modes.get(graph.node(a).artifact_type ?? '') ?? null));
  const mode = modes.has('FALLBACK_DEGRADED') ? 'FALLBACK_DEGRADED' : modes.has('PROVIDER_SUCCESS') ? 'PROVIDER_SUCCESS' : null;
  const subjects = new Set([root, `accept:${spec.output_contract}`, `ref:${spec.output_contract}`]);
  const approved = validApprovals(ctx, (s) => s.subject_refs.some((r) => subjects.has(r)));
  const results = request.validation_results.filter((r) => ancestry.has(r.node_id) && r.obligation === 'PROFILE:BRAND_COHESION');
  const brandOk = results.length ? results.every((r) => r.status === 'PASS') : null;
  const external = spec.external_action !== null;
  const extId = external ? `external:${spec.external_action}:${spec.id}` : null;
  const skip = new Set(['VALIDATION_OBLIGATION', 'ACCEPTED_ARTIFACT', 'EXTERNAL_ACTION']);
  const unmet = sortStrings([...ancestry].filter((a) => graph.node(a).status !== 'SATISFIED' && !skip.has(graph.node(a).type)));
  const codes = releaseBlockers({
    generation_mode: mode, approval_decision: approved.length ? 'approve' : null, brand_safety_passed: brandOk,
    external_side_effect: external,
    // N2's spend guard covers any spend/publication side effect; only a fully resolved external node discharges it.
    spend_authorized: Boolean(external && !blocked.has(extId as string)), unmet_hard_dependencies: unmet,
  });
  if (external && blocked.has(extId as string)) codes.push('external_action_blocked');
  return codes;
}

function rootsIndex(graph: CausalWorkGraph): Map<string, Set<string>> {
  const out = new Map<string, Set<string>>();
  for (const root of graph.roots) {
    for (const anc of [...graph.ancestors(root), root]) out.set(anc, (out.get(anc) ?? new Set<string>()).add(root));
  }
  return out;
}

function makeContext(request: CompiledAgencyRequest, registry: RoleOSRegistry, options: PlanOptions): Context {
  const spine = new DecisionSpine(request.decisions);
  const accepted = spine.acceptedByKind();
  const graph = compileBackchain(request.deliverables, {
    existing_artifacts: request.existing_artifacts, accepted_decisions: accepted, evidence: request.evidence,
  });
  const leaves = unresolvedLeaves(graph);
  if (leaves.length) throw new CompiledValueError(`unresolved backchain leaves: [${leaves.map(pyRepr).join(', ')}]`);
  const [bridge, sourceHashes] = buildBridge(registry, options);
  const sorted = [...request.deliverables].sort((a, b) => compareCodePoints(a.id, b.id));
  const missionId = `mission-${pySlice(semanticHash({ project: request.project_id, deliverables: sorted as unknown as HashValue }), 0, 20)}`;
  const current = new Map([...graph.nodes].map(([id, n]) => [id, n.semantic_hash]));
  for (const [k, v] of request.artifact_hashes) current.set(k, v);
  return {
    request, registry, graph, bridge, sourceHashes, missionId, currentHashes: current, acceptedDecisions: accepted,
    genome: projectGenome(request.genome), forward: graph.dependents(), rootsFor: rootsIndex(graph),
    specByRoot: new Map(request.deliverables.map((s) => [`deliverable:${s.id}`, s])),
  };
}

/** `compile_agency_plan`. */
export function compileAgencyPlan(request: CompiledAgencyRequest, registry: RoleOSRegistry, options: PlanOptions = {}): CompiledAgencyPlan {
  const ctx = makeContext(request, registry, options);
  const { graph } = ctx;
  const domains = uniqueSorted(request.deliverables.flatMap((s) => s.domains));
  const overlays = selectOverlays(domains, request.deliverables.some((s) => s.live_service));
  const nodes = [...graph.workNodes(), ...[...graph.nodes.values()].filter((n) => n.type === 'EXTERNAL_ACTION')];
  const bindings = new Map<string, SpecialistBinding>();
  const capsules = new Map<string, ContextCapsule>();
  const workOrders = new Map<string, PCWO>();
  const cells = new Map<string, MissionCell>();
  const cellForNode = new Map<string, string>();
  const autonomy = new Map<string, AutonomyDecision>();
  const blocked = new Map<string, readonly string[]>();
  const cards = new Map<string, NodeCard>();
  for (const node of nodes) {
    const r = planNode(ctx, node);
    bindings.set(node.id, r.binding);
    capsules.set(node.id, r.capsule);
    if (r.pcwo !== null) workOrders.set(node.id, r.pcwo);
    autonomy.set(node.id, r.autonomy);
    cards.set(node.id, r.card);
    if (r.blockers.length) blocked.set(node.id, r.blockers);
    cells.set(r.cell.cell_id, r.cell);
    for (const ref of r.cell.node_refs) cellForNode.set(ref, r.cell.cell_id);
  }
  const waves = scheduleWaves(graph, cells, cellForNode);
  const executable = new Map([...workOrders.keys()].map((nid) => [nid, !blocked.has(nid) && !waves.held.has(cellForNode.get(nid) ?? '\u0000')]));
  const release = new Map(graph.roots.map((root) => [root, releaseFor(ctx, root, blocked)]));
  return finishPlan(ctx, options, {
    overlays, bindings, capsules, workOrders, cells, waves, autonomy, executable, blocked, release, cards,
  });
}

interface Parts {
  readonly overlays: readonly string[];
  readonly bindings: ReadonlyMap<string, SpecialistBinding>;
  readonly capsules: ReadonlyMap<string, ContextCapsule>;
  readonly workOrders: ReadonlyMap<string, PCWO>;
  readonly cells: ReadonlyMap<string, MissionCell>;
  readonly waves: WavePlan;
  readonly autonomy: ReadonlyMap<string, AutonomyDecision>;
  readonly executable: ReadonlyMap<string, boolean>;
  readonly blocked: ReadonlyMap<string, readonly string[]>;
  readonly release: ReadonlyMap<string, readonly string[]>;
  readonly cards: ReadonlyMap<string, NodeCard>;
}

function hashMap<T>(map: ReadonlyMap<string, T>, pick: (v: T) => string): Record<string, HashValue> {
  const out: Record<string, HashValue> = {};
  for (const k of sortStrings(map.keys())) out[k] = pick(map.get(k) as T);
  return out;
}

function listMap(map: ReadonlyMap<string, readonly string[]>): Record<string, HashValue> {
  const out: Record<string, HashValue> = {};
  for (const k of sortStrings(map.keys())) out[k] = [...(map.get(k) as readonly string[])];
  return out;
}

function finishPlan(ctx: Context, options: PlanOptions, p: Parts): CompiledAgencyPlan {
  const { graph, request, registry } = ctx;
  const humanGates = uniqueSorted([
    ...[...graph.nodes.values()].filter((n) => n.type === 'MATERIAL_DECISION' && n.status === 'AWAITING_HUMAN').map((n) => n.id),
    ...[...p.release].filter(([, codes]) => codes.includes('approval_missing')).map(([r]) => `approval:${r}`),
    ...[...graph.nodes.values()].filter((n) => n.type === 'EXTERNAL_ACTION').map((n) => n.id),
  ]);
  const activated = uniqueSorted([
    ...[...p.bindings.values()].map((b) => b.specialist_role_id).filter((s): s is string => Boolean(s)),
    ...[...p.cells.values()].flatMap((c) => c.contributor_specialists),
  ]);
  const jit = options.jitStatusFor ? new Map(options.jitStatusFor(activated)) : new Map<string, string>();
  const genome = ctx.genome;
  const body = {
    version: COMPILED_AGENCY_VERSION, project_id: request.project_id, as_of: request.as_of, registry_hash: registry.registry_hash,
    overlays: [...p.overlays], genome_hash: genome.genome_hash, graph_hash: graph.graph_hash,
    bindings: hashMap(p.bindings, (b) => b.binding_hash), capsules: hashMap(p.capsules, (c) => c.capsule_hash),
    work_orders: hashMap(p.workOrders, (w) => w.work_order_hash), cells: hashMap(p.cells, cellHash), waves: p.waves.wave_hash,
    blocked: listMap(p.blocked), release: listMap(p.release),
  };
  return {
    version: COMPILED_AGENCY_VERSION, project_id: request.project_id, as_of: request.as_of, registry_hash: registry.registry_hash,
    overlays: p.overlays, genome_hash: genome.genome_hash, graph, bindings: p.bindings, capsules: p.capsules,
    shared_genome_refs: hoistSharedRefs(p.capsules.values()), work_orders: p.workOrders, cells: p.cells, waves: p.waves,
    autonomy: p.autonomy, executable: p.executable, blocked: p.blocked, human_gates: humanGates, release_readiness: p.release,
    uncertainty_first: uncertaintyPriority(graph), activated_specialists: activated,
    dormant_specialist_count: registry.roles.size - activated.length, jit_skills: jit, node_cards: p.cards,
    plan_hash: semanticHash(body),
  };
}

/** `plan_metrics`: structural facts of a compiled plan (planned, not observed). */
export function planMetrics(plan: CompiledAgencyPlan) {
  return {
    planned_work_nodes: plan.work_orders.size, activated_specialists: plan.activated_specialists.length,
    dormant_specialists: plan.dormant_specialist_count, shared_context_refs_hoisted: plan.shared_genome_refs.length,
    dedup_hits: plan.graph.dedup_hits, held_cells: plan.waves.held.size,
  };
}

export type { BindingStatus };
