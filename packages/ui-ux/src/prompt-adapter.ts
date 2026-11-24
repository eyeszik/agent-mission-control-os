/**
 * Mapping a UIUXDesignIR onto prompt-compiler inputs (twin of
 * `ui_ux/prompt_adapter.py`). It selects the parts of the spec a generation
 * prompt needs and never dumps the whole IR into every prompt.
 *
 * Python reads attributes off the real `BrandCore` / `AssetRequirement`
 * objects; here the caller passes their plain-data shape (`BrandCoreLike`,
 * `AssetRequirementLike`), so this package does not depend on those models.
 */
import { BrandContextSchema, ValidationError, parseUiuxRequest, type BrandContext, type UIUXRequest } from './models';
import { uniqueInOrder } from './python';
import type { SurfaceMode, UIUXDesignIR } from './types';

const ASSET_TYPE_SURFACE: ReadonlyArray<readonly [readonly string[], SurfaceMode]> = [
  [['landing', 'homepage', 'website', 'marketing page', 'microsite'], 'LANDING_PAGE'],
  [['dashboard', 'analytics', 'report'], 'DASHBOARD'],
  [['assistant', 'chat', 'copilot', 'ai interface'], 'AI_INTERFACE'],
  [['checkout', 'signup', 'onboarding', 'form', 'wizard'], 'FORM_FLOW'],
  [['app', 'application', 'screen', 'ui', 'product', 'tool', 'portal'], 'APPLICATION'],
];

export function surfaceForAssetType(assetType: string): SurfaceMode | null {
  const lowered = assetType.toLowerCase();
  for (const [words, mode] of ASSET_TYPE_SURFACE) if (words.some((word) => lowered.includes(word))) return mode;
  return null;
}

/** The slice of canonical BrandCore the compiler may read. Never written. */
export interface BrandCoreLike {
  readonly brand_name: string;
  readonly positioning_essence: string | null;
  readonly voice: { readonly tone_attributes: readonly string[] };
  readonly typography_direction: string | null;
  readonly imagery_style: string | null;
  readonly motion: { readonly pace: string | null; readonly reduced_motion_fallback: string | null };
  readonly color_story: ReadonlyArray<{ readonly reference_hex?: string | null }>;
}

export interface AssetRequirementLike {
  readonly asset_id: string;
  readonly asset_type: string;
  readonly objective: string;
  readonly audience: string;
  readonly business_reason: string | null;
  readonly content_requirements: readonly string[];
  readonly quality_constraints: readonly string[];
  readonly negative_constraints: readonly string[];
}

/**
 * `ColorRole.reference_hex` is optional reference data on a qualitative color
 * story; when every role lacks it, the palette stays unresolved, never guessed.
 */
export function brandContextFromCore(brand: BrandCoreLike): BrandContext {
  const palette = brand.color_story.map((role) => role.reference_hex).filter((hex): hex is string => Boolean(hex));
  const result = BrandContextSchema.safeParse({
    brand_name: brand.brand_name,
    positioning: brand.positioning_essence,
    tone_attributes: [...brand.voice.tone_attributes],
    typography_direction: brand.typography_direction,
    imagery_style: brand.imagery_style,
    motion_pace: brand.motion.pace,
    reduced_motion_fallback: brand.motion.reduced_motion_fallback,
    palette_hex: palette,
    palette_source: palette.length > 0 ? 'BRAND_CORE' : 'COMPILER_DEFAULT',
  });
  if (result.success) return result.data;
  throw new ValidationError('BrandContext', result.error.issues.map((issue) => issue.message));
}

export function requestFromAssetRequirement(requirement: AssetRequirementLike, brand: BrandCoreLike): UIUXRequest {
  return parseUiuxRequest({
    project_ref: requirement.asset_id,
    surface: surfaceForAssetType(requirement.asset_type),
    surface_hint: requirement.asset_type,
    purpose: requirement.objective,
    primary_user: requirement.audience,
    primary_task: requirement.objective,
    business_goal: requirement.business_reason || '',
    content_requirements: [...requirement.content_requirements],
    constraints: [...requirement.quality_constraints],
    negative_constraints: [...requirement.negative_constraints],
    brand: brandContextFromCore(brand),
  });
}

const prefixed = (lines: readonly string[]): string[] => lines.map((line) => `UI/UX compiler: ${line}`);

function interactionLine(i: UIUXDesignIR['interactions'][number]): string {
  const fallback = i.fallback ? `; fallback: ${i.fallback}` : '';
  return `UI/UX compiler: ${i.component_ref} ${i.trigger} via ${i.input_modes.join(', ')}; feedback: ${i.feedback}${fallback}`;
}

function unresolved(ir: UIUXDesignIR): string[] {
  return ir.evaluation
    .filter((f) => !f.repaired && f.severity !== 'INFO')
    .map((f) => `UI/UX compiler: unresolved ${f.engine} — ${f.subject}: ${f.message}`);
}

/** Concise, deduplicated directives keyed by the prompt compiler's bucket names. */
export function directiveBuckets(ir: UIUXDesignIR): Record<string, string[]> {
  const buckets: Record<string, string[]> = {
    composition: [
      `UI/UX compiler: direction — ${ir.selected_direction}`,
      `UI/UX compiler: genome hierarchy — ${ir.design_genome.hierarchy}; density ${ir.design_genome.density}`,
      ...prefixed(ir.generation_prompts),
    ],
    interaction: [...prefixed(ir.design_system.patterns), ...ir.interactions.map(interactionLine)],
    accessibility: ir.accessibility.requirements.map(
      (req) => `UI/UX compiler: ${req.criterion} — ${req.rule} [${req.verification}]`,
    ),
    tokens: [
      `UI/UX compiler: tokens are DTCG 2025.10, tiers ${ir.tokens.tiers.join('/')}, CSS prefix --${ir.tokens.css_prefix}-; ` +
        'consumers reference semantic/component tokens only.',
      `UI/UX compiler: palette — ${ir.tokens.palette_resolution}`,
    ],
    motion: prefixed(ir.design_system.motion_rules),
    engineering: [
      ...prefixed(ir.performance.requirements),
      ...ir.implementation_mapping.contracts.map((c) => `UI/UX compiler: contract ${c}`),
    ],
    quality: [...prefixed(ir.design_system.state_rules), ...prefixed(ir.design_system.content_rules), ...unresolved(ir)],
    governance: [
      ...ir.approval_required.map((item) => `UI/UX compiler: approval — ${item}`),
      ...[...ir.ai_trust.provenance_rules, ...ir.ai_trust.uncertainty_rules].map((rule) => `UI/UX compiler: AI trust — ${rule}`),
    ],
  };
  return Object.fromEntries(Object.entries(buckets).map(([key, values]) => [key, uniqueInOrder(values)]));
}

export function serializeSpecSection(ir: UIUXDesignIR): string[] {
  return [
    '## UI/UX design specification (compiled)',
    `- Surface: ${ir.mode}; platform ${ir.product_model.platform}; terminal ${ir.terminal}`,
    `- Primary user: ${ir.product_model.primary_user}`,
    `- Primary task: ${ir.product_model.primary_task}`,
    `- IA: ${ir.information_architecture.primary_nav.map((item) => `${item.label} (${item.priority})`).join(', ')}`,
    `- Flows: ${ir.flows.map((flow) => `${flow.name} -> ${flow.success_signal}`).join('; ')}`,
    `- Components: ${ir.components.map((component) => component.name).join(', ')}`,
    `- Spec hash: ${ir.spec_hash}`,
    '',
  ];
}
