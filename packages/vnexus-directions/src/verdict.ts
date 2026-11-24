/**
 * Verdicts, the comparison recommendation, brand memory, refinement checks and work orders
 * (`directions/review.py`). Gates are non-compensatory: a creative mean never overrides a failed gate. Work orders
 * are `PROPOSAL_ONLY`; a recommendation is not an approval.
 */
import { CanonicalFloat } from '@amc/canonical';
import { compareCodePoints, formatFixed, formatPercent0, pyFloatStr, pyRound, type PyValue } from '@amc/vnexus-brandbook';
import {
  COMPARE_COVERAGE, COMPARE_MARGIN, CREATIVE_LENSES, LENSES, SMALL_SIZE_RETENTION,
} from './board';
import type { CandidateMeasurement } from './measure';
import {
  GATES, RECOMMENDATION_NOTE, WORK_ORDER_EXECUTION, recordId,
  type CandidateOutcome, type CreativeIntent, type CriterionAssessment, type DirectionRecommendation, type GateResult, type GenerationCandidate,
  type ReviewFinding, type ReviewMode, type ReviewSession, type RevisionWorkOrder, type Verdict,
} from './records';

type Rec = { [key: string]: PyValue };

/** A Python float that may be integral: it must stay a float in hashes and serialized output. */
export function pyFloat(x: number): number | CanonicalFloat {
  return Number.isInteger(x) || Object.is(x, -0) ? new CanonicalFloat(x) : x;
}

export function workOrders(intent: CreativeIntent, findings: readonly ReviewFinding[]): RevisionWorkOrder[] {
  const protectedInvariants = [...intent.vector_instructions.protected, 'approved palette roles', 'exact identity text'];
  const out: RevisionWorkOrder[] = [];
  for (const f of findings) {
    if (!f.actionable || f.severity === 'NOTE') continue;
    out.push({ work_order_id: recordId('vdw', { f: f.finding_id }), candidate_id: f.candidate_id, asset_hash: f.asset_hash,
      change: f.proposed_change ?? '', why: f.rationale ? `${f.observation} (${f.rationale})` : f.observation, protected_invariants: protectedInvariants,
      dependencies: { asset_sha256: f.asset_hash, intent_id: intent.intent_id, genome_ref: intent.genome_ref,
        intent_dependency_hash: intent.dependency_hash, criterion: f.criterion, seat: f.seat },
      verification: f.acceptance_check ?? '', finding_ids: [f.finding_id], authority: 'PROPOSAL_ONLY', execution: WORK_ORDER_EXECUTION });
  }
  return out;
}

/** Blinded labels A, B, ... by asset hash (COMPARE) or by slot order. Label -> candidate id. */
export function labels(cands: readonly GenerationCandidate[], blinded: boolean): { [label: string]: string } {
  const ordered = [...cands].sort(blinded ? (a, b) => compareCodePoints(a.observed.sha256, b.observed.sha256)
    : (a, b) => a.slot - b.slot || compareCodePoints(a.candidate_id, b.candidate_id));
  return Object.fromEntries(ordered.map((c, i) => [String.fromCharCode(65 + i), c.candidate_id]));
}

export function verdictFor(mode: ReviewMode, cand: GenerationCandidate, gates: readonly GateResult[], findings: readonly ReviewFinding[],
  missing: ReadonlySet<string>, label: string, regressions: readonly Rec[]): CandidateOutcome {
  const mine = gates.filter((g) => g.candidate_id === cand.candidate_id);
  const reasons: string[] = [];
  const result = (v: Verdict): CandidateOutcome => ({ candidate_id: cand.candidate_id, label, asset_hash: cand.observed.sha256, verdict: v, reasons });
  const out = mine.find((g) => g.gate === 'OUTPUT_PROVENANCE');
  if (out === undefined) throw new StopIteration();
  if (out.status !== 'PASS') {
    reasons.push(`OUTPUT_PROVENANCE ${out.status}: ${out.evidence}`);
    return result('BLOCKED');
  }
  const failed = mine.filter((g) => g.status === 'FAIL');
  const severe = findings.filter((f) => f.candidate_id === cand.candidate_id && (f.severity === 'BLOCKER' || f.severity === 'MAJOR')
    && (f.evidence_class === 'OBSERVED' || f.evidence_class === 'INFERRED'));
  const regress = regressions.filter((r) => r['candidate_id'] === cand.candidate_id);
  if (failed.length > 0 || severe.length > 0 || regress.length > 0) {
    reasons.push(...failed.map((g) => `GATE_FAILED ${g.gate}: ${g.evidence}`), ...severe.map((f) => `${f.severity} ${f.criterion}: ${f.observation}`),
      ...regress.map((r) => `REGRESSION ${r['metric'] || r['work_order_id']}`));
    return result('REVISE');
  }
  return clearVerdict(mode, mine, missing, reasons, result);
}

