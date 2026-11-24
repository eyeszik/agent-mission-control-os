/**
 * The review board's evidence side (`directions/review.py`): the 14 PROPOSED lenses and six modes, finding
 * creation, local-measurement findings and the five non-compensatory gates.
 *
 * Two kinds of assessor contribute: LOCAL_MEASUREMENT (deterministic facts, findings and gate evidence, never
 * creative scores) and HUMAN (a named reviewer's findings and 0-10 scores). No vision route is enabled, so a lens
 * that needs perception and has no human input is NOT_REVIEWED, and required ones block readiness.
 */
import { CanonicalFloat } from '@amc/canonical';
import { PY_WORD, formatG, formatPercent0, pyFloatStr, pySplitWs, pyStr, type PyValue } from '@amc/vnexus-brandbook';
import { MEASURE_VERSION, OFF_PALETTE_DELTA_E, n, type CandidateMeasurement, type DominantColour, type Pixels } from './measure';
import {
  NONE, RASTER_NATIVE, VECTOR_REQUIRED, recordId,
  type Assessor, type CreativeIntent, type EvidenceClass, type EvidenceSource, type Gate, type GateResult, type GateStatus,
  type GenerationCandidate, type ReviewFinding, type ReviewMode, type Severity,
} from './records';

export interface Lens {
  readonly name: string;
  readonly criteria: readonly string[];
  readonly local: boolean;
}

export const LENSES: { readonly [seat: string]: Lens } = {
  '01': { name: 'Brand strategist', criteria: ['positioning_fit', 'audience_relevance', 'category_relevance'], local: false },
  '02': { name: 'Creative director', criteria: ['concept_coherence', 'differentiation'], local: false },
  '03': { name: 'Identity designer', criteria: ['silhouette', 'symbolism', 'system_potential'], local: false },
  '04': { name: 'Typography specialist', criteria: ['spelling', 'hierarchy', 'spacing_lettering'], local: false },
  '05': { name: 'Composition specialist', criteria: ['balance', 'alignment', 'proportion'], local: false },
  '06': { name: 'Color specialist', criteria: ['palette_roles', 'reproduction', 'applicable_contrast'], local: true },
  '07': { name: 'Accessibility reviewer', criteria: ['readability', 'contrast', 'non_color_cues'], local: true },
  '08': { name: 'Imagery/art-direction reviewer', criteria: ['framing', 'lighting', 'style_fit'], local: false },
  '09': { name: 'Emotional-response reviewer', criteria: ['intended_vs_apparent'], local: false },
  '10': { name: 'Brand-memory reviewer', criteria: ['distinguishing_cues', 'category_overlap'], local: false },
  '11': { name: 'Production/vector specialist', criteria: ['paths_topology', 'small_size', 'exports'], local: true },
  '12': { name: 'Application/UX reviewer', criteria: ['channel_fit', 'crop', 'layout_fit'], local: false },
  '13': { name: 'Brand-safety/rights reviewer', criteria: ['prohibited_content', 'privacy', 'provenance'], local: true },
  '14': { name: 'Evidence/QA reviewer', criteria: ['substantiation', 'uncertainty', 'coverage'], local: true },
};

/** Insertion order of `LENSES`: a JS object would list the integer-like keys '10'..'14' first. */
export const LENS_ORDER: readonly string[] = ['01', '02', '03', '04', '05', '06', '07', '08', '09', '10', '11', '12', '13', '14'];

export const MODE_LENSES: { readonly [mode in ReviewMode]: readonly string[] } = {
  QUICK: ['04', '06', '07', '13', '14'], FULL: LENS_ORDER, COMPARE: ['01', '02', '03', '04', '05', '06', '10', '13', '14'],
  REFINE: ['14'], VECTOR: ['03', '04', '06', '07', '11', '13', '14'], RELEASE: ['04', '06', '07', '11', '12', '13', '14'],
};
export const CREATIVE_LENSES: readonly string[] = ['01', '02', '03', '04', '05', '08', '09', '10', '12'];
export const COMPARE_COVERAGE = 0.5;
export const COMPARE_MARGIN = 1.0;
export const SMALL_SIZE_RETENTION = 0.35;
export const VISION_GAP = 'VISION_CRITIQUE_ROUTE_DISABLED: gemini.image_critique has no adapter; no human assessment was supplied';
export const GATE_CRITERIA: ReadonlySet<string> = new Set(['exact_identity_text', 'accessibility', 'safety_privacy_rights', 'canonical_integrity',
  'output_provenance']);

