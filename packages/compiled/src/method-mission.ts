/**
 * Twin of `agency/compiled/method_mission.py`: MethodPlan → mission → canonical
 * work orders → cells/waves. This is the delegation boundary. It reuses the
 * work-order compiler (`roleos.ts`), the CausalWorkGraph and the cell/wave
 * scheduler; it re-implements none of them.
 *
 * No generic executor consumes compiled work orders in this codebase, so every
 * compiled mission reports `EXECUTOR_GAP`. Nothing here runs a node. Envelopes
 * carry no authority or approval refs, the adapter is given none, and a
 * ProofOfNonAuthority per node checks the work order holds exactly what the
 * envelope held (delta 0): consequential nodes compile but are never
 * execution-ready, whatever their routing score.
 */
import { pyRepr } from '@amc/kernel';
import {
  CausalWorkGraph, finalizeNode, topological, type BackchainNode, type RawNode,
} from './backchain';
import { CompiledKeyError, MethodCompileError, MissionAdapterError } from './errors';
import { buildCell, scheduleWaves, waveHash, type MissionCell, type Wave, type WavePlan } from './execution';
import { semanticHash, type HashValue } from './hashing';
import type { MethodCatalog } from './method-catalog';
import {
  MAX_PLAN_REPAIRS, MAX_RETRIEVAL_PASSES, MAX_SPECIALISTS_PER_WAVE, MAX_TASK_RETRIES, type DelegationEnvelope, type MethodPlan,
} from './method-models';
import { envelopeContextHash } from './method-router';
import { sortStrings } from './python';
import {
  compileMission, type MissionCapability, type MissionNode, type MissionPayload, type RoleOSRegistry, type WorkOrder,
} from './roleos';

export const EXECUTOR_GAP = 'EXECUTOR_GAP';
/** Tools the method layer may plan to call. None are registered: any tool use would need a reviewed adapter. */
export const AVAILABLE_TOOLS: ReadonlySet<string> = new Set();

export interface ProofOfNonAuthority {
  readonly node_id: string;
  readonly routing_score_used: number;
  readonly authority_source_refs: readonly string[];
  readonly authority_before: readonly string[];
  readonly authority_after: readonly string[];
  readonly authority_delta: 0;
}

export interface NodeEligibility {
  readonly node_id: string;
  readonly capability_match: boolean;
  readonly schema_valid: boolean;
  readonly tool_available: boolean;
  readonly permission_valid: boolean;
  readonly authority_valid_if_required: boolean;
  readonly approval_valid_if_required: boolean;
  readonly dependencies_current: boolean;
  readonly policy_pass: boolean;
  readonly blockers: readonly string[];
}

export const eligibleToExecute = (e: NodeEligibility): boolean => !e.blockers.length;

export interface CompiledMethodMission {
  readonly plan_hash: string;
  readonly mission: MissionPayload;
  readonly phase_map: ReadonlyMap<string, string>;
  readonly work_orders: readonly WorkOrder[];
  readonly task_to_work_order: ReadonlyMap<string, string>;
  readonly eligibility: readonly NodeEligibility[];
  readonly non_authority_proofs: readonly ProofOfNonAuthority[];
  readonly graph: CausalWorkGraph;
  readonly cells: ReadonlyMap<string, MissionCell>;
  readonly wave_plan: WavePlan;
  readonly blocked_nodes: ReadonlyMap<string, readonly string[]>;
  readonly executor_status: string;
  readonly executor_reason: string;
}

const CONSEQUENTIAL = new Set(['REVERSIBLE_WRITE', 'IRREVERSIBLE_WRITE']);

