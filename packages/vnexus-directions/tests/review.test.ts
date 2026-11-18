import { describe, expect, it } from 'vitest';
import {
  COMPARE_COVERAGE, COMPARE_MARGIN, CORRELATION_NOTE, CREATIVE_LENSES, LENSES, MEASURE_VERSION, MODE_LENSES, OFF_PALETTE_DELTA_E, RECOMMENDATION_NOTE,
  SMALL_SIZE_RETENTION, VISION_GAP, WORK_ORDER_EXECUTION, activeLenses, isVague, parseFinding, review, sessionHash,
  type CandidateMeasurement, type CreativeIntent, type GenerationCandidate, type ReviewCandidate, type ReviewMode, type ReviewSession,
} from '../src/index';
import { dec, expectOutcome, fixture, list, rec, str } from './helpers';

const rv = rec(fixture['review']);
const intents = rec(rv['intents']);
const pools = rec(rv['pools']);

function candidatesOf(cands: unknown, measurements: unknown, storedOk?: readonly boolean[]): ReviewCandidate[] {
  const table = rec(measurements);
  return list(cands).map((c, i) => {
    const candidate = dec<GenerationCandidate>(c);
    return { candidate, measurement: dec<CandidateMeasurement>(table[candidate.candidate_id]), stored_ok: storedOk?.[i] ?? true };
  });
}

function run(intent: CreativeIntent, cs: ReviewCandidate[], mode: ReviewMode, human: readonly unknown[], extra: { reviewer?: string; base?: ReviewSession } = {}): ReviewSession {
  return review(intent, cs, mode, { human: human.map((h) => parseFinding(dec(h))), reviewer: extra.reviewer ?? 'reviewer-1', current_genome_ref: intent.genome_ref,
    tenant_id: 't1', created_at: '2026-02-02T00:00:00Z', base: extra.base ?? null });
}

describe('review board constants', () => {
  it('carries the same 14 lenses, modes and thresholds', () => {
    const l = rec(rv['lens']);
    expect(LENSES).toEqual(l['lenses']);
    expect(MODE_LENSES).toEqual(l['modes']);
    expect([...CREATIVE_LENSES]).toEqual(l['creative']);
    expect([COMPARE_COVERAGE, COMPARE_MARGIN, SMALL_SIZE_RETENTION, OFF_PALETTE_DELTA_E]).toEqual(l['numbers']);
    expect([VISION_GAP, MEASURE_VERSION]).toEqual([l['vision_gap'], l['measure_version']]);
    const records = rec(rec(fixture['records'])['constants']);
    expect([WORK_ORDER_EXECUTION, RECOMMENDATION_NOTE, CORRELATION_NOTE]).toEqual([records['work_order_execution'], records['recommendation_note'], records['correlation_note']]);
  });

  it('recognises vague aesthetic wishes with Python\'s case folds and Unicode word boundaries', () => {
    for (const [text, out] of list(rec(rv['lens'])['vague']).map((x) => x as [string, boolean])) expect(isVague(text), text).toBe(out);
  });
});

describe('review sessions', () => {
  it('reproduces every session (hash, verdicts, gates, recommendation, counts); full dumps match exactly', () => {
    for (const c of list(rv['cases']).map(rec)) {
      const role = str(c['role']);
      const pool = rec(pools[role]);
      const cs = candidatesOf(list(pool['candidates']).slice(0, c['n_candidates'] as number), pool['measurements']);
      const session = run(dec<CreativeIntent>(intents[role]), cs, c['mode'] as ReviewMode, list(c['human']));
      const label = `${role} ${c['mode']} ${c['n_candidates']} ${c['human_set']}`;
      const s = rec(c['summary']);
      expect(session.outcomes.map((o) => [o.label, o.verdict, o.reasons]), label).toEqual(s['verdicts']);
      expect(session.recommendation, label).toEqual(dec(s['recommendation']));
      expect(session.gates.map((g) => [g.candidate_id, g.gate, g.status]), label).toEqual(s['gates']);
      expect([session.findings.length, session.assessments.length, session.work_orders.length], label).toEqual(s['counts']);
      expect(session.lenses_required_missing, label).toEqual(s['missing']);
      if ('session' in c) expect(session, label).toEqual(dec(c['session']));
      expect(sessionHash(session), label).toBe(c['session_hash']);
    }
  }, 60000);

  it('keeps every review effect false and never recommends without evidence', () => {
    for (const c of list(rv['cases']).map(rec).slice(0, 40)) {
      expect(c['session_hash']).toMatch(/^[a-f0-9]{64}$/);
    }
    const role = 'LOGO_MARK';
    const pool = rec(pools[role]);
    const session = run(dec<CreativeIntent>(intents[role]), candidatesOf(list(pool['candidates']), pool['measurements']), 'COMPARE', []);
    expect(session.effects).toEqual({ regenerated: false, spent: false, approved: false, mutated_master: false, published: false });
    expect(session.recommendation.verdict).not.toBe('RECOMMENDED_DIRECTION');
    expect(session.assessments.every((a) => a.score === null)).toBe(true);
    expect(session.brand_memory['measured_recall']).toBe('HUMAN_RECALL_NOT_TESTED');
  });

  it('raises the same errors for malformed reviews', () => {
    for (const e of list(rv['errors']).map(rec)) {
      const intent = dec<CreativeIntent>(intents['LOGO_MARK']);
      const cs = candidatesOf(e['candidates'], e['measurements']);
      expectOutcome(() => sessionHash(run(intent, cs, e['mode'] as ReviewMode, list(e['human']), { reviewer: str(e['reviewer']) })), e['result'], str(e['name']),
        (a, x) => expect(a).toBe(x));
    }
  });

  it('flags regressions and unmet work orders when refining a base review', () => {
    const intent = dec<CreativeIntent>(intents['LOGO_MARK']);
    for (const r of list(rv['refine']).map(rec)) {
      const base = dec<ReviewSession>(r['base']);
      const cs = candidatesOf(r['candidates'], r['measurements']);
      const revised = run(intent, cs, 'REFINE', [], { base });
      const label = `${r['before']} -> ${r['after']}`;
      expect(sessionHash(revised), label).toBe(r['session_hash']);
      expect([...revised.regressions], label).toEqual(dec(r['regressions']));
      expect(revised.outcomes.map((o) => o.verdict), label).toEqual(r['verdicts']);
      expect(base.work_orders.length, label).toBe(r['work_orders']);
    }
  });
});

describe('lens activation', () => {
  it('activates and skips lenses per role and mode, including refine seats', () => {
    for (const row of list(rec(rv['lens'])['rows']).map(rec)) {
      const [active, skipped] = activeLenses(row['mode'] as ReviewMode, dec<CreativeIntent>(intents[str(row['role'])]), row['refine'] as string[]);
      expect([active, Object.fromEntries(skipped)]).toEqual([row['active'], row['skipped']]);
    }
    expect(Object.keys(intents).length).toBeGreaterThan(0);
  });
});
