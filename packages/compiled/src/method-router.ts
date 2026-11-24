/**
 * Twin of `agency/compiled/method_router.py`: objective → ProblemSignature →
 * minimal MethodStack → MethodPlan.
 *
 * Classification is multi-label and evidence-gated: a family is selected only
 * when a structural fact in the request supports it. Words in the objective
 * are corroborating cues and yield at most three clarification gates. The stack
 * is a deterministic minimum (greedy set cover, then counterfactual pruning
 * with a MinimalityCertificate per survivor, then a planning-only shadow duel
 * on the first exact tie). Nothing here executes, calls a model or grants
 * authority.
 */
import { PyFloat } from '@amc/kernel';
import {
  allHold, anyHolds, type MethodCatalog,
} from './method-catalog';
import {
  MAX_ROUTER_PASSES, MAX_SHADOW_STACKS, MAX_TASK_RETRIES, PLAN_VERSION, POLICY_VERSION, SLOT_ORDER,
  type DelegationEnvelope, type ExcludedMethod, type FamilyEvidence, type HumanGate, type MethodPlan, type MethodSpec,
  type MethodStack, type MinimalityCertificate, type ObjectiveRequest, type ProblemSignature, type ShadowDuel, type Slot,
  type SideEffectClass,
} from './method-models';
import { CompiledKeyError, CompiledValidationError } from './errors';
import { semanticHash, type HashValue } from './hashing';
import {
  collapseWhitespace, compareScalars, pyCasefold, pyLower, pyRound, pyStrip, pySlice, sortStrings,
} from './python';
import { pyRepr } from '@amc/kernel';

export const MACRO_NEED = 'macro:structured_cycle';
export const PREREQ_NODE = 'prereq:measurement_plan';
export const MAX_CLARIFICATIONS = 3;

type Req = ObjectiveRequest;

/** Structural signals: each is a fact the caller stated, not a word they used. */
export const SIGNALS: ReadonlyMap<string, (r: Req) => boolean> = new Map<string, (r: Req) => boolean>([
  ['items_to_rank', (r) => r.items_to_rank.length >= 2],
  ['options', (r) => r.options.length >= 2],
  ['process_gap_defined', (r) => Boolean(r.process_exists && r.current_state_known && r.target_state_known)],
  ['problem_recurs_cause_unknown', (r) => Boolean(r.problem_recurs) && r.root_cause_known !== true],
  ['waste_observed', (r) => Boolean(r.waste_observed)],
  ['throughput_constrained', (r) => Boolean(r.throughput_constrained)],
  ['variation_observed', (r) => Boolean(r.variation_observed)],
  ['high_consequence_or_irreversible', (r) => r.consequence === 'high' || r.consequence === 'critical' || r.reversibility === 'irreversible'],
  ['customer_needs_unknown', (r) => Boolean(r.customer_needs_unknown)],
  ['scoped_known_solution', (r) => Boolean(r.deliverable_scope_defined && r.solution_known)],
  ['unknown_solution_high_uncertainty', (r) => r.solution_known === false && r.uncertainty === 'high'],
  ['strategic_question', (r) => Boolean(r.strategic_question)],
  ['strategy_needs_alignment', (r) => Boolean(r.strategy_needs_alignment)],
  ['decision_rights_unclear', (r) => Boolean(r.decision_rights_unclear)],
  ['change_adoption_required', (r) => Boolean(r.change_adoption_required)],
  ['coupled_feedback_system', (r) => r.system_coupling === 'high' && Boolean(r.feedback_loops_suspected)],
  ['live_service_incidents', (r) => Boolean(r.live_service && r.incidents_recurring)],
  ['lessons_or_recurrence', (r) => Boolean(r.lessons_to_capture || r.problem_recurs)],
]);

const OBSERVABLE = [
  'problem_recurs', 'variation_observed', 'waste_observed', 'throughput_constrained', 'customer_needs_unknown',
  'deliverable_scope_defined', 'strategic_question', 'strategy_needs_alignment', 'decision_rights_unclear',
  'change_adoption_required', 'feedback_loops_suspected', 'live_service', 'incidents_recurring', 'lessons_to_capture',
] as const;