/** The canonical mission payload plus an explicit phase_map. Phase comes from the problem family, never from prose. */
export function missionProjection(plan: MethodPlan, catalog: MethodCatalog): [MissionPayload, Map<string, string>] {
  if (!plan.delegation_envelopes.length) throw new MethodCompileError('PLAN_EMPTY', 'the method plan has no delegation envelopes');
  const capabilities = new Map<string, MissionCapability>();
  const nodes: MissionNode[] = [];
  const acceptance: { artifact_id: string; criterion: string }[] = [];
  const phaseMap = new Map<string, string>();
  for (const env of plan.delegation_envelopes) {
    const family = catalog.families.get(env.problem_family);
    if (family === undefined) throw new CompiledKeyError(pyRepr(env.problem_family));
    const capId = `cap:${family.family_id}`;
    capabilities.set(capId, { id: capId, skills: [...family.capability_terms] });
    const produces = env.expected_outputs.map((tag) => `${env.node_id}#${tag}`);
    nodes.push({
      id: env.node_id, capability: capId, description: env.objective, dependencies: [...env.dependencies], produces,
      verification: [...env.acceptance_criteria], execution_mode: CONSEQUENTIAL.has(env.side_effect_class) ? 'HUMAN' : 'AGENT',
      tool: env.tool_plan[0] ?? null,
    });
    const shared = Math.min(produces.length, env.acceptance_criteria.length);
    for (let i = 0; i < shared; i += 1) acceptance.push({ artifact_id: produces[i] as string, criterion: env.acceptance_criteria[i] as string });
    phaseMap.set(env.node_id, family.phase_id);
  }
  const mission: MissionPayload = {
    mission_id: `mission-${plan.plan_hash.slice(0, 20)}`,
    capabilities: sortStrings(capabilities.keys()).map((k) => capabilities.get(k) as MissionCapability),
    task_graph: { nodes }, acceptance_contracts: acceptance,
  };
  return [mission, phaseMap];
}

/** Node ids whose recorded context hash no longer matches its inputs; the stale set is the causal closure. */
export function verifyContextChain(plan: MethodPlan): string[] {
  const recomputed = new Map<string, string>();
  const stale: string[] = [];
  for (const env of plan.delegation_envelopes) {
    const digest = envelopeContextHash(env, recomputed);
    recomputed.set(env.node_id, digest);
    if (digest !== env.context_hash) stale.push(env.node_id);
  }
  return stale;
}

/** Nodes to invalidate and recompile when `changed` nodes change, in plan order. */
export function causalClosure(plan: MethodPlan, changed: Iterable<string>): string[] {
  const dependents = new Map<string, Set<string>>();
  for (const env of plan.delegation_envelopes) {
    for (const dep of env.dependencies) dependents.set(dep, (dependents.get(dep) ?? new Set<string>()).add(env.node_id));
  }
  const start = [...changed];
  const seen = new Set(start);
  const frontier = [...start];
  while (frontier.length) {
    for (const next of dependents.get(frontier.pop() as string) ?? []) {
      if (!seen.has(next)) {
        seen.add(next);
        frontier.push(next);
      }
    }
  }
  return plan.delegation_envelopes.map((e) => e.node_id).filter((n) => seen.has(n));
}

function eligibilityFor(env: DelegationEnvelope, wo: WorkOrder, stale: ReadonlySet<string>): NodeEligibility {
  const blockers = [...wo._runtime.blockers];
  const toolOk = env.tool_plan.every((t) => AVAILABLE_TOOLS.has(t));
  if (!toolOk) blockers.push('TOOL_UNAVAILABLE');
  const depsCurrent = !stale.has(env.node_id) && !env.dependencies.some((d) => stale.has(d));
  if (!depsCurrent) blockers.push('DEPENDENCY_OR_CONTEXT_STALE');
  const consequential = CONSEQUENTIAL.has(env.side_effect_class);
  const authorityOk = !consequential || wo.authority_refs.length > 0;
  const approvalNeeded = env.side_effect_class === 'IRREVERSIBLE_WRITE' || env.risk_level === 'high' || env.risk_level === 'critical';
  const approvalOk = !approvalNeeded || wo.approval_refs.length > 0;
  const permissionOk = !consequential || wo.permission_refs.length > 0;
  if (!permissionOk) blockers.push('MISSING_PERMISSION_REF');
  if (!approvalOk) blockers.push('MISSING_EXACT_APPROVAL_REF');
  return {
    node_id: env.node_id, capability_match: wo._runtime.role_match.matched_tokens.length > 0, schema_valid: true,
    tool_available: toolOk, permission_valid: permissionOk, authority_valid_if_required: authorityOk,
    approval_valid_if_required: approvalOk, dependencies_current: depsCurrent,
    // Irreversible work never runs on policy defaults: it needs an exact approval.
    policy_pass: env.side_effect_class !== 'IRREVERSIBLE_WRITE' || approvalOk, blockers: sortStrings(new Set(blockers)),
  };
}

