/**
 * Maps each fixture `call` name to the `@amc/compiled` function it exercises. Arguments arrive
 * as the tagged JSON the Python test recorded.
 */
import { ARTIFACT_TYPES, PyFloat, pyRepr, type ArtifactType } from '@amc/kernel';
import type { z } from 'zod';
import * as C from '../src/index';
import methodsFx from './fixtures/compiled-methods.json';
import plansFx from './fixtures/compiled-plans.json';

export interface FixtureCase {
  readonly call: string;
  readonly args: unknown[];
  readonly ok?: unknown;
  readonly error?: { type: string; message?: string; locs?: string[] };
  readonly ts_refuses?: string;
  readonly loose?: boolean;
}

type Fn = (a: unknown[]) => unknown;
type Rec = Record<string, unknown>;

const str = (v: unknown): string => v as string;
const strs = (v: unknown): string[] => v as string[];
const rec = (v: unknown): Rec => v as Rec;
const recs = (v: unknown): Rec[] => v as Rec[];

function decode(node: unknown): C.HashValue {
  if (Array.isArray(node)) return node.map(decode);
  if (node === null || typeof node !== 'object') return node as C.HashValue;
  const entries = Object.entries(node);
  if (entries.length === 1) {
    const [tag, raw] = entries[0] as [string, unknown];
    if (tag === '$float') return new PyFloat(Number(raw));
    if (tag === '$int') return BigInt(str(raw));
    if (tag === '$set') return new Set((raw as unknown[]).map(decode));
  }
  return Object.fromEntries(entries.map(([k, v]) => [k, decode(v)])) as C.HashValue;
}

function errRecord(error: unknown): Rec {
  if (error instanceof C.CompiledValidationError) {
    return { type: 'ValidationError', locs: [...new Set(error.issues.map((i) => C.locKey(i.loc)))].sort() };
  }
  if (!(error instanceof Error)) throw error;
  return { type: error.name, message: error.message };
}

function steps(items: unknown[], run: (op: string, rest: unknown[]) => unknown): Rec[] {
  return items.map((step) => {
    const [op, ...rest] = step as [string, ...unknown[]];
    try {
      return { ok: C.toPlain(run(op, rest)) };
    } catch (error) {
      return { error: errRecord(error) };
    }
  });
}

const map = (v: unknown): Map<string, string> => new Map(Object.entries(rec(v)).map(([k, x]) => [k, str(x)]));
const enumValue = <T extends string>(members: readonly T[], v: unknown, name: string): T => C.enumMember(members, v, name);
const artifact = (v: unknown): ArtifactType => {
  const known = (ARTIFACT_TYPES as readonly string[]).includes(str(v));
  if (!known) throw new C.CompiledValueError(`${pyRepr(str(v))} is not a valid ArtifactType`);
  return v as ArtifactType;
};

function list<S extends z.ZodType>(schema: S, model: string, items: unknown): z.output<S>[] {
  return (items as unknown[]).map((i) => C.parseModel(schema, model, i));
}

// ---- registries -----------------------------------------------------------------------

interface Compact {
  registry_hash: string;
  roles: [string, string, string, string, string, string, string[], number][];
  authorities: Rec[];
  phases: [string, string[], string][];
  grant_contract: C.GrantContract;
}
interface Variant { registry_hash: string; grant_contract: C.GrantContract; authority_edits: Record<string, Rec> }

const regs = new Map<string, C.RoleOSRegistry>();