/** `next()` on an empty iterator: raised when a candidate has no OUTPUT_PROVENANCE gate. */
export class StopIteration extends Error {
  override name = 'StopIteration';
  constructor() {
    super('');
  }
}

function clearVerdict(mode: ReviewMode, mine: readonly GateResult[], missing: ReadonlySet<string>, reasons: string[],
  result: (v: Verdict) => CandidateOutcome): CandidateOutcome {
  const unknown = mine.filter((g) => g.status === 'UNKNOWN');
  if (missing.size > 0) {
    reasons.push('required lenses not reviewed: ' + [...missing].sort().map((s) => `${s} ${LENSES[s]?.name ?? ''}`).join(', '));
    return result(mode === 'FULL' || mode === 'VECTOR' || mode === 'RELEASE' ? 'BLOCKED' : 'INCONCLUSIVE');
  }
  if (unknown.length > 0) {
    reasons.push(...unknown.map((g) => `GATE_UNKNOWN ${g.gate}: ${g.evidence}`));
    return result(mode === 'RELEASE' ? 'BLOCKED' : 'INCONCLUSIVE');
  }
  if (mode === 'QUICK') {
    reasons.push('QUICK triage found no blocker or major defect; it cannot substitute for release review');
    return result('INCONCLUSIVE');
  }
  if (mode === 'COMPARE') {
    reasons.push('eligible for comparison');
    return result('INCONCLUSIVE');
  }
  reasons.push('applicable checks satisfied; the existing human decision is pending');
  return result('READY_FOR_APPROVAL');
}

function recommendation(verdict: Verdict, o: Partial<DirectionRecommendation> & { reasons: readonly string[] }): DirectionRecommendation {
  return { verdict, candidate_id: o.candidate_id ?? null, label: o.label ?? null, reasons: o.reasons, aggregate: o.aggregate ?? null, note: RECOMMENDATION_NOTE };
}

function failedComparison(outcomes: readonly CandidateOutcome[]): DirectionRecommendation {
  const kinds = new Set(outcomes.map((o) => o.verdict));
  const worst: Verdict = kinds.has('INCONCLUSIVE') ? 'INCONCLUSIVE' : (kinds.has('REVISE') ? 'REVISE' : 'BLOCKED');
  const reasons = [...new Set(outcomes.flatMap((o) => o.reasons))].sort(compareCodePoints).slice(0, 6);
  return recommendation(worst, { reasons: ['no candidate passed the non-compensatory gates and evidence floor', ...reasons] });
}

export function recommend(mode: ReviewMode, outcomes: readonly CandidateOutcome[], assessments: readonly CriterionAssessment[],
  active: readonly string[], labelOf: { readonly [cid: string]: string }): DirectionRecommendation {
  if (mode !== 'COMPARE') {
    const only = outcomes[0];
    if (outcomes.length === 1 && only) return recommendation(only.verdict, { candidate_id: only.candidate_id, label: only.label, reasons: only.reasons });
    const ready = outcomes.filter((o) => o.verdict === 'READY_FOR_APPROVAL').length;
    return recommendation('INCONCLUSIVE', { reasons: [`${ready} of ${outcomes.length} candidates satisfy the ${mode} checks; use COMPARE to choose a direction`] });
  }
  const eligible = outcomes.filter((o) => o.verdict === 'INCONCLUSIVE' && o.reasons.includes('eligible for comparison'));
  if (eligible.length === 0) return failedComparison(outcomes);
  return compareEligible(eligible, assessments, active, labelOf);
}

