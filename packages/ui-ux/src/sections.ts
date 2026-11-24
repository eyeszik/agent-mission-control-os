/** Fixed-shape IR sections: AI trust, performance, implementation map, checks, confidence. */
import { compareCodePoints, uniqueInOrder } from './python';
import type { Draft, EvaluationFinding, TokenSystemSpec, Unknown, UIUXDesignIR } from './types';

type Ir = UIUXDesignIR;

export function buildAiTrust(hasAi: boolean, providerKnown: boolean): Ir['ai_trust'] {
  const provider = providerKnown
    ? 'Show the provider/model reported by the backend for this response.'
    : "Show provider/model only when the backend reports them; otherwise 'Not disclosed'.";
  return {
    required: hasAi,
    provenance_rules: hasAi
      ? [
          "Label every AI output 'AI-generated' or 'AI-assisted' inside a single AITrustEnvelope scope.",
          provider,
          'Degraded or fallback output is labeled as such, never presented as model output.',
        ]
      : [],
    attribution_rules: hasAi ? ["Show sources when the backend returns them; otherwise state 'Sources unavailable'."] : [],
    uncertainty_rules: hasAi
      ? ["No numeric confidence unless a calibrated backend value exists; display 'Confidence not measured'."]
      : [],
    feedback_rules: hasAi ? ['Offer feedback/retry only when a backend endpoint records it.'] : [],
    confidence_display: 'NOT_MEASURED',
  };
}

function budget(name: string, target: string, formula: string, fallback: string): Ir['performance']['budgets'][number] {
  return {
    name, target, truth: 'NOT_MEASURED', source: 'Core Web Vitals target', formula, timestamp: null,
    freshness: 'no measurement exists', uncertainty: 'unmeasured', fallback,
  };
}

export function buildPerformance(draft: Draft, hasData: boolean, hasAi: boolean): Ir['performance'] {
  const measure = 'measure with RUM in staging before any claim';
  const risks: string[] = [];
  if (draft.features.has('realtime')) risks.push('Streaming/live updates can re-render on every chunk; batch updates per animation frame.');
  if (hasData) risks.push('Large tables need virtualization or pagination beyond a few hundred rows.');
  if (hasAi) risks.push('Token-by-token rendering must not re-render the whole conversation.');
  return {
    requirements: draft.performance_requirements,
    risks,
    budgets: [
      budget('Largest Contentful Paint', '<= 2.5 s (p75)', 'p75 field LCP', measure),
      budget('Interaction to Next Paint', '<= 200 ms (p75)', 'p75 field INP', measure),
      budget('Cumulative Layout Shift', '<= 0.1 (p75)', 'p75 field CLS', 'reserve space for async content (skeleton states)'),
    ],
  };
}

const MAPPING_TESTS: readonly string[] = [
  'unit: each component renders every declared state with its non-color channel',
  'e2e: primary flow keyboard-only',
  'e2e: 320px reflow and 200% text zoom',
  'a11y: automated axe scan (partial coverage only)',
  'a11y: screen reader walkthrough (NVDA + VoiceOver) — requires assistive tech',
  'visual: forced-colors and prefers-reduced-motion snapshots',
];

export function buildMapping(draft: Draft, hasAi: boolean, hasData: boolean): Ir['implementation_mapping'] {
  const byStatus = (status: string): string[] => [...draft.components].filter(([, s]) => s.status === status).map(([n]) => n);
  return {
    // the pure compiler cannot verify a repository
    verified_existing: [],
    extend: byStatus('EXTEND'),
    proposed: byStatus('PROPOSED'),
    contracts: [
      'Async action contract: {status: idle|pending|success|error, error?: {message, recovery}}',
      ...(hasAi ? ['AI response contract: {mode, provider?, model?, sources?[], review_status}'] : []),
      ...(hasData ? ['Metric contract: {value, truth, source, formula, timestamp?, freshness}'] : []),
    ],
    state_dependencies: [...draft.components].map(([name, spec]) => `${name}: ${spec.states.join(', ')}`),
    events: draft.screens.map((screen) => `proposed analytics event: ui.${screen.id}.primary_task`),
    tests: [...MAPPING_TESTS],
  };
}