function registry(name: string): C.RoleOSRegistry {
  const cached = regs.get(name);
  if (cached) return cached;
  const fx = (plansFx as unknown as { registries: [Record<string, unknown>] }).registries[0];
  const sealed = fx['sealed'] as Compact;
  const variant = name === 'sealed' ? null : (fx[name] as Variant);
  const roles: C.RuntimeRole[] = sealed.roles.map(([role_id, title, skill_name, department, family, seniority, caps, auth]) => ({
    role_id, title, skill_name, department, family, organizational_seniority: seniority, capabilities: caps,
    runtime_authority: { ...(sealed.authorities[auth] as Rec), ...(variant?.authority_edits[skill_name] ?? {}) },
  }));
  const data: C.RoleOSData = {
    registry_hash: variant?.registry_hash ?? sealed.registry_hash, roles,
    phases: sealed.phases.map(([phase_id, orchestrator_ids, output_contract]) => ({ phase_id, orchestrator_ids, output_contract })),
    grant_contract: variant?.grant_contract ?? sealed.grant_contract,
  };
  const built = new C.RoleOSRegistry(data);
  regs.set(name, built);
  return built;
}

const catalogRaw = (): Rec => (methodsFx as unknown as { catalog: Rec[] }).catalog[0] as Rec;
let catalogCache: C.MethodCatalog | null = null;
const catalog = (): C.MethodCatalog => (catalogCache ??= C.parseCatalog(catalogRaw()));

// ---- helpers mirroring the Python builders ----------------------------------------------

const CAMPAIGN = {
  id: 'dcampaign', requested_outcome: 'Outcome campaign', output_contract: 'campaign_package',
  acceptance_criteria: ['on-brief', 'brand-safe'], domains: ['BRAND', 'CONTENT'],
};
const CAMPAIGN_EVIDENCE = ['research_brief', 'market_analysis', 'positioning_statement', 'brand_core', 'brand_platform', 'identity_guidelines']
  .flatMap((a) => [0, 1, 2].map((i) => ({ ref: `ev:${a}:${i}`, supports: [a], verified: true })));

function compile(deliverables: unknown, existing: unknown, accepted: unknown, evidence: unknown): C.CausalWorkGraph {
  return C.compileBackchain(list(C.DeliverableSpecSchema, 'DeliverableSpec', deliverables), {
    existing_artifacts: map(existing), accepted_decisions: map(accepted), evidence: list(C.EvidenceItemSchema, 'EvidenceItem', evidence),
  });
}

function campaignGraph(accepted: Rec = {}): C.CausalWorkGraph {
  return compile([CAMPAIGN], {}, accepted, CAMPAIGN_EVIDENCE);
}

function backchainExtras(g: C.CausalWorkGraph) {
  const ids = [...g.nodes.keys()];
  const sorted = (s: Iterable<string>): string[] => C.sortStrings(s);
  return {
    unresolved: C.unresolvedLeaves(g), work_nodes: g.workNodes().map((n) => n.id),
    ancestors: Object.fromEntries(ids.map((n) => [n, sorted(g.ancestors(n))])),
    descendants: Object.fromEntries(ids.map((n) => [n, sorted(g.descendants([n]))])),
    dependents: Object.fromEntries([...g.dependents()].map(([n, s]) => [n, sorted(s)])),
  };
}

function backchainDigest(g: C.CausalWorkGraph) {
  const nodes = [...g.nodes];
  const hashed = (f: (id: string) => C.HashValue): string => C.semanticHash(Object.fromEntries(nodes.map(([id]) => [id, f(id)])));
  return {
    graph_hash: g.graph_hash, roots: g.roots, topological_order: g.topological_order, eliminated: g.eliminated,
    redundant_candidates: g.redundant_candidates, dedup_hits: g.dedup_hits,
    node_hashes: Object.fromEntries(nodes.map(([id, n]) => [id, n.semantic_hash])),
    node_status: Object.fromEntries(nodes.map(([id, n]) => [id, [n.status, n.resolution]])),
    purposes: hashed((id) => g.node(id).purpose), unresolved: C.unresolvedLeaves(g), work_nodes: g.workNodes().map((n) => n.id),
    closure: hashed((id) => C.sortStrings(g.ancestors(id))), descendants: hashed((id) => C.sortStrings(g.descendants([id]))),
  };
}