/** Python's `re.I` also folds `İ`/`ı` onto `i`; `\b` is Unicode-aware. */
const vagueBody = '(make (it )?(look )?(more )?(premium|better|nicer|modern|pop|cleaner|sleeker)|improve (the )?aesthetics?|more premium|'
  + 'look better|make it pop|enhance (the )?design)';
const VAGUE = new RegExp(`(?<![${PY_WORD}])${vagueBody.replace(/i/g, '[iİı]')}(?![${PY_WORD}])`, 'iu');

/** Whether a proposed change is a vague aesthetic wish (such a short change is not actionable). */
export function isVague(text: string): boolean {
  return VAGUE.test(text);
}

const LOCAL_ASSESSOR: Assessor = { kind: 'LOCAL_MEASUREMENT', id: 'local.measure', version: MEASURE_VERSION };

export class ReviewValueError extends Error {
  override name = 'ValueError';
}

export function applicable(lens: string, intent: CreativeIntent, exact: readonly string[]): string | null {
  const role = intent.asset_role;
  if (lens === '04' && exact.length === 0 && role !== 'WORDMARK' && role !== 'LOCKUP') return 'no identity text in this brief';
  if (lens === '08' && VECTOR_REQUIRED.has(role)) return 'imagery/art direction applies to illustration, photography, texture and hero images';
  if (lens === '11' && RASTER_NATIVE.has(role)) return 'raster-native role: no vector production';
  return null;
}

export function activeLenses(mode: ReviewMode, intent: CreativeIntent, refineSeats: readonly string[] = []): [string[], Map<string, string>] {
  const exact = intent.vector_instructions.exact_text;
  const wanted = [...new Set([...MODE_LENSES[mode], ...refineSeats])].sort();
  const active: string[] = [];
  const skipped = new Map<string, string>();
  for (const lens of wanted) {
    const why = applicable(lens, intent, exact);
    if (why) skipped.set(lens, why);
    else active.push(lens);
  }
  return [active, skipped];
}

export interface AddOptions {
  readonly criterion: string;
  readonly seat: string;
  readonly observation: string;
  readonly evidence: EvidenceClass;
  readonly source: EvidenceSource;
  readonly severity: Severity;
  readonly rationale?: string;
  readonly change?: string | null;
  readonly check?: string | null;
  readonly uncertainty?: string;
  readonly region?: string;
  readonly assessor?: Assessor;
  readonly measurement?: { readonly [key: string]: PyValue } | null;
}

export class Board {
  readonly findings: ReviewFinding[] = [];

  constructor(readonly intent: CreativeIntent, readonly mode: ReviewMode, readonly reviewer: string) {}

  add(cand: GenerationCandidate, o: AddOptions): ReviewFinding {
    const change = o.change ?? null;
    const check = o.check ?? null;
    const actionable = Boolean(change && check && !(VAGUE.test(change) && pySplitWs(change).length < 12));
    const by = o.assessor ?? LOCAL_ASSESSOR;
    const id = recordId('vdf', { c: cand.candidate_id, criterion: o.criterion, seat: o.seat, obs: o.observation, n: this.findings.length, by: by.id });
    const finding: ReviewFinding = { finding_id: id, candidate_id: cand.candidate_id, criterion: o.criterion, seat: o.seat,
      asset_hash: cand.observed.sha256, region_or_element: o.region ?? 'whole asset', evidence_class: o.evidence, evidence_source: o.source,
      observation: o.observation, severity: o.severity, rationale: o.rationale ?? '', proposed_change: change, acceptance_check: check,
      uncertainty: o.uncertainty ?? '', actionable, assessor: by, measurement: o.measurement ?? null };
    this.findings.push(finding);
    return finding;
  }
}

function pct(v: number | CanonicalFloat): string {
  return formatPercent0(n(v));
}

function orNone(a: string | undefined, b: string | undefined): string {
  return a ? a : pyStr(b ?? null);
}

/** The largest dominant colour farther than the palette threshold from every approved role (first of equals). */
function worstColour(px: Pixels): DominantColour | null {
  let worst: DominantColour | null = null;
  for (const d of px.dominant) {
    const de = d.delta_e76 === null ? 0 : n(d.delta_e76);
    if ((de || 99) > OFF_PALETTE_DELTA_E && (worst === null || n(d.share) > n(worst.share))) worst = d;
  }
  return worst;
}

