/**
 * Pure part of `agency/role_os/` that the compiled planner reuses: the
 * read-only registry view, the deterministic `RoleResolver`, the
 * `WorkOrderCompiler` and the `MissionWorkOrderAdapter`.
 *
 * Python's `RoleOSRegistry` reads and hash-verifies `runtime/role_os/*.json`.
 * That file I/O (and the manifest check) stays in Python; the twin takes the
 * already-loaded, already-verified data as `RoleOSData`. Nothing here grants
 * authority: role resolution is metadata, and consequential work compiles but
 * is never execution-ready without authority and approval refs.
 */
import { PyFloat, pyRepr, sha256Hex } from '@amc/kernel';
import {
  CompiledKeyError, MissionAdapterError, RoleResolutionError, WorkOrderError,
} from './errors';
import { compareCodePoints, compareTuples, pyLower, pyRound, pyStrip, sortStrings } from './python';

export interface RuntimeRole {
  readonly role_id: string;
  readonly title: string;
  readonly skill_name: string;
  readonly department: string;
  readonly family: string;
  readonly organizational_seniority: string;
  readonly capabilities: readonly string[];
  readonly runtime_authority: Readonly<Record<string, unknown>>;
}

export interface RuntimePhase {
  readonly phase_id: string;
  readonly orchestrator_ids: readonly string[];
  readonly output_contract: string;
}

export interface GrantContract {
  readonly required?: readonly string[];
  readonly high_consequence_requires_exact_approval_ref?: boolean;
}

/** The already-loaded, hash-verified registry files the planner consumes. */
export interface RoleOSData {
  readonly registry_hash: string;
  readonly roles: readonly RuntimeRole[];
  readonly phases: readonly RuntimePhase[];
  readonly grant_contract: GrantContract;
}

const STOPWORDS: ReadonlySet<string> = new Set([
  'and', 'of', 'the', 'for', 'to', 'a', 'an', 'in', 'with', 'role', 'work', 'manager', 'director', 'senior', 'junior',
  'lead', 'specialist', 'associate',
]);

const ALIASES: ReadonlyMap<string, string> = new Map([
  ['copywriting', 'copywriter'], ['copy', 'copywriter'], ['branding', 'brand'], ['engineering', 'engineer'],
  ['development', 'developer'], ['analytics', 'analytics'], ['measurement', 'measurement'], ['researching', 'research'],
  ['designing', 'design'], ['launch', 'release'], ['publishing', 'release'], ['publish', 'release'],
]);

const SENIORITY_PREFERENCE: ReadonlyMap<string, number> = new Map([
  ['IC', 6], ['SENIOR_IC', 5], ['MANAGEMENT', 4], ['LEADERSHIP', 3], ['EXECUTIVE', 2], ['JUNIOR', 1],
]);

function tokensOf(values: Iterable<string>): Set<string> {
  const out = new Set<string>();
  for (const value of values) {
    const slug = pyLower(pyStrip(value)).replaceAll('&', ' and ');
    for (const tok of slug.match(/[a-z0-9]+/g) ?? []) {
      if (STOPWORDS.has(tok) || tok.length <= 1) continue;
      out.add(ALIASES.get(tok) ?? tok);
    }
  }
  return out;
}

function slugOf(value: string): string {
  return (pyLower(value).match(/[a-z0-9]+/g) ?? []).join('-');
}

export interface RoleMatch {
  readonly role_id: string;
  readonly title: string;
  readonly department: string;
  readonly family: string;
  readonly score: number;
  readonly coverage: PyFloat;
  readonly matched_tokens: readonly string[];
}

export interface ResolveOptions {
  readonly department_hint?: string | null;
  readonly family_hint?: string | null;
  readonly limit?: number;
}

/** `RoleOSRegistry`: a read-only view over the loaded runtime registries. */
export class RoleOSRegistry {
  readonly roles: ReadonlyMap<string, RuntimeRole>;
  readonly phases: ReadonlyMap<string, RuntimePhase>;
  private readonly roleTokens = new Map<string, Set<string>>();

  constructor(private readonly data: RoleOSData) {
    this.roles = new Map(data.roles.map((r) => [r.role_id, r]));
    this.phases = new Map(data.phases.map((p) => [p.phase_id, p]));
  }

  get registry_hash(): string {
    return this.data.registry_hash;
  }

  get grant_contract(): GrantContract {
    return this.data.grant_contract;
  }

  getRole(roleId: string): RuntimeRole {
    const found = this.roles.get(roleId);
    if (found === undefined) throw new CompiledKeyError(pyRepr(`unknown role_id: ${roleId}`));
    return found;
  }