const VISION = 'VISION_CRITIQUE_ROUTE_DISABLED: gemini.image_critique has no adapter; no human assessment was supplied';

function compareEligible(eligible: readonly CandidateOutcome[], assessments: readonly CriterionAssessment[], active: readonly string[],
  labelOf: { readonly [cid: string]: string }): DirectionRecommendation {
  const creative: Array<[string, string]> = active.filter((l) => CREATIVE_LENSES.includes(l))
    .flatMap((lens) => (LENSES[lens]?.criteria ?? []).map((c): [string, string] => [lens, c]));
  const scored = new Map(assessments.filter((a) => a.score !== null).map((a) => [`${a.candidate_id}|${a.seat}|${a.criterion}`, a.score as number] as const));
  const common = creative.filter(([s, c]) => eligible.every((o) => scored.has(`${o.candidate_id}|${s}|${c}`)));
  const coverage = creative.length > 0 ? common.length / creative.length : 0.0;
  if (coverage < COMPARE_COVERAGE) {
    return recommendation('INCONCLUSIVE', { reasons: [`criterion coverage ${formatPercent0(coverage)} is below ${formatPercent0(COMPARE_COVERAGE)} for every eligible `
      + 'candidate: comparison evidence is insufficient', VISION],
      aggregate: { coverage: pyFloat(pyRound(coverage, 3)), criteria: creative.length, common: common.length } });
  }
  const means = eligible.map((o): [string, number] => [o.candidate_id,
    common.reduce((sum, [s, c]) => sum + (scored.get(`${o.candidate_id}|${s}|${c}`) as number), 0) / common.length]);
  const ranked = [...means].sort((a, b) => (b[1] - a[1]) || compareCodePoints(labelOf[a[0]] ?? '', labelOf[b[0]] ?? ''));
  const aggregate: Rec = { weights: 'equal across the common criteria', coverage: pyFloat(pyRound(coverage, 3)),
    criteria_used: common.map(([s, c]) => `${s}:${c}`), missing_criteria: creative.filter(([s, c]) => !common.some(([a, b]) => a === s && b === c)).map(([s, c]) => `${s}:${c}`),
    means: Object.fromEntries(ranked.map(([cid, v]) => [labelOf[cid] ?? '', pyFloat(pyRound(v, 2))])),
    note: 'rubric judgments, not probabilities; a mean is not proof of quality' };
  const [first, second] = ranked;
  if (first && second && first[1] - second[1] < COMPARE_MARGIN) {
    return recommendation('INCONCLUSIVE', { aggregate, reasons: [`leading margin ${formatFixed(first[1] - second[1], 2)} is below ${pyFloatStr(COMPARE_MARGIN)} rubric point`] });
  }
  const best = (first as [string, number])[0];
  return recommendation('RECOMMENDED_DIRECTION', { candidate_id: best, label: labelOf[best] ?? null, aggregate,
    reasons: [`passes every gate and leads on ${common.length} commonly assessed criteria`] });
}

export function brandMemory(cands: readonly GenerationCandidate[], measurements: { readonly [cid: string]: CandidateMeasurement },
  findings: readonly ReviewFinding[], labelOf: { readonly [cid: string]: string }): Rec {
  const entries = cands.map((c): Rec => {
    const px = measurements[c.candidate_id]?.pixels ?? null;
    const overlap = findings.filter((f) => f.candidate_id === c.candidate_id && f.criterion === 'category_overlap').map((f) => f.observation);
    const predicted = findings.filter((f) => f.candidate_id === c.candidate_id && f.criterion === 'distinguishing_cues' && f.assessor.kind === 'HUMAN')
      .map((f) => f.observation);
    return { candidate: labelOf[c.candidate_id] ?? '',
      observed_cues: px ? { dominant_colours: px.dominant.slice(0, 4).map((d) => d.hex), figure_share: px.figure_share, aspect: px.aspect } : 'NOT_RUN',
      category_overlap: overlap.length > 0 ? overlap : 'UNKNOWN: no reviewer assessed category overlap',
      predicted_memorability: predicted.length > 0 ? predicted : 'NOT_ASSESSED', predicted_label: 'PREDICTION by a reviewer, not measured recall' };
  });
  return { entries, measured_recall: 'HUMAN_RECALL_NOT_TESTED',
    recall_protocol: 'a recall test needs participants, an exposure/delay protocol and recorded results; none exist',
    trademark_clearance: 'NOT_ASSESSED: no clearance search was performed and none is claimed' };
}

