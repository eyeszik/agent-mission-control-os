/**
 * Quality engines and bounded repair (twin of `ui_ux/evaluator.py`).
 * Repair only performs edits that are true by construction; what it cannot
 * know (a missing justification, a failing brand palette) is escalated to
 * `approval_required` instead of papered over.
 */
import { floatRepr } from '@amc/kernel';
import { componentTemplate, componentTokens, stateRow } from './catalog';
import { compareCodePoints } from './python';
import type {
  ContrastCheck,
  Draft,
  EvaluationEngine,
  EvaluationFinding,
  InteractionSpec,
  Severity,
  TokenSystemSpec,
  UIState,
} from './types';

export const MAX_REPAIR_ITERATIONS = 3;

const GENERIC_MOTIFS: ReadonlyArray<readonly [string, string]> = [
  ['purple gradient', 'Purple gradients read as template AI branding.'],
  ['gradient', 'Decorative gradients need a brand reason.'],
  ['glow', 'Glows add noise without meaning.'],
  ['glassmorphism', 'Glass effects hurt contrast and read as templated.'],
  ['glass', 'Glass effects hurt contrast and read as templated.'],
  ['floating blob', 'Floating blobs are generic decoration.'],
  ['blob', 'Floating blobs are generic decoration.'],
  ['card everything', 'Card-everything layouts flatten hierarchy.'],
  ['pill', 'Pill overload blurs the difference between tags, actions, and status.'],
  ['ai badge', 'Decorative AI badges without provenance mislead.'],
  ['sparkle', "Sparkle 'AI' iconography is decoration, not provenance."],
];

const STATUS_STATES: ReadonlySet<UIState> = new Set<UIState>([
  'ERROR', 'WARNING', 'INVALID', 'SUCCESS', 'DEGRADED', 'OFFLINE', 'UNAVAILABLE', 'PENDING_APPROVAL', 'APPROVED',
  'REJECTED', 'STALE', 'SELECTED', 'CHECKED', 'CURRENT', 'FOCUS_VISIBLE', 'DISABLED',
]);

const GENOME_TEXT_FIELDS = [
  'hierarchy', 'density', 'geometry', 'typography', 'color', 'material', 'motion', 'interaction', 'signature',
] as const;

export interface RequestText {
  readonly content: readonly string[];
  readonly constraints: readonly string[];
  readonly generic_copy: readonly string[];
}

export interface EvaluationState {
  findings: EvaluationFinding[];
  iterations: number;
  approval_required: string[];
}

interface Issue {
  readonly finding: EvaluationFinding;
  readonly repair?: (draft: Draft) => string;
  readonly approval?: string;
}

function finding(engine: EvaluationEngine, severity: Severity, subject: string, message: string): EvaluationFinding {
  return { engine, severity, subject, message, repaired: false, repair_action: null };
}

const findingKey = (f: EvaluationFinding): string => [f.engine, f.subject, f.message].join('\u0000');

function tagged(draft: Draft, tag: string): string[] {
  return [...draft.components].filter(([, spec]) => spec.template.tags.includes(tag)).map(([name]) => name);
}

function addRule(draft: Draft, key: 'patterns' | 'content_rules' | 'motion_rules', rule: string): string {
  if (!draft.design_system[key].includes(rule)) draft.design_system[key].push(rule);
  return `design_system.${key} += rule`;
}

function replaceMotif(draft: Draft, motif: string): string {
  const rule = `Do not use '${motif}' decoration; express the brand through the product-specific signature element instead.`;
  addRule(draft, 'patterns', rule);
  return `added pattern rule against '${motif}'`;
}

function motifIssues(subject: string, text: string, justification: string): Issue[] {
  const issues: Issue[] = [];
  const seen: string[] = [];
  for (const [motif, reason] of GENERIC_MOTIFS) {
    if (!text.includes(motif) || seen.some((item) => item.includes(motif))) continue;
    seen.push(motif);
    if (justification.includes(motif) && (justification.includes('brand') || justification.includes('required'))) continue;
    issues.push({
      finding: finding('ANTI_GENERIC', 'WARNING', subject, `unjustified '${motif}': ${reason}`),
      repair: (d) => replaceMotif(d, motif),
    });
  }
  return issues;
}