  getPhase(phaseId: string): RuntimePhase {
    const found = this.phases.get(phaseId);
    if (found === undefined) throw new CompiledKeyError(pyRepr(`unknown phase_id: ${phaseId}`));
    return found;
  }

  /** Canonical capability tokens plus those derived from the role's title, skill, department and family. */
  tokensFor(role: RuntimeRole): Set<string> {
    const cached = this.roleTokens.get(role.role_id);
    if (cached !== undefined) return cached;
    const tokens = new Set([...role.capabilities, ...tokensOf([role.title, role.skill_name, role.department, role.family])]);
    this.roleTokens.set(role.role_id, tokens);
    return tokens;
  }
}

function scoreRole(
  registry: RoleOSRegistry, role: RuntimeRole, query: ReadonlySet<string>, slugs: ReadonlySet<string>, options: ResolveOptions,
): RoleMatch | null {
  const roleTokens = registry.tokensFor(role);
  const matched = sortStrings([...query].filter((t) => roleTokens.has(t)));
  if (!matched.length) return null;
  let score = matched.length * 100;
  if (matched.length === query.size) score += 250;
  if (slugs.has(role.skill_name)) score += 1000;
  if (slugs.has(slugOf(role.title))) score += 900;
  if (options.department_hint && role.department === options.department_hint) score += 180;
  if (options.family_hint && role.family === options.family_hint) score += 220;
  score += SENIORITY_PREFERENCE.get(role.organizational_seniority) ?? 0;
  return {
    role_id: role.role_id, title: role.title, department: role.department, family: role.family, score,
    coverage: new PyFloat(pyRound(matched.length / query.size, 6)), matched_tokens: matched,
  };
}

/** `RoleResolver.resolve`: deterministic metadata matching; never authority. */
export function resolveRoles(registry: RoleOSRegistry, requiredCapabilities: readonly string[], options: ResolveOptions = {}): RoleMatch[] {
  if (!requiredCapabilities.length) throw new RoleResolutionError('required_capabilities must not be empty');
  const query = tokensOf(requiredCapabilities);
  if (!query.size) throw new RoleResolutionError('required_capabilities contain no resolvable tokens');
  const slugs = new Set(requiredCapabilities.map(slugOf));
  const matches: RoleMatch[] = [];
  for (const role of registry.roles.values()) {
    const match = scoreRole(registry, role, query, slugs, options);
    if (match !== null) matches.push(match);
  }
  matches.sort((a, b) => compareTuples([-a.score, -a.coverage.value, a.role_id], [-b.score, -b.coverage.value, b.role_id]));
  if (!matches.length) {
    throw new RoleResolutionError(`no role matches capabilities: [${requiredCapabilities.map(pyRepr).join(', ')}]`);
  }
  return matches.slice(0, Math.max(1, options.limit ?? 5));
}

const CONSEQUENTIAL: ReadonlySet<string> = new Set(['REVERSIBLE_WRITE', 'IRREVERSIBLE_WRITE']);
const RISK_LEVELS = ['low', 'medium', 'high', 'critical'];
const SIDE_EFFECT_CLASSES = ['PURE', 'DRAFT', 'REVERSIBLE_WRITE', 'IRREVERSIBLE_WRITE'];

const ESCAPES: Readonly<Record<string, string>> = { '"': '\\"', '\\': '\\\\', '\n': '\\n', '\r': '\\r', '\t': '\\t', '\b': '\\b', '\f': '\\f' };

function dumpString(text: string): string {
  let out = '"';
  for (const ch of text) {
    const point = ch.codePointAt(0) ?? 0;
    if (point >= 0xd800 && point <= 0xdfff) throw new WorkOrderError("'utf-8' codec can't encode character: surrogates not allowed");
    out += ESCAPES[ch] ?? (point < 0x20 ? `\\u${point.toString(16).padStart(4, '0')}` : ch);
  }
  return `${out}"`;
}

/** `_stable_id`: `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)` of a string map, SHA-256, 20 hex. */
export function stableId(prefix: string, payload: Readonly<Record<string, string>>): string {
  const body = Object.keys(payload).sort(compareCodePoints).map((k) => `${dumpString(k)}:${dumpString(payload[k] as string)}`);
  const digest = sha256Hex(new TextEncoder().encode(`{${body.join(',')}}`));
  return `${prefix}-${digest.slice(0, 20)}`;
}

