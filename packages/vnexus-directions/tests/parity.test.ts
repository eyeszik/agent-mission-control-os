import { CreativeIntentSchema } from '@amc/shared';
import { describe, expect, it } from 'vitest';
import {
  ASSET_ROLES, COMPOSE_ROLES, FIDELITY_MAX_DELTA_E, GATES, GENERIC_AXES, INTENT_COMPILER_VERSION, LOGO_ROLES, NEAR_DUPLICATE_BITS, NONE, PALETTE_ROLES,
  RASTER_NATIVE, REVIEW_MODES, ROUTES, RUBRIC_VERSION, SCHEMA, SEVERITIES, TEXT_ROLES, TRACE_BUDGETS, VECTOR_REQUIRED, VERDICTS, ValidationError,
  candidateName, compileIntent, decide, decideReconstruction, decideRoute, describeRoutes, directions, flattenGradients, getRoute, hamming, handoffPackage, hexRgb, marksFor,
  masterKeys, nearDuplicate, parseBrief, parseFinding, recordId, reconstructionName, storageKey, tone, validateGeometry, vectorNeed, withText,
  type AssetRole, type CompiledPrompt, type CreativeIntent, type DirectionBrief, type Geometry, type RouteEnv, type Task,
} from '../src/index';
import { dec, expectOutcome, fixture, list, rec, str } from './helpers';

function expectValidation(run: () => unknown, outcome: unknown, label: string): void {
  const o = rec(outcome);
  if ('ok' in o) {
    expect(run(), label).toEqual(dec(o['ok']));
    return;
  }
  let thrown: unknown;
  try {
    run();
  } catch (e) {
    thrown = e;
  }
  expect(thrown, label).toBeInstanceOf(ValidationError);
  expect((thrown as ValidationError).issues.map((i) => [i.loc, i.type]), label).toEqual(o['issues']);
}

describe('records', () => {
  const r = rec(fixture['records']);

  it('carries the same constants and vocabularies', () => {
    const c = rec(r['constants']);
    expect([SCHEMA, RUBRIC_VERSION, INTENT_COMPILER_VERSION, NONE]).toEqual([c['schema'], c['rubric'], c['intent_compiler'], c['none']]);
    expect([...ASSET_ROLES]).toEqual(c['roles']);
    expect([...VECTOR_REQUIRED].sort()).toEqual(c['vector_required']);
    expect([...RASTER_NATIVE].sort()).toEqual(c['raster_native']);
    expect([...LOGO_ROLES].sort()).toEqual(c['logo_roles']);
    expect([[...GATES], [...SEVERITIES], [...REVIEW_MODES], [...VERDICTS]]).toEqual([c['gates'], c['severities'], c['modes'], c['verdicts']]);
    expect([...PALETTE_ROLES]).toEqual(c['palette_roles']);
    expect([...GENERIC_AXES]).toEqual(c['generic_axes']);
    for (const [role, need] of Object.entries(rec(r['vector_need']))) expect(vectorNeed(role as AssetRole), role).toBe(need);
    for (const [prefix, payload, id] of list(r['record_ids']).map((x) => x as [string, unknown, string])) expect(recordId(prefix, dec(payload))).toBe(id);
  });

  it('validates briefs and findings the way Pydantic does (same error locations and types)', () => {
    for (const [input, outcome] of list(r['briefs']).map((x) => x as [unknown, unknown])) expectValidation(() => parseBrief(dec(input)), outcome, JSON.stringify(input));
    for (const [input, outcome] of list(r['bad_briefs']).map((x) => x as [unknown, unknown])) expectValidation(() => parseBrief(dec(input)), outcome, JSON.stringify(input));
    for (const [input, outcome] of list(r['findings']).map((x) => x as [unknown, unknown])) expectValidation(() => parseFinding(dec(input)), outcome, JSON.stringify(input));
    for (const [input, outcome] of list(r['bad_findings']).map((x) => x as [unknown, unknown])) expectValidation(() => parseFinding(dec(input)), outcome, JSON.stringify(input));
  });

  it('refuses the lax coercions Pydantic accepts ("3", 2.0, True for an int)', () => {
    for (const [input, outcome] of list(r['lax_briefs']).map((x) => x as [unknown, unknown])) {
      expect('ok' in rec(outcome), JSON.stringify(input)).toBe(true);
      expect(() => parseBrief(dec(input)), JSON.stringify(input)).toThrow(ValidationError);
    }
    for (const [input, outcome] of list(r['lax_findings']).map((x) => x as [unknown, unknown])) {
      expect('ok' in rec(outcome)).toBe(true);
      expect(() => parseFinding(dec(input)), JSON.stringify(input)).toThrow(ValidationError);
    }
  });
});

