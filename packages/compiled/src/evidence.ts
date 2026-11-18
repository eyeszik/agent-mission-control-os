/**
 * Twin of `agency/compiled/evidence.py` (T03/T04): the three authority
 * layers, rule promotion and the volatile firewall. Evidence may flow
 * A → candidate → review → B → C, never A → C; promotion returns a candidate
 * status and never widens authority on its own.
 */
import { semanticHash, type HashValue } from './hashing';
import { CompiledValueError } from './errors';
import { constraintInstant } from './isotime';
import { pyStrip, sortStrings, uniqueSorted } from './python';

export const SOURCE_CLASSES = [
  'PRIMARY_OFFICIAL', 'PROFESSIONAL_STANDARD', 'PRACTITIONER_PATTERN', 'CASE_STUDY', 'ACADEMIC', 'VENDOR_DOCUMENTATION',
  'REPOSITORY_EVIDENCE', 'INFERENCE', 'PROPOSED_POLICY',
] as const;
export type SourceClass = (typeof SOURCE_CLASSES)[number];

export const RULE_STATUSES = [
  'SOURCE_CLAIM', 'VERIFIED_PATTERN', 'ORG_POLICY_CANDIDATE', 'RUNTIME_CONSTRAINT_CANDIDATE', 'SUPERSEDED', 'CONFLICTED',
  'STALE', 'GAP', 'REJECTED',
] as const;
export type RuleStatus = (typeof RULE_STATUSES)[number];

export const TARGET_LAYERS = ['A_INDUSTRY_EVIDENCE', 'B_ORGANIZATION_POLICY', 'C_RUNTIME_AUTHORITY'] as const;
export type TargetLayer = (typeof TARGET_LAYERS)[number];

export const VOLATILITIES = ['STABLE', 'SLOW', 'VOLATILE'] as const;
export type Volatility = (typeof VOLATILITIES)[number];

export const EVIDENCE_STRENGTHS = ['NONE', 'WEAK', 'MODERATE', 'STRONG'] as const;
export type EvidenceStrength = (typeof EVIDENCE_STRENGTHS)[number];

export const CLAIM_LABELS = [
  'FACT', 'INDUSTRY_PATTERN', 'SOURCE_SPECIFIC_PRACTICE', 'INFERENCE', 'PROPOSED_AUTOMATION', 'CONFLICT', 'GAP',
] as const;
export type ClaimLabel = (typeof CLAIM_LABELS)[number];

export interface SourceRecord {
  readonly id: string;
  readonly title: string;
  readonly canonical_ref: string;
  readonly source_type: SourceClass;
  readonly publisher: string;
  readonly author: string | null;
  readonly date: string | null;
  readonly domains: readonly string[];
  readonly stages: readonly string[];
  readonly departments: readonly string[];
  readonly artifacts: readonly string[];
  readonly primary: boolean;
  readonly quality: string | null;
  readonly claims: readonly string[];
  readonly limitations: readonly string[];
}

export interface Claim {
  readonly id: string;
  readonly statement: string;
  readonly label: ClaimLabel;
  readonly source_refs: readonly string[];
}

const TRIANGULATION: readonly (readonly [string, ReadonlySet<SourceClass>])[] = [
  ['PRIMARY_PROCESS', new Set<SourceClass>(['PRIMARY_OFFICIAL', 'REPOSITORY_EVIDENCE'])],
  ['PRACTITIONER_OR_CASE', new Set<SourceClass>(['PRACTITIONER_PATTERN', 'CASE_STUDY'])],
  ['STANDARD_OR_TECHNICAL', new Set<SourceClass>(['PROFESSIONAL_STANDARD', 'PRIMARY_OFFICIAL', 'VENDOR_DOCUMENTATION', 'ACADEMIC'])],
];