export interface WorkOrderInput {
  readonly project_id: string;
  readonly mission_id: string;
  readonly phase_id: string;
  readonly objective: string;
  readonly required_capabilities: readonly string[];
  readonly acceptance_criteria: readonly string[];
  readonly input_refs?: readonly string[];
  readonly dependency_refs?: readonly string[];
  readonly required_artifact_refs?: readonly string[];
  readonly required_evidence?: readonly string[];
  readonly risk_level?: string;
  readonly side_effect_class?: string;
  readonly department_hint?: string | null;
  readonly family_hint?: string | null;
  readonly authority_refs?: readonly string[];
  readonly permission_refs?: readonly string[];
  readonly approval_refs?: readonly string[];
  readonly tool_plan?: readonly string[];
  readonly context_capsule_hash?: string | null;
  readonly expected_state_transition?: string;
  readonly next_route?: string;
}

export interface WorkOrder {
  readonly work_order_id: string;
  readonly project_id: string;
  readonly mission_id: string;
  readonly phase_id: string;
  readonly objective: string;
  readonly orchestrator_ids: readonly string[];
  readonly accountable_role_id: string;
  readonly contributor_role_ids: readonly string[];
  readonly dependency_refs: readonly string[];
  readonly required_artifact_refs: readonly string[];
  readonly input_refs: readonly string[];
  readonly output_contract: { readonly phase_output: string };
  readonly acceptance_criteria: readonly string[];
  readonly required_evidence: readonly string[];
  readonly risk_level: string;
  readonly side_effect_class: string;
  readonly tool_plan: readonly string[];
  readonly authority_refs: readonly string[];
  readonly permission_refs: readonly string[];
  readonly approval_refs: readonly string[];
  readonly verification_contract: readonly string[];
  readonly context_capsule_hash: string | null;
  readonly idempotency: { readonly logical_operation_id: string; readonly strategy: string };
  readonly retry_limit: number;
  readonly stop_conditions: readonly string[];
  readonly expected_state_transition: string;
  readonly next_route: string;
  readonly _runtime: WorkOrderRuntime;
}

export interface WorkOrderRuntime {
  readonly registry_hash: string;
  readonly role_match: RoleMatch;
  readonly execution_ready: boolean;
  readonly blockers: readonly string[];
  mission_task_id?: string;
  mission_dependency_task_ids?: readonly string[];
}

function validateWorkOrderInput(input: WorkOrderInput): void {
  const required: [string, string][] = [
    ['project_id', input.project_id], ['mission_id', input.mission_id], ['phase_id', input.phase_id], ['objective', input.objective],
  ];
  for (const [label, value] of required) if (!value || !pyStrip(value)) throw new WorkOrderError(`${label} is required`);
  const risk = input.risk_level ?? 'medium';
  if (!RISK_LEVELS.includes(risk)) throw new WorkOrderError(`invalid risk_level: ${risk}`);
  const effect = input.side_effect_class ?? 'PURE';
  if (!SIDE_EFFECT_CLASSES.includes(effect)) throw new WorkOrderError(`invalid side_effect_class: ${effect}`);
  if (!input.acceptance_criteria.length) throw new WorkOrderError('acceptance_criteria must not be empty');
}

function readiness(effect: string, risk: string, authority: readonly string[], approvals: readonly string[]): string[] {
  const blockers: string[] = [];
  if (CONSEQUENTIAL.has(effect) && !authority.length) blockers.push('MISSING_AUTHORITY_REF');
  if (effect === 'IRREVERSIBLE_WRITE' && !approvals.length) blockers.push('MISSING_EXACT_APPROVAL_REF');
  if ((risk === 'high' || risk === 'critical') && !approvals.length) blockers.push('MISSING_HIGH_RISK_APPROVAL_REF');
  return blockers;
}

function resolveOrFail(registry: RoleOSRegistry, input: WorkOrderInput): RoleMatch {
  try {
    const matches = resolveRoles(registry, input.required_capabilities, {
      department_hint: input.department_hint, family_hint: input.family_hint, limit: 1,
    });
    return matches[0] as RoleMatch;
  } catch (error) {
    if (error instanceof RoleResolutionError) throw new WorkOrderError(error.message);
    throw error;
  }
}

function phaseOrFail(registry: RoleOSRegistry, phaseId: string): RuntimePhase {
  try {
    return registry.getPhase(phaseId);
  } catch (error) {
    if (error instanceof CompiledKeyError) throw new WorkOrderError(error.message);
    throw error;
  }
}

