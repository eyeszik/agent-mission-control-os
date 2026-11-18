/**
 * Twin of `agency/compiled/validation.py` (T12): per-node validation
 * obligations, independence checks, smallest-causal-producer repair routing
 * and release readiness delegated to the N2 guards (never decided here).
 */
import { ROLE_REGISTRY, releaseGuardFailures, type ArtifactType } from '@amc/kernel';
import { CompiledKeyError } from './errors';
import { pyRepr } from '@amc/kernel';
import { compareTuples, uniqueSorted } from './python';

export const MAX_REPAIR_ATTEMPTS = 3;

export const VALIDATION_STAGES = [
  'SCHEMA', 'PROVENANCE', 'LOGICAL_CONSISTENCY', 'FRESHNESS', 'AUTHORITY', 'ACCEPTANCE_CRITERIA', 'DISCIPLINE_QA',
  'BRAND', 'ACCESSIBILITY', 'LEGAL_RIGHTS', 'PRIVACY', 'SECURITY', 'FINANCIAL_COMMERCIAL', 'GOVERNANCE', 'TOOL_PROOF',
  'COMPLETION_PROOF',
] as const;
export type ValidationStage = (typeof VALIDATION_STAGES)[number];

const STAGE_ORDER = new Map<ValidationStage, number>(VALIDATION_STAGES.map((s, i) => [s, i]));
const order = (s: ValidationStage): number => STAGE_ORDER.get(s) ?? 0;

const BRAND_ARTIFACTS: ReadonlySet<string> = new Set([
  'brand_platform', 'brand_core', 'identity_guidelines', 'brand_guidelines_doc', 'creative_concept', 'copy_variant',
  'campaign_package', 'asset_prompt_set', 'design_brief', 'design_system_spec', 'design_token_set', 'website_lockup_spec',
]);
const INTERFACE_ARTIFACTS: ReadonlySet<string> = new Set([
  'design_system_spec', 'design_token_set', 'website_lockup_spec', 'app_build_spec', 'product_spec',
]);
const SOFTWARE_ARTIFACTS: ReadonlySet<string> = new Set(['app_build_spec', 'implementation_plan', 'automation_spec']);
const STRATEGIC_ARTIFACTS: ReadonlySet<string> = new Set([
  'research_brief', 'market_analysis', 'positioning_statement', 'brand_platform', 'business_model_spec',
  'offer_definition', 'measurement_plan',
]);
const PUBLIC_COPY: ReadonlySet<string> = new Set(['copy_variant', 'campaign_package']);
const MEDIA_DOMAINS: readonly string[] = ['FILM', 'VIDEO', 'MOTION', 'ANIMATION', 'VFX'];
const DATA_ARTIFACTS: ReadonlySet<string> = new Set(['measurement_plan', 'media_plan', 'app_build_spec', 'automation_spec']);

type Applies = (artifact: string, domains: ReadonlySet<string>, live: boolean) => boolean;

export interface ValidationProfile {
  readonly profile_id: string;
  readonly stage: ValidationStage;
  readonly validator_skill: string;
  readonly validator_department: string;
  readonly applies: Applies;
  readonly volatile_keys: readonly string[];
}

const p = (
  profile_id: string, stage: ValidationStage, validator_skill: string, validator_department: string,
  applies: Applies, volatile_keys: readonly string[] = [],
): ValidationProfile => ({ profile_id, stage, validator_skill, validator_department, applies, volatile_keys });
const among = (...items: string[]): ReadonlySet<string> => new Set(items);

