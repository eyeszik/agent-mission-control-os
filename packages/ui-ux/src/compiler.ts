/**
 * Deterministic UI/UX design compiler (twin of `ui_ux/compiler.py`):
 *
 *   REQUEST -> PRODUCT -> USER -> TASK -> IA -> FLOW -> PRINCIPLES -> DIRECTION
 *   -> DESIGN_GENOME -> TOKENS -> SCREENS -> COMPONENTS -> STATES -> INTERACTIONS
 *   -> RESPONSIVE -> A11Y -> PERFORMANCE -> AI_TRUST -> IMPLEMENTATION
 *   -> (evaluate + bounded repair) -> UIUXDesignIR
 *
 * Pure: no provider calls, no I/O, no clock. The same request always yields the
 * same IR and the same `spec_hash`. It produces a governed *specification*; it
 * never generates, renders or ships an interface.
 */
import { addUnique, surfaceTemplate } from './catalog';
import {
  buildAccessibility, buildComponents, buildGenerationPrompts, buildResponsive, buildScreens, buildStates,
} from './assemble';
import { buildDraft, productFields, type Ledger, type ProductFields } from './draft';
import { applyPrinciples } from './effects';
import { evaluateAndRepair, type EvaluationState } from './evaluator';
import { buildGenome, territories } from './genome';
import { genomeHash, specHash } from './hash';
import { UIUX_COMPILER_VERSION, UIUX_SCHEMA_VERSION, parseUiuxRequest, type UIUXRequest } from './models';
import { extractFeatures, selectPrinciples } from './principles';
import { pyWordSearch, roundTo, sortedStrings } from './python';
import {
  approvalList, buildAiTrust, buildChecks, buildConfidence, buildDesignSystem, buildMapping, buildPerformance, terminalFor,
} from './sections';
import { inferSurface } from './surface';
import { compileTokenSystem } from './tokens';
import type { Assumption, Draft, SourceRef, Territory, TokenSystemSpec, Unknown, UIUXDesignIR } from './types';

const GENERIC_COPY: readonly string[] = [
  'unlock', 'supercharge', 'seamless', 'revolutionize', 'revolutionise', 'next-gen', 'game-changing', 'game changer',
  '10x', 'cutting-edge', 'world-class', 'synergy',
];

const PROOF_WORDS: readonly string[] = ['testimonial', 'review', 'logo', 'customer count', 'case stud', 'award', 'rating'];

function addProofRules(draft: Draft, content: readonly string[]): void {
  for (const item of content) {
    if (!pyWordSearch(PROOF_WORDS, item.toLowerCase(), false)) continue;
    addUnique(
      draft.design_system.content_rules,
      `'${item}' renders only sourced items with visible attribution; no placeholder or invented proof.`,
    );
  }
}

function paletteGiven(request: UIUXRequest): boolean {
  return request.brand !== null && request.brand.palette_hex.length > 0;
}

function addPaletteAssumption(draft: Draft, ledger: Ledger): void {
  ledger.assumptions.push({
    id: 'assume.palette',
    statement: 'Brand palette unresolved; structural tokens use neutral placeholders.',
    reason: 'No palette reference was supplied.',
    impact: 'design_token_set must compile the brand color story before visual sign-off.',
  });
  draft.approval_required.push(
    'DECISION: brand palette must be compiled by the design_token_set role before visual sign-off.',
  );
}

function platformFor(request: UIUXRequest, ledger: Ledger): NonNullable<UIUXRequest['platform']> {
  if (request.platform !== null) return request.platform;
  ledger.assumptions.push({
    id: 'assume.platform',
    statement: 'Platform treated as responsive web.',
    reason: 'No platform was given.',
    impact: 'Responsive rules cover 320px through desktop.',
  });
  return 'WEB_RESPONSIVE';
}

interface Prepared {
  readonly ledger: Ledger;
  readonly sources: SourceRef[];
  readonly mode: UIUXDesignIR['mode'];
  readonly platform: NonNullable<UIUXRequest['platform']>;
  readonly brandName: string;
  readonly product: ProductFields;
}

