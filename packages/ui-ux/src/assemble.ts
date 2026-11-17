/**
 * Turning the repaired draft into IR sections (the second half of Python
 * `compile_uiux`). Each function builds one section of `UIUXDesignIR`.
 */
import { floatRepr } from '@amc/kernel';
import { componentTokens, slug, stateRow } from './catalog';
import { compareCodePoints, sortedStrings } from './python';
import type {
  ComponentSpecs,
  StateSpecs,
} from './assemble-types';
import type { UIUXRequest } from './models';
import type { Draft, DraftScreen, LayoutRegion, Territory, TokenSystemSpec, UIState, UIUXDesignIR } from './types';

type Ir = UIUXDesignIR;

const joinStates = (draft: Draft, screen: DraftScreen): string =>
  sortedStrings(new Set(screen.components.flatMap((name) => draft.components.get(name)?.states ?? []))).join(', ');

export interface ScreenContext {
  readonly draft: Draft;
  readonly request: UIUXRequest;
  readonly primaryTask: string;
  readonly selected: Territory;
}

function screenTrace(ctx: ScreenContext, screen: DraftScreen): Ir['screens'][number]['trace'] {
  const p0 = screen.components.slice(0, 3).join(', ');
  const { draft, request } = ctx;
  const interactions = draft.interactions.filter((i) => screen.components.includes(i.component_ref)).map((i) => i.id);
  return {
    user_task: ctx.primaryTask,
    content: `${screen.purpose}; content requirements: ${request.content_requirements.join(', ') || 'none stated'}`,
    contract: `async state contract for ${p0}`,
    component: p0,
    token: (screen.regions[0] as LayoutRegion).spacing_token,
    state: joinStates(draft, screen),
    interaction: interactions.join(', ') || 'read-only screen',
    responsive_rule: screen.regions.map((r) => `${r.id}:${r.responsive_transform}`).join(', '),
    a11y_rule: sortedStrings(new Set(draft.a11y.map((req) => req.id))).slice(0, 4).join(', '),
    performance_rule: draft.performance_requirements[0] as string,
    implementation_path: `screens/${screen.id} -> components/{${p0}}`,
    test: `e2e: ${screen.id} primary task, keyboard-only, 320px reflow`,
    evidence: `spec-level (compiler ${ctx.selected.id}); implementation evidence pending`,
  };
}

export function buildScreens(ctx: ScreenContext): Ir['screens'] {
  return ctx.draft.screens.map((screen) => ({
    id: screen.id,
    name: screen.name,
    purpose: screen.purpose,
    user_task: ctx.primaryTask,
    priority: screen.priority,
    regions: screen.regions,
    components: screen.components,
    trace: screenTrace(ctx, screen),
  }));
}

export function buildComponents(draft: Draft): ComponentSpecs {
  return [...draft.components].map(([name, spec]) => ({
    id: `cmp.${slug(name)}`,
    name,
    semantic_role: spec.template.role,
    purpose: spec.template.purpose,
    tokens: componentTokens(spec.template.tags),
    states: spec.states,
    interactions: draft.interactions.filter((i) => i.component_ref === name).map((i) => i.id),
    a11y: [...spec.template.a11y],
    implementation: spec.status,
  }));
}

export function buildStates(draft: Draft): StateSpecs {
  return [...draft.components].flatMap(([name, spec]) => spec.states.map((state) => stateSpec(name, state)));
}

function stateSpec(component: string, state: UIState): StateSpecs[number] {
  const row = stateRow(state);
  return {
    component_ref: component, state, trigger: row[0], visual_delta: row[1], content_delta: row[2], semantics: row[3],
    keyboard: row[4], announcement: row[5], motion: row[6], recovery: row[7], persistence: row[8], non_color_channel: row[9],
  };
}

export function buildResponsive(draft: Draft): Ir['responsive_rules'] {
  return draft.screens.flatMap((screen) =>
    screen.regions.map((region) => ({
      region_ref: `${screen.id}.${region.id}`,
      condition: 'container inline-size < 40rem',
      transform: region.responsive_transform,
      rationale: `${region.priority} region; ${region.purpose.toLowerCase()}`,
    })),
  );
}

export function buildAccessibility(draft: Draft, tokens: TokenSystemSpec, tests: readonly string[]): Ir['accessibility'] {
  return {
    target: 'WCAG 2.2',
    requirements: [...draft.a11y].sort((a, b) => compareCodePoints(a.id, b.id)),
    predicted: [
      'Keyboard-complete flows if native elements are used as specified.',
      'Reflow at 320px given the declared region transforms.',
    ],
    verified: tokens.contrast
      .filter((c) => c.passes)
      .map((c) => `${c.foreground} on ${c.background}: ${floatRepr(c.wcag_ratio)}:1 meets ${c.wcag_requirement} (static token check)`),
    risks: tokens.contrast
      .filter((c) => !c.passes)
      .map((c) => `${c.foreground} on ${c.background}: ${floatRepr(c.wcag_ratio)}:1 fails ${c.wcag_requirement}`),
    tests_required: tests.filter((test) => ['a11y', 'e2e', 'visual'].some((prefix) => test.startsWith(prefix))),
  };
}

export function buildGenerationPrompts(screens: Ir['screens'], prefix: string): string[] {
  return screens.map((screen) => {
    const ordered = [...screen.regions].sort((a, b) => compareCodePoints(a.priority, b.priority) || b.emphasis - a.emphasis);
    const regions = ordered
      .map((r) => `${r.id} [${r.priority}, ${r.parent_layout.toLowerCase()}, ${r.responsive_transform.toLowerCase()} when narrow]`)
      .join('; ');
    return (
      `Screen '${screen.name}' (${screen.priority}): ${screen.purpose}. Regions in priority order: ${regions}` +
      `. Components: ${screen.components.join(', ')}. Use only --${prefix}-semantic-* and ` +
      `--${prefix}-component-* tokens. Every state keeps a non-color channel. ` +
      'Do not invent testimonials, logos, metrics, or AI confidence.'
    );
  });
}