const clean = (text: string): string => pyStrip(collapseWhitespace(text));

function setLike(values: readonly string[], lower = false): string[] {
  const cleaned = new Set<string>();
  for (const v of values) {
    const c = clean(v);
    if (c) cleaned.add(lower ? pyLower(c) : c);
  }
  return sortStrings(cleaned);
}

/** Canonical form: equivalent requests (reordered, re-spaced) are equal. */
export function normalizeRequest(request: Req): Req {
  return {
    ...request,
    objective: clean(request.objective),
    desired_outcome: clean(request.desired_outcome),
    domains: setLike(request.domains, true),
    constraints: setLike(request.constraints),
    non_goals: setLike(request.non_goals),
    items_to_rank: setLike(request.items_to_rank),
    options: setLike(request.options),
  };
}

export function requestHash(request: Req): string {
  return semanticHash(normalizeRequest(request) as unknown as HashValue);
}

function observations(request: Req): string[] {
  const facts: string[] = OBSERVABLE.filter((name) => Boolean(request[name]));
  if (request.items_to_rank.length >= 2) facts.push('items_to_rank');
  if (request.options.length >= 2) facts.push('options');
  return sortStrings(facts);
}

/** `re.search(rf"(?<![a-z]){re.escape(cue.casefold())}", lowered)`. */
function cueMatches(lowered: string, cue: string): boolean {
  const needle = pyCasefold(cue);
  for (let at = lowered.indexOf(needle); at >= 0; at = lowered.indexOf(needle, at + 1)) {
    const before = at === 0 ? '' : (lowered[at - 1] as string);
    if (!/^[a-z]$/.test(before)) return true;
  }
  return false;
}

function cuesIn(text: string, cues: readonly string[]): string[] {
  const lowered = pyCasefold(text);
  return sortStrings(cues.filter((c) => cueMatches(lowered, c)));
}

function signalOf(name: string): (r: Req) => boolean {
  const fn = SIGNALS.get(name);
  if (fn === undefined) throw new CompiledKeyError(pyRepr(name));
  return fn;
}

export function classifyFamilies(request: Req, catalog: MethodCatalog): FamilyEvidence[] {
  const text = `${request.objective} ${request.desired_outcome}`;
  const families = [...catalog.families.values()].sort((a, b) => compareScalars(a.family_id, b.family_id));
  const evidence: FamilyEvidence[] = [];
  for (const family of families) {
    const signals = sortStrings(family.signals.filter((s) => signalOf(s)(request)));
    const cues = cuesIn(text, family.lexical_cues);
    if (signals.length || cues.length) {
      evidence.push({ family_id: family.family_id, structural_signals: signals, lexical_cues: cues, selected: signals.length > 0 });
    }
  }
  return evidence;
}

export function buildSignature(request: Req, families: readonly string[]): ProblemSignature {
  const r = request;
  return {
    objective: r.objective, desired_outcome: r.desired_outcome, problem_families: families, domains: r.domains,
    current_state_known: r.current_state_known, target_state_known: r.target_state_known, process_exists: r.process_exists,
    root_cause_known: r.root_cause_known, solution_known: r.solution_known, measurement_available: r.measurement_available,
    uncertainty: r.uncertainty, reversibility: r.reversibility, consequence: r.consequence, externality: r.externality,
    data_sensitivity: r.data_sensitivity, system_coupling: r.system_coupling, time_pressure: r.time_pressure,
    change_adoption_required: r.change_adoption_required, evidence_status: r.evidence_status, constraints: r.constraints,
    non_goals: r.non_goals, observations: observations(r),
  };
}

