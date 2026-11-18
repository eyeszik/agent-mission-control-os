/**
 * The claims-audit passes of the prompt compiler (twin of the first half of
 * `agency/prompt_compiler.py`): intake, gap hunt, research backfill, claim
 * validation, computation assessment and the evidence ceiling carried into the
 * prompt. Retrieval never silently rewrites source material: no research result
 * is fabricated, and a computation can never mark a claim VERIFIED.
 */
import { CanonicalFloat } from '@amc/canonical';
import type {
  ClaimRecord,
  ClaimStatus,
  ClaimType,
  ComputationAssessment,
  ComputationEvidence,
  GapRecord,
  PromptCompilerRequest,
  ResearchRequest,
  SourceClass,
  SourceEvidence,
} from './compiler-models';
import { ignoreCaseAny, PY_BOUNDARY, PY_DIGIT, PY_SPACE, pyRegExp } from './pyre';
import { compareCodePoints, pyCasefold, pyLen, pyStrip, sha256Text, sortedStrings } from './pytext';

const SENTENCE_SPLIT = pyRegExp(`(?<=[.!?])${PY_SPACE}+`);
const B = PY_BOUNDARY;
const API_HINT = pyRegExp(`${B}(?:${ignoreCaseAny(['api', 'sdk', 'endpoint', 'webhook', 'mcp', 'provider', 'model'])})${B}`);
const ic = (literal: string): string => ignoreCaseAny([literal]);
const optionalS = (word: string): string => `${ic(word)}${ic('s')}?`;
const METRIC_UNITS = [
  '%', ic('x'), ic('ms'), ic('s'), optionalS('second'), optionalS('minute'), optionalS('hour'), optionalS('day'),
  optionalS('user'), optionalS('request'), ic('usd'), '\\$',
];
const METRIC_HINT = pyRegExp(`${B}${PY_DIGIT}+(?:\\.${PY_DIGIT}+)?${PY_SPACE}*(?:${METRIC_UNITS.join('|')})${B}`);
const MARKET_HINT = pyRegExp(
  `${B}(?:${ignoreCaseAny(['market', 'competitor', 'industry', 'audience', 'customer', 'tam', 'sam', 'som', 'share'])})${B}`,
);
const LEGAL_HINT = pyRegExp(
  `${B}(?:${ignoreCaseAny(['legal', 'law', 'regulation', 'compliance', 'licensed', 'copyright', 'trademark', 'wcag', 'privacy'])})${B}`,
);
const COMPARATIVES = ['better', 'faster', 'cheaper', 'stronger', 'safer', 'smarter', 'easier', 'healthier', 'cleaner', 'quieter'];
// Comparative or superiority claims ("faster than X", "#1", "industry-leading") are market claims.
const COMPARATIVE_HINT = pyRegExp(
  [
    `${B}(?:${ignoreCaseAny(COMPARATIVES)})${PY_SPACE}+${ic('than')}${B}`,
    `#1${B}`,
    `${B}${ic('number')}[- ]${ic('one')}${B}`,
    `${B}${ic('industry')}[- ]${ic('leading')}${B}`,
    `${B}${ic('market')}[- ]${ic('leading')}${B}`,
    `${B}${ic('market leader')}${B}`,
  ].join('|'),
);

/** Python `re.search` on the compiled pattern: first match anywhere. */
function found(pattern: RegExp, text: string): boolean {
  return text.search(pattern) !== -1;
}

export function claimId(text: string, index: number): string {
  return `clm_${String(index).padStart(3, '0')}_${sha256Text(text).slice(0, 10)}`;
}

export function inferClaimType(text: string): ClaimType {
  if (found(API_HINT, text)) return 'API_CLAIM';
  if (found(METRIC_HINT, text)) return 'METRIC';
  if (found(LEGAL_HINT, text)) return 'LEGAL_CLAIM';
  if (found(MARKET_HINT, text) || found(COMPARATIVE_HINT, text)) return 'MARKET_CLAIM';
  return 'FACT';
}

function seededClaims(request: PromptCompilerRequest): ClaimRecord[] {
  return request.claims.map((seed, index) => ({
    claim_id: claimId(seed.text, index + 1),
    text: pyStrip(seed.text),
    claim_type: seed.claim_type,
    source_ref: seed.source_ref,
    stakeholder: seed.stakeholder,
    temporal_scope: seed.temporal_scope,
    status: 'USER_ASSERTED',
    confidence: new CanonicalFloat(0.55),
  }));
}

export function intakeClaims(request: PromptCompilerRequest): ClaimRecord[] {
  const records = seededClaims(request);
  const content = pyStrip(request.content);
  if (!request.extract_content_claims || content === '') return records;
  const known = new Set(records.map((record) => pyCasefold(record.text)));
  for (const sentence of content.split(SENTENCE_SPLIT)) {
    const text = pyStrip(sentence);
    if (pyLen(text) < 20 || known.has(pyCasefold(text))) continue;
    records.push({
      claim_id: claimId(text, records.length + 1),
      text,
      claim_type: inferClaimType(text),
      source_ref: null,
      stakeholder: null,
      temporal_scope: null,
      status: 'UNVERIFIED',
      confidence: new CanonicalFloat(0.35),
    });
    known.add(pyCasefold(text));
  }
  return records;
}