function planDigest(plan: C.CompiledAgencyPlan) {
  const obj = <T, V>(m: ReadonlyMap<string, T>, f: (v: T) => V): Record<string, V> => Object.fromEntries([...m].map(([k, v]) => [k, f(v)]));
  return {
    plan_hash: plan.plan_hash, graph_hash: plan.graph.graph_hash, node_count: plan.graph.nodes.size, overlays: plan.overlays,
    genome_hash: plan.genome_hash, registry_hash: plan.registry_hash,
    bindings: obj(plan.bindings, (b) => [b.binding_hash, b.status, b.specialist_role_id, b.side_effect_ceiling]),
    capsules: obj(plan.capsules, (c) => c.capsule_hash),
    work_orders: obj(plan.work_orders, (w) => [w.work_order_hash, w.execution_ready, w.blockers]),
    cells: obj(plan.cells, (c) => [C.cellHash(c), c.status, c.blockers]),
    waves: plan.waves.waves.map((w) => [w.index, w.cells, w.serialized_reason]), held: plan.waves.held, wave_hash: plan.waves.wave_hash,
    autonomy: obj(plan.autonomy, (a) => [a.route, a.level, a.reasons]), executable: plan.executable, blocked: plan.blocked,
    human_gates: plan.human_gates, release_readiness: plan.release_readiness, uncertainty_first: plan.uncertainty_first,
    activated_specialists: plan.activated_specialists, dormant: plan.dormant_specialist_count,
    shared_genome_refs: plan.shared_genome_refs, jit_skills: plan.jit_skills,
    node_cards: obj(plan.node_cards, (c) => [c.unresolved, C.semanticHash(c.dimensions as C.HashValue)]), summary: C.planSummary(plan),
  };
}

function plan(a: unknown[]): C.CompiledAgencyPlan {
  const request = C.parseModel(C.CompiledAgencyRequestSchema, 'CompiledAgencyRequest', a[1]) as C.CompiledAgencyRequest;
  const hashes = a[2] === null ? null : map(a[2]);
  return C.compileAgencyPlan(request, registry(str(a[0])), { sourceHashes: hashes });
}

function methodPlan(req: unknown): C.MethodPlan {
  return C.compileMethodPlan(C.parseModel(C.ObjectiveRequestSchema, 'ObjectiveRequest', req), catalog());
}

function methodDigest(p: C.MethodPlan) {
  const dump = (xs: readonly unknown[]): C.HashValue => C.toPlain(xs) as C.HashValue;
  return {
    plan_hash: p.plan_hash, stack_hash: p.method_stack.stack_hash, selected: C.stackSelected(p.method_stack),
    families: p.problem_signature.problem_families, unresolved: p.unresolved, confidence: p.method_stack.selection_confidence,
    envelopes: p.delegation_envelopes.map((e) => [e.node_id, e.context_hash, e.side_effect_class, e.slot]),
    gates: p.human_gates.map((g) => g.gate_id), duels: p.shadow_duels.length,
    certs: p.minimality_certificates.map((c) => [c.method_id, c.necessary_for]),
    excluded: C.semanticHash(dump(p.method_stack.excluded_methods)), classification: C.semanticHash(dump(p.classification)),
  };
}

function missionDigest(a: unknown[]) {
  const p = a[0] as C.MethodPlan;
  const m = C.compileMethodMission(p, registry(str(a[1])), 'proj', catalog());
  return {
    mission: m.mission, phase_map: m.phase_map, task_to_work_order: m.task_to_work_order,
    work_orders: C.semanticHash(m.work_orders as unknown as C.HashValue), eligibility: m.eligibility,
    proofs: m.non_authority_proofs, graph_hash: m.graph.graph_hash,
    graph_nodes: Object.fromEntries([...m.graph.nodes].map(([k, n]) => [k, [n.semantic_hash, n.status]])), roots: m.graph.roots,
    cells: Object.fromEntries([...m.cells].map(([k, c]) => [k, [C.cellHash(c), c.status]])),
    waves: m.wave_plan.waves.map((w) => [w.index, w.cells, w.serialized_reason]), held: m.wave_plan.held,
    wave_hash: m.wave_plan.wave_hash, executor: [m.executor_status, m.executor_reason],
  };
}