export function computeNeeds(signature: ProblemSignature, catalog: MethodCatalog): Map<string, Slot> {
  const needs = new Map<string, Slot>();
  for (const familyId of signature.problem_families) {
    const family = catalog.families.get(familyId);
    if (family === undefined) throw new CompiledKeyError(pyRepr(familyId));
    for (const [need, slot] of Object.entries(family.needs)) if (!needs.has(need)) needs.set(need, slot);
  }
  const families = new Set(signature.problem_families);
  if (families.has('DECISION') && ['high', 'critical'].includes(signature.consequence)) needs.set('validation:decision_robustness', 'DECIDE');
  if (families.has('STRATEGY') && signature.uncertainty === 'high') needs.set('output:scenarios_explored', 'DIAGNOSE');
  if (families.has('STRATEGY_EXECUTION') && signature.target_state_known !== true) needs.set('output:goals_specified', 'DECIDE');
  // A structured lifecycle method earns its place only when the work spans at least three distinct slots.
  if (new Set(needs.values()).size >= 3) needs.set(MACRO_NEED, 'MACRO');
  return new Map(sortStrings(needs.keys()).map((k) => [k, needs.get(k) as Slot]));
}

export function needsMeasurement(needs: ReadonlyMap<string, Slot>): boolean {
  return [...needs.keys()].some((n) => n.startsWith('measurement:') || n.startsWith('control:'));
}

/** With a measurement-plan prerequisite, later methods may assume data. */
function effective(signature: ProblemSignature, prereq: boolean): ProblemSignature {
  return prereq ? { ...signature, measurement_available: true } : signature;
}

function screenOne(method: MethodSpec, signature: ProblemSignature, banned: ReadonlySet<string>): string | null {
  if (banned.has(method.method_id)) return 'CONFLICT_RESOLUTION';
  const families = new Set(signature.problem_families);
  if (method.slot === 'MACRO' && ![method.family, ...method.secondary_families].some((f) => families.has(f))) {
    return 'MACRO_FAMILY_MISMATCH';
  }
  if (anyHolds(method.contraindications, signature)) return 'CONTRAINDICATED';
  if (!allHold(method.applicability_predicates, signature)) return 'NOT_APPLICABLE';
  return null;
}

function screen(
  catalog: MethodCatalog, signature: ProblemSignature, needs: ReadonlyMap<string, Slot>, banned: ReadonlySet<string>,
): { usable: MethodSpec[]; excluded: ExcludedMethod[] } {
  const usable: MethodSpec[] = [];
  const excluded: ExcludedMethod[] = [];
  const methods = [...catalog.methods.values()].sort((a, b) => compareScalars(a.method_id, b.method_id));
  for (const method of methods) {
    if (!method.expected_outputs.some((o) => needs.has(o))) continue;
    const reason = screenOne(method, signature, banned);
    if (reason === null) usable.push(method);
    else excluded.push({ method_id: method.method_id, reason });
  }
  return { usable, excluded };
}

const outputsIn = (method: MethodSpec, within: ReadonlySet<string>): Set<string> =>
  new Set(method.expected_outputs.filter((o) => within.has(o)));

function greedy(usable: readonly MethodSpec[], needs: ReadonlySet<string>, force: string | null = null): [string[], [string, string] | null] {
  const uncovered = new Set(needs);
  const chosen: string[] = [];
  let firstTie: [string, string] | null = null;
  const pool = new Map(usable.map((m) => [m.method_id, m]));
  while (uncovered.size) {
    const scored = [...pool.values()].filter((m) => !chosen.includes(m.method_id))
      .map((m) => ({ gain: outputsIn(m, uncovered).size, m })).filter((x) => x.gain > 0);
    if (!scored.length) break;
    scored.sort((a, b) => keyCompare(a.m, a.gain, b.m, b.gain));
    const best = scored[0] as { gain: number; m: MethodSpec };
    const tied = scored.filter((x) => x.gain === best.gain && x.m.effort === best.m.effort).map((x) => x.m);
    let pick = best.m;
    if (tied.length > 1 && firstTie === null) {
      firstTie = [(tied[0] as MethodSpec).method_id, (tied[1] as MethodSpec).method_id];
      const forced = force === null ? undefined : tied.find((t) => t.method_id === force);
      if (forced !== undefined) pick = pool.get(force as string) as MethodSpec;
    }
    chosen.push(pick.method_id);
    for (const o of pick.expected_outputs) uncovered.delete(o);
  }
  return [chosen, firstTie];
}

