/**
 * `review()` (`directions/review.py`): one coordinated schema for the 14-lens board, six modes, gates, verdicts,
 * work orders and the recommendation. It only computes a record: `effects` are fixed false, so it cannot regenerate,
 * spend, approve, mutate a master or publish.
 *
 * Python measures stored bytes inside `review()` (PNG decode, Chromium raster, SVG parse). The twin takes each
 * candidate's measurement as input, so everything downstream of the measurement is pure.
 */
import { canonicalHash, pyRepr, pyRoundInt, type PyValue } from '@amc/vnexus-brandbook';
import {
  Board, GATE_CRITERIA, LENSES, ReviewValueError, VISION_GAP, activeLenses, gatesFor, localFindings, type Attest,
} from './board';
import { ROUTES, health } from './providers';
import type { CandidateMeasurement } from './measure';
import {
  CORRELATION_NOTE, RUBRIC_VERSION, SCHEMA, recordId,
  type Assessor, type CreativeIntent, type CriterionAssessment, type FindingIn, type Gate, type GateResult, type GenerationCandidate,
  type ReviewFinding, type ReviewMode, type ReviewSession,
} from './records';
import { checkAssessorId } from './validate';
import { brandMemory, labels, recommend, refine, verdictFor, workOrders } from './verdict';

type Rec = { [key: string]: PyValue };

export interface ReviewCandidate {
  readonly candidate: GenerationCandidate;
  readonly measurement: CandidateMeasurement;
  /** Whether the stored bytes re-hash to the recorded sha256. */
  readonly stored_ok: boolean;
}

export interface ReviewOptions {
  readonly human: readonly FindingIn[];
  readonly reviewer: string;
  readonly current_genome_ref: string;
  readonly tenant_id: string;
  readonly created_at: string;
  readonly base?: ReviewSession | null;
}

function humanFinding(board: Board, byRef: ReadonlyMap<string, GenerationCandidate>, f: FindingIn): [GenerationCandidate, ReviewFinding] {
  const cand = byRef.get(f.candidate);
  if (cand === undefined) throw new ReviewValueError(`finding refers to unknown candidate ${pyReprText(f.candidate)}`);
  if (!(LENSES[f.seat]?.criteria.includes(f.criterion) ?? false) && !GATE_CRITERIA.has(f.criterion)) {
    throw new ReviewValueError(`criterion ${pyReprText(f.criterion)} is not in seat ${f.seat}'s rubric`);
  }
  if (f.gate_status && f.evidence_class !== 'OBSERVED') throw new ReviewValueError('a gate attestation must be an OBSERVED inspection');
  checkAssessorId(board.reviewer);
  const who: Assessor = { kind: 'HUMAN', id: board.reviewer, version: null };
  return [cand, board.add(cand, { criterion: f.criterion, seat: f.seat, observation: f.observation, evidence: f.evidence_class, source: f.evidence_source,
    severity: f.severity, rationale: f.rationale, change: f.proposed_change, check: f.acceptance_check, uncertainty: f.uncertainty,
    region: f.region_or_element, assessor: who })];
}

const pyReprText = pyRepr;

interface HumanPass {
  readonly attest: Map<string, Map<Gate, [string, string]>>;
  readonly seen: Map<string, Set<string>>;
  readonly scores: Map<string, Array<[number, string, string]>>;
  readonly emotional: Rec[];
}

function humanPass(board: Board, cands: readonly GenerationCandidate[], byRef: ReadonlyMap<string, GenerationCandidate>,
  labelOf: { readonly [cid: string]: string }, human: readonly FindingIn[], reviewer: string): HumanPass {
  const pass: HumanPass = { attest: new Map(cands.map((c) => [c.candidate_id, new Map()])), seen: new Map(cands.map((c) => [c.candidate_id, new Set()])),
    scores: new Map(), emotional: [] };
  for (const f of human) {
    const [cand, rf] = humanFinding(board, byRef, f);
    pass.seen.get(cand.candidate_id)?.add(f.seat);
    if (f.gate && f.gate_status) pass.attest.get(cand.candidate_id)?.set(f.gate, [f.gate_status, rf.finding_id]);
    if (f.score !== null) {
      const key = `${cand.candidate_id}|${f.seat}|${f.criterion}`;
      pass.scores.set(key, [...(pass.scores.get(key) ?? []), [f.score, rf.finding_id, reviewer]]);
    }
    if (f.trait || f.cue) {
      pass.emotional.push({ candidate: labelOf[cand.candidate_id] ?? '', target_trait: f.trait, visible_cue: f.cue, reviewer_interpretation: f.observation,
        possible_mismatch: f.severity === 'MAJOR' || f.severity === 'BLOCKER', finding_id: rf.finding_id });
    }
  }
  return pass;
}