function applyPatch(raw: Rec, ops: unknown[]): Rec {
  const c = structuredClone(raw) as Rec;
  for (const o of ops) {
    const op = o as unknown[];
    if (op[0] === 'set') {
      let target: Rec = c;
      const path = op[1] as (string | number)[];
      for (const key of path.slice(0, -1)) target = target[key as string] as Rec;
      target[String(path[path.length - 1])] = op[2];
    } else if (op[0] === 'append_copy') {
      const at = (p: unknown): unknown => (p as (string | number)[]).reduce<unknown>((t, k) => (t as Rec)[k as string], c);
      (at(op[1]) as unknown[]).push(structuredClone(at(op[2])));
    } else if (op[0] === 'remove_method') {
      c['methods'] = recs(c['methods']).filter((m) => m['method_id'] !== op[1]);
    } else if (op[0] === 'strip_macro') {
      for (const m of recs(c['methods'])) {
        if (m['slot'] === 'MACRO') m['expected_outputs'] = strs(m['expected_outputs']).filter((x) => x !== 'macro:structured_cycle');
      }
    } else {
      c['families'] = [];
      c['methods'] = [];
    }
  }
  return c;
}

function ontologyTables() {
  return {
    stages: C.LIFECYCLE_STAGES,
    overlays: C.MASTER_BUILDER_OVERLAYS.map((o) => ({ overlay_id: o.overlay_id, name: o.name, stages: o.stages, domains: C.sortStrings(o.domains) })),
    process_maps: C.DOMAIN_PROCESS_MAPS, exceptions: Object.fromEntries(C.EXCEPTION_CATALOG),
    artifact_stage: Object.fromEntries(C.ARTIFACT_STAGE),
    phases: Object.fromEntries([...C.ARTIFACT_STAGE.keys()].map((a) => [a, C.roleosPhaseFor(a)])),
    consequential: C.CONSEQUENTIAL_STAGES, domains: C.DOMAINS, process_elements: C.PROCESS_ELEMENTS, failure_routes: C.FAILURE_ROUTES,
  };
}

function validationTables() {
  return {
    profiles: C.VALIDATION_PROFILES.map((p) => ({ profile_id: p.profile_id, stage: p.stage, skill: p.validator_skill,
      department: p.validator_department, volatile_keys: p.volatile_keys })),
    base: C.BASE_OBLIGATIONS, stages: C.VALIDATION_STAGES, max_repair_attempts: C.MAX_REPAIR_ATTEMPTS,
  };
}

function decisionScript(a: unknown[]): Rec[] {
  const graph = campaignGraph();
  const spine = new C.DecisionSpine(list(C.DecisionNodeSchema, 'DecisionNode', a[0]) as C.DecisionNode[]);
  const kind = (v: unknown): C.DecisionKind => enumValue(C.DECISION_KINDS, v, 'DecisionKind');
  return steps(a[1] as unknown[], (op, r) => {
    if (op === 'propose') return spine.propose(C.parseModel(C.DecisionNodeSchema, 'DecisionNode', r[0]) as C.DecisionNode);
    if (op === 'accept') return spine.accept(kind(r[0]), str(r[1]), str(r[2]));
    if (op === 'revise') return spine.revise(kind(r[0]), graph, r[1] as C.DecisionChanges);
    if (op === 'current') return spine.current(kind(r[0]));
    if (op === 'effective') return spine.effectiveStatus(spine.current(kind(r[0])) as C.DecisionNode);
    if (op === 'accepted') return spine.acceptedByKind();
    if (op === 'versions') return spine.versions.map((v) => [v, C.decisionHash(v)]);
    return C.uncertaintyPriority(graph);
  });
}