function keyCompare(a: MethodSpec, ag: number, b: MethodSpec, bg: number): number {
  return (bg - ag) || (a.effort - b.effort) || (SLOT_ORDER.indexOf(a.slot) - SLOT_ORDER.indexOf(b.slot))
    || compareScalars(a.method_id, b.method_id);
}

/** Counterfactually remove each method; keep only those some need requires. */
function prune(chosen: readonly string[], catalog: MethodCatalog, needs: ReadonlySet<string>): string[] {
  let kept = [...chosen];
  for (const methodId of [...chosen].reverse()) {
    const others = kept.filter((m) => m !== methodId);
    const covered = new Set(others.flatMap((m) => [...outputsIn(method(catalog, m), needs)]));
    const mine = outputsIn(method(catalog, methodId), needs);
    if ([...mine].every((o) => covered.has(o))) kept = others;
  }
  return kept;
}

function method(catalog: MethodCatalog, id: string): MethodSpec {
  const found = catalog.methods.get(id);
  if (found === undefined) throw new CompiledKeyError(pyRepr(id));
  return found;
}

function compareStackScore(a: readonly string[], b: readonly string[], catalog: MethodCatalog, needs: ReadonlySet<string>): number {
  const score = (s: readonly string[]) => {
    const covered = new Set(s.flatMap((m) => [...outputsIn(method(catalog, m), needs)]));
    return [needs.size - covered.size, s.reduce((n, m) => n + method(catalog, m).effort, 0), s.length];
  };
  const [x, y] = [score(a), score(b)];
  for (let i = 0; i < 3; i += 1) if (x[i] !== y[i]) return (x[i] as number) - (y[i] as number);
  const [sa, sb] = [sortStrings(a), sortStrings(b)];
  for (let i = 0; i < Math.min(sa.length, sb.length); i += 1) {
    const d = compareScalars(sa[i] as string, sb[i] as string);
    if (d) return d;
  }
  return sa.length - sb.length;
}

function conflictLosers(chosen: readonly string[], catalog: MethodCatalog): string[] {
  const losers: string[] = [];
  for (const methodId of chosen) {
    for (const other of method(catalog, methodId).conflicts_with) {
      if (!chosen.includes(other)) continue;
      const [a, b] = [method(catalog, methodId), method(catalog, other)];
      const key = (m: MethodSpec): (string | number)[] => [m.effort, m.method_id];
      const bigger = compareScalars(key(a)[0] as number, key(b)[0] as number) || compareScalars(a.method_id, b.method_id);
      losers.push(bigger >= 0 ? a.method_id : b.method_id);
    }
  }
  return sortStrings(new Set(losers));
}

const sortedHash = (ids: readonly string[]): string => semanticHash(sortStrings(ids));

function shadowDuel(
  usable: readonly MethodSpec[], needSet: ReadonlySet<string>, catalog: MethodCatalog, primary: string[], tie: [string, string],
): { primary: string[]; duel: ShadowDuel | null } {
  const [raw] = greedy(usable, needSet, tie[1]);
  const alternative = prune(raw, catalog, needSet);
  if (sortStrings(alternative).join('\u0000') === sortStrings(primary).join('\u0000')) return { primary, duel: null };
  const winner = compareStackScore(primary, alternative, catalog, needSet) <= 0 ? primary : alternative;
  return {
    primary: winner,
    duel: { candidates: [sortedHash(primary), sortedHash(alternative)], winner: sortedHash(winner), rule: 'fewest_uncovered_needs,lowest_effort,fewest_methods,lexical' },
  };
}

export interface Selection {
  readonly primary: string[];
  readonly certificates: MinimalityCertificate[];
  readonly excluded: ExcludedMethod[];
  readonly duels: ShadowDuel[];
  readonly unresolved: string[];
  readonly needs: Map<string, Slot>;
}