export const VALIDATION_PROFILES: readonly ValidationProfile[] = [
  p('GROUNDING', 'PROVENANCE', 'research-manager', 'strategy', (a) => STRATEGIC_ARTIFACTS.has(a)),
  p('USER_NEED', 'ACCEPTANCE_CRITERIA', 'ux-researcher', 'strategy', (a) => among('product_spec', 'app_build_spec').has(a)),
  p('ACCESSIBILITY', 'ACCESSIBILITY', 'accessibility-qa-analyst', 'technology', (a) => INTERFACE_ARTIFACTS.has(a),
    ['accessibility.standard']),
  p('SECURITY', 'SECURITY', 'cloud-security-engineer', 'technology', (a) => SOFTWARE_ARTIFACTS.has(a),
    ['security.testing_standard']),
  p('PRIVACY', 'PRIVACY', 'privacy-officer', 'operations', (a) => DATA_ARTIFACTS.has(a)),
  p('AI_POLICY', 'GOVERNANCE', 'ai-governance-lead', 'ai-data',
    (a) => among('asset_prompt_set', 'copy_variant', 'creative_concept').has(a)),
  p('BRAND_COHESION', 'BRAND', 'brand-governance-manager', 'brand', (a) => BRAND_ARTIFACTS.has(a)),
  p('VISUAL_DIRECTION', 'BRAND', 'creative-director', 'creative',
    (a) => among('identity_guidelines', 'design_system_spec', 'design_token_set', 'website_lockup_spec').has(a)),
  p('TRADEMARK', 'LEGAL_RIGHTS', 'trademark-counsel', 'operations', (a) => a === 'naming_candidate'),
  p('CLAIMS_LEGAL', 'LEGAL_RIGHTS', 'advertising-compliance-specialist', 'operations', (a) => PUBLIC_COPY.has(a)),
  p('APP_STORE', 'GOVERNANCE', 'mobile-engineer', 'technology',
    (a, d) => d.has('MOBILE_APP') && among('app_build_spec', 'release_record').has(a), ['app_store.requirements']),
  p('VIDEO_RIGHTS', 'LEGAL_RIGHTS', 'rights-and-clearances-manager', 'operations',
    (a, d) => MEDIA_DOMAINS.some((m) => d.has(m)) && among('asset_prompt_set', 'campaign_package', 'release_record').has(a)),
  p('LIVE_OPERATION', 'GOVERNANCE', 'site-reliability-engineer', 'technology',
    (a, _d, live) => live && among('release_record', 'app_build_spec').has(a)),
];
export const PROFILES_BY_ID: ReadonlyMap<string, ValidationProfile> = new Map(VALIDATION_PROFILES.map((x) => [x.profile_id, x]));

export const BASE_OBLIGATIONS: readonly ValidationStage[] = [
  'SCHEMA', 'PROVENANCE', 'ACCEPTANCE_CRITERIA', 'DISCIPLINE_QA', 'GOVERNANCE', 'COMPLETION_PROOF',
];

export function applicableProfiles(artifactType: ArtifactType, domains: Iterable<string>, liveService = false): ValidationProfile[] {
  const d = new Set(domains);
  return VALIDATION_PROFILES.filter((x) => x.applies(artifactType, d, liveService));
}

export interface ObligationOptions {
  readonly externalAction?: boolean;
  readonly liveService?: boolean;
}

/** `obligations_for`: ordered obligation ids for one artifact's validation node. */
export function obligationsFor(artifactType: ArtifactType, domains: Iterable<string>, options: ObligationOptions = {}): string[] {
  const items: [number, string][] = BASE_OBLIGATIONS.map((s) => [order(s), s]);
  const producer = [...ROLE_REGISTRY.values()].find((r) => r.produces.has(artifactType));
  if (producer !== undefined && producer.min_evidence) {
    items.push([order('PROVENANCE'), `EVIDENCE_FLOOR:${producer.min_evidence}`]);
  }
  for (const profile of applicableProfiles(artifactType, domains, options.liveService ?? false)) {
    items.push([order(profile.stage), `PROFILE:${profile.profile_id}`]);
  }
  if (options.externalAction) {
    items.push([order('AUTHORITY'), 'AUTHORITY'], [order('TOOL_PROOF'), 'TOOL_PROOF']);
  }
  const unique = new Map(items.map((item) => [`${item[0]}\u0000${item[1]}`, item]));
  return [...unique.values()].sort(compareTuples).map(([, obligation]) => obligation);
}

/** Volatile requirement keys the profiles in `obligations` cannot evaluate without fresh evidence. */
export function volatileKeysFor(obligations: Iterable<string>): string[] {
  const keys: string[] = [];
  for (const ob of obligations) {
    if (!ob.startsWith('PROFILE:')) continue;
    const profile = PROFILES_BY_ID.get(ob.slice('PROFILE:'.length));
    if (profile === undefined) throw new CompiledKeyError(pyRepr(ob.slice('PROFILE:'.length)));
    keys.push(...profile.volatile_keys);
  }
  return uniqueSorted(keys);
}

export const RESULT_STATUSES = ['PASS', 'FAIL'] as const;
export type ResultStatus = (typeof RESULT_STATUSES)[number];

export interface ValidationResult {
  readonly node_id: string;
  readonly obligation: string;
  readonly status: ResultStatus;
  readonly validator_ref: string;
  readonly attempt: number;
  readonly failure_fingerprint: string | null;
}

export interface ValidationVerdict {
  readonly node_id: string;
  readonly passed: readonly string[];
  readonly failed: readonly string[];
  readonly pending: readonly string[];
  readonly independence_violations: readonly string[];
  readonly repair_routes: readonly (readonly [string, string])[];
  readonly escalation: string | null;
}

export function verdictComplete(v: ValidationVerdict): boolean {
  return !v.failed.length && !v.pending.length && !v.independence_violations.length && v.escalation === null;
}

const ROUTE_TO_RESEARCH = new Set(['PROVENANCE', 'FRESHNESS', 'PROFILE:GROUNDING']);
const ROUTE_TO_SECURITY = new Set(['SECURITY', 'PROFILE:SECURITY']);