function changeScript(a: unknown[]): Rec[] {
  const graph = campaignGraph({ positioning: 'a'.repeat(64), brand_platform: 'a'.repeat(64), creative_direction: 'a'.repeat(64) });
  const hashes = new Map([...graph.nodes].map(([n, node]) => [n, node.semantic_hash]));
  const scopes: C.ApprovalScope[] = [];
  const idx = (v: unknown): C.ApprovalScope[] => (v as number[]).map((i) => scopes[i] as C.ApprovalScope);
  return steps(a[0] as unknown[], (op, r) => {
    if (op === 'buildScope') {
      const s = { ...rec(r[0]) };
      const subjects = new Map(Object.entries(rec(s['subjects'])).map(([k, v]) => [k, v === '$node' ? (hashes.get(k) as string) : str(v)]));
      const scope = C.buildScope(graph, { ...(s as unknown as C.BuildScopeInputs), subjects, artifact_hashes: map(s['artifact_hashes']) });
      scopes.push(scope);
      return [scope, C.scopeHash(scope)];
    }
    if (op === 'evaluate') {
      const scope = scopes[r[0] as number] as C.ApprovalScope;
      return C.evaluateScope(scope, {
        current_subject_hashes: r[1] === '$nodes' ? hashes : map(r[1]),
        current_closure_hash: r[2] === '$same' ? scope.dependency_closure_hash : str(r[2]), current_policy_version: str(r[3]),
        preservation_permitted: r[4] as boolean, high_risk_change: r[5] as boolean,
      });
    }
    if (op === 'closure') return C.dependencyClosureHash(graph, strs(r[0]), map(r[1]));
    if (op === 'blast') {
      const changes = new Map(Object.entries(rec(r[0])).map(([ref, pair]): [string, [string, string]] => {
        const [o, n] = pair as [unknown, unknown];
        return [ref, [o === '$node' ? (hashes.get(ref) as string) : str(o), str(n)]];
      }));
      return C.computeBlastRadius(graph, changes, idx(r[1]));
    }
    if (op === 'dna') {
      const refs = new Map(Object.entries(rec(r[1])).map(([k, v]): [string, string[]] => [k, strs(v)]));
      return C.artifactDna(graph, str(r[0]), refs, idx(r[2]));
    }
    return C.sortStrings(graph.nodes.keys());
  });
}

function ledgerScript(a: unknown[]): Rec[] {
  const ledger = new C.LearningLedger();
  const sealed: C.LearningSignal[] = [];
  return steps(a[0] as unknown[], (op, r) => {
    if (op === 'append') {
      const s = ledger.append(C.parseModel(C.LearningSignalSchema, 'LearningSignal', r[0]) as C.LearningSignal);
      sealed.push(s);
      return s;
    }
    if (op === 'entries') return ledger.entries(str(r[0]));
    if (op === 'verify') return ledger.verifyChain();
    if (op === 'proposals') return ledger.proposals;
    if (op === 'tamper') {
      const entries = sealed.map((s, i) => (i === r[0] ? { ...s, observation: 'tampered' } : s));
      return C.LearningLedger.replay(entries).entries((entries[0] as C.LearningSignal).tenant_scope).map((e) => e.hash);
    }
    return C.LearningLedger.replay(sealed).entries(str(r[0])).map((e) => e.hash);
  });
}

function genome(v: unknown): ReturnType<typeof C.projectGenome> {
  return C.projectGenome(list(C.GenomeAssertionSchema, 'GenomeAssertion', v) as C.GenomeAssertion[]);
}

const emptyCapsule = (refs: string[]): C.ContextCapsule => ({ relevant_genome_refs: refs } as unknown as C.ContextCapsule);

function capsuleFor(deps: Map<string, string>): C.ContextCapsule {
  return C.projectCapsule(C.projectGenome([]), { objective: 'o', acceptance_criteria: [], domains: [], dependency_hashes: deps });
}