function paletteFinding(board: Board, cand: GenerationCandidate, px: Pixels, final: boolean): void {
  const worst = worstColour(px);
  const target = worst && worst.nearest_role ? ` with the nearest approved role colour (${worst.nearest_role})` : '';
  board.add(cand, { criterion: 'palette_roles', seat: '06', evidence: 'OBSERVED', source: 'PIXELS', severity: final ? 'MAJOR' : 'MINOR',
    observation: `${pct(px.off_palette_share)} of pixels are in dominant colours more than ${formatG(OFF_PALETTE_DELTA_E)} dE76 from every approved palette role`
      + (worst ? ` (largest: ${worst.hex}, ${pct(worst.share)})` : ''),
    rationale: 'masters use approved palette roles only; a concept may explore but the master may not',
    change: worst ? `Replace ${worst.hex}${target}; preserve the silhouette and composition.` : null,
    check: 'Re-render the stored bytes: off-palette share at most 5% of pixels.',
    measurement: { off_palette_share: px.off_palette_share, dominant: px.dominant as unknown as PyValue } });
}

function smallSizeFinding(board: Board, cand: GenerationCandidate, r32: number | CanonicalFloat): void {
  board.add(cand, { criterion: 'small_size', seat: '11', evidence: 'INFERRED', source: 'PIXELS', severity: 'MAJOR',
    observation: `at 32 px the luminance spread falls to ${pct(r32)} of the full-size asset`,
    rationale: 'detail that disappears at 32 px is lost at favicon and app-icon sizes (a proxy, not legibility testing)',
    change: 'Open the smallest counters and thicken the thinnest strokes until they survive a 32 px raster; preserve the outer silhouette.',
    check: 'Render at 32 px and full size; 32 px luminance retention at least 35% and counters visibly open.',
    uncertainty: 'luminance spread is a proxy; a human must confirm legibility', measurement: { retention_32: r32 } });
}

function pixelFindings(board: Board, cand: GenerationCandidate, m: CandidateMeasurement, active: readonly string[]): void {
  const px = m.pixels;
  if (px === null) {
    board.add(cand, { criterion: 'coverage', seat: '14', observation: `pixel checks not run: ${m.pixel_source}`, evidence: 'UNKNOWN', source: 'NONE',
      severity: 'MAJOR', uncertainty: 'no rendered-image inspection; visual lenses cannot use measured facts' });
    return;
  }
  const final = board.mode === 'VECTOR' || board.mode === 'RELEASE';
  if (!px.nonblank) {
    board.add(cand, { criterion: 'exports', seat: '11', observation: 'the rendered asset is a single flat colour', evidence: 'OBSERVED',
      source: 'PIXELS', severity: 'BLOCKER', measurement: px as unknown as { [key: string]: PyValue } });
  }
  if (active.includes('06') && n(px.off_palette_share) > 0.05) paletteFinding(board, cand, px, final);
  if (active.includes('11') || active.includes('07')) {
    const r32 = px.retention_32;
    if (r32 !== null && n(r32) < SMALL_SIZE_RETENTION) smallSizeFinding(board, cand, r32);
  }
}

function geometryFindings(board: Board, cand: GenerationCandidate, m: CandidateMeasurement): void {
  const geo = m.geometry;
  if (geo === undefined) return;
  const final = board.mode === 'VECTOR' || board.mode === 'RELEASE';
  if (!geo.parseable || !(geo.safe ?? false)) {
    board.add(cand, { criterion: 'prohibited_content', seat: '13', evidence: 'OBSERVED', source: 'GEOMETRY', severity: 'BLOCKER',
      observation: `SVG refused by the safety verifier: ${orNone(geo.safety_detail, geo.error)}` });
  }
  if (geo.classification === 'RASTER_IN_SVG') {
    board.add(cand, { criterion: 'paths_topology', seat: '11', observation: 'the SVG embeds a raster image; it is raster, not vector',
      evidence: 'OBSERVED', source: 'GEOMETRY', severity: final ? 'MAJOR' : 'NOTE',
      change: 'Rebuild the artwork as native shapes or paths; remove the embedded image.', check: 'geometry: classification VECTOR and no <image> element' });
  }
  if (geo.pii_like_text && geo.pii_like_text.length > 0) {
    board.add(cand, { criterion: 'privacy', seat: '13', observation: 'text that looks like personal contact data: ' + geo.pii_like_text.join('; '),
      evidence: 'OBSERVED', source: 'GEOMETRY', severity: 'BLOCKER', change: 'Remove the personal data from the artwork.', check: 'geometry: no PII-like text' });
  }
}