function assessmentsFor(cands: readonly GenerationCandidate[], active: readonly string[], skipped: ReadonlyMap<string, string>,
  measurements: { readonly [cid: string]: CandidateMeasurement }, pass: HumanPass): [CriterionAssessment[], Set<string>] {
  const out: CriterionAssessment[] = [];
  const missing = new Set<string>();
  for (const cand of cands) {
    const m = measurements[cand.candidate_id];
    const pxOk = (m?.pixels ?? null) !== null || m?.geometry !== undefined;
    for (const lens of active) {
      const localOk = (LENSES[lens]?.local ?? false) && pxOk;
      if (!(localOk || (pass.seen.get(cand.candidate_id)?.has(lens) ?? false))) missing.add(lens);
      for (const crit of LENSES[lens]?.criteria ?? []) out.push(assessment(cand, lens, crit, localOk, pass));
    }
  }
  for (const [lens, why] of skipped) {
    for (const cand of cands) {
      for (const crit of LENSES[lens]?.criteria ?? []) {
        out.push({ candidate_id: cand.candidate_id, criterion: crit, seat: lens, score: null, status: 'NOT_APPLICABLE', reason: why, finding_ids: [], assessors: [] });
      }
    }
  }
  return [out, missing];
}

/** Scores come only from named human reviewers; a measurement never becomes a creative score. */
function assessment(cand: GenerationCandidate, lens: string, crit: string, localOk: boolean, pass: HumanPass): CriterionAssessment {
  const got = pass.scores.get(`${cand.candidate_id}|${lens}|${crit}`);
  if (got && got.length > 0) {
    return { candidate_id: cand.candidate_id, criterion: crit, seat: lens, score: pyRoundInt(got.reduce((s, [v]) => s + v, 0) / got.length), status: 'ASSESSED',
      reason: '', finding_ids: got.map(([, fid]) => fid), assessors: got.map(([, , who]): Assessor => ({ kind: 'HUMAN', id: who, version: null })) };
  }
  return { candidate_id: cand.candidate_id, criterion: crit, seat: lens, score: null, status: 'NOT_REVIEWED',
    reason: localOk ? 'measured facts only; scores are rubric judgments by a reviewer' : VISION_GAP, finding_ids: [], assessors: [] };
}

function preconditions(candidates: readonly ReviewCandidate[], mode: ReviewMode, base: ReviewSession | null | undefined): void {
  if (candidates.length === 0) throw new ReviewValueError('a review needs at least one candidate');
  if (mode === 'COMPARE' && candidates.length < 2) throw new ReviewValueError('COMPARE needs at least two candidates');
  if (mode === 'REFINE' && !base) throw new ReviewValueError('REFINE needs the base review session');
}

function publicMeasure(m: CandidateMeasurement): Rec {
  const out: Rec = {};
  for (const k of ['sha256', 'mime', 'pixel_source', 'pixels', 'geometry'] as const) if (k in m) out[k] = m[k] as unknown as PyValue;
  return out;
}

function emotionalMap(intent: CreativeIntent, entries: readonly Rec[]): Rec {
  return { targets: (intent.shared['emotional_targets'] as PyValue) || [], targets_source: (intent.shared['emotional_targets_source'] as PyValue) ?? null,
    entries: entries as unknown as PyValue, status: entries.length > 0 ? 'ASSESSED' : 'NOT_ASSESSED',
    note: 'reviewer interpretation of visible cues; not a measurement of audience emotion' };
}