function attempts(v: unknown): C.Attempt[] {
  return recs(v).map((x) => ({
    succeeded: (x['succeeded'] as boolean | undefined) ?? false, failure_class: (x['failure_class'] as C.FailureClass | undefined) ?? null,
    failure_fingerprint: (x['failure_fingerprint'] as string | undefined) ?? null, progress: (x['progress'] as number | undefined) ?? null,
    retrieval_new_evidence: (x['retrieval_new_evidence'] as boolean | undefined) ?? null,
  }));
}

function evaluation(a: unknown[]): C.ValidationVerdict {
  const results = list(C.ValidationResultSchema, 'ValidationResult', a[2]) as C.ValidationResult[];
  return C.evaluateValidation(str(a[0]), strs(a[1]), results, {
    creatorRef: str(a[3]), riskLevel: str(a[4]), graphNodes: new Set(strs(a[5])),
  });
}

function bindCall(a: unknown[]): C.SpecialistBinding {
  const reg = registry(str(a[0]));
  const bySkill = map(a[2]);
  const hashes = new Map([...reg.roles].filter(([, r]) => bySkill.has(r.skill_name)).map(([id, r]) => [id, bySkill.get(r.skill_name) as string]));
  const kw = rec(a[1]);
  const grants = list(C.AuthorityGrantSchema, 'AuthorityGrant', kw['grants']) as C.AuthorityGrant[];
  return new C.AuthorityBridge(reg, hashes).bind({ ...(kw as unknown as C.BindInput), grants });
}

const instant = (a: unknown[]): unknown => C.constraintInstant(str(a[0]));
const parseObjective = (v: unknown) => C.parseModel(C.ObjectiveRequestSchema, 'ObjectiveRequest', v);
const parseConstraint = (v: unknown) => C.parseModel(C.VolatileConstraintSchema, 'VolatileConstraint', v) as C.VolatileConstraint;