function certificatesFor(primary: readonly string[], catalog: MethodCatalog, needSet: ReadonlySet<string>): MinimalityCertificate[] {
  return sortStrings(primary).map((methodId) => {
    const others = new Set(primary.filter((m) => m !== methodId).flatMap((m) => method(catalog, m).expected_outputs));
    const unique = sortStrings([...outputsIn(method(catalog, methodId), needSet)].filter((o) => !others.has(o)));
    if (!unique.length) throw new CompiledValidationError('MinimalityCertificate', [{ loc: ['necessary_for'], message: 'too_short' }]);
    return {
      method_id: methodId, necessary_for: unique, redundant: false as const,
      downstream_effect_if_removed: `Uncovered needs: ${unique.join(', ')}; dependents lose these inputs.`,
    };
  });
}

/** The macro need is optional: dropped, not reported as a gap, when no lifecycle methodology fits. */
function withoutUnfittableMacro(catalog: MethodCatalog, eff: ProblemSignature, needs: Map<string, Slot>): Map<string, Slot> {
  if (!needs.has(MACRO_NEED)) return needs;
  const { usable } = screen(catalog, eff, needs, new Set());
  if (usable.some((m) => m.expected_outputs.includes(MACRO_NEED))) return needs;
  return new Map([...needs].filter(([k]) => k !== MACRO_NEED));
}

export function selectMethods(signature: ProblemSignature, needsIn: Map<string, Slot>, catalog: MethodCatalog, prereq: boolean): Selection {
  const eff = effective(signature, prereq);
  const needs = withoutUnfittableMacro(catalog, eff, needsIn);
  const needSet = new Set(needs.keys());
  const banned = new Set<string>();
  const unresolved: string[] = [];
  let duels: ShadowDuel[] = [];
  let primary: string[] = [];
  let excluded: ExcludedMethod[] = [];
  let resolved = false;
  for (let pass = 0; pass < MAX_ROUTER_PASSES && !resolved; pass += 1) {
    const screened = screen(catalog, eff, needs, banned);
    excluded = screened.excluded;
    const [first, tie] = greedy(screened.usable, needSet);
    primary = prune(first, catalog, needSet);
    duels = [];
    if (tie !== null && MAX_SHADOW_STACKS >= 2) {
      const result = shadowDuel(screened.usable, needSet, catalog, primary, tie);
      primary = result.primary;
      if (result.duel) duels.push(result.duel);
    }
    const losers = conflictLosers(primary, catalog);
    if (!losers.length) resolved = true;
    else for (const l of losers) banned.add(l);
  }
  if (!resolved) {
    unresolved.push('METHOD_CONFLICT_UNRESOLVED');
    const losers = new Set(conflictLosers(primary, catalog));
    primary = primary.filter((m) => !losers.has(m));
  }
  const covered = new Set(primary.flatMap((m) => method(catalog, m).expected_outputs));
  unresolved.push(...sortStrings([...needSet].filter((n) => !covered.has(n))).map((n) => `NO_APPLICABLE_METHOD:${n}`));
  return { primary, certificates: certificatesFor(primary, catalog, needSet), excluded, duels, unresolved, needs };
}

function buildStack(primary: readonly string[], catalog: MethodCatalog, excluded: readonly ExcludedMethod[], classification: readonly FamilyEvidence[]): MethodStack {
  const bySlot = new Map<Slot, string[]>(SLOT_ORDER.map((s) => [s, []]));
  for (const id of sortStrings(primary)) bySlot.get(method(catalog, id).slot)?.push(id);
  const strength = classification.filter((e) => e.selected)
    .map((e) => Math.min(1.0, (e.structural_signals.length + (e.lexical_cues.length ? 1 : 0)) / 2));
  const body: Record<string, HashValue> = {};
  for (const slot of SLOT_ORDER) body[slot] = bySlot.get(slot) as string[];
  const slotIds = (s: Slot): string[] => bySlot.get(s) as string[];
  return {
    macro_methodologies: slotIds('MACRO'), diagnostic_methods: slotIds('DIAGNOSE'), decision_methods: slotIds('DECIDE'),
    execution_methods: slotIds('EXECUTE'), control_methods: slotIds('CONTROL'), learning_methods: slotIds('LEARN'),
    excluded_methods: [...excluded], source_refs: sortStrings(new Set(primary.flatMap((m) => method(catalog, m).source_refs))),
    selection_confidence: new PyFloat(strength.length ? pyRound(strength.reduce((a, b) => a + b, 0) / strength.length, 4) : 0),
    stack_hash: semanticHash(body),
  };
}