/** Compute one immutable ReviewSession. `human` findings are validated `FindingIn` records. */
export function review(intent: CreativeIntent, candidates: readonly ReviewCandidate[], mode: ReviewMode, options: ReviewOptions): ReviewSession {
  preconditions(candidates, mode, options.base);
  const base = options.base ?? null;
  const cands = candidates.map((c) => c.candidate);
  const blinded = mode === 'COMPARE';
  const labelMap = labels(cands, blinded);
  const labelOf = Object.fromEntries(Object.entries(labelMap).map(([lab, cid]) => [cid, lab]));
  const byRef = new Map<string, GenerationCandidate>([...cands.map((c) => [c.candidate_id, c] as const),
    ...Object.entries(labelMap).map(([lab, cid]) => [lab, cands.find((c) => c.candidate_id === cid) as GenerationCandidate] as const)]);
  const refineSeats = base ? [...new Set(base.work_orders.map((wo) => String(wo.dependencies['seat'])))].sort() : [];
  const [active, skipped] = activeLenses(mode, intent, refineSeats);
  const board = new Board(intent, mode, options.reviewer);
  const measurements = Object.fromEntries(candidates.map((c) => [c.candidate.candidate_id, c.measurement]));
  for (const c of candidates) localFindings(board, c.candidate, c.measurement, active);
  const pass = humanPass(board, cands, byRef, labelOf, options.human, options.reviewer);
  const gates = candidates.flatMap((c) => gatesFor(intent, c.candidate, c.measurement, mode, { currentGenomeRef: options.current_genome_ref,
    storedOk: c.stored_ok, attest: (pass.attest.get(c.candidate.candidate_id) ?? new Map()) as Attest }));
  return assemble(intent, mode, options, { cands, blinded, labelMap, labelOf, active, skipped, board, measurements, pass, gates, base });
}

interface Parts {
  readonly cands: readonly GenerationCandidate[];
  readonly blinded: boolean;
  readonly labelMap: { readonly [label: string]: string };
  readonly labelOf: { readonly [cid: string]: string };
  readonly active: readonly string[];
  readonly skipped: ReadonlyMap<string, string>;
  readonly board: Board;
  readonly measurements: { readonly [cid: string]: CandidateMeasurement };
  readonly pass: HumanPass;
  readonly gates: readonly GateResult[];
  readonly base: ReviewSession | null;
}

function assemble(intent: CreativeIntent, mode: ReviewMode, o: ReviewOptions, p: Parts): ReviewSession {
  const [assessments, missing] = assessmentsFor(p.cands, p.active, p.skipped, p.measurements, p.pass);
  const [regressions, checks] = p.base ? refine(p.base, p.cands, p.measurements, p.gates) : [[], []];
  for (const chk of checks) if (chk['status'] === 'NOT_MET') regressions.push({ kind: 'WORK_ORDER_NOT_MET', ...chk });
  const outcomes = p.cands.map((c) => verdictFor(mode, c, p.gates, p.board.findings, missing, p.labelOf[c.candidate_id] ?? '', regressions));
  const sessionBody = { intent: intent.intent_id, mode, cands: p.cands.map((c) => c.observed.sha256).sort(), human: o.human, reviewer: o.reviewer,
    at: o.created_at, base: p.base ? p.base.session_id : null };
  return {
    schema_version: SCHEMA, rubric_version: RUBRIC_VERSION, session_id: recordId('vdr', sessionBody), intent_id: intent.intent_id, tenant_id: o.tenant_id,
    project_id: intent.project_id, brand_id: intent.brand_id, genome_ref: o.current_genome_ref, mode, blinded: p.blinded, labels: p.labelMap,
    candidates: Object.fromEntries(p.cands.map((c) => [c.candidate_id, c.observed.sha256])), lenses_active: p.active,
    lenses_required_missing: [...missing].sort(), routes: routeHealth(), findings: p.board.findings, assessments, gates: p.gates, outcomes,
    recommendation: recommend(mode, outcomes, assessments, p.active, p.labelOf), work_orders: workOrders(intent, p.board.findings),
    emotional_map: emotionalMap(intent, p.pass.emotional), brand_memory: brandMemory(p.cands, p.measurements, p.board.findings, p.labelOf),
    regressions: [...regressions, ...checks.filter((c) => c['status'] !== 'NOT_MET').map((c) => ({ kind: 'WORK_ORDER_CHECK', ...c }))],
    base_session_id: p.base ? p.base.session_id : null, correlation_note: CORRELATION_NOTE,
    effects: { regenerated: false, spent: false, approved: false, mutated_master: false, published: false }, created_by: o.reviewer, created_at: o.created_at,
    measurements: Object.fromEntries(Object.entries(p.measurements).map(([k, v]) => [k, publicMeasure(v)])),
  };
}

function routeHealth(): { [routeId: string]: string } {
  return Object.fromEntries(ROUTES.filter((r) => r.route_id === 'gemini.image_critique' || r.route_id === 'local.measure')
    .map((r) => [r.route_id, health(r)[0]]));
}

export function sessionHash(session: ReviewSession): string {
  return canonicalHash(session);
}