/** Missing triangulation categories; non-empty means EVIDENCE_DEFICIT. */
export function triangulationDeficits(claim: Claim, sources: Iterable<SourceRecord>): string[] {
  const byId = new Map<string, SourceRecord>();
  for (const s of sources) byId.set(s.id, s);
  const classes = new Set(claim.source_refs.filter((r) => byId.has(r)).map((r) => byId.get(r)?.source_type));
  const missing = TRIANGULATION.filter(([, allowed]) => ![...allowed].some((c) => classes.has(c))).map(([name]) => name);
  if (claim.source_refs.length && claim.source_refs.some((r) => !byId.has(r))) missing.push('UNRESOLVED_SOURCE_REF');
  return missing;
}

export interface RuleCandidate {
  readonly id: string;
  readonly statement: string;
  readonly source_refs: readonly string[];
  readonly source_class: SourceClass;
  readonly jurisdiction: string | null;
  readonly domain: readonly string[];
  readonly applicable_context: readonly string[];
  readonly freshness: string | null;
  readonly recheck_at: string | null;
  readonly organization_specific: boolean;
  readonly volatility: Volatility;
  readonly evidence_strength: EvidenceStrength;
  readonly conflicts: readonly string[];
  readonly target_layer: TargetLayer;
  readonly status: RuleStatus;
  readonly runtime_ref: string | null;
}

export type RuleCandidateInput = Pick<RuleCandidate, 'id' | 'statement' | 'source_class'> & Partial<RuleCandidate>;

/** A RuleCandidate with Pydantic's field defaults filled in. */
export function ruleCandidate(input: RuleCandidateInput): RuleCandidate {
  return {
    source_refs: [], jurisdiction: null, domain: [], applicable_context: [], freshness: null, recheck_at: null,
    organization_specific: false, volatility: 'STABLE', evidence_strength: 'WEAK', conflicts: [],
    target_layer: 'A_INDUSTRY_EVIDENCE', status: 'SOURCE_CLAIM', runtime_ref: null, ...input,
  };
}

export interface PromotionContext {
  readonly as_of: string;
  readonly applicability_verified: boolean;
  readonly repository_contract_compatible: boolean | null;
  readonly org_policy_approval_ref: string | null;
  readonly jurisdictions_in_scope: readonly string[];
}

export interface PromotionResult {
  readonly rule_id: string;
  readonly status: RuleStatus;
  readonly effective_layer: TargetLayer;
  readonly may_become_executable: boolean;
  readonly failures: readonly string[];
  readonly result_hash: string;
}

export const RUNTIME_SUFFICIENT_SOURCES: ReadonlySet<SourceClass> = new Set<SourceClass>([
  'REPOSITORY_EVIDENCE', 'PRIMARY_OFFICIAL', 'PROFESSIONAL_STANDARD',
]);

function done(candidate: RuleCandidate, failures: readonly string[], status: RuleStatus, layer: TargetLayer, executable = false): PromotionResult {
  const body = { rule_id: candidate.id, status, effective_layer: layer, may_become_executable: executable, failures: uniqueSorted(failures) };
  return { ...body, result_hash: semanticHash({ ...body, candidate: candidate as unknown as HashValue }) };
}

/** Terminal, unsourced, conflicted or volatile-stale candidates short-circuit. */
function earlyExit(candidate: RuleCandidate, context: PromotionContext): PromotionResult | null {
  if (candidate.status === 'REJECTED' || candidate.status === 'SUPERSEDED') {
    return done(candidate, [`TERMINAL_${candidate.status}`], candidate.status, 'A_INDUSTRY_EVIDENCE');
  }
  if (!candidate.source_refs.length) return done(candidate, ['NO_SOURCE_REFS'], 'GAP', 'A_INDUSTRY_EVIDENCE');
  if (candidate.conflicts.length) return done(candidate, ['UNRESOLVED_CONFLICT'], 'CONFLICTED', 'A_INDUSTRY_EVIDENCE');
  if (candidate.volatility === 'VOLATILE') {
    if (!candidate.freshness) return done(candidate, ['VOLATILE_NEVER_VERIFIED'], 'GAP', 'A_INDUSTRY_EVIDENCE');
    if (!candidate.recheck_at || candidate.recheck_at <= context.as_of) {
      return done(candidate, ['VOLATILE_RECHECK_EXPIRED'], 'STALE', 'A_INDUSTRY_EVIDENCE');
    }
  }
  return null;
}

