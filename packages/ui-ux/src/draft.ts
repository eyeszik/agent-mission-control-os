/**
 * Building the working draft from the request (the first half of Python
 * `compile_uiux`): required-field assumptions, the surface template, components
 * and interactions.
 */
import { componentTemplate, slug, surfaceTemplate } from './catalog';
import { intersect, pyStrip, pyWordSearch, uniqueInOrder } from './python';
import type { UIUXRequest } from './models';
import type {
  A11yRequirement,
  Assumption,
  Draft,
  DraftComponent,
  DraftScreen,
  InteractionSpec,
  SurfaceMode,
  SurfaceTemplate,
  Unknown,
} from './types';

/** The request's required fields after `need()`: provided values, else a recorded assumption. */
export interface ProductFields {
  readonly purpose: string;
  readonly primary_user: string;
  readonly primary_task: string;
  readonly business_goal: string;
}

export interface Ledger {
  readonly assumptions: Assumption[];
  readonly unknowns: Unknown[];
}

function need(ledger: Ledger, value: string, key: string, question: string, fallback: string): string {
  if (pyStrip(value)) return pyStrip(value);
  ledger.unknowns.push({ id: `unknown.${key}`, question, blocks: false });
  ledger.assumptions.push({
    id: `assume.${key}`,
    statement: `${key.replace(/_/g, ' ')}: ${fallback}`,
    reason: 'Not provided in the request.',
    impact: 'Treated as provisional until confirmed.',
  });
  return fallback;
}

export function productFields(request: UIUXRequest, brandName: string, ledger: Ledger): ProductFields {
  const purpose = need(ledger, request.purpose, 'purpose', 'What is this interface for?',
    `Help ${brandName}'s users complete their primary task`);
  const primaryUser = need(ledger, request.primary_user, 'primary_user', 'Who is the primary user?',
    'The product\'s primary audience (unspecified)');
  const primaryTask = need(ledger, request.primary_task, 'primary_task',
    'What single task must the interface make easy?', purpose);
  const businessGoal = need(ledger, request.business_goal, 'business_goal',
    'What business outcome does this serve?', 'Unstated; do not invent metrics for it');
  return { purpose, primary_user: primaryUser, primary_task: primaryTask, business_goal: businessGoal };
}

/** Any AI output anywhere needs exactly one truthful provenance scope. */
function injectAiEnvelope(template: SurfaceTemplate): void {
  const screen = template.screens.find((s) => s.priority === 'P0' && !s.components.includes('AITrustEnvelope'));
  (screen?.components as string[] | undefined)?.push('AITrustEnvelope');
}

function componentNames(template: SurfaceTemplate): string[] {
  return uniqueInOrder(template.screens.flatMap((screen) => screen.components));
}

function draftComponents(names: readonly string[], existing: ReadonlySet<string>): Map<string, DraftComponent> {
  return new Map(
    names.map((name): [string, DraftComponent] => [
      name,
      {
        template: componentTemplate(name),
        states: [...componentTemplate(name).states],
        status: existing.has(name.toLowerCase()) ? 'EXTEND' : 'PROPOSED',
      },
    ]),
  );
}

const INTERACTIVE_TAGS = ['action', 'field', 'nav', 'filter'];

function activateInteraction(name: string, tags: readonly string[]): InteractionSpec {
  return {
    id: `ix.${slug(name)}.activate`,
    component_ref: name,
    trigger: tags.includes('field') ? 'enter value' : 'activate',
    input_modes: ['POINTER', 'TOUCH', 'SCREEN_READER'],
    feedback: 'PRESSED within one frame; outcome via state change and status text',
    standard: true,
    justification: null,
    fallback: null,
  };
}

function reorderInteraction(names: readonly string[], text: string): InteractionSpec {
  const target = names.find((n) => componentTemplate(n).tags.includes('data')) ?? (names[0] as string);
  return {
    id: `ix.${slug(target)}.reorder`,
    component_ref: target,
    trigger: 'drag to reorder',
    input_modes: ['POINTER', 'TOUCH'],
    feedback: 'lifted item + drop target outline',
    standard: false,
    justification: text.toLowerCase().includes('reorder') ? 'Requested reordering of items by direct manipulation.' : null,
    fallback: null,
  };
}