function proofFor(env: DelegationEnvelope, wo: WorkOrder): ProofOfNonAuthority {
  const before = sortStrings(new Set([...env.authority_refs, ...env.approval_refs]));
  const after = sortStrings(new Set([...wo.authority_refs, ...wo.approval_refs, ...wo.permission_refs]));
  const gained = sortStrings(after.filter((r) => !before.includes(r)));
  if (gained.length) throw new MethodCompileError('ROUTER_AUTHORITY_ESCALATION', `${env.node_id} gained authority [${gained.map(pyRepr).join(', ')}]`);
  return {
    node_id: env.node_id, routing_score_used: wo._runtime.role_match.score, authority_source_refs: before,
    authority_before: before, authority_after: after, authority_delta: 0,
  };
}

function methodGraph(plan: MethodPlan, phaseMap: ReadonlyMap<string, string>, eligibility: ReadonlyMap<string, NodeEligibility>): CausalWorkGraph {
  const nodes = new Map<string, BackchainNode>();
  for (const env of plan.delegation_envelopes) {
    const gate = eligibility.get(env.node_id) as NodeEligibility;
    const phase = phaseMap.get(env.node_id) as string;
    const raw: RawNode = {
      id: env.node_id, type: 'EXECUTABLE_WORK', purpose: env.objective, satisfies: env.justified_by,
      hard_dependencies: env.dependencies, phase_compatibility: [phase], required_capabilities: env.required_capabilities,
      validation_obligations: env.acceptance_criteria, side_effect_class: env.side_effect_class,
      mutation_targets: env.mutation_targets, status: gate.blockers.length ? 'BLOCKED' : 'PLANNED',
      resolution: 'EXECUTABLE_WORK', stage: phase, blockers: gate.blockers,
    };
    nodes.set(env.node_id, finalizeNode(raw));
  }
  const order = topological(nodes);
  const depended = new Set([...nodes.values()].flatMap((n) => n.dependencies));
  const roots = sortStrings([...nodes.keys()].filter((n) => !depended.has(n)));
  const hashes: Record<string, HashValue> = {};
  for (const [id, n] of nodes) hashes[id] = n.semantic_hash;
  const eliminated = sortStrings(plan.method_stack.excluded_methods.map((e) => e.method_id));
  return new CausalWorkGraph(nodes, roots, order, eliminated, [], 0, semanticHash(hashes));
}

function capWaves(plan: WavePlan): WavePlan {
  const waves: Wave[] = [];
  for (const wave of plan.waves) {
    for (let start = 0; start < wave.cells.length; start += MAX_SPECIALISTS_PER_WAVE) {
      const reason = start === 0 ? wave.serialized_reason : 'MAX_SPECIALISTS_PER_WAVE';
      waves.push({ index: waves.length, cells: wave.cells.slice(start, start + MAX_SPECIALISTS_PER_WAVE), serialized_reason: reason });
    }
  }
  if (waves.length === plan.waves.length) return plan;
  return { waves, held: plan.held, wave_hash: waveHash(waves, plan.held) };
}