function promotionFacts(candidate: RuleCandidate, context: PromotionContext) {
  const external = candidate.source_class !== 'REPOSITORY_EVIDENCE';
  return {
    sourceSufficient: RUNTIME_SUFFICIENT_SOURCES.has(candidate.source_class),
    jurisdictionValid: candidate.jurisdiction === null || context.jurisdictions_in_scope.includes(candidate.jurisdiction),
    repositoryCompatible: context.repository_contract_compatible === true,
    orgApproved: Boolean(context.org_policy_approval_ref),
    orgNeeded: external || candidate.organization_specific,
  };
}

/** `evaluate_promotion`: deterministic; never widens authority on its own. */
export function evaluatePromotion(candidate: RuleCandidate, context: PromotionContext): PromotionResult {
  const early = earlyExit(candidate, context);
  if (early !== null) return early;
  const f = promotionFacts(candidate, context);
  const failures: string[] = [];
  if (!context.applicability_verified) failures.push('APPLICABILITY_UNVERIFIED');
  if (!f.sourceSufficient) failures.push('SOURCE_AUTHORITY_INSUFFICIENT_FOR_RUNTIME');
  if (!f.jurisdictionValid) failures.push('JURISDICTION_OUT_OF_SCOPE');
  if (!f.repositoryCompatible) failures.push('REPOSITORY_CONTRACT_UNPROVEN');
  if (f.orgNeeded && !f.orgApproved) failures.push('ORG_POLICY_APPROVAL_REQUIRED');
  if (candidate.organization_specific && !f.orgApproved) failures.push('ORG_SPECIFIC_NOT_UNIVERSAL');
  const executable = context.applicability_verified && f.sourceSufficient && f.jurisdictionValid
    && f.repositoryCompatible && (f.orgApproved || !f.orgNeeded);
  if (executable && candidate.target_layer === 'C_RUNTIME_AUTHORITY') {
    return done(candidate, failures, 'RUNTIME_CONSTRAINT_CANDIDATE', 'C_RUNTIME_AUTHORITY', true);
  }
  if (context.applicability_verified && candidate.target_layer !== 'A_INDUSTRY_EVIDENCE') {
    return done(candidate, failures, 'ORG_POLICY_CANDIDATE', 'B_ORGANIZATION_POLICY');
  }
  if ((candidate.evidence_strength === 'MODERATE' || candidate.evidence_strength === 'STRONG') && context.applicability_verified) {
    return done(candidate, failures, 'VERIFIED_PATTERN', 'A_INDUSTRY_EVIDENCE');
  }
  return done(candidate, failures, 'SOURCE_CLAIM', 'A_INDUSTRY_EVIDENCE');
}

const C: TargetLayer = 'C_RUNTIME_AUTHORITY';
const B: TargetLayer = 'B_ORGANIZATION_POLICY';

