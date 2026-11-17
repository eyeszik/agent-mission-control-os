import { expect } from 'vitest';
import { CanonicalFloat } from '@amc/design-tokens';
import {
  BrandContextSchema,
  componentTemplate,
  compileTokenSystem,
  evaluateAndRepair,
  type Draft,
  type UIState,
} from '../src/index';
import evaluatorJson from './fixtures/ui-ux-evaluator.json';

// Builds the drafts the Python fixture crafted and runs the evaluator on them.
type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
type Obj = { [key: string]: Json };
type Case = { spec: Obj; ok?: Obj; raises?: { error: string } };

function plain(value: unknown): Json {
  if (value instanceof CanonicalFloat) return value.value;
  if (Array.isArray(value)) return value.map(plain);
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, plain(v)]));
  }
  return value as Json;
}

type Spec = {
  mode: Draft['mode']; features: string[]; screens: Draft['screens']; components: Array<[string, UIState[], string]>;
  interactions: Draft['interactions']; genome: Draft['genome']; design_system: Draft['design_system']; a11y: Draft['a11y'];
  performance_requirements: string[]; palette: string[]; has_ai: boolean; include_data: boolean;
  request_text: { content: string[]; constraints: string[]; generic_copy: string[] };
};

function buildDraft(spec: Spec): Draft {
  return {
    mode: spec.mode,
    features: new Set(spec.features),
    screens: structuredClone(spec.screens),
    components: new Map(
      spec.components.map(([name, states, status]) => [
        name,
        { template: componentTemplate(name), states: [...states], status: status as 'PROPOSED' | 'EXTEND' },
      ]),
    ),
    interactions: structuredClone(spec.interactions),
    genome: { ...spec.genome },
    design_system: structuredClone(spec.design_system),
    a11y: structuredClone(spec.a11y),
    performance_requirements: [...spec.performance_requirements],
    assumptions: [],
    approval_required: [],
  };
}

function evaluate(spec: Spec): Json {
  const draft = buildDraft(spec);
  const brand = spec.palette.length > 0 ? BrandContextSchema.parse({ brand_name: 'B', palette_hex: spec.palette }) : null;
  const tokenSystem = compileTokenSystem(brand, draft.genome, { includeAi: spec.has_ai, includeData: spec.include_data });
  const state = evaluateAndRepair({ draft, tokenSystem, requestText: spec.request_text, hasAi: spec.has_ai });
  return plain({
    findings: state.findings,
    iterations: state.iterations,
    approval_required: state.approval_required,
    draft: {
      screens: draft.screens.map((s) => ({ id: s.id, regions: s.regions, components: s.components })),
      components: Object.fromEntries([...draft.components].map(([n, c]) => [n, c.states])),
      interactions: draft.interactions,
      design_system: draft.design_system,
      genome: draft.genome,
    },
  });
}

export function runEvaluatorCases(): void {
  const cases = (evaluatorJson as unknown as { evaluator: Case[] }).evaluator;
  expect(cases.length).toBeGreaterThanOrEqual(150);
  for (const [index, c] of cases.entries()) {
    expect(c.raises, `case ${index} raises in Python`).toBeUndefined();
    expect(evaluate(c.spec as unknown as Spec), `case ${index}`).toEqual(c.ok);
  }
}