function firstPresent(candidates: readonly string[], graphNodes: ReadonlySet<string>): string | undefined {
  return candidates.find((c) => graphNodes.has(c));
}

/** `route_failure`: smallest causal producer for a failed obligation. */
export function routeFailure(obligation: string, nodeId: string, graphNodes: ReadonlySet<string>): string {
  const cut = nodeId.indexOf(':');
  const artifact = cut >= 0 ? nodeId.slice(cut + 1) : nodeId;
  const producer = `work:${artifact}`;
  if (ROUTE_TO_RESEARCH.has(obligation) || obligation.startsWith('EVIDENCE_FLOOR')) {
    return firstPresent(['work:market_analysis', 'work:research_brief'], graphNodes) ?? `evidence:${artifact}`;
  }
  if (ROUTE_TO_SECURITY.has(obligation)) {
    const found = firstPresent(['work:app_build_spec', 'work:implementation_plan'], graphNodes);
    if (found !== undefined) return found;
  }
  if (obligation === 'AUTHORITY') return `asg:${artifact}`;
  if (obligation === 'APPROVAL_SCOPE') return `approval_scope:${artifact}`;
  return graphNodes.has(producer) ? producer : nodeId;
}

export interface EvaluateValidationOptions {
  readonly creatorRef: string;
  readonly riskLevel: string;
  readonly graphNodes: ReadonlySet<string>;
}

function latestResults(nodeId: string, results: Iterable<ValidationResult>) {
  const latest = new Map<string, ValidationResult>();
  const history = new Map<string, ValidationResult[]>();
  const own = [...results].filter((r) => r.node_id === nodeId)
    .sort((a, b) => compareTuples([a.obligation, a.attempt], [b.obligation, b.attempt]));
  for (const r of own) {
    latest.set(r.obligation, r);
    history.set(r.obligation, [...(history.get(r.obligation) ?? []), r]);
  }
  return { latest, history };
}

function escalationFor(failed: readonly string[], history: ReadonlyMap<string, ValidationResult[]>): string | null {
  let escalation: string | null = null;
  for (const o of failed) {
    const attempts = history.get(o) ?? [];
    if (attempts.length > MAX_REPAIR_ATTEMPTS) return 'CIRCUIT_BREAKER';
    const prints = attempts.filter((a) => a.status === 'FAIL' && a.failure_fingerprint).map((a) => a.failure_fingerprint);
    if (prints.length >= 2 && prints[prints.length - 1] === prints[prints.length - 2]) escalation = 'HUMAN_REVIEW_REQUIRED';
  }
  return escalation;
}

/** `evaluate_validation`: latest result per obligation, independence and escalation. */
export function evaluateValidation(
  nodeId: string, obligations: Iterable<string>, results: Iterable<ValidationResult>, options: EvaluateValidationOptions,
): ValidationVerdict {
  const obs = [...obligations];
  const { latest, history } = latestResults(nodeId, results);
  const passed = obs.filter((o) => latest.get(o)?.status === 'PASS');
  const failed = obs.filter((o) => latest.get(o)?.status === 'FAIL');
  const pending = obs.filter((o) => !latest.has(o));
  const violations = ['medium', 'high', 'critical'].includes(options.riskLevel)
    ? passed.filter((o) => latest.get(o)?.validator_ref === options.creatorRef).map((o) => `CREATOR_SOLE_REVIEWER:${o}`)
    : [];
  const routes = failed.map((o): [string, string] => [o, routeFailure(o, nodeId, options.graphNodes)]).sort(compareTuples);
  return {
    node_id: nodeId, passed, failed, pending, independence_violations: violations, repair_routes: routes,
    escalation: escalationFor(failed, history),
  };
}

export interface ReleaseFacts {
  readonly generation_mode: string | null;
  readonly approval_decision: string | null;
  readonly brand_safety_passed: boolean | null;
  readonly external_side_effect: boolean;
  readonly spend_authorized: boolean;
  readonly unmet_hard_dependencies?: readonly string[];
}

/** `release_blockers`: delegate the release decision to N2; return stable guard codes. */
export function releaseBlockers(facts: ReleaseFacts): string[] {
  const unmet = [...(facts.unmet_hard_dependencies ?? [])];
  const codes = releaseGuardFailures({
    generation_mode: facts.generation_mode,
    approval_exists: facts.approval_decision !== null,
    approval_resolved: facts.approval_decision !== null,
    approval_decision: facts.approval_decision,
    brand_safety_passed: facts.brand_safety_passed,
    external_side_effect: facts.external_side_effect,
    spend_authorized: facts.spend_authorized,
    unmet_hard_dependencies: unmet,
  }).map((f) => f.code);
  if (unmet.length) codes.push('unmet_hard_dependencies');
  return codes;
}