describe('intent compiler', () => {
  const it0 = rec(fixture['intent']);
  const projections = rec(it0['projections']);

  it('compiles every intent the same way, handing the prompt compiler the same document', () => {
    for (const c of list(it0['cases']).map(rec)) {
      const brief = parseBrief(c['brief']);
      const proj = rec(projections[str(c['projection'])]);
      const prohibited = rec(c['prohibited']);
      const intent = compileIntent({ tenant_id: 't1', project_id: 'p1', brand_id: 'b1', scope: 'brand', scope_ref: 'b1', brief,
        projection: { values: dec(proj['values']), genome_ref: 'gv-1', resolution_hash: 'ab'.repeat(32), grammar_weights: dec(proj['weights']) },
        brand_constraints: list(it0['constraints']) as never },
      { prohibitedReason: (text) => {
        if (!(text in prohibited)) throw new Error(`no recorded filter verdict for ${text}`);
        return prohibited[text] as string | null;
      },
      compile: (promptId, doc) => {
        expect([promptId, doc]).toEqual(c['doc']);
        return rec(it0['compiled'])[str(c['compiled'])] as CompiledPrompt;
      } });
      const label = `${JSON.stringify(c['brief'])} ${c['projection']} ${c['compiled']}`;
      expect(intent, label).toEqual(dec(c['intent']));
      if (c['handoff'] !== null) expect(handoffPackage(intent), label).toEqual(dec(c['handoff']));
      if (c['compiled'] === 'ready') expect(CreativeIntentSchema.safeParse(JSON.parse(JSON.stringify(intent))).success, label).toBe(true);
    }
  });

  it('picks directions, rotating marks and tone targets the same way', () => {
    for (const c of list(it0['directions']).map(rec)) {
      const brief: DirectionBrief = parseBrief({ asset_role: 'LOGO_MARK', objective: 'o', directions: c['dirs'], candidate_count: c['count'] });
      expect(directions(brief, dec(c['weights'])), JSON.stringify(c)).toEqual(c['out']);
    }
    for (const [h, count, approved, out] of list(it0['marks']).map((x) => x as [string, number, never, string[]])) expect(marksFor(h, count, approved)).toEqual(out);
    for (const [v, out] of list(it0['tone']).map((x) => x as [unknown, string[]])) expect(tone({ 'verbal.voice.tone': dec(v) }), JSON.stringify(v)).toEqual(out);
    expect([...COMPOSE_ROLES].sort()).toEqual(['ICON', 'LOGO_MARK']);
  });
});

describe('route registry', () => {
  const p = rec(fixture['providers']);

  it('declares the same routes, all hosted ones DISABLED', () => {
    expect(ROUTES).toEqual(list(p['routes']));
    expect(ROUTES.filter((r) => !r.adapter_implemented).length).toBeGreaterThan(0);
    expectOutcome(() => getRoute('nope'), p['unknown'], 'unknown route', () => undefined);
  });

  it('applies the spend and budget rules to priced routes', () => {
    for (const c of list(p['priced']).map(rec)) {
      const env: RouteEnv = { spend_mode: (c['spend_mode'] as string | null) ?? undefined, browser: { available: true } };
      expect(decideRoute(dec(c['route']), 'CONCEPT_COMPOSE', c['budget'] as number, env), JSON.stringify(c)).toEqual(dec(c['decision']));
    }
  });

  it('describes and decides identically for every env (spend mode, credentials, mock, browser)', () => {
    for (const e of list(p['envs']).map(rec)) {
      const env = rec(e['env']) as unknown as RouteEnv;
      if (e['describe'] !== null) expect(describeRoutes(env)).toEqual(dec(e['describe']));
      for (const [route, task, budget, decision] of list(e['decisions']).map((x) => x as [string, Task, number, unknown])) {
        expect(decide(route, task, budget, env), `${JSON.stringify(env)} ${route} ${task} ${budget}`).toEqual(dec(decision));
      }
    }
  });
});

