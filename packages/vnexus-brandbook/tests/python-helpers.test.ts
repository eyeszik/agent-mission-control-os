import { describe, expect, it } from 'vitest';
import {
  base64, canonicalHash, cpLen, escapeHtml, floatRepr, formatFixed, formatG, formatPercent0, pyJsonDumps, pyLstrip, pyRepr, pyRound,
  pyRoundInt, pyRstrip, pySplitWs, pyStr, pyStrip, relativeLuminance, sha256, wcagContrastRatio, type PyValue,
} from '../src/index';
import { dec, expectOutcome, fixture, list, num, rec, str } from './helpers';

const helpers = rec(fixture['python_helpers']);

describe('Python number formatting', () => {
  it('reproduces :.Nf, round(), :g, :.0% and repr(float) for every recorded float', () => {
    for (const c of list(helpers['numbers']).map(rec)) {
      const x = num(c['x']);
      if (c['op'] === 'fixed') {
        expect(formatFixed(x, c['places'] as number), JSON.stringify(c)).toBe(c['out']);
        const rounded = c['places'] === 0 ? pyRoundInt(x) : pyRound(x, c['places'] as number);
        expect(floatRepr(c['places'] === 0 ? Number(rounded) : rounded), JSON.stringify(c)).toBe(c['round']);
      } else if (c['op'] === 'g' || c['op'] === 'float_g_in_clearspace') expect(formatG(x), JSON.stringify(c)).toBe(c['out']);
      else if (c['op'] === 'pct0') expect(formatPercent0(x), JSON.stringify(c)).toBe(c['out']);
      else expect(floatRepr(x), JSON.stringify(c)).toBe(c['out']);
    }
  });
});

describe('Python string behaviour', () => {
  it('reproduces strip, split, html.escape, len, repr, base64, sha256 and json.dumps of strings', () => {
    for (const c of list(helpers['strings']).map(rec)) {
      const s = str(c['s']);
      const label = `${c['op']} ${JSON.stringify(s)}`;
      const ops: Record<string, () => unknown> = {
        strip: () => pyStrip(s), lstrip: () => pyLstrip(s), rstrip: () => pyRstrip(s), split_ws: () => pySplitWs(s),
        escape: () => escapeHtml(s), len: () => cpLen(s), repr: () => pyRepr(s), b64: () => base64(new TextEncoder().encode(s)),
        sha256: () => sha256(s), json: () => pyJsonDumps(s),
      };
      expect((ops[str(c['op'])] as () => unknown)(), label).toEqual(c['out']);
      if (c['op'] === 'json') expect(pyJsonDumps(s, { ensureAscii: false }), label).toBe(c['out_unicode']);
    }
  });

  it('reproduces json.dumps with indent, sort_keys and ensure_ascii', () => {
    for (const c of list(helpers['json']).map(rec)) {
      const options = { sortKeys: c['sort'] as boolean, ensureAscii: c['ascii'] as boolean,
        ...(c['indent'] === null ? {} : { indent: c['indent'] as number }) };
      expect(pyJsonDumps(dec(c['value']), options), JSON.stringify(c)).toBe(c['out']);
    }
  });

  it('reproduces str() and repr() of genome values', () => {
    for (const c of list(helpers['repr']).map(rec)) {
      const v = dec(c['value']) as PyValue;
      expect(pyStr(v), JSON.stringify(c)).toBe(c['str']);
      expect(pyRepr(v), JSON.stringify(c)).toBe(c['repr']);
    }
  });
});

describe('WCAG contrast', () => {
  const contrast = rec(fixture['contrast']);

  it('reproduces relative luminance exactly for every 8-bit channel value', () => {
    for (const [hex, out] of list(contrast['luminance']).map((r) => r as [string, string])) {
      expect(floatRepr(relativeLuminance(hex)), hex).toBe(out);
    }
  }, 30000);

  it('reproduces the rounded ratio for recorded pairs', () => {
    for (const [a, b, outcome] of list(contrast['ratios']).map((r) => r as [string, string, unknown])) {
      expectOutcome(() => wcagContrastRatio(a, b), outcome, `${a} ${b}`, (actual, expected) => expect(actual).toBe(num(expected)));
    }
  });

  it('raises the same ValueError for hex Python rejects, and refuses its lax int() forms', () => {
    const all = [...list(contrast['errors']), ...list(contrast['python_accepts_ts_refuses'])].map((r) => r as [string, unknown]);
    for (const [hex, outcome] of all) {
      if ('error' in rec(outcome)) {
        expectOutcome(() => relativeLuminance(hex), outcome, hex, () => undefined);
      } else {
        expect(() => relativeLuminance(hex), hex).toThrow(/invalid literal for int\(\) with base 16/);
      }
    }
  });
});

describe('canonical hash wiring', () => {
  it('hashes through AMC-CANON-1', () => {
    expect(canonicalHash({ probe: [1, 2.5] })).toBe(rec(fixture['versions'])['canonical_hash_probe']);
  });
});