const HIGH_RISK: ReadonlySet<ClaimType> = new Set<ClaimType>(['API_CLAIM', 'METRIC', 'LEGAL_CLAIM', 'MARKET_CLAIM']);
const pad3 = (value: number): string => String(value).padStart(3, '0');

export function huntGaps(claims: readonly ClaimRecord[]): GapRecord[] {
  const gaps: GapRecord[] = [];
  for (const claim of claims) {
    if (claim.source_ref !== null && claim.source_ref !== '') continue;
    const highRisk = HIGH_RISK.has(claim.claim_type);
    gaps.push({
      gap_id: `gap_${pad3(gaps.length + 1)}`,
      claim_refs: [claim.claim_id],
      category: claim.claim_type === 'API_CLAIM' ? 'UNDOCUMENTED_API' : 'MISSING_SOURCE',
      description: `No authoritative evidence is attached to claim: ${claim.text}`,
      materiality: highRisk ? 'HIGH' : 'MEDIUM',
      retrieval_target: claim.text,
      required_source_class: highRisk ? 'OFFICIAL' : 'PRIMARY',
      blocks_synthesis: highRisk,
    });
    if (claim.claim_type === 'PROMISE' && (claim.stakeholder === null || claim.stakeholder === '')) {
      gaps.push({
        gap_id: `gap_${pad3(gaps.length + 1)}`,
        claim_refs: [claim.claim_id],
        category: 'UNDECLARED_STAKEHOLDER',
        description: 'Promise claim does not identify who makes or receives the commitment.',
        materiality: 'HIGH',
        retrieval_target: null,
        required_source_class: null,
        blocks_synthesis: true,
      });
    }
  }
  return gaps;
}

export function buildResearchBackfill(gaps: readonly GapRecord[]): ResearchRequest[] {
  const requests: ResearchRequest[] = [];
  for (const gap of gaps) {
    if (gap.materiality !== 'CRITICAL' && gap.materiality !== 'HIGH') continue;
    if (gap.retrieval_target === null || gap.retrieval_target === '') continue;
    requests.push({
      request_id: `rr_${pad3(requests.length + 1)}`,
      gap_id: gap.gap_id,
      query: gap.retrieval_target,
      required_source_class: gap.required_source_class,
      max_hops: 3,
    });
  }
  return requests;
}

const SOURCE_WEIGHT: Readonly<Record<SourceClass, number>> = {
  PRIMARY: 0.95,
  OFFICIAL: 0.9,
  SECONDARY: 0.78,
  COMMUNITY: 0.62,
  USER: 0.55,
};

function withStatus(claim: ClaimRecord, status: ClaimStatus, confidence: number): ClaimRecord {
  return { ...claim, status, confidence: new CanonicalFloat(confidence) };
}

function evidenceByClaim(evidence: readonly SourceEvidence[]): Map<string, SourceEvidence[]> {
  const byClaim = new Map<string, SourceEvidence[]>();
  for (const item of evidence) {
    for (const id of item.claim_ids) byClaim.set(id, [...(byClaim.get(id) ?? []), item]);
  }
  return byClaim;
}

function validateOne(claim: ClaimRecord, linked: readonly SourceEvidence[]): ClaimRecord {
  if (linked.length === 0) return claim;
  const supporting = linked.filter((item) => item.supports);
  const opposing = linked.filter((item) => !item.supports);
  if (supporting.length > 0 && opposing.length > 0) return withStatus(claim, 'CONFLICTED', 0.5);
  if (opposing.length > 0) return withStatus(claim, 'VOID', 0.15);
  let score = Math.max(...supporting.map((item) => SOURCE_WEIGHT[item.source_class]));
  if (supporting.length > 1) score = Math.min(0.99, score + 0.03);
  return withStatus(claim, score >= 0.8 ? 'VERIFIED' : 'PARTIALLY_VERIFIED', score);
}

export function validateClaims(claims: readonly ClaimRecord[], evidence: readonly SourceEvidence[]): ClaimRecord[] {
  const byClaim = evidenceByClaim(evidence);
  return claims.map((claim) => validateOne(claim, byClaim.get(claim.claim_id) ?? []));
}

const VERIFIED: ReadonlySet<ClaimStatus> = new Set<ClaimStatus>(['VERIFIED', 'PARTIALLY_VERIFIED']);
const NOTE_PREMISES = 'A correct computation does not verify its input premises.';
const NOTE_NO_EMPIRICAL = 'Result depends only on stated inputs and assumptions, not on empirical claims.';