describe('reconstruction rules and storage keys', () => {
  const rc = rec(fixture['reconstruct']);
  const intents = rec(rc['intents']);

  it('decides when a selected raster needs vector reconstruction', () => {
    for (const d of list(rc['decide']).map(rec)) {
      const role = d['role'] as AssetRole;
      const intent = { asset_role: role, vector_need: vectorNeed(role) } as CreativeIntent;
      const cand = { observed: { format_class: d['format'] } } as never;
      expect(decideReconstruction(intent, cand), JSON.stringify(d)).toEqual(d['result']);
    }
    expect([FIDELITY_MAX_DELTA_E, [...TRACE_BUDGETS], [...TEXT_ROLES].sort(), NEAR_DUPLICATE_BITS]).toEqual(rc['constants']);
  });

  it('flattens gradients and sets identity text exactly', () => {
    for (const [svg, out] of list(rc['flatten']).map((x) => x as [string, string])) expect(flattenGradients(svg), svg).toBe(out);
    for (const c of list(rc['with_text']).map(rec)) {
      expectOutcome(() => withText(str(c['svg']), c['texts'] as string[], c['box'] as [number, number, number, number], c['face'] as never, str(c['fill'])),
        c['result'], JSON.stringify(c), (actual, expected) => expect(actual).toBe(expected));
    }
  });

  it('validates SVG geometry into the same classification and checks', () => {
    for (const v of list(rc['validate']).map(rec)) {
      const intent = dec<CreativeIntent>(intents[str(v['role'])]);
      const [cls, checks] = validateGeometry(dec<Geometry>(v['geo']), intent);
      expect([cls, checks], JSON.stringify(v)).toEqual([v['class'], v['checks']]);
    }
  });

  it('derives the same Project OS keys, master keys and near-duplicate matches', () => {
    const s = rec(fixture['storage']);
    for (const [id, suffix, out] of list(s['keys']).map((x) => x as [string, string, unknown])) {
      expectOutcome(() => storageKey(id, suffix), out, `${id} ${suffix}`, (a, e) => expect(a).toBe(e));
    }
    for (const [id, cid, suffix, out] of list(s['names']).map((x) => x as [string, string, string, unknown])) {
      expectOutcome(() => candidateName(id, cid, suffix), out, `${id} ${cid}`, (a, e) => expect(a).toBe(e));
    }
    for (const [id, rid, out] of list(s['recon']).map((x) => x as [string, string, unknown])) {
      expectOutcome(() => reconstructionName(id, rid), out, `${id} ${rid}`, (a, e) => expect(a).toBe(e));
    }
    for (const [role, keys] of Object.entries(rec(s['master_keys']))) expect(masterKeys({ asset_role: role as AssetRole })).toEqual(keys);
    for (const n of list(s['near']).map(rec)) expect(nearDuplicate(n['others'] as never, n['phash'] as string | null, str(n['sha'])), JSON.stringify(n)).toBe(n['result']);
  });

  it('parses hex and compares perceptual hashes like Python, refusing int()\'s lax forms', () => {
    const m = rec(fixture['measure']);
    for (const [h, out] of list(m['hex_rgb']).map((x) => x as [string, unknown])) expectOutcome(() => hexRgb(h), out, h, (a, e) => expect(a).toEqual(e));
    for (const [a, b, out] of list(m['hamming']).map((x) => x as [string, string, unknown])) {
      if ('ok' in rec(out) && !(/^[0-9a-fA-F]+$/.test(a) && /^[0-9a-fA-F]+$/.test(b))) expect(() => hamming(a, b)).toThrow();
      else expectOutcome(() => hamming(a, b), out, `${a} ${b}`, (x, e) => expect(x).toBe(e));
    }
  });
});
