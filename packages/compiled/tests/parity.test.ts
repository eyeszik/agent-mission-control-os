/**
 * Replays every case recorded by `services/langgraph/tests/test_compiled_parity_fixture.py`
 * against `@amc/compiled`. Results and raised errors must match Python exactly, except the
 * explicit, pinned "Python accepts, TS refuses" cases at the bottom of this file.
 */
import { describe, expect, it } from 'vitest';
import { PyFloat } from '@amc/kernel';
import * as C from '../src/index';
import core from './fixtures/compiled-core.json';
import plansFx from './fixtures/compiled-plans.json';
import methodsFx from './fixtures/compiled-methods.json';
import { CALLS, type FixtureCase } from './dispatch';

type Section = readonly FixtureCase[];
const sections = (fx: unknown): [string, Section][] => Object.entries(fx as Record<string, Section>);

function caught(fn: () => unknown): unknown {
  try {
    fn();
  } catch (error) {
    return error;
  }
  return undefined;
}

function errorMatches(error: unknown, exp: NonNullable<FixtureCase['error']>, loose: boolean): void {
  expect(error).toBeInstanceOf(Error);
  if (loose) return;
  if (exp.type === 'ValidationError') {
    expect(error).toBeInstanceOf(C.CompiledValidationError);
    const locs = [...new Set((error as C.CompiledValidationError).issues.map((i) => C.locKey(i.loc)))].sort();
    expect(locs).toEqual(exp.locs);
    return;
  }
  expect({ type: (error as Error).name, message: (error as Error).message }).toEqual({ type: exp.type, message: exp.message });
}

/** Python-ok cases the twin refuses on purpose (Pydantic lax coercion, unsupported date spellings), by call. */
const refused: Record<string, string[]> = {};
const mismatched: Record<string, string[]> = {};

function note(into: Record<string, string[]>, c: FixtureCase): void {
  into[c.call] = [...(into[c.call] ?? []), JSON.stringify(c.args).slice(0, 160)];
}

function runCase(c: FixtureCase): void {
  const fn = CALLS[c.call];
  if (fn === undefined) throw new Error(`no dispatcher for ${c.call}`);
  const outcome = caught(() => {
    (c as { _result?: unknown })._result = fn(c.args);
  });
  if (c.ts_refuses !== undefined) {
    expect((outcome as Error).name).toBe(c.ts_refuses);
    return;
  }
  if (c.error !== undefined) {
    expect(outcome, `${c.call} should have raised`).toBeDefined();
    errorMatches(outcome, c.error, c.loose === true);
    return;
  }
  if (outcome !== undefined) {
    note(refused, c);
    return;
  }
  const actual = C.toPlain((c as { _result?: unknown })._result);
  const wanted = c.call === 'constraintInstant' ? (c.ok as { $int: string }).$int : c.ok;
  if (SOFT.has(c.call)) {
    if (JSON.stringify(actual) !== JSON.stringify(wanted)) note(mismatched, c);
    return;
  }
  expect(actual).toEqual(wanted);
}

const SOFT = new Set<string>();

describe('compiled parity: core', () => {
  for (const [name, cases] of sections(core)) {
    it(`${name} (${cases.length} cases)`, { timeout: 120_000 }, () => {
      expect(cases.length).toBeGreaterThan(0);
      for (const c of cases) runCase(c);
    });
  }
});

describe('compiled parity: plans', () => {
  for (const [name, cases] of sections(plansFx)) {
    if (name === 'registries') continue;
    it(`${name} (${cases.length} cases)`, { timeout: 300_000 }, () => {
      for (const c of cases) runCase(c);
    });
  }
});

describe('compiled parity: methods', () => {
  for (const [name, cases] of sections(methodsFx)) {
    if (name === 'catalog' || name === 'registry_note') continue;
    it(`${name} (${cases.length} cases)`, { timeout: 300_000 }, () => {
      for (const c of cases) runCase(c);
    });
  }
});

describe('known gaps (Python accepts, TS refuses or differs)', () => {
  it('are exactly the pinned ones', () => {
    expect({ refused, mismatched }).toEqual({ refused: PINNED_REFUSED, mismatched: PINNED_MISMATCHED });
  });
});

const PINNED_REFUSED: Record<string, string[]> = {
  "classify": [
    "[{\"determinism\":\"medium\",\"ambiguity\":\"high\",\"consequence\":\"medium\",\"reversible\":\"yes\",\"data_sensitivity\":\"low\",\"creative_judgment\":\"high\",\"factual_verifiability"
  ],
  "compileAgencyPlanDigest": [
    "[\"sealed\",{\"project_id\":\"e\",\"as_of\":\"2026-10-29\",\"deliverables\":[{\"id\":\"dx\",\"requested_outcome\":\"Outcome x\",\"output_contract\":\"copy_variant\",\"acceptance_criteri",
    "[\"sealed\",{\"project_id\":\"e\",\"as_of\":\"2026-10-29\",\"deliverables\":[{\"id\":\"dx\",\"requested_outcome\":\"Outcome x\",\"output_contract\":\"copy_variant\",\"acceptance_criteri"
  ],
  "constraintInstant": [
    "[\"2026-10-29 10:00:00 +00:00\"]",
    "[\"2026-10-29T10:00:00.Z\"]",
    "[\"2026-10-29T10:00:00+05:30:15.5\"]",
    "[\"2026-10-29T10:00:00,Z\"]"
  ],
  "evaluateValidation": [
    "[\"n\",[\"o\"],[{\"node_id\":\"n\",\"obligation\":\"o\",\"status\":\"PASS\",\"validator_ref\":\"v\",\"attempt\":\"2\"}],\"c\",\"low\",[]]"
  ],
  "parseCatalog": [
    "[[[\"set\",[\"methods\",0,\"contraindications\"],[\"family:X\\n\"]]]]"
  ],
  "validateObjectiveRequest": [
    "[{\"objective\":\"x\",\"live_service\":\"yes\"}]",
    "[{\"objective\":\"x\",\"live_service\":1}]"
  ]
};
const PINNED_MISMATCHED: Record<string, string[]> = {};
void PyFloat;