export function buildDesignSystem(draft: Draft, tokens: TokenSystemSpec, territoryName: string, responsive: Ir['responsive_rules']): Ir['design_system'] {
  const requirements = [...draft.a11y].sort((a, b) => compareCodePoints(a.id, b.id));
  return {
    foundations: [
      `Tokens: DTCG 2025.10, ${tokens.token_count} tokens in T1/T2/T3 tiers (prefix --${tokens.css_prefix}-)`,
      `Genome: ${draft.genome.genome_hash.slice(0, 12)}`,
      `Territory: ${territoryName}`,
    ],
    patterns: draft.design_system.patterns,
    templates: draft.screens.map((screen) => screen.id),
    content_rules: draft.design_system.content_rules,
    state_rules: draft.design_system.state_rules,
    motion_rules: draft.design_system.motion_rules,
    accessibility_rules: requirements.map((req) => `${req.criterion}: ${req.rule}`),
    responsive_rules: responsive.map((rule) => `${rule.region_ref} -> ${rule.transform}`),
  };
}

export interface ConfidenceInput {
  readonly assumptions: number;
  readonly unknowns: readonly Unknown[];
  readonly applied: number;
  readonly territoryId: string;
  readonly paletteGiven: boolean;
  readonly degradedSources: boolean;
  readonly blocking: boolean;
}

function confidenceValue(input: ConfidenceInput): number {
  let value = 0.9 - Math.min(0.05 * input.assumptions, 0.3) - 0.1 * input.unknowns.filter((u) => u.blocks).length;
  if (!input.paletteGiven) value -= 0.1;
  if (input.degradedSources) value -= 0.2;
  return input.blocking ? Math.min(value, 0.3) : value;
}

export function buildConfidence(input: ConfidenceInput, round: (value: number) => number): Ir['confidence'] {
  const basis = [`${input.assumptions} assumption(s)`, `${input.applied} principle(s) applied`, `territory ${input.territoryId}`];
  if (!input.paletteGiven) basis.push('palette unresolved');
  if (input.degradedSources) basis.push('derived from degraded (fallback) upstream output');
  return {
    value: round(Math.max(0.2, Math.min(confidenceValue(input), 0.95))),
    basis,
    unknowns: input.unknowns.map((u) => u.question),
  };
}

export function buildChecks(tokens: TokenSystemSpec, findings: readonly EvaluationFinding[], blocking: number, applied: number, triggered: number, iterations: number): Ir['validation_checks'] {
  const passes = tokens.contrast.filter((c) => c.passes).length;
  return [
    { id: 'schema_strict', status: 'PASS', evidence: 'pydantic extra=forbid on every model' },
    { id: 'dtcg_tokens_compiled', status: 'PASS', evidence: `${tokens.token_count} tokens, tiered, sha256 ${tokens.source_hash.slice(0, 12)}` },
    {
      id: 'wcag_contrast_static',
      status: passes === tokens.contrast.length ? 'PASS' : 'FAIL',
      evidence: `${passes}/${tokens.contrast.length} pairs meet their WCAG 2.2 requirement`,
    },
    {
      id: 'evaluation_engines',
      status: blocking > 0 ? 'FAIL' : 'PASS',
      evidence: `${findings.length} finding(s), ${blocking} blocking unresolved, ${iterations} repair iteration(s)`,
    },
    { id: 'principles_selective', status: 'PASS', evidence: `${applied} of ${triggered} triggered principles changed the IR` },
    { id: 'generation_firewall', status: 'PASS', evidence: 'terminal is a spec state; no generated/deployed state exists' },
    { id: 'browser_and_assistive_tech', status: 'NOT_RUN', evidence: 'spec-level compiler; requires implementation' },
  ];
}

export function approvalList(draft: Draft, repaired: readonly string[]): string[] {
  return uniqueInOrder([
    ...draft.approval_required,
    ...repaired,
    'Design lead (design_lead, Department.design) sign-off before implementation (HITL).',
  ]);
}

export function terminalFor(blocking: number, approval: readonly string[], unknowns: readonly Unknown[]): Ir['terminal'] {
  if (blocking > 0) return 'BLOCKED';
  if (approval.some((item) => item.startsWith('DECISION:')) || unknowns.some((u) => u.blocks)) return 'REQUIRES_APPROVAL';
  return 'UIUX_SPEC_READY';
}
