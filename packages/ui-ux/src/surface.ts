/** Surface inference (Python `infer_surface`): the explicit mode, else the brief's own words. */
import { pyWordSearch } from './python';
import type { UIUXRequest } from './models';
import type { Assumption, SurfaceMode } from './types';

export const SURFACE_KEYWORDS: ReadonlyArray<readonly [SurfaceMode, readonly string[]]> = [
  ['AI_INTERFACE', ['assistant', 'chat', 'copilot', 'ai interface', 'agent console', 'conversational']],
  ['DASHBOARD', ['dashboard', 'analytics', 'kpi', 'metrics', 'reporting', 'monitoring']],
  ['FORM_FLOW', ['checkout', 'signup', 'sign up', 'registration', 'application form', 'wizard', 'onboarding flow', 'booking']],
  ['LANDING_PAGE', ['landing', 'homepage', 'home page', 'marketing site', 'website', 'launch page', 'microsite']],
  ['APPLICATION', ['app', 'application', 'saas', 'tool', 'workspace', 'portal', 'platform', 'admin']],
];

function inferredFrom(mode: SurfaceMode, label: string): Assumption {
  return {
    id: 'assume.surface',
    statement: `Surface treated as ${mode}.`,
    reason: `Inferred from the ${label}; no explicit surface was given.`,
    impact: 'Selects the screen/flow template and principle set.',
  };
}

const DEFAULT_ASSUMPTION: Assumption = {
  id: 'assume.surface',
  statement: 'Surface treated as APPLICATION.',
  reason: 'No surface was given and the request wording did not identify one.',
  impact: 'Default application template; confirm before implementation.',
};

/**
 * The surface hint (e.g. a brief's product type) is the more deliberate
 * statement, so it is consulted on its own before the free-text description.
 */
export function inferSurface(request: UIUXRequest): [SurfaceMode, Assumption | null] {
  if (request.surface !== null) return [request.surface, null];
  const sources: ReadonlyArray<readonly [string, string]> = [
    ['surface hint', request.surface_hint],
    ['request wording', [request.purpose, request.primary_task].join(' ')],
  ];
  for (const [label, text] of sources) {
    const lowered = text.toLowerCase();
    for (const [mode, words] of SURFACE_KEYWORDS) {
      if (pyWordSearch(words, lowered)) return [mode, inferredFrom(mode, label)];
    }
  }
  return ['APPLICATION', { ...DEFAULT_ASSUMPTION }];
}