function antiGeneric(draft: Draft, request: RequestText): Issue[] {
  const justification = request.constraints.join(' ').toLowerCase();
  const genome = GENOME_TEXT_FIELDS.map((field) => draft.genome[field]).join(' ').toLowerCase();
  const issues = [
    ...motifIssues('request.content', request.content.join(' ').toLowerCase(), justification),
    ...motifIssues('design_genome', genome, justification),
  ];
  for (const phrase of request.generic_copy) {
    issues.push({
      finding: finding('ANTI_GENERIC', 'WARNING', 'request.copy', `generic SaaS phrase '${phrase}'`),
      repair: (d) =>
        addRule(d, 'content_rules', `Replace generic phrasing ('${phrase}') with a specific, verifiable claim about the product.`),
    });
  }
  return issues;
}

function demote(screenIndex: number, regionIndex: number): (draft: Draft) => string {
  return (draft) => {
    const screen = draft.screens[screenIndex];
    const region = screen?.regions[regionIndex];
    if (screen === undefined || region === undefined) throw new Error('salience repair target is gone');
    screen.regions[regionIndex] = { ...region, emphasis: 1 };
    return `demoted ${region.id} emphasis to 1`;
  };
}

function salience(draft: Draft): Issue[] {
  const issues: Issue[] = [];
  draft.screens.forEach((screen, screenIndex) => {
    const p0 = screen.regions.filter((r) => r.priority === 'P0').map((r) => r.emphasis);
    if (p0.length === 0) {
      issues.push({
        finding: finding('SALIENCE_BUDGET', 'BLOCKING', `screens.${screen.id}`, 'no P0 region: the primary task has no home'),
      });
      return;
    }
    const top = Math.max(...p0);
    screen.regions.forEach((region, index) => {
      if (region.priority !== 'P3' || region.emphasis < top) return;
      issues.push({
        finding: finding(
          'SALIENCE_BUDGET', 'BLOCKING', `screens.${screen.id}.${region.id}`,
          `P3 region emphasis ${region.emphasis} >= P0 emphasis ${top}`,
        ),
        repair: demote(screenIndex, index),
      });
    });
  });
  return issues;
}

function addFallback(index: number): (draft: Draft) => string {
  return (draft) => {
    const current = draft.interactions[index] as InteractionSpec;
    const modes = [...new Set([...current.input_modes, 'KEYBOARD', 'SCREEN_READER'])] as InteractionSpec['input_modes'];
    draft.interactions[index] = {
      ...current,
      fallback: "Standard control alternative: 'Move up/down' buttons and a position menu, operable by keyboard.",
      input_modes: modes,
    };
    return `added standard keyboard fallback to ${current.id}`;
  };
}

function interactionDebt(draft: Draft): Issue[] {
  const issues: Issue[] = [];
  draft.interactions.forEach((interaction, index) => {
    if (interaction.standard) return;
    if (!interaction.fallback) {
      issues.push({
        finding: finding('INTERACTION_DEBT', 'BLOCKING', interaction.id, 'nonstandard interaction has no standard fallback'),
        repair: addFallback(index),
      });
    }
    if (!interaction.justification) {
      issues.push({
        finding: finding(
          'INTERACTION_DEBT', 'WARNING', interaction.id,
          'nonstandard interaction lacks a stated user-value justification',
        ),
        approval: `DECISION: justify or remove nonstandard interaction ${interaction.id}.`,
      });
    }
  });
  return issues;
}

function stateEntropy(draft: Draft): Issue[] {
  const issues: Issue[] = [];
  for (const [name, spec] of draft.components) {
    const seen = new Map<string, UIState>();
    for (const state of spec.states) {
      const row = stateRow(state);
      const key = `${row[1]}\u0000${row[2]}`;
      const earlier = seen.get(key);
      if (earlier !== undefined && earlier !== state) {
        issues.push({
          finding: finding('STATE_ENTROPY', 'BLOCKING', name, `${state} is visually/contentually identical to ${earlier}`),
        });
      }
      if (!seen.has(key)) seen.set(key, state);
    }
  }
  return issues;
}

function needState(draft: Draft, tag: string, state: UIState, scenario: string): Issue[] {
  return tagged(draft, tag)
    .filter((name) => !draft.components.get(name)?.states.includes(state))
    .map((name) => ({
      finding: finding('COUNTERFACTUAL_UX', 'BLOCKING', name, `'${scenario}': missing ${state} state`),
      repair: (d: Draft): string => {
        d.components.get(name)?.states.push(state);
        return `added ${state} to ${name}`;
      },
    }));
}

function colorRemoved(draft: Draft): Issue[] {
  const issues: Issue[] = [];
  for (const [name, spec] of draft.components) {
    for (const state of spec.states) {
      if (STATUS_STATES.has(state) && !stateRow(state)[9]) {
        issues.push({
          finding: finding('COUNTERFACTUAL_UX', 'BLOCKING', `${name}.${state}`, "'color removed': status state has no non-color channel"),
        });
      }
    }
  }
  return issues;
}