/** Local measurements become findings (never scores). */
export function localFindings(board: Board, cand: GenerationCandidate, m: CandidateMeasurement, active: readonly string[]): void {
  pixelFindings(board, cand, m, active);
  geometryFindings(board, cand, m);
}

export type Attest = ReadonlyMap<Gate, readonly [string, string]>;

class GateList {
  readonly out: GateResult[] = [];

  constructor(readonly candidateId: string, readonly attest: Attest) {}

  gate(g: Gate, status: GateStatus, evidence: string, cls: EvidenceClass): void {
    // A human OBSERVED attestation may settle an UNKNOWN; it never overrides an observed FAIL or PASS.
    const settled = status === 'UNKNOWN' ? this.attest.get(g) : undefined;
    if (settled !== undefined) {
      this.out.push({ candidate_id: this.candidateId, gate: g, status: settled[0] as GateStatus,
        evidence: `human inspection (${settled[1]}); was UNKNOWN: ${evidence}`, evidence_class: 'OBSERVED', finding_ids: [settled[1]] });
      return;
    }
    this.out.push({ candidate_id: this.candidateId, gate: g, status, evidence, evidence_class: cls, finding_ids: [] });
  }
}

function provenanceGate(l: GateList, cand: GenerationCandidate, m: CandidateMeasurement, storedOk: boolean): void {
  if (cand.provenance === 'SIMULATED') l.gate('OUTPUT_PROVENANCE', 'FAIL', 'SIMULATED output is a test stand-in, not an asset', 'OBSERVED');
  else if (!storedOk) l.gate('OUTPUT_PROVENANCE', 'FAIL', 'stored bytes do not re-hash to the recorded sha256', 'OBSERVED');
  else if (m.pixels === null && m.geometry === undefined) l.gate('OUTPUT_PROVENANCE', 'UNKNOWN', m.pixel_source, 'UNKNOWN');
  else {
    const label = cand.provenance === 'RECORDED' ? 'recorded adapter output' : 'USER_REPORTED import: bytes bound by hash; provider/model/seed unverified';
    l.gate('OUTPUT_PROVENANCE', 'PASS', `stored bytes re-hash to ${cand.observed.sha256.slice(0, 16)}; ${label}`, 'OBSERVED');
  }
}

function textGate(l: GateList, intent: CreativeIntent, m: CandidateMeasurement, final: boolean): void {
  const exact = intent.vector_instructions.exact_text;
  const texts = m.geometry?.text_elements ?? [];
  if (intent.brief.exact_text === NONE) l.gate('EXACT_IDENTITY_TEXT', 'NOT_APPLICABLE', 'identity text decided NONE', 'OBSERVED');
  else if (exact.length === 0) l.gate('EXACT_IDENTITY_TEXT', 'UNKNOWN', 'exact identity text was not supplied in the brief', 'UNKNOWN');
  else if (texts.length > 0) {
    const missing = exact.filter((t) => !texts.includes(t));
    l.gate('EXACT_IDENTITY_TEXT', missing.length > 0 ? 'FAIL' : 'PASS',
      missing.length > 0 ? `missing verbatim: ${pyStr(missing)}` : 'every required string is present verbatim as editable text', 'OBSERVED');
  } else if (!final) {
    l.gate('EXACT_IDENTITY_TEXT', 'NOT_APPLICABLE',
      'concept stage: identity text is set from the approved face in vector production, never taken from generated pixels', 'OBSERVED');
  } else if (m.geometry !== undefined) {
    l.gate('EXACT_IDENTITY_TEXT', 'FAIL', 'required identity text is absent as editable text in the master', 'OBSERVED');
  } else l.gate('EXACT_IDENTITY_TEXT', 'UNKNOWN', 'raster master: text cannot be read without OCR; no OCR route', 'UNKNOWN');
}