function assessOne(computation: ComputationEvidence, byId: ReadonlyMap<string, ClaimRecord>): ComputationAssessment {
  const refs = [...computation.input_claim_ids, ...computation.derived_claim_ids];
  const unknown = sortedStrings(refs.filter((ref) => !byId.has(ref)));
  const derived = sortedStrings(computation.derived_claim_ids);
  if (unknown.length > 0) {
    return {
      computation_id: computation.computation_id,
      status: 'INVALID_REFERENCE',
      derived_claim_ids: derived,
      unverified_inputs: [],
      notes: unknown.map((ref) => `unknown claim reference: ${ref}`),
    };
  }
  const unverified = sortedStrings(computation.input_claim_ids.filter((ref) => !VERIFIED.has((byId.get(ref) as ClaimRecord).status)));
  const hasInputs = computation.input_claim_ids.length > 0;
  const status = unverified.length > 0 ? 'PREMISES_UNVERIFIED' : hasInputs ? 'DERIVED_FROM_VERIFIED_INPUTS' : 'NO_EMPIRICAL_INPUTS';
  const notes = unverified.length > 0 ? [NOTE_PREMISES] : hasInputs ? [] : [NOTE_NO_EMPIRICAL];
  if (computation.assumptions.length > 0) notes.push(`Assumptions remain assumptions: ${computation.assumptions.join('; ')}`);
  return { computation_id: computation.computation_id, status, derived_claim_ids: derived, unverified_inputs: unverified, notes };
}

/** Classify each computation without ever upgrading an empirical premise. */
export function assessComputations(claims: readonly ClaimRecord[], computations: readonly ComputationEvidence[]): ComputationAssessment[] {
  const byId = new Map(claims.map((claim) => [claim.claim_id, claim] as const));
  const ordered = [...computations].sort((a, b) => compareCodePoints(a.computation_id, b.computation_id));
  return ordered.map((computation) => assessOne(computation, byId));
}

export function soundDerivedClaimIds(assessments: readonly ComputationAssessment[]): Set<string> {
  const sound = new Set<string>();
  for (const item of assessments) {
    if (item.status === 'DERIVED_FROM_VERIFIED_INPUTS' || item.status === 'NO_EMPIRICAL_INPUTS') {
      for (const ref of item.derived_claim_ids) sound.add(ref);
    }
  }
  return sound;
}

/** Mark soundly derived claims DERIVED. Never VERIFIED; inputs untouched. */
export function applyComputations(
  claims: readonly ClaimRecord[],
  assessments: readonly ComputationAssessment[],
  computations: readonly ComputationEvidence[],
): ClaimRecord[] {
  const itemInputs = new Map(computations.map((item) => [item.computation_id, [...item.input_claim_ids]] as const));
  const sound = soundDerivedClaimIds(assessments);
  const byId = new Map(claims.map((claim) => [claim.claim_id, claim] as const));
  return claims.map((claim) => {
    if (!sound.has(claim.claim_id) || VERIFIED.has(claim.status)) return claim;
    const inputs = assessments
      .filter((item) => item.derived_claim_ids.includes(claim.claim_id))
      .flatMap((item) => itemInputs.get(item.computation_id) ?? [])
      .filter((ref) => byId.has(ref))
      .map((ref) => (byId.get(ref) as ClaimRecord).confidence.value);
    return withStatus(claim, 'DERIVED', Math.min(0.8, ...inputs));
  });
}

const MATERIAL_TYPES: ReadonlySet<ClaimType> = new Set<ClaimType>(['API_CLAIM', 'METRIC', 'LEGAL_CLAIM', 'MARKET_CLAIM', 'PROMISE']);
export { MATERIAL_TYPES, VERIFIED as VERIFIED_STATUSES };

function groupBy(pairs: ReadonlyArray<readonly [string, string]>): Map<string, string[]> {
  const out = new Map<string, string[]>();
  for (const [key, value] of pairs) out.set(key, [...(out.get(key) ?? []), value]);
  return out;
}

function evidenceLine(claim: ClaimRecord, sources: ReadonlyMap<string, string[]>, derivedFrom: ReadonlyMap<string, string[]>): string | null {
  if (VERIFIED.has(claim.status)) {
    const refs = sortedStrings(sources.get(claim.claim_id) ?? []).join(', ') || 'linked evidence';
    return `Supported claim (${claim.status}; evidence: ${refs}): ${claim.text}`;
  }
  if (claim.status === 'DERIVED') {
    const refs = sortedStrings(derivedFrom.get(claim.claim_id) ?? []).join(', ');
    return `Derived claim (computed from verified inputs; computation: ${refs}): ${claim.text}`;
  }
  if (MATERIAL_TYPES.has(claim.claim_type)) {
    return `Not verified — do not state as fact; qualify or omit (${claim.status}): ${claim.text}`;
  }
  return null;
}

/** Carry the evidence ceiling into the prompt: what may be stated, and what may not. */
export function evidenceDirectives(
  claims: readonly ClaimRecord[],
  evidence: readonly SourceEvidence[],
  assessments: readonly ComputationAssessment[],
): string[] {
  const sources = groupBy(evidence.filter((item) => item.supports).flatMap((item) => item.claim_ids.map((ref) => [ref, item.source_id] as const)));
  const derivedFrom = groupBy(assessments.flatMap((item) => item.derived_claim_ids.map((ref) => [ref, item.computation_id] as const)));
  return claims.map((claim) => evidenceLine(claim, sources, derivedFrom)).filter((line): line is string => line !== null);
}