function buildCells(plan: MethodPlan, graph: CausalWorkGraph, byTask: ReadonlyMap<string, WorkOrder>, eligibility: ReadonlyMap<string, NodeEligibility>) {
  const cells = new Map<string, MissionCell>();
  const cellForNode = new Map<string, string>();
  for (const env of plan.delegation_envelopes) {
    const wo = byTask.get(env.node_id) as WorkOrder;
    const cell = buildCell({
      graph, work_node_id: env.node_id, accountable_specialist: wo.accountable_role_id, contributor_specialists: [],
      binding_hash: semanticHash({ role: wo.accountable_role_id, authority: [...wo.authority_refs] }),
      work_order_ids: [wo.work_order_id], capsule_hash: plan.plan_hash, validators: ['acceptance_criteria'],
      resource_locks: env.mutation_targets, risk_class: wo.risk_level, approval_refs: wo.approval_refs,
      blockers: (eligibility.get(env.node_id) as NodeEligibility).blockers,
    });
    cells.set(cell.cell_id, cell);
    cellForNode.set(env.node_id, cell.cell_id);
  }
  return { cells, cellForNode };
}

const GAP_REASON = 'No generic executor consumes compiled work orders or mission cells in this codebase; '
  + 'schedule_waves/advance_cell are planning-time only. The plan, work orders and waves are '
  + 'complete and callable; execution needs a reviewed runtime.';

function adaptMission(registry: RoleOSRegistry, mission: MissionPayload, projectId: string, phaseMap: ReadonlyMap<string, string>, planHash: string) {
  try {
    return compileMission(registry, mission, projectId, phaseMap, {}, planHash);
  } catch (error) {
    if (!(error instanceof MissionAdapterError)) throw error;
    const gap = error.message.includes('no role matches') || error.message.includes('no resolvable tokens');
    throw new MethodCompileError(gap ? 'CAPABILITY_GAP' : 'MISSION_INVALID', error.message);
  }
}

/** `compile_method_mission`. Plan-only: it always reports EXECUTOR_GAP. */
export function compileMethodMission(plan: MethodPlan, registry: RoleOSRegistry, projectId: string, catalog: MethodCatalog): CompiledMethodMission {
  const [mission, phaseMap] = missionProjection(plan, catalog);
  const compiled = adaptMission(registry, mission, projectId, phaseMap, plan.plan_hash);
  const stale = new Set(verifyContextChain(plan));
  const byTask = new Map(compiled.work_orders.map((wo) => [wo._runtime.mission_task_id as string, wo]));
  const task = (id: string): WorkOrder => {
    const found = byTask.get(id);
    if (found === undefined) throw new CompiledKeyError(pyRepr(id));
    return found;
  };
  const eligibility = new Map(plan.delegation_envelopes.map((env) => [env.node_id, eligibilityFor(env, task(env.node_id), stale)]));
  const proofs = plan.delegation_envelopes.map((env) => proofFor(env, task(env.node_id)));
  const graph = methodGraph(plan, phaseMap, eligibility);
  const { cells, cellForNode } = buildCells(plan, graph, byTask, eligibility);
  const waves = capWaves(scheduleWaves(graph, cells, cellForNode));
  return {
    plan_hash: plan.plan_hash, mission, phase_map: phaseMap, work_orders: compiled.work_orders,
    task_to_work_order: compiled.task_to_work_order,
    eligibility: plan.delegation_envelopes.map((e) => eligibility.get(e.node_id) as NodeEligibility),
    non_authority_proofs: proofs, graph, cells, wave_plan: waves, blocked_nodes: waves.held, executor_status: EXECUTOR_GAP,
    executor_reason: GAP_REASON,
  };
}

export interface MutationKeyInput {
  readonly tenant_id: string;
  readonly project_id: string;
  readonly mission_id: string;
  readonly node_id: string;
  readonly operation: string;
  readonly input_hash: string;
}

/** Stable semantic identity for a node's mutation: never time or randomness. */
export function mutationKey(input: MutationKeyInput): string {
  return semanticHash({
    tenant: input.tenant_id, project: input.project_id, mission: input.mission_id, node: input.node_id,
    operation: input.operation, input_hash: input.input_hash,
  });
}

export type FailureClass = 'TRANSIENT' | 'ACCEPTANCE' | 'AUTHORITY' | 'DEPENDENCY_STALE' | 'TOOL_UNAVAILABLE';
export type NextAction = 'DONE' | 'RETRY' | 'REPAIR' | 'RECLASSIFY_PROBLEM' | 'INVALIDATE_AND_RECOMPILE' | 'ESCALATE_HUMAN';