function interactionsFor(names: readonly string[], text: string): InteractionSpec[] {
  const interactions = names
    .filter((name) => intersect(componentTemplate(name).tags, new Set(INTERACTIVE_TAGS)).length > 0)
    .map((name) => activateInteraction(name, componentTemplate(name).tags));
  if (pyWordSearch(['drag', 'reorder', 'kanban'], text.toLowerCase())) interactions.push(reorderInteraction(names, text));
  return interactions;
}

const BASE_A11Y: readonly A11yRequirement[] = [
  { id: 'a11y.contrast', criterion: 'WCAG 2.2 SC 1.4.3 Contrast (Minimum)', rule: 'Text meets 4.5:1 (AA); body text targets 7:1 (AAA) where tokens allow.', verification: 'VERIFIED_STATIC' },
  { id: 'a11y.non-text-contrast', criterion: 'WCAG 2.2 SC 1.4.11 Non-text Contrast', rule: 'Focus indicators, control borders and meaningful graphics reach 3:1.', verification: 'VERIFIED_STATIC' },
  { id: 'a11y.name-role-value', criterion: 'WCAG 2.2 SC 4.1.2 Name, Role, Value', rule: 'Every control exposes an accessible name, role, and state.', verification: 'REQUIRES_ASSISTIVE_TECH' },
  { id: 'a11y.use-of-color', criterion: 'WCAG 2.2 SC 1.4.1 Use of Color', rule: 'Status and state are never conveyed by color alone.', verification: 'REQUIRES_HUMAN_EVALUATION' },
  { id: 'a11y.forced-colors', criterion: 'Forced colors (Windows High Contrast)', rule: 'Under forced-colors: active, states keep icon + text channels and borders use system colors.', verification: 'REQUIRES_HUMAN_EVALUATION' },
  { id: 'a11y.resize', criterion: 'WCAG 2.2 SC 1.4.4 Resize Text', rule: 'Text resizes to 200% without loss of content or function.', verification: 'REQUIRES_HUMAN_EVALUATION' },
];

const BASE_PERFORMANCE: readonly string[] = [
  'Prefer semantic HTML and CSS over client JavaScript for layout and state styling.',
  'Keep client components at the interaction boundary; render static content on the server.',
  'Subscribe to the smallest stable store slice a component needs.',
];

export interface DraftInput {
  readonly mode: SurfaceMode;
  readonly features: ReadonlySet<string>;
  readonly text: string;
  readonly existingComponents: readonly string[];
  readonly hasAi: boolean;
  readonly assumptions: Assumption[];
}

export interface BuiltDraft {
  readonly draft: Draft;
  readonly template: SurfaceTemplate;
  readonly componentNames: readonly string[];
}

function draftScreens(template: SurfaceTemplate): DraftScreen[] {
  return template.screens.map((s) => ({
    id: s.id, name: s.name, purpose: s.purpose, priority: s.priority, regions: [...s.regions], components: [...s.components],
  }));
}

export function buildDraft(input: DraftInput): BuiltDraft {
  const template = surfaceTemplate(input.mode);
  if (input.hasAi && input.mode !== 'AI_INTERFACE') injectAiEnvelope(template);
  const names = componentNames(template);
  const existing = new Set(input.existingComponents.map((item) => pyStrip(item).toLowerCase()));
  const draft: Draft = {
    mode: input.mode,
    features: input.features,
    screens: draftScreens(template),
    components: draftComponents(names, existing),
    interactions: interactionsFor(names, input.text),
    genome: {
      hierarchy: '', density: 'MEDIUM', geometry: '', typography: '', color: '', material: '', motion: '',
      interaction: '', signature: '', genome_hash: '',
    },
    design_system: { patterns: [], state_rules: [], content_rules: [], motion_rules: [] },
    a11y: BASE_A11Y.map((item) => ({ ...item })),
    performance_requirements: [...BASE_PERFORMANCE],
    assumptions: input.assumptions,
    approval_required: [],
  };
  return { draft, template, componentNames: names };
}