const METRICS: ReadonlyArray<readonly [string, 'lower' | 'higher']> = [['off_palette_share', 'lower'], ['retention_32', 'higher'], ['dominant_pair_contrast', 'higher']];
const WORK_ORDER_METRIC: { readonly [criterion: string]: string } = { palette_roles: 'off_palette_share', small_size: 'retention_32' };

function pixelOf(m: CandidateMeasurement | undefined): { [key: string]: PyValue | undefined } {
  return (m?.pixels ?? {}) as { [key: string]: PyValue | undefined };
}

function numeric(v: PyValue | undefined): number | null {
  if (v === undefined || v === null) return null;
  return v instanceof CanonicalFloat ? v.value : (v as number);
}

function metricRegressions(c: GenerationCandidate, px: { [k: string]: PyValue | undefined }, bid: string, basePx: { [k: string]: PyValue | undefined }): Rec[] {
  const out: Rec[] = [];
  for (const [metric, better] of METRICS) {
    const a = numeric(basePx[metric]);
    const b = numeric(px[metric]);
    if (a === null || b === null) continue;
    const worse = better === 'lower' ? b > a + 0.02 : b < a - 0.02;
    if (worse) out.push({ kind: 'METRIC_REGRESSION', candidate_id: c.candidate_id, base_candidate_id: bid, metric, before: basePx[metric] ?? null, after: px[metric] ?? null });
  }
  return out;
}

function workOrderChecks(c: GenerationCandidate, px: { [k: string]: PyValue | undefined }, base: ReviewSession): Rec[] {
  const out: Rec[] = [];
  for (const wo of base.work_orders) {
    const metric = WORK_ORDER_METRIC[String(wo.dependencies['criterion'])];
    const value = metric === undefined ? null : numeric(px[metric]);
    if (metric === undefined || value === null) {
      out.push({ work_order_id: wo.work_order_id, candidate_id: c.candidate_id, status: 'NOT_VERIFIED',
        detail: 'no automatic check for this criterion; a reviewer must verify it' });
      continue;
    }
    const met = metric === 'off_palette_share' ? value <= 0.05 : value >= SMALL_SIZE_RETENTION;
    out.push({ work_order_id: wo.work_order_id, candidate_id: c.candidate_id, status: met ? 'MET' : 'NOT_MET', metric, value: px[metric] ?? null });
  }
  return out;
}

/** Compare each revised candidate with the base session's candidates on the measured metrics and gates. */
export function refine(base: ReviewSession, cands: readonly GenerationCandidate[], measurements: { readonly [cid: string]: CandidateMeasurement },
  gates: readonly GateResult[]): [Rec[], Rec[]] {
  const regressions: Rec[] = [];
  const checks: Rec[] = [];
  const baseGate = new Map(base.gates.map((g) => [`${g.candidate_id}|${g.gate}`, g.status] as const));
  const basePx = new Map(Object.entries(base.measurements).map(([cid, m]) => [cid, (m['pixels'] ?? {}) as { [k: string]: PyValue | undefined }] as const));
  for (const c of cands) {
    const px = pixelOf(measurements[c.candidate_id]);
    for (const bid of Object.keys(base.candidates)) {
      regressions.push(...metricRegressions(c, px, bid, basePx.get(bid) ?? {}));
      for (const g of GATES) {
        const nowFailed = gates.some((x) => x.candidate_id === c.candidate_id && x.gate === g && x.status === 'FAIL');
        if (baseGate.get(`${bid}|${g}`) === 'PASS' && nowFailed) {
          regressions.push({ kind: 'GATE_REGRESSION', candidate_id: c.candidate_id, base_candidate_id: bid, metric: g });
        }
      }
    }
    checks.push(...workOrderChecks(c, px, base));
  }
  return [regressions, checks];
}

