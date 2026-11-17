/** Applying principle effects to the draft (Python `_apply_effect`, `_apply_principles`). */
import { addUnique, slug } from './catalog';
import { sortedStrings, uniqueInOrder } from './python';
import type {
  A11yRequirement,
  A11yVerification,
  Draft,
  DesignSystemKey,
  Effect,
  InteractionSpec,
  Principle,
  PrincipleApplication,
  ResponsiveTransform,
  UIUXDesignIR,
} from './types';

const RULE_KEYS: Readonly<Record<string, DesignSystemKey>> = {
  pattern: 'patterns',
  state_rule: 'state_rules',
  content_rule: 'content_rules',
  motion_rule: 'motion_rules',
};

const TRANSFORMS: ReadonlySet<string> = new Set([
  'WRAP', 'STACK', 'REORDER', 'COLLAPSE', 'SCROLL', 'MENU', 'DRAWER', 'FULL_WIDTH', 'PRIORITY_REDUCTION',
]);

/** Python `_a11y_verification`. */
export function a11yVerification(criterion: string): A11yVerification {
  if (criterion.includes('1.4.3') || criterion.includes('1.4.11')) return 'VERIFIED_STATIC';
  if (['4.1.2', '1.3.1', '3.3.1'].some((sc) => criterion.includes(sc))) return 'REQUIRES_ASSISTIVE_TECH';
  return 'REQUIRES_HUMAN_EVALUATION';
}

function applyRule(draft: Draft, effect: Effect): string[] {
  const key = RULE_KEYS[effect.kind] as DesignSystemKey;
  return addUnique(draft.design_system[key], effect.value) ? [`design_system.${key}`] : [];
}

function applyA11y(draft: Draft, effect: Effect): string[] {
  if (draft.a11y.some((item) => item.criterion === effect.target)) return [];
  const requirement: A11yRequirement = {
    id: `a11y.${slug(effect.target)}`,
    criterion: effect.target,
    rule: effect.value,
    verification: a11yVerification(effect.target),
  };
  draft.a11y.push(requirement);
  return ['accessibility.requirements'];
}

function applyComponentState(draft: Draft, effect: Effect): string[] {
  const tag = effect.target.replace(/^\*+/, '');
  const changes: string[] = [];
  for (const [name, spec] of draft.components) {
    if (!spec.template.tags.includes(tag) || effect.state === null || spec.states.includes(effect.state)) continue;
    spec.states.push(effect.state);
    changes.push(`components.${name}.states`);
  }
  return changes;
}

function applyResponsive(draft: Draft, effect: Effect): string[] {
  if (!TRANSFORMS.has(effect.value)) throw new Error(`'${effect.value}' is not a valid ResponsiveTransform`);
  const transform = effect.value as ResponsiveTransform;
  const changes: string[] = [];
  for (const screen of draft.screens) {
    screen.regions.forEach((region, index) => {
      if (!region.id.includes(effect.target) || region.responsive_transform === transform) return;
      screen.regions[index] = { ...region, responsive_transform: transform };
      changes.push(`screens.${screen.id}.regions.${region.id}.responsive_transform`);
    });
  }
  return changes;
}

function applyGenome(draft: Draft, effect: Effect): string[] {
  const key = effect.target as keyof typeof draft.genome;
  if (draft.genome[key] === effect.value) return [];
  draft.genome = { ...draft.genome, [key]: effect.value };
  return [`design_genome.${effect.target}`];
}

function applyInteractionInput(draft: Draft, effect: Effect): string[] {
  const changes: string[] = [];
  draft.interactions.forEach((interaction, index) => {
    const mode = effect.value as InteractionSpec['input_modes'][number];
    if (interaction.input_modes.includes(mode)) return;
    draft.interactions[index] = { ...interaction, input_modes: [...interaction.input_modes, mode] };
    changes.push(`interactions.${interaction.id}.input_modes`);
  });
  return changes;
}

/** Apply one effect; returns the IR paths it changed (empty when it changed nothing). */
export function applyEffect(draft: Draft, effect: Effect): string[] {
  if (effect.kind in RULE_KEYS) return applyRule(draft, effect);
  switch (effect.kind) {
    case 'a11y': return applyA11y(draft, effect);
    case 'component_state': return applyComponentState(draft, effect);
    case 'responsive': return applyResponsive(draft, effect);
    case 'perf': return addUnique(draft.performance_requirements, effect.value) ? ['performance.requirements'] : [];
    case 'genome': return applyGenome(draft, effect);
    case 'interaction_input': return applyInteractionInput(draft, effect);
    default: throw new Error(`unknown principle effect kind '${effect.kind}'`);
  }
}

function application(principle: Principle, draft: Draft, changes: readonly string[]): PrincipleApplication {
  const matched = sortedStrings(principle.triggers.filter((trigger) => draft.features.has(trigger)));
  return {
    id: principle.id,
    name: principle.name,
    family: principle.family,
    user_problem: principle.user_problem,
    relevance: `triggered by [${matched.map((word) => `'${word}'`).join(', ')}]`,
    application: principle.application,
    tradeoff: principle.tradeoff,
    a11y_effect: principle.a11y_effect,
    responsive_effect: principle.responsive_effect,
    implementation_effect: principle.implementation_effect,
    changes: uniqueInOrder(changes),
  };
}

/** A principle that relevant but changed nothing is not "applied", however relevant it sounds. */
export function applyPrinciples(draft: Draft, principles: readonly Principle[]): UIUXDesignIR['principles_applied'] {
  const applied: PrincipleApplication[] = [];
  for (const principle of principles) {
    const changes = principle.effects.flatMap((effect) => applyEffect(draft, effect));
    if (changes.length > 0) applied.push(application(principle, draft, changes));
  }
  return applied;
}