function motionRemoved(draft: Draft): Issue[] {
  const covered = draft.design_system.motion_rules.some((rule) => rule.includes('reduced-motion') || rule.includes('prefers-reduced-motion'));
  if (covered) return [];
  return [{
    finding: finding('COUNTERFACTUAL_UX', 'BLOCKING', 'design_system.motion_rules', "'motion removed': no reduced-motion rule"),
    repair: (d) =>
      addRule(d, 'motion_rules', 'prefers-reduced-motion: reduce disables non-essential animation; meaning never depends on motion.'),
  }];
}

function pointerUnavailable(draft: Draft): Issue[] {
  const issues: Issue[] = [];
  draft.interactions.forEach((interaction, index) => {
    if (interaction.input_modes.includes('KEYBOARD')) return;
    issues.push({
      finding: finding('COUNTERFACTUAL_UX', 'BLOCKING', interaction.id, "'pointer unavailable': no keyboard path"),
      repair: (d) => {
        const current = d.interactions[index] as InteractionSpec;
        d.interactions[index] = { ...current, input_modes: [...current.input_modes, 'KEYBOARD'] };
        return `added KEYBOARD input to ${current.id}`;
      },
    });
  });
  return issues;
}

const OVERFLOWS: ReadonlySet<string> = new Set(['WRAP', 'SCROLL', 'TRUNCATE_WITH_DISCLOSURE', 'GROW']);

function clippingRegions(draft: Draft): Issue[] {
  return draft.screens.flatMap((screen) =>
    screen.regions
      .filter((region) => !OVERFLOWS.has(region.overflow))
      .map((region) => ({
        finding: finding('COUNTERFACTUAL_UX', 'BLOCKING', `${screen.id}.${region.id}`, "'copy +200%': region clips content"),
      })),
  );
}

function counterfactual(draft: Draft, hasAi: boolean): Issue[] {
  return [
    ...colorRemoved(draft),
    ...motionRemoved(draft),
    ...pointerUnavailable(draft),
    ...clippingRegions(draft),
    ...needState(draft, 'data', 'EMPTY', 'data empty'),
    ...needState(draft, 'data', 'LOADING', 'network degraded'),
    ...needState(draft, 'data', 'OFFLINE', 'network degraded'),
    ...needState(draft, 'action', 'DISABLED', 'permission denied'),
    ...(hasAi ? needState(draft, 'ai', 'UNAVAILABLE', 'AI unavailable') : []),
    ...(hasAi ? needState(draft, 'ai', 'DEGRADED', 'AI unavailable') : []),
  ];
}

function resetSpacing(screenIndex: number, regionIndex: number): (draft: Draft) => string {
  return (draft) => {
    const screen = draft.screens[screenIndex];
    const region = screen?.regions[regionIndex];
    if (screen === undefined || region === undefined) throw new Error('layout repair target is gone');
    screen.regions[regionIndex] = { ...region, spacing_token: 'semantic.space.stack' };
    return `reset ${region.id} spacing to semantic.space.stack`;
  };
}

function layoutGrammar(draft: Draft, tokenPaths: ReadonlySet<string>): Issue[] {
  const issues: Issue[] = [];
  draft.screens.forEach((screen, screenIndex) => {
    screen.regions.forEach((region, index) => {
      if (tokenPaths.has(region.spacing_token)) return;
      issues.push({
        finding: finding(
          'LAYOUT_GRAMMAR', 'BLOCKING', `${screen.id}.${region.id}`,
          `spacing token '${region.spacing_token}' is not a defined token`,
        ),
        repair: resetSpacing(screenIndex, index),
      });
    });
  });
  return issues;
}

/** Python `repr(list[str])` for the traceability message. */
function reprStrings(values: readonly string[]): string {
  return `[${values.map((value) => `'${value}'`).join(', ')}]`;
}

function traceability(draft: Draft, tokenPaths: ReadonlySet<string>): Issue[] {
  const issues: Issue[] = [];
  for (const screen of draft.screens) {
    for (const name of screen.components.filter((n) => !draft.components.has(n))) {
      issues.push({ finding: finding('TRACEABILITY', 'BLOCKING', `screens.${screen.id}`, `references undefined component ${name}`) });
    }
  }
  for (const [name, spec] of draft.components) {
    const missing = componentTokens(spec.template.tags).filter((t) => !tokenPaths.has(t));
    if (missing.length > 0) {
      issues.push({ finding: finding('TRACEABILITY', 'BLOCKING', name, `references undefined tokens ${reprStrings(missing)}`) });
    }
  }
  return issues;
}