const RISK: Readonly<Record<string, DelegationEnvelope['risk_level']>> = { low: 'low', medium: 'medium', high: 'high', critical: 'critical', unknown: 'medium' };
const STOP = [
  'acceptance criteria pass', 'retry limit exhausted', 'required authority or approval missing',
  'dependency or context becomes stale', 'same failure fingerprint twice',
  'no measurable contract progress: reclassify problem',
];
const PROOF = ['validator confirms each expected output against its acceptance criterion', 'output content hash recorded'];

function sideEffect(m: MethodSpec | null, signature: ProblemSignature): SideEffectClass {
  if (m === null || m.slot !== 'EXECUTE') return 'DRAFT';
  return signature.reversibility === 'irreversible' && signature.externality === 'external' ? 'IRREVERSIBLE_WRITE' : 'REVERSIBLE_WRITE';
}

const RETRY_LIMIT: Readonly<Record<SideEffectClass, number>> = { PURE: MAX_TASK_RETRIES, DRAFT: MAX_TASK_RETRIES, REVERSIBLE_WRITE: 1, IRREVERSIBLE_WRITE: 0 };

export type ContextSource = Pick<DelegationEnvelope,
  'objective' | 'inputs' | 'method_refs' | 'evidence_requirements' | 'acceptance_criteria' | 'authority_refs' | 'approval_refs'
  | 'tool_plan' | 'dependencies'>;

/** Proof-carrying handoff: binds objective, inputs, methods, evidence, acceptance, authority, tools and each dependency's own hash. */
export function envelopeContextHash(body: ContextSource, upstream: ReadonlyMap<string, string>): string {
  const deps = body.dependencies.map((dep): [string, string] => [dep, upstream.get(dep) ?? 'UNRESOLVED'])
    .sort((a, b) => compareScalars(a[0], b[0]) || compareScalars(a[1], b[1]));
  return semanticHash({
    objective: body.objective, inputs: [...body.inputs], method_refs: [...body.method_refs],
    evidence_requirements: [...body.evidence_requirements], acceptance_criteria: [...body.acceptance_criteria],
    authority_refs: [...body.authority_refs], approval_refs: [...body.approval_refs], tool_plan: [...body.tool_plan],
    dependencies: deps,
  });
}

interface Layer { readonly nodes: readonly [string, MethodSpec | null][] }

function layersFor(primary: readonly string[], catalog: MethodCatalog, prereq: boolean): Layer[] {
  const layers: Layer[] = [];
  for (const slot of SLOT_ORDER) {
    const nodes = sortStrings(primary).filter((id) => method(catalog, id).slot === slot)
      .map((id): [string, MethodSpec | null] => [`m:${id}`, method(catalog, id)]);
    // Uncertainty first: the missing measurement baseline is resolved before any method that consumes measurements.
    if (slot === 'DIAGNOSE' && prereq) layers.push({ nodes: [[PREREQ_NODE, null]] });
    if (nodes.length) layers.push({ nodes });
  }
  return layers;
}

function requireNonEmpty(model: string, field: string, value: readonly unknown[]): void {
  if (!value.length) throw new CompiledValidationError(model, [{ loc: [field], message: 'too_short' }]);
}

interface NodeParts {
  family: string; outputs: string[]; inputs: string[]; evidence: string[]; justified: string[]; methodRefs: string[];
  objective: string; slot: Slot;
}