function accessibilityGate(l: GateList, intent: CreativeIntent, m: CandidateMeasurement): void {
  const role = intent.asset_role;
  const exact = intent.vector_instructions.exact_text;
  if (role === 'ICON') {
    const pair = m.pixels?.dominant_pair_contrast ?? null;
    if (pair === null) l.gate('ACCESSIBILITY', 'UNKNOWN', 'no measured pixels for the WCAG 1.4.11 non-text contrast check', 'UNKNOWN');
    else {
      l.gate('ACCESSIBILITY', n(pair) >= 3.0 ? 'PASS' : 'FAIL',
        `dominant figure/ground contrast ${pyFloatStr(n(pair))}:1 against the WCAG 2.2 1.4.11 3:1 floor`, 'OBSERVED');
    }
  } else if (role === 'HERO_IMAGE' && exact.length > 0) {
    l.gate('ACCESSIBILITY', 'UNKNOWN', 'text is overlaid downstream; contrast is checked on the composed layout', 'UNKNOWN');
  } else {
    const logo = role === 'LOGO_MARK' || role === 'WORDMARK' || role === 'LOCKUP';
    l.gate('ACCESSIBILITY', 'NOT_APPLICABLE', logo
      ? 'logotypes are exempt from WCAG 1.4.3 and this role carries no required information-bearing graphics'
      : 'no information-bearing text or graphics declared', 'INFERRED');
  }
}

function safetyGate(l: GateList, intent: CreativeIntent, cand: GenerationCandidate, m: CandidateMeasurement): void {
  const geo = m.geometry;
  const problems: string[] = [];
  if (geo !== undefined && (!geo.parseable || !geo.safe)) problems.push('unsafe SVG');
  if (geo?.pii_like_text && geo.pii_like_text.length > 0) problems.push('PII-like text in the artwork');
  if (intent.prohibited.length > 0) problems.push('prohibited brief content');
  if (problems.length > 0) l.gate('SAFETY_PRIVACY_RIGHTS', 'FAIL', problems.join('; '), 'OBSERVED');
  else if (cand.provenance === 'RECORDED' && cand.route_id === 'local.foundry_compose') {
    l.gate('SAFETY_PRIVACY_RIGHTS', 'PASS', 'composed locally from the approved genome; no external source material', 'OBSERVED');
  } else if (!cand.reported.rights_basis) l.gate('SAFETY_PRIVACY_RIGHTS', 'UNKNOWN', 'no rights basis recorded for this import', 'UNKNOWN');
  else {
    l.gate('SAFETY_PRIVACY_RIGHTS', 'UNKNOWN',
      "rights basis is the importer's statement; third-party marks and likeness need a human inspection (seat 13)", 'UNKNOWN');
  }
}

function integrityGate(l: GateList, intent: CreativeIntent, cand: GenerationCandidate, m: CandidateMeasurement, o: {
  readonly final: boolean; readonly currentGenomeRef: string }): void {
  const px = m.pixels;
  if (cand.genome_ref !== o.currentGenomeRef || intent.genome_ref !== o.currentGenomeRef) {
    l.gate('CANONICAL_INTEGRITY', 'FAIL', `STALE: compiled against genome ${intent.genome_ref}, current is ${o.currentGenomeRef}`, 'OBSERVED');
  } else if (o.final && px !== null && n(px.off_palette_share) > 0.05) {
    l.gate('CANONICAL_INTEGRITY', 'FAIL', `master uses ${pct(px.off_palette_share)} off-palette colour`, 'OBSERVED');
  } else if (o.final && px === null) {
    l.gate('CANONICAL_INTEGRITY', 'UNKNOWN', 'palette conformance not measured: ' + m.pixel_source, 'UNKNOWN');
  } else l.gate('CANONICAL_INTEGRITY', 'PASS', 'bound to the current approved genome' + (o.final ? ' and palette' : ''), 'OBSERVED');
}

/** The five non-compensatory gates for one candidate. */
export function gatesFor(intent: CreativeIntent, cand: GenerationCandidate, m: CandidateMeasurement, mode: ReviewMode, o: {
  readonly currentGenomeRef: string; readonly storedOk: boolean; readonly attest: Attest }): GateResult[] {
  const l = new GateList(cand.candidate_id, o.attest);
  const final = mode === 'VECTOR' || mode === 'RELEASE';
  provenanceGate(l, cand, m, o.storedOk);
  textGate(l, intent, m, final);
  accessibilityGate(l, intent, m);
  safetyGate(l, intent, cand, m);
  integrityGate(l, intent, cand, m, { final, currentGenomeRef: o.currentGenomeRef });
  return l.out;
}