function contrastIssue(check: ContrastCheck): Issue {
  const essential =
    check.wcag_requirement === 'AAA_NORMAL' || check.wcag_requirement === 'NON_TEXT' ||
    check.foreground.endsWith('on-accent') || check.foreground.endsWith('foreground');
  return {
    finding: finding(
      'CONTRAST', essential ? 'BLOCKING' : 'WARNING', `${check.foreground} on ${check.background}`,
      `${floatRepr(check.wcag_ratio)}:1 fails ${check.wcag_requirement} (WCAG 2.2); ` +
        `APCA Lc ${floatRepr(check.apca_lc_advisory)} reported as advisory only`,
    ),
    approval:
      `DECISION: token pair ${check.foreground}/${check.background} fails WCAG 2.2 ` +
      `${check.wcag_requirement}; adjust the palette.`,
  };
}

/** Every token path (a node with `$value`) in a DTCG document. */
export function tokenPaths(document: Readonly<Record<string, unknown>>, prefix = ''): Set<string> {
  const paths = new Set<string>();
  for (const [key, value] of Object.entries(document)) {
    if (key.startsWith('$') || typeof value !== 'object' || value === null || Array.isArray(value)) continue;
    const path = prefix ? `${prefix}.${key}` : key;
    const node = value as Record<string, unknown>;
    if (Object.hasOwn(node, '$value')) paths.add(path);
    else for (const nested of tokenPaths(node, path)) paths.add(nested);
  }
  return paths;
}

function runEngines(draft: Draft, tokenSystem: TokenSystemSpec, request: RequestText, hasAi: boolean): Issue[] {
  const paths = tokenPaths(tokenSystem.document);
  return [
    ...antiGeneric(draft, request),
    ...salience(draft),
    ...interactionDebt(draft),
    ...stateEntropy(draft),
    ...counterfactual(draft, hasAi),
    ...layoutGrammar(draft, paths),
    ...traceability(draft, paths),
    ...tokenSystem.contrast.filter((check) => !check.passes).map(contrastIssue),
  ];
}

export interface EvaluationInput {
  readonly draft: Draft;
  readonly tokenSystem: TokenSystemSpec;
  readonly requestText: RequestText;
  readonly hasAi: boolean;
}

function record(issues: readonly Issue[], recorded: Map<string, EvaluationFinding>, state: EvaluationState): void {
  for (const issue of issues) {
    const key = findingKey(issue.finding);
    if (!recorded.has(key)) recorded.set(key, issue.finding);
    if (issue.approval && !state.approval_required.includes(issue.approval)) state.approval_required.push(issue.approval);
  }
}

function applyRepairs(issues: readonly Issue[], input: EvaluationInput, recorded: Map<string, EvaluationFinding>): void {
  for (const issue of issues) {
    const action = issue.repair?.(input.draft) ?? null;
    const key = findingKey(issue.finding);
    recorded.set(key, { ...(recorded.get(key) as EvaluationFinding), repaired: true, repair_action: action });
  }
}

/** Python `evaluate_and_repair`: run the engines, repair what is true by construction, at most 3 passes. */
export function evaluateAndRepair(input: EvaluationInput): EvaluationState {
  const state: EvaluationState = { findings: [], iterations: 0, approval_required: [] };
  const recorded = new Map<string, EvaluationFinding>();
  const run = (): Issue[] => runEngines(input.draft, input.tokenSystem, input.requestText, input.hasAi);
  for (let pass = 0; pass <= MAX_REPAIR_ITERATIONS; pass += 1) {
    const issues = run();
    record(issues, recorded, state);
    const repairable = issues.filter((issue) => issue.repair !== undefined);
    if (repairable.length === 0 || state.iterations >= MAX_REPAIR_ITERATIONS) break;
    state.iterations += 1;
    applyRepairs(repairable, input, recorded);
  }
  // Anything the final pass still reports is unrepaired, whatever earlier passes did.
  const final = new Set(run().map((issue) => findingKey(issue.finding)));
  for (const [key, found] of recorded) if (final.has(key) && found.repaired) recorded.set(key, { ...found, repaired: false });
  state.findings = [...recorded.values()].sort(
    (a, b) => compareCodePoints(a.engine, b.engine) || compareCodePoints(a.subject, b.subject) || compareCodePoints(a.message, b.message),
  );
  return state;
}

/** Exposed so a draft can be built from a component name (Python `_COMPONENTS[name]`). */
export { componentTemplate };