function nodeParts(
  m: MethodSpec | null, signature: ProblemSignature, needs: ReadonlyMap<string, Slot>, unique: ReadonlyMap<string, readonly string[]>,
): NodeParts {
  const families = new Set(signature.problem_families);
  if (m === null) {
    return {
      family: 'PROCESS_VARIATION', outputs: ['measurement:baseline_defined'], inputs: ['desired outcome', 'candidate metrics'],
      evidence: ['metric definitions', 'data sources'], methodRefs: [], slot: 'DIAGNOSE',
      justified: ['E3:NO_MEASURABLE_TARGET', ...sortStrings([...needs.keys()].filter((n) => n.startsWith('measurement:') || n.startsWith('control:')))],
      objective: `Define measurable targets and a baseline for: ${signature.objective}`,
    };
  }
  const family = families.has(m.family) ? m.family : (m.secondary_families.find((f) => families.has(f)) ?? m.family);
  return {
    family, outputs: sortStrings(m.expected_outputs.filter((o) => needs.has(o))), inputs: [...m.expected_inputs],
    evidence: [...m.evidence_needs], justified: [...(unique.get(m.method_id) ?? [])], methodRefs: [m.method_id],
    objective: `Apply ${m.name} to: ${signature.objective}`, slot: m.slot,
  };
}

function buildEnvelope(
  nodeId: string, m: MethodSpec | null, ctx: { signature: ProblemSignature; needs: ReadonlyMap<string, Slot>; catalog: MethodCatalog; unique: ReadonlyMap<string, readonly string[]>; target: string },
  previous: readonly string[], context: Map<string, string>,
): DelegationEnvelope {
  const parts = nodeParts(m, ctx.signature, ctx.needs, ctx.unique);
  const family = ctx.catalog.families.get(parts.family);
  if (family === undefined) throw new CompiledKeyError(pyRepr(parts.family));
  const effect = sideEffect(m, ctx.signature);
  const base = {
    node_id: nodeId, objective: parts.objective, problem_family: parts.family, method_refs: parts.methodRefs,
    dependencies: [...previous], required_capabilities: [...family.capability_terms],
    inputs: [...parts.inputs, ...previous.map((dep) => `ref:${dep}`)], expected_outputs: parts.outputs,
    acceptance_criteria: parts.outputs.map((tag) => `${tag}: produced, evidenced and reviewable`),
    evidence_requirements: parts.evidence, tool_plan: [] as string[], side_effect_class: effect,
    risk_level: RISK[ctx.signature.consequence] as DelegationEnvelope['risk_level'], authority_refs: [] as string[],
    approval_refs: [] as string[], idempotency_class: effect, retry_limit: RETRY_LIMIT[effect], stop_conditions: STOP,
    completion_proof: PROOF, slot: parts.slot, justified_by: parts.justified, delegation_depth: 1,
    mutation_targets: effect !== 'DRAFT' ? [ctx.target] : [],
  };
  requireNonEmpty('DelegationEnvelope', 'expected_outputs', base.expected_outputs);
  requireNonEmpty('DelegationEnvelope', 'acceptance_criteria', base.acceptance_criteria);
  requireNonEmpty('DelegationEnvelope', 'justified_by', base.justified_by);
  const contextHash = envelopeContextHash(base, context);
  context.set(nodeId, contextHash);
  return { ...base, context_hash: contextHash };
}

export function buildEnvelopes(
  signature: ProblemSignature, primary: readonly string[], needs: ReadonlyMap<string, Slot>,
  certificates: readonly MinimalityCertificate[], catalog: MethodCatalog, prereq: boolean,
): DelegationEnvelope[] {
  const unique = new Map(certificates.map((c) => [c.method_id, c.necessary_for]));
  const target = `process:${pySlice(semanticHash(signature.objective), 0, 16)}`;
  const context = new Map<string, string>();
  const envelopes: DelegationEnvelope[] = [];
  let previous: string[] = [];
  for (const layer of layersFor(primary, catalog, prereq)) {
    for (const [id, m] of layer.nodes) envelopes.push(buildEnvelope(id, m, { signature, needs, catalog, unique, target }, previous, context));
    previous = layer.nodes.map(([id]) => id);
  }
  return envelopes;
}