/** The rule-promotion ledger seeded from the specification and repository. */
export const SPEC_RULE_CANDIDATES: readonly RuleCandidate[] = [
  ruleCandidate({ id: 'rule.degraded_cannot_release', statement: 'FALLBACK_DEGRADED generation cannot reach a client-visible state.',
    source_refs: ['repo:services/langgraph/agency/kernel/lifecycle.py#_guard_not_degraded'], source_class: 'REPOSITORY_EVIDENCE',
    evidence_strength: 'STRONG', target_layer: C, runtime_ref: 'services/langgraph/agency/kernel/lifecycle.py' }),
  ruleCandidate({ id: 'rule.consequential_requires_exact_approval',
    statement: 'Irreversible or high-risk work is not execution-ready without an exact approval ref.',
    source_refs: ['repo:services/langgraph/agency/role_os/work_order.py'], source_class: 'REPOSITORY_EVIDENCE',
    evidence_strength: 'STRONG', target_layer: C, runtime_ref: 'services/langgraph/agency/role_os/work_order.py' }),
  ruleCandidate({ id: 'rule.role_title_grants_no_authority',
    statement: 'Role seniority/title/source authority labels never grant runtime permission.',
    source_refs: ['repo:runtime/role_os/authority_registry.runtime.json', 'repo:docs/agency-role-os/source_instruction_dispositions.json#R01'],
    source_class: 'REPOSITORY_EVIDENCE', evidence_strength: 'STRONG', target_layer: C,
    runtime_ref: 'runtime/role_os/authority_registry.runtime.json' }),
  ruleCandidate({ id: 'rule.brand.logo_last', statement: "Develop strategy and territories before the mark ('logo last').",
    source_refs: ['spec:§10', 'spec:§11.B'], source_class: 'PRACTITIONER_PATTERN', domain: ['BRAND'],
    organization_specific: true, evidence_strength: 'MODERATE', target_layer: B }),
  ruleCandidate({ id: 'rule.creative.direction_freeze',
    statement: 'Freeze selected creative direction; changes go through controlled change.', source_refs: ['spec:§11.C'],
    source_class: 'PRACTITIONER_PATTERN', domain: ['BRAND', 'CONTENT'], organization_specific: true,
    evidence_strength: 'MODERATE', target_layer: B }),
  ruleCandidate({ id: 'rule.media.budget_ratio', statement: 'Fixed production-to-media budget ratios.', source_refs: ['spec:§11.F'],
    source_class: 'CASE_STUDY', domain: ['MEDIA', 'VIDEO'], organization_specific: true, evidence_strength: 'WEAK', target_layer: C }),
  ruleCandidate({ id: 'rule.service.govuk_phases', statement: 'Discovery/Alpha/Beta/Live service phases apply to all digital work.',
    source_refs: ['spec:§11.A'], source_class: 'PRIMARY_OFFICIAL', domain: ['WEB', 'SOFTWARE'], jurisdiction: 'GB-public-sector',
    evidence_strength: 'STRONG', target_layer: C }),
  ruleCandidate({ id: 'rule.naming.automated_search_not_clearance',
    statement: 'Automated availability search is never presented as legal trademark clearance.', source_refs: ['spec:§11.D'],
    source_class: 'PROFESSIONAL_STANDARD', domain: ['BRAND'], evidence_strength: 'STRONG', target_layer: B }),
  ruleCandidate({ id: 'rule.app_store.metadata_limits', statement: 'App-store name/description character limits.',
    source_refs: ['spec:§32'], source_class: 'PRIMARY_OFFICIAL', domain: ['MOBILE_APP'], volatility: 'VOLATILE', target_layer: C }),
  ruleCandidate({ id: 'rule.accessibility.standard_version', statement: 'Accessibility conformance target version.',
    source_refs: ['spec:§31', 'repo:services/langgraph/agency/ui_ux'], source_class: 'PROFESSIONAL_STANDARD',
    domain: ['UX_UI', 'WEB'], volatility: 'VOLATILE', target_layer: C }),
  ruleCandidate({ id: 'rule.security.testing_standard_version', statement: 'Web/software security testing standard version.',
    source_refs: ['spec:§31'], source_class: 'PROFESSIONAL_STANDARD', domain: ['WEB', 'SOFTWARE'], volatility: 'VOLATILE',
    target_layer: C }),
  ruleCandidate({ id: 'rule.meetings.weekly_status', statement: 'A fixed weekly status meeting cadence is an invariant.',
    source_refs: [], source_class: 'INFERENCE', target_layer: C }),
  ruleCandidate({ id: 'rule.cloudflare.runtime_topology', statement: 'Agency runtime executes on Cloudflare Durable Objects/D1/KV.',
    source_refs: ['zip:references/imported_specs/runtime_topology.yaml'], source_class: 'VENDOR_DOCUMENTATION',
    conflicts: ['repo:docs/agency-role-os/source_instruction_dispositions.json#R08'], target_layer: C }),
];