function prepare(request: UIUXRequest): Prepared {
  const ledger: Ledger = { assumptions: [], unknowns: [] };
  const sources: SourceRef[] = [{ kind: 'REQUEST', ref: request.project_ref, detail: 'UIUXRequest' }, ...request.sources];
  const [mode, surfaceAssumption] = inferSurface(request);
  if (surfaceAssumption !== null) ledger.assumptions.push(surfaceAssumption);
  const platform = platformFor(request, ledger);
  const brandName = request.brand ? request.brand.brand_name : request.project_ref;
  return { ledger, sources, mode, platform, brandName, product: productFields(request, brandName, ledger) };
}

function requestText(request: UIUXRequest, product: ProductFields): string {
  return [
    request.surface_hint, product.purpose, product.primary_task, product.business_goal,
    ...request.content_requirements, ...request.constraints,
  ].join(' ');
}

interface Analysis {
  readonly draft: Draft;
  readonly template: ReturnType<typeof surfaceTemplate>;
  readonly territories: Territory[];
  readonly selected: Territory;
  readonly applied: UIUXDesignIR['principles_applied'];
  readonly triggered: number;
  readonly tokens: TokenSystemSpec;
  readonly evaluation: EvaluationState;
  readonly hasAi: boolean;
  readonly hasData: boolean;
}

function genomeFor(request: UIUXRequest, prep: Prepared, draft: Draft, selected: Territory): void {
  draft.genome = buildGenome({
    mode: prep.mode,
    territory: selected,
    brandTypography: request.brand ? request.brand.typography_direction : null,
    features: draft.features,
    brandName: prep.brandName,
  });
}

function analyse(request: UIUXRequest, prep: Prepared): Analysis {
  const text = requestText(request, prep.product);
  const features = extractFeatures(prep.mode, text, { aiFeatures: request.ai_features, rtl: request.locale_rtl });
  const [hasAi, hasData] = [features.has('ai'), features.has('data')];
  const { draft, template } = buildDraft({
    mode: prep.mode, features, text, existingComponents: request.existing_components, hasAi, assumptions: prep.ledger.assumptions,
  });
  const scored = territories(prep.mode, request.brand ? request.brand.tone_attributes : [], features);
  const selected = scored.find((item) => item.selected) as Territory;
  genomeFor(request, prep, draft, selected);
  const principles = selectPrinciples(features);
  const applied = applyPrinciples(draft, principles);
  draft.genome = { ...draft.genome, genome_hash: genomeHash(draft.genome) };
  const tokens = compileTokenSystem(request.brand, draft.genome, { includeAi: hasAi, includeData: hasData });
  return { draft, template, territories: scored, selected, applied, triggered: principles.length, tokens, evaluation: emptyEvaluation(), hasAi, hasData };
}

function emptyEvaluation(): EvaluationState {
  return { findings: [], iterations: 0, approval_required: [] };
}

function evaluate(request: UIUXRequest, prep: Prepared, analysis: Analysis): EvaluationState {
  const { draft } = analysis;
  if (!paletteGiven(request)) addPaletteAssumption(draft, prep.ledger);
  const lowered = `${prep.product.purpose} ${prep.product.business_goal}`.toLowerCase();
  addProofRules(draft, request.content_requirements);
  return evaluateAndRepair({
    draft,
    tokenSystem: analysis.tokens,
    requestText: {
      content: [...request.content_requirements],
      constraints: [...request.constraints, ...request.negative_constraints],
      generic_copy: sortedStrings(GENERIC_COPY.filter((word) => lowered.includes(word))),
    },
    hasAi: analysis.hasAi,
  });
}

interface Verdict {
  readonly blocking: number;
  readonly approval: string[];
  readonly terminal: UIUXDesignIR['terminal'];
}

function judge(draft: Draft, evaluation: EvaluationState, unknowns: readonly Unknown[]): Verdict {
  const blocking = evaluation.findings.filter((f) => f.severity === 'BLOCKING' && !f.repaired).length;
  const approval = approvalList(draft, evaluation.approval_required);
  return { blocking, approval, terminal: terminalFor(blocking, approval, unknowns) };
}

