/**
 * Source-spec functional roles mapped onto the sealed RoleOS registry (twin of
 * the pure half of `agency/prompt_families/roles.py`). The 26 functional
 * responsibilities are not new runtime roles: each maps to an existing sealed
 * RoleOS skill (exact, or the nearest equivalent). Role identity grants nothing:
 * no publication, spend, secret or approval authority.
 *
 * `resolve_functional_roles` needs the RoleOS registry and stays in Python.
 */
import type { PromptFamily } from '@amc/guidance';
import type { ProductionMedium } from './models';

export interface FunctionalRoleBinding {
  readonly functional_role: string;
  readonly skill_name: string;
  readonly department: string;
  readonly match: 'EXACT' | 'NEAREST_EQUIVALENT';
}

const E = 'EXACT';
const N = 'NEAREST_EQUIVALENT';
const ROWS: ReadonlyArray<readonly [string, string, string, 'EXACT' | 'NEAREST_EQUIVALENT']> = [
  ['brand_strategist', 'brand-strategist', 'brand', E],
  ['verbal_identity_architect', 'verbal-identity-strategist', 'brand', N],
  ['messaging_architect', 'brand-narrative-strategist', 'brand', N],
  ['copywriter', 'copywriter', 'creative', E],
  ['editor', 'copy-editor', 'creative', N],
  ['UX_writer', 'ux-writer', 'creative', E],
  ['content_designer', 'information-architect', 'experience-product', N],
  ['content_strategist', 'content-strategist', 'marketing', E],
  ['research_editor', 'research-manager', 'strategy', N],
  ['SEO_strategist', 'seo-strategist', 'search-social', E],
  ['creative_director', 'creative-director', 'creative', E],
  ['art_director', 'art-director', 'creative', E],
  ['visual_identity_designer', 'brand-identity-designer', 'creative', N],
  ['graphic_designer', 'graphic-designer', 'creative', E],
  ['production_designer', 'production-designer', 'creative', E],
  ['environmental_signage_designer', 'environmental-graphic-designer', 'creative', N],
  ['motion_director', 'motion-design-director', 'production', N],
  ['storyboard_artist', 'storyboard-artist', 'creative', E],
  ['cinematographer', 'cinematographer', 'production', E],
  ['video_prompt_engineer', 'prompt-engineer', 'ai-data', N],
  ['image_prompt_engineer', 'prompt-designer', 'ai-data', N],
  ['prompt_system_architect', 'prompt-architect', 'ai-data', N],
  ['brand_guardian', 'brand-governance-manager', 'brand', N],
  ['accessibility_reviewer', 'accessibility-qa-analyst', 'technology', N],
  ['rights_claims_reviewer', 'rights-and-clearances-manager', 'operations', N],
  ['analytics_experiment_lead', 'experimentation-lead', 'growth-media', N],
];

export const FUNCTIONAL_ROLE_BINDINGS: ReadonlyMap<string, FunctionalRoleBinding> = new Map(
  ROWS.map(([functional_role, skill_name, department, match]) => [functional_role, { functional_role, skill_name, department, match }]),
);

const BY_FAMILY: Readonly<Record<PromptFamily, readonly string[]>> = {
  COPY: ['copywriter', 'editor'],
  IMAGE: ['art_director', 'image_prompt_engineer'],
  PRINT: ['graphic_designer', 'production_designer'],
  PRESENTATION: ['graphic_designer'],
  VIDEO: ['cinematographer', 'video_prompt_engineer'],
  STORYBOARD: ['storyboard_artist'],
  MOTION: ['motion_director'],
  UI_UX: ['UX_writer', 'content_designer'],
};

/** Responsibilities a family's work order should route to (always reviewed). */
export function functionalRolesFor(family: PromptFamily, medium: ProductionMedium): string[] {
  const roles = ['prompt_system_architect', ...BY_FAMILY[family]];
  if (medium === 'SIGNAGE') roles.push('environmental_signage_designer');
  else if (medium === 'PRINT' || medium === 'MERCH') roles.push('production_designer');
  roles.push('brand_guardian', 'accessibility_reviewer', 'rights_claims_reviewer');
  return Array.from(new Set(roles));
}
