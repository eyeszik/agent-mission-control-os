/**
 * Selective, deterministic UX principle routing (twin of `ui_ux/principles.py`).
 * A principle is data: the features that make it relevant and the concrete
 * edits it makes to the spec. The catalog itself is `principles-data.ts`.
 */
import { FEATURE_KEYWORDS, PRINCIPLE_CATALOG } from './principles-data';
import { sortedStrings } from './python';
import type { Principle, SurfaceMode } from './types';

export { FEATURE_KEYWORDS, PRINCIPLE_CATALOG as CATALOG };

const WORD = /[a-z0-9][a-z0-9\- ]*/g;

export interface FeatureOptions {
  readonly aiFeatures: boolean | null;
  readonly rtl: boolean;
}

function haystackOf(text: string): string {
  return ` ${(text.toLowerCase().match(WORD) ?? []).join(' ')} `;
}

function keywordFeatures(haystack: string): string[] {
  return Object.entries(FEATURE_KEYWORDS)
    .filter(([, words]) => words.some((word) => haystack.includes(` ${word} `) || haystack.includes(` ${word}s `)))
    .map(([feature]) => feature);
}

const SURFACE_FEATURES: Readonly<Partial<Record<SurfaceMode, readonly string[]>>> = {
  DASHBOARD: ['data', 'high_density'],
  FORM_FLOW: ['forms', 'multi_step'],
  APPLICATION: ['stateful'],
  LANDING_PAGE: ['persuasion'],
};

/** Python `extract_features`: the sorted feature set a request implies. */
export function extractFeatures(mode: SurfaceMode, text: string, options: FeatureOptions): ReadonlySet<string> {
  const features = new Set<string>([`surface:${mode}`, ...keywordFeatures(haystackOf(text))]);
  for (const feature of SURFACE_FEATURES[mode] ?? []) features.add(feature);
  // An explicit flag beats keyword inference in both directions...
  if (options.aiFeatures === true) features.add('ai');
  else if (options.aiFeatures === false) features.delete('ai');
  // ...except that an AI interface is AI output by definition.
  if (mode === 'AI_INTERFACE') {
    features.add('ai');
    features.add('realtime');
  }
  if (options.rtl) features.add('rtl');
  features.add('interactive');
  return new Set(sortedStrings(features));
}

/** Python `select_principles`: catalog order, any-of trigger match. */
export function selectPrinciples(features: ReadonlySet<string>): Principle[] {
  return PRINCIPLE_CATALOG.filter((principle) => principle.triggers.some((trigger) => features.has(trigger)));
}