function confidenceOf(request: UIUXRequest, prep: Prepared, analysis: Analysis, verdict: Verdict): UIUXDesignIR['confidence'] {
  return buildConfidence(
    {
      assumptions: prep.ledger.assumptions.length,
      unknowns: prep.ledger.unknowns,
      applied: analysis.applied.length,
      territoryId: analysis.selected.id,
      paletteGiven: paletteGiven(request),
      degradedSources: prep.sources.some((s) => s.detail.includes('FALLBACK_DEGRADED')),
      blocking: verdict.blocking > 0,
    },
    (value) => roundTo(value, 2),
  );
}

function informationArchitecture(template: Analysis['template']): UIUXDesignIR['information_architecture'] {
  return {
    primary_nav: template.nav.map(([id, label, purpose, priority]) => ({ id, label, purpose, priority, children: [] })),
    hierarchy_depth: 2,
    labeling_rule: 'Labels name the user\'s object or task in plain language; no internal jargon.',
  };
}

function flows(template: Analysis['template']): UIUXDesignIR['flows'] {
  return template.flows.map((flow) => ({
    id: flow.id,
    name: flow.name,
    goal: flow.goal,
    steps: flow.steps.map((step, index) => ({ id: `${flow.id}.${index + 1}`, ...step })),
    success_signal: flow.success_signal,
  }));
}

function sections(request: UIUXRequest, prep: Prepared, analysis: Analysis, verdict: Verdict): Partial<UIUXDesignIR> {
  const { draft, tokens } = analysis;
  const screens = buildScreens({ draft, request, primaryTask: prep.product.primary_task, selected: analysis.selected });
  const responsive = buildResponsive(draft);
  const mapping = buildMapping(draft, analysis.hasAi, analysis.hasData);
  return {
    screens,
    components: buildComponents(draft),
    states: buildStates(draft),
    responsive_rules: responsive,
    accessibility: buildAccessibility(draft, tokens, mapping.tests),
    performance: buildPerformance(draft, analysis.hasData, analysis.hasAi),
    ai_trust: buildAiTrust(analysis.hasAi, request.ai_provider_known),
    implementation_mapping: mapping,
    design_system: buildDesignSystem(draft, tokens, analysis.selected.name, responsive),
    generation_prompts: buildGenerationPrompts(screens, tokens.css_prefix),
    validation_checks: buildChecks(
      tokens, analysis.evaluation.findings, verdict.blocking, analysis.applied.length, analysis.triggered, analysis.evaluation.iterations,
    ),
  };
}

/** Python `compile_uiux`, on an already validated request. */
export function compileUiuxRequest(request: UIUXRequest): UIUXDesignIR {
  const prep = prepare(request);
  const analysis = analyse(request, prep);
  const evaluation = evaluate(request, prep, analysis);
  const full: Analysis = { ...analysis, evaluation };
  const verdict = judge(full.draft, evaluation, prep.ledger.unknowns);
  const { draft } = full;
  const ir = {
    schema_version: UIUX_SCHEMA_VERSION,
    compiler_version: UIUX_COMPILER_VERSION,
    project_ref: request.project_ref,
    mode: prep.mode,
    product_model: { ...prep.product, platform: prep.platform },
    sources: prep.sources,
    assumptions: prep.ledger.assumptions as Assumption[],
    unknowns: prep.ledger.unknowns,
    constraints: [...request.constraints, ...request.negative_constraints.map((item) => `NOT: ${item}`)],
    capabilities: sortedStrings(draft.features),
    information_architecture: informationArchitecture(full.template),
    flows: flows(full.template),
    territories: full.territories,
    selected_direction: `${full.selected.name}: ${full.selected.thesis}`,
    principles_applied: full.applied,
    design_genome: draft.genome,
    tokens: full.tokens,
    interactions: draft.interactions,
    ...sections(request, prep, full, verdict),
    evaluation: evaluation.findings,
    repair_iterations: evaluation.iterations,
    approval_required: verdict.approval,
    confidence: confidenceOf(request, prep, full, verdict),
    handoff_only: true,
    terminal: verdict.terminal,
    spec_hash: '',
  } as UIUXDesignIR;
  return { ...ir, spec_hash: specHash(ir) };
}

/** Python `compile_uiux(UIUXRequest.model_validate(data))`: validate, then compile. */
export function compileUiux(data: unknown): UIUXDesignIR {
  return compileUiuxRequest(parseUiuxRequest(data));
}