/** `WorkOrderCompiler.compile`: a bounded, role-resolved work order that manufactures no authority. */
export function compileWorkOrder(registry: RoleOSRegistry, input: WorkOrderInput): WorkOrder {
  validateWorkOrderInput(input);
  const phase = phaseOrFail(registry, input.phase_id);
  const match = resolveOrFail(registry, input);
  const effect = input.side_effect_class ?? 'PURE';
  const risk = input.risk_level ?? 'medium';
  const authority = [...(input.authority_refs ?? [])];
  const approvals = [...(input.approval_refs ?? [])];
  const blockers = readiness(effect, risk, authority, approvals);
  const basis = {
    project_id: input.project_id, mission_id: input.mission_id, phase_id: input.phase_id, objective: input.objective,
    accountable_role_id: match.role_id, registry_hash: registry.registry_hash,
  };
  return {
    work_order_id: stableId('wo', basis),
    project_id: input.project_id, mission_id: input.mission_id, phase_id: input.phase_id, objective: input.objective,
    orchestrator_ids: [...phase.orchestrator_ids], accountable_role_id: match.role_id, contributor_role_ids: [],
    dependency_refs: [...(input.dependency_refs ?? [])], required_artifact_refs: [...(input.required_artifact_refs ?? [])],
    input_refs: [...(input.input_refs ?? [])], output_contract: { phase_output: phase.output_contract },
    acceptance_criteria: [...input.acceptance_criteria], required_evidence: [...(input.required_evidence ?? [])],
    risk_level: risk, side_effect_class: effect, tool_plan: [...(input.tool_plan ?? [])], authority_refs: authority,
    permission_refs: [...(input.permission_refs ?? [])], approval_refs: approvals,
    verification_contract: [
      'validate output against acceptance_criteria', 'verify dependency refs are current',
      'verify accountable role exists in registry', 'verify authority immediately before consequential execution',
    ],
    context_capsule_hash: input.context_capsule_hash ?? null,
    idempotency: {
      logical_operation_id: stableId('op', { ...basis, side_effect_class: effect }),
      strategy: effect !== 'PURE' ? 'CONTENT_HASH' : 'NONE',
    },
    retry_limit: 3,
    stop_conditions: [
      'acceptance criteria pass', 'retry limit exhausted', 'required authority or approval missing', 'dependency becomes stale',
    ],
    expected_state_transition: input.expected_state_transition ?? 'ACTIVE', next_route: input.next_route ?? 'VALIDATE',
    _runtime: { registry_hash: registry.registry_hash, role_match: match, execution_ready: blockers.length === 0, blockers },
  };
}

export interface MissionCapability {
  readonly id: string;
  readonly skills?: readonly string[];
  readonly context_refs?: readonly string[];
}

export interface MissionNode {
  readonly id: string;
  readonly capability: string;
  readonly description?: string;
  readonly dependencies?: readonly string[];
  readonly produces?: readonly string[];
  readonly verification?: readonly string[];
  readonly execution_mode?: string;
  readonly tool?: string | null;
}

export interface MissionPayload {
  readonly mission_id: string;
  readonly capabilities: readonly MissionCapability[];
  readonly task_graph: { readonly nodes: readonly MissionNode[] };
  readonly acceptance_contracts?: readonly { readonly artifact_id: string; readonly criterion: string }[];
}

export interface CompiledMissionWorkOrders {
  readonly mission_id: string;
  readonly registry_hash: string;
  readonly work_orders: readonly WorkOrder[];
  readonly task_to_work_order: ReadonlyMap<string, string>;
}

function roleResolutionTerms(cap: MissionCapability): string[] {
  const terms: string[] = [];
  for (const ref of cap.context_refs ?? []) {
    if (ref.startsWith('agency-role:')) terms.push(ref.slice('agency-role:'.length).replaceAll('_', '-'));
  }
  for (const skill of cap.skills ?? []) terms.push(skill.replaceAll('_', '-'));
  if (!terms.length) terms.push(cap.id);
  return terms.filter((t) => t);
}

function missionSideEffect(node: MissionNode): string {
  const mode = (node.execution_mode ?? '').toUpperCase();
  const tool = (node.tool ?? '').toLowerCase();
  return mode === 'HUMAN' || tool.startsWith('approval.') ? 'REVERSIBLE_WRITE' : 'PURE';
}

function checkPhaseMap(nodes: readonly MissionNode[], phaseMap: ReadonlyMap<string, string>): void {
  const known = new Set(nodes.map((n) => n.id));
  const missing = sortStrings([...known].filter((t) => !phaseMap.has(t)));
  if (missing.length) throw new MissionAdapterError(`phase_map missing task ids: [${missing.map(pyRepr).join(', ')}]`);
  const unknown = sortStrings([...phaseMap.keys()].filter((t) => !known.has(t)));
  if (unknown.length) throw new MissionAdapterError(`phase_map contains unknown task ids: [${unknown.map(pyRepr).join(', ')}]`);
}