/** Repository-evidence rules are contract-compatible; nothing is org-adopted. */
export function defaultPromotionContext(asOf: string): PromotionContext {
  return { as_of: asOf, applicability_verified: true, repository_contract_compatible: true, org_policy_approval_ref: null,
    jurisdictions_in_scope: [] };
}

export function ruleLedger(asOf: string, candidates: readonly RuleCandidate[] = SPEC_RULE_CANDIDATES) {
  const ctx = defaultPromotionContext(asOf);
  const results = candidates.map((c) => evaluatePromotion(c, ctx));
  const count = (pred: (r: PromotionResult) => boolean): number => results.filter(pred).length;
  return {
    summary: {
      candidates: results.length,
      accepted: count((r) => r.status === 'RUNTIME_CONSTRAINT_CANDIDATE'),
      rejected: count((r) => r.status === 'REJECTED' || r.status === 'CONFLICTED'),
      stale: count((r) => r.status === 'STALE'),
      gaps: count((r) => r.status === 'GAP'),
    },
    results,
  };
}

export const VOLATILE_VERIFICATIONS = ['VERIFIED', 'UNVERIFIED', 'EXPIRED'] as const;
export type VolatileVerification = (typeof VOLATILE_VERIFICATIONS)[number];

export interface VolatileConstraint {
  readonly key: string;
  readonly source_ref: string | null;
  readonly retrieved_at: string | null;
  readonly effective_date: string | null;
  readonly value: string | null;
  readonly applicability: readonly string[];
  readonly verification_status: VolatileVerification;
  readonly expires_or_recheck_at: string | null;
}

function sourced(c: VolatileConstraint): boolean {
  return c.verification_status === 'VERIFIED' && Boolean(c.source_ref) && nonBlank(c.source_ref) && Boolean(c.retrieved_at)
    && c.value !== null && nonBlank(c.value);
}

function nonBlank(text: string | null): boolean {
  return text !== null && pyStrip(text) !== '';
}

function instants(c: VolatileConstraint, asOf: string) {
  return {
    current: constraintInstant(asOf),
    retrieved: constraintInstant(c.retrieved_at ?? ''),
    effective: c.effective_date !== null ? constraintInstant(c.effective_date) : null,
    expires: c.expires_or_recheck_at ? constraintInstant(c.expires_or_recheck_at) : null,
  };
}

/** `volatile_status`: sourced, current values, compared as instants, never as strings. */
export function volatileStatus(constraint: VolatileConstraint, asOf: string): VolatileVerification {
  if (constraint.verification_status === 'EXPIRED') return 'EXPIRED';
  if (!sourced(constraint)) return 'UNVERIFIED';
  let t: ReturnType<typeof instants>;
  try {
    t = instants(constraint, asOf);
  } catch (error) {
    if (error instanceof CompiledValueError) return 'UNVERIFIED';
    throw error;
  }
  if (t.retrieved > t.current || (t.effective !== null && t.effective > t.current)) return 'UNVERIFIED';
  if (t.expires === null || t.expires <= t.current) return 'EXPIRED';
  return 'VERIFIED';
}

export function volatileReleaseBlockers(constraints: Iterable<VolatileConstraint>, asOf: string): string[] {
  const out: string[] = [];
  for (const c of constraints) {
    const status = volatileStatus(c, asOf);
    if (status !== 'VERIFIED') out.push(`VOLATILE_${status}:${c.key}`);
  }
  return sortStrings(out);
}