export interface Attempt {
  readonly succeeded: boolean;
  readonly failure_class: FailureClass | null;
  readonly failure_fingerprint: string | null;
  /** Contract progress measured after the attempt; null when nothing was measured. */
  readonly progress: number | null;
  readonly retrieval_new_evidence: boolean | null;
}

export interface NextStep {
  readonly action: NextAction;
  readonly reason: string;
}

const step = (action: NextAction, reason: string): NextStep => ({ action, reason });

function escalation(history: readonly Attempt[]): NextStep | null {
  const prints = history.map((a) => a.failure_fingerprint).filter((f): f is string => Boolean(f));
  if (prints.length >= 2 && prints[prints.length - 1] === prints[prints.length - 2]) {
    return step('ESCALATE_HUMAN', 'CIRCUIT_BREAKER:SAME_FAILURE_TWICE');
  }
  const retrievals = history.map((a) => a.retrieval_new_evidence).filter((r): r is boolean => r !== null);
  if (retrievals.length >= MAX_RETRIEVAL_PASSES) return step('ESCALATE_HUMAN', 'RETRIEVAL_BUDGET_EXHAUSTED');
  if (retrievals.length >= 2 && !retrievals[retrievals.length - 1] && !retrievals[retrievals.length - 2]) {
    return step('ESCALATE_HUMAN', 'NO_NEW_EVIDENCE_TWICE');
  }
  return null;
}

function classified(last: Attempt, history: readonly Attempt[]): NextStep | null {
  if (last.failure_class === 'AUTHORITY') return step('ESCALATE_HUMAN', 'AUTHORITY_OR_APPROVAL_MISSING');
  if (last.failure_class === 'TOOL_UNAVAILABLE') return step('ESCALATE_HUMAN', 'TOOL_UNAVAILABLE');
  if (last.failure_class === 'DEPENDENCY_STALE') return step('INVALIDATE_AND_RECOMPILE', 'RECOMPILE_CAUSAL_CLOSURE_ONLY');
  const progress = history.map((a) => a.progress).filter((p): p is number => p !== null);
  // Method drift: valid work that no longer moves the outcome means the problem model is wrong.
  if (progress.length >= 3 && (progress[progress.length - 1] as number) <= (progress[progress.length - 3] as number)) {
    return step('RECLASSIFY_PROBLEM', 'NO_MEASURABLE_PROGRESS');
  }
  if (last.failure_class === 'ACCEPTANCE') {
    const repairs = history.filter((a) => a.failure_class === 'ACCEPTANCE').length;
    return repairs > MAX_PLAN_REPAIRS ? step('ESCALATE_HUMAN', 'REPAIR_BUDGET_EXHAUSTED') : step('REPAIR', 'REPAIR_SMALLEST_CAUSAL_PRODUCER');
  }
  return null;
}

/** `next_step(envelope, history)`: decide what follows an attempt history; every path is bounded. */
export function nextStep(envelope: Pick<DelegationEnvelope, 'retry_limit'>, history: readonly Attempt[]): NextStep {
  const last = history[history.length - 1];
  if (last === undefined) return step('RETRY', 'FIRST_ATTEMPT');
  if (last.succeeded) return step('DONE', 'ACCEPTANCE_PASS');
  const stopped = escalation(history) ?? classified(last, history);
  if (stopped !== null) return stopped;
  // TRANSIENT (or unclassified) failure.
  if (envelope.retry_limit === 0) return step('ESCALATE_HUMAN', 'NO_AUTOMATIC_RETRY_FOR_THIS_SIDE_EFFECT_CLASS');
  const failures = history.filter((a) => !a.succeeded).length;
  if (failures > Math.min(envelope.retry_limit, MAX_TASK_RETRIES)) return step('ESCALATE_HUMAN', 'RETRY_BUDGET_EXHAUSTED');
  return step('RETRY', 'TRANSIENT_FAILURE');
}