export const CALLS: Record<string, Fn> = {
  pyLower: (a) => C.pyLower(str(a[0])),
  pyCasefold: (a) => C.pyCasefold(str(a[0])),
  pyStrip: (a) => C.pyStrip(str(a[0])),
  collapseWhitespace: (a) => C.collapseWhitespace(str(a[0])),
  sortStrings: (a) => C.sortStrings(strs(a[0])),
  pyRound: (a) => C.pyRound(a[0] as number, a[1] as number),
  semanticHash: (a) => C.semanticHash(decode(a[0]), strs(a[1])),
  closureHash: (a) => C.closureHash((a[0] as [string, string][])),
  ontologyTables: () => ontologyTables(),
  selectOverlays: (a) => C.selectOverlays(a[0] as string[], a[1] as boolean),
  routeException: (a) => C.routeException(str(a[0])),
  validationTables: () => validationTables(),
  obligationsFor: (a) => C.obligationsFor(artifact(a[0]), strs(a[1]), { externalAction: a[2] as boolean, liveService: a[3] as boolean }),
  volatileKeysFor: (a) => C.volatileKeysFor(strs(a[0])),
  routeFailure: (a) => C.routeFailure(str(a[0]), str(a[1]), new Set(strs(a[2]))),
  evaluateValidation: evaluation,
  releaseBlockers: (a) => C.releaseBlockers(a[0] as C.ReleaseFacts),
  classify: (a) => C.classify(C.parseModel(C.TaskSuitabilitySchema, 'TaskSuitability', a[0]) as C.TaskSuitability),
  suitabilityForNode: (a) => {
    const k = rec(a[0]);
    return C.suitabilityForNode({ artifactType: k['artifact_type'] as string | null, sideEffectClass: str(k['side_effect_class']),
      evidenceSufficient: k['evidence_sufficient'] as boolean, rightsUncertain: k['rights_uncertain'] as boolean });
  },
  triangulationDeficits: (a) => C.triangulationDeficits(C.parseModel(C.ClaimSchema, 'Claim', a[0]) as C.Claim,
    list(C.SourceRecordSchema, 'SourceRecord', a[1]) as C.SourceRecord[]),
  evaluatePromotion: (a) => C.evaluatePromotion(C.parseModel(C.RuleCandidateSchema, 'RuleCandidate', a[0]) as C.RuleCandidate,
    C.parseModel(C.PromotionContextSchema, 'PromotionContext', a[1]) as C.PromotionContext),
  ruleLedger: (a) => C.ruleLedger(str(a[0])),
  constraintInstant: instant,
  volatileStatus: (a) => C.volatileStatus(parseConstraint(a[0]), str(a[1])),
  volatileReleaseBlockers: (a) => C.volatileReleaseBlockers((a[0] as unknown[]).map(parseConstraint), str(a[1])),
  projectGenome: (a) => genome(a[0]),
  projectCapsule: (a) => {
    const kw = rec(a[1]);
    return C.projectCapsule(genome(a[0]), { ...(kw as unknown as C.CapsuleInputs), dependency_hashes: map(kw['dependency_hashes']) });
  },
  capsuleFreshness: (a) => C.capsuleFreshness(capsuleFor(new Map([['ref:x', 'a'.repeat(64)], ['accept:y', 'b'.repeat(64)]])), map(a[0])),
  hoistSharedRefs: (a) => C.hoistSharedRefs((a[0] as string[][]).map(emptyCapsule)),
  compileBackchain: (a) => {
    const graph = compile(a[0], a[1], a[2], a[3]);
    return { graph, ...backchainExtras(graph) };
  },
  compileBackchainDigest: (a) => backchainDigest(compile(a[0], a[1], a[2], a[3])),
  decisionScript, changeScript: changeScript, ledgerScript,
  measureRun: (a) => C.measureRun(a[0] as C.EventRow[], strs(a[1])),
  conformance: (a) => C.conformance(strs(a[0]), strs(a[1])),
  resolveRoles: (a) => C.resolveRoles(registry(str(a[0])), strs(a[1]), {
    department_hint: a[2] as string | null, family_hint: a[3] as string | null, limit: a[4] as number }),
  resolveSpecialist: (a) => new C.AuthorityBridge(registry(str(a[0]))).resolveSpecialist({ skill_name: str(a[1]), department: str(a[2]) }),
  bind: bindCall,
  compileWorkOrder: (a) => C.compileWorkOrder(registry(str(a[0])), a[1] as C.WorkOrderInput),
  compileAgencyPlan: plan,
  compileAgencyPlanDigest: (a) => planDigest(plan(a)),
  parseCatalog: (a) => {
    const c = C.parseCatalog(applyPatch(catalogRaw(), a[0] as unknown[]));
    return { hash: c.catalog_hash, families: C.sortStrings(c.families.keys()), methods: C.sortStrings(c.methods.keys()) };
  },
  evaluatePredicate: (a) => C.evaluatePredicate(str(a[0]), C.buildSignature(C.normalizeRequest(parseObjective(a[1])), strs(a[2]))),
  validateObjectiveRequest: (a) => parseObjective(a[0]),
  normalizeRequest: (a) => C.normalizeRequest(parseObjective(a[0])),
  requestHash: (a) => C.requestHash(parseObjective(a[0])),
  compileMethodPlan: (a) => methodPlan(a[0]),
  compileMethodPlanDigest: (a) => methodDigest(methodPlan(a[0])),
  compileMethodMission: missionDigest,
  verifyContextChain: (a) => C.verifyContextChain(a[0] as C.MethodPlan),
  causalClosure: (a) => C.causalClosure(a[0] as C.MethodPlan, strs(a[1])),
  nextStep: (a) => C.nextStep({ retry_limit: a[0] as number }, attempts(a[1])),
  mutationKey: (a) => C.mutationKey(a[0] as C.MutationKeyInput),
};