function authorityGate(env: DelegationEnvelope): HumanGate {
  const requires = ['authority_ref', 'permission_ref', 'approval_ref'];
  if (env.side_effect_class === 'IRREVERSIBLE_WRITE') requires.push('exact_approval_ref');
  return {
    gate_id: `gate:authority:${env.node_id}`, node_id: env.node_id, kind: 'EXECUTION_AUTHORITY', requires,
    separation_of_duties: true,
    enforced_by: 'role_os.WorkOrderCompiler.execution_ready + security.approval_authority.assert_may_decide',
  };
}

function gatesFor(signature: ProblemSignature, envelopes: readonly DelegationEnvelope[], classification: readonly FamilyEvidence[]): [HumanGate[], string[]] {
  const gates: HumanGate[] = [];
  const debt: string[] = [];
  for (const env of envelopes) {
    if (env.side_effect_class === 'REVERSIBLE_WRITE' || env.side_effect_class === 'IRREVERSIBLE_WRITE') gates.push(authorityGate(env));
    if (env.slot === 'DECIDE' && (signature.consequence === 'high' || signature.consequence === 'critical')) {
      gates.push({
        gate_id: `gate:decision:${env.node_id}`, node_id: env.node_id, kind: 'MATERIAL_DECISION',
        requires: ['human_decision_record'], separation_of_duties: true, enforced_by: 'security.approval_authority.assert_may_decide',
      });
      debt.push(`DECISION_PENDING:${env.node_id}`);
    }
  }
  const cueOnly = classification.filter((e) => !e.selected)
    .sort((a, b) => (b.lexical_cues.length - a.lexical_cues.length) || compareScalars(a.family_id, b.family_id)).slice(0, MAX_CLARIFICATIONS);
  for (const e of cueOnly) {
    gates.push({
      gate_id: `gate:clarify:${e.family_id}`, node_id: null, kind: 'CLARIFICATION',
      requires: [`Confirm with a structural fact whether ${e.family_id} applies (cues: ${e.lexical_cues.join(', ')})`],
      separation_of_duties: false, enforced_by: 'caller supplies the structured fact; keywords alone never route',
    });
  }
  return [gates, debt];
}

/** `compile_method_plan(request, catalog)`. The request must already be validated (`ObjectiveRequestSchema`). */
export function compileMethodPlan(request: Req, catalog: MethodCatalog): MethodPlan {
  const normalized = normalizeRequest(request);
  const classification = classifyFamilies(normalized, catalog);
  const families = classification.filter((e) => e.selected).map((e) => e.family_id);
  const signature = buildSignature(normalized, families);
  const unresolved: string[] = [];
  if (!families.length) unresolved.push('NO_STRUCTURAL_EVIDENCE');
  unresolved.push(...classification.filter((e) => !e.selected).map((e) => `KEYWORD_ONLY:${e.family_id}`));
  const needs0 = computeNeeds(signature, catalog);
  const prereq = needsMeasurement(needs0) && signature.measurement_available !== true;
  if (prereq) unresolved.push('ASSUMPTION:measurement_plan_precedes_measurement_methods');
  const sel = selectMethods(signature, needs0, catalog, prereq);
  unresolved.push(...sel.unresolved);
  const stack = buildStack(sel.primary, catalog, sel.excluded, classification);
  const envelopes = buildEnvelopes(signature, sel.primary, sel.needs, sel.certificates, catalog, prereq);
  const [gates, debt] = gatesFor(signature, envelopes, classification);
  unresolved.push(...debt);
  const body = {
    version: PLAN_VERSION as 'amc-method-plan/v1', policy_version: POLICY_VERSION, catalog_hash: catalog.catalog_hash,
    request_hash: semanticHash(normalized as unknown as HashValue), problem_signature: signature, classification,
    method_stack: stack, minimality_certificates: sel.certificates, shadow_duels: sel.duels, delegation_envelopes: envelopes,
    human_gates: gates, unresolved,
  };
  const planHash = semanticHash({ ...body, plan_hash: 'pending' } as unknown as HashValue, ['plan_hash']);
  return { ...body, plan_hash: planHash };
}