function acceptanceIndex(mission: MissionPayload): Map<string, string[]> {
  const out = new Map<string, string[]>();
  for (const item of mission.acceptance_contracts ?? []) {
    if (item.artifact_id && item.criterion) out.set(item.artifact_id, [...(out.get(item.artifact_id) ?? []), item.criterion]);
  }
  return out;
}

export interface MissionRefs {
  readonly authority?: ReadonlyMap<string, readonly string[]>;
  readonly permission?: ReadonlyMap<string, readonly string[]>;
  readonly approval?: ReadonlyMap<string, readonly string[]>;
}

function phaseOf(phaseMap: ReadonlyMap<string, string>, taskId: string): string {
  const phase = phaseMap.get(taskId);
  if (phase === undefined) throw new CompiledKeyError(pyRepr(taskId));
  return phase;
}

function compileTask(
  registry: RoleOSRegistry, mission: MissionPayload, node: MissionNode, projectId: string,
  phaseMap: ReadonlyMap<string, string>, criteriaIndex: ReadonlyMap<string, string[]>, refs: MissionRefs, capsule: string | null,
): WorkOrder {
  const cap = mission.capabilities.find((c) => c.id === node.capability);
  if (cap === undefined) throw new MissionAdapterError(`task ${node.id} references unknown capability ${node.capability}`);
  const produces = [...(node.produces ?? [])];
  let criteria = produces.flatMap((a) => criteriaIndex.get(a) ?? []);
  if (!criteria.length) criteria = (node.verification ?? []).filter((x) => pyStrip(x));
  if (!criteria.length) throw new MissionAdapterError(`task ${node.id} has no acceptance/verification criteria`);
  try {
    return compileWorkOrder(registry, {
      project_id: projectId, mission_id: mission.mission_id, phase_id: phaseOf(phaseMap, node.id),
      objective: node.description || node.id, required_capabilities: roleResolutionTerms(cap), acceptance_criteria: criteria,
      dependency_refs: [...(node.dependencies ?? [])], required_artifact_refs: produces,
      required_evidence: [...(node.verification ?? [])],
      risk_level: (node.execution_mode ?? '').toUpperCase() === 'HUMAN' ? 'high' : 'medium',
      side_effect_class: missionSideEffect(node), authority_refs: [...(refs.authority?.get(node.id) ?? [])],
      permission_refs: [...(refs.permission?.get(node.id) ?? [])], approval_refs: [...(refs.approval?.get(node.id) ?? [])],
      tool_plan: node.tool ? [node.tool] : [], context_capsule_hash: capsule, expected_state_transition: 'VALIDATE',
      next_route: 'VALIDATE',
    });
  } catch (error) {
    if (error instanceof WorkOrderError) throw new MissionAdapterError(`failed to compile task ${node.id}: ${error.message}`);
    throw error;
  }
}

/** `MissionWorkOrderAdapter.compile`: bind a validated mission payload to work orders with an explicit phase map. */
export function compileMission(
  registry: RoleOSRegistry, mission: MissionPayload, projectId: string, phaseMap: ReadonlyMap<string, string>,
  refs: MissionRefs = {}, contextCapsuleHash: string | null = null,
): CompiledMissionWorkOrders {
  const missionId = pyStrip(mission.mission_id);
  if (!missionId) throw new MissionAdapterError('mission_id is required');
  const nodes = mission.task_graph.nodes;
  if (!nodes.length) throw new MissionAdapterError('mission.task_graph.nodes must be a non-empty array');
  checkPhaseMap(nodes, phaseMap);
  const criteriaIndex = acceptanceIndex(mission);
  const orders = nodes.map((n) => {
    const taskId = pyStrip(n.id);
    if (!taskId) throw new MissionAdapterError('task id is required');
    const wo = compileTask(registry, { ...mission, mission_id: missionId }, { ...n, id: taskId }, projectId, phaseMap, criteriaIndex, refs, contextCapsuleHash);
    wo._runtime.mission_task_id = taskId;
    return wo;
  });
  const taskToWo = new Map(orders.map((wo) => [wo._runtime.mission_task_id as string, wo.work_order_id]));
  const resolved = orders.map((wo) => {
    const original = [...wo.dependency_refs];
    wo._runtime.mission_dependency_task_ids = original;
    const deps = original.map((d) => {
      const id = taskToWo.get(d);
      if (id === undefined) throw new CompiledKeyError(pyRepr(d));
      return id;
    });
    return { ...wo, dependency_refs: deps };
  });
  return { mission_id: missionId, registry_hash: registry.registry_hash, work_orders: resolved, task_to_work_order: taskToWo };
}
