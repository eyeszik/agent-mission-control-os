/**
 * Typed contracts for reusable prompt families (twin of
 * `agency/prompt_families/models.py`): invariants that hold across a series,
 * variation axes each instance draws from, a concept ledger that prevents
 * repetition, and a campaign anchor every derivative inherits. Instances compile
 * through the guidance prompt compiler, so every family output still ends at
 * `PROMPT_PACKAGE_READY` and inherits its claim, evidence and exact-text gates.
 *
 * Nothing in this package executes: it generates no media, creates no ads or
 * products, publishes nothing and spends nothing. Hook scores are never observed
 * performance, and a paid-media spec can never mutate a platform.
 */
import type { CanonicalFloat } from '@amc/canonical';
import {
  BRAND_CORE,
  CLAIM_SEED,
  COMPUTATION_EVIDENCE,
  INVALID,
  PROMPT_FAMILIES,
  PROVIDER_CAPABILITY,
  PRODUCTION_SPEC,
  REFERENCE_SPEC,
  SOURCE_EVIDENCE,
  defaultsOf,
  dict,
  dictEntries,
  enumOf,
  float,
  int,
  list,
  literal,
  model,
  nullable,
  pyFloat,
  pyStrip,
  refine,
  str,
  type Issues,
  type Loc,
  type Parser,
} from '@amc/guidance';

export const FAMILY_ENGINE_VERSION = 'amc-prompt-families/v1';
export const EXECUTION_STATEMENT =
  'Compiles prompt packages only: generates no media, creates no ads, creates no products, publishes nothing, spends nothing.';

/** Declared in priority order: high-level concept variables first. */
export const AXIS_PRIORITY = [
  'concept_metaphor', 'subject', 'environment', 'composition', 'perspective', 'scale', 'crop', 'graphic_device',
  'type_treatment', 'lighting', 'material', 'narrative_beat', 'motion_pattern',
] as const;
export type VariationAxis = (typeof AXIS_PRIORITY)[number];
/** The concept-level variables whose repetition makes two outputs "the same idea". */
export const SIGNATURE_AXES: readonly VariationAxis[] = ['concept_metaphor', 'composition', 'subject', 'graphic_device'];

export const PRODUCTION_MEDIA = ['DIGITAL', 'PRINT', 'SIGNAGE', 'MERCH'] as const;
export type ProductionMedium = (typeof PRODUCTION_MEDIA)[number];
export const ARTWORK_BACKGROUNDS = ['TRANSPARENT', 'SOLID', 'UNSPECIFIED'] as const;
export const LEDGER_STATUSES = ['ACCEPTED', 'REJECTED_DUPLICATE'] as const;
export type LedgerStatus = (typeof LEDGER_STATUSES)[number];
export const HOOK_STATUSES = ['CANDIDATE', 'APPROVED_FOR_TEST', 'MEASURED', 'WINNER_BY_METRIC', 'SATURATED', 'RETIRED'] as const;
export const UNKNOWN = 'UNKNOWN';

type ParsedOf<P> = P extends Parser<infer T> ? T : never;
const strings = { parse: list(str()), default: (): readonly string[] => [] };
const optText = { parse: nullable(str()), default: (): string | null => null };

export const INVARIANT_SET = model({
  brand_voice: optText,
  visual_thesis: optText,
  palette_behavior: optText,
  type_behavior: optText,
  layout_grammar: optText,
  signature_devices: strings,
  image_treatment: optText,
  material_language: optText,
  motion_behavior: optText,
  claim_limits: strings,
  logo_rules: optText,
  accessibility: strings,
});
export type InvariantSet = ParsedOf<typeof INVARIANT_SET>;

const LINE_FIELDS = [
  'brand_voice', 'visual_thesis', 'palette_behavior', 'type_behavior', 'layout_grammar', 'image_treatment',
  'material_language', 'motion_behavior', 'logo_rules',
] as const;

/** `InvariantSet.lines()`: the frozen lines every instance must carry. */
export function invariantLines(invariants: InvariantSet): string[] {
  const out: string[] = [];
  for (const name of LINE_FIELDS) {
    const value = invariants[name];
    if (value !== null && value !== '') out.push(`${name}: ${value}`);
  }
  out.push(...invariants.signature_devices.map((item) => `signature_device: ${item}`));
  out.push(...invariants.claim_limits.map((item) => `claim_limit: ${item}`));
  out.push(...invariants.accessibility.map((item) => `accessibility: ${item}`));
  return out;
}

export const CAMPAIGN_ANCHOR = model({
  campaign_id: { parse: str({ min: 1 }) },
  objective: { parse: str({ min: 1 }) },
  audience: { parse: str({ min: 1 }) },
  insight: optText,
  promise: optText,
  proof: strings,
  creative_territory: optText,
  visual_thesis: optText,
  verbal_thesis: optText,
  signature_device: optText,
  cta: optText,
  channels: strings,
  formats: strings,
  claims: strings,
  legal: strings,
  measurement: optText,
});
export type CampaignAnchor = ParsedOf<typeof CAMPAIGN_ANCHOR>;

export const PRODUCTION_TARGET = model({
  medium: { parse: enumOf(PRODUCTION_MEDIA), default: (): ProductionMedium => 'DIGITAL' },
  editable_master: {
    parse: str(),
    default: () => 'Layered editable master: live type, vector marks, linked assets, documented construction.',
  },
  export: { parse: PRODUCTION_SPEC, default: defaultsOf(PRODUCTION_SPEC) },
  vendor_profile: optText,
  print_method: optText,
  background: { parse: enumOf(ARTWORK_BACKGROUNDS), default: () => 'UNSPECIFIED' as (typeof ARTWORK_BACKGROUNDS)[number] },
});
export type ProductionTarget = ParsedOf<typeof PRODUCTION_TARGET>;

const VENDOR_CONTROLLED = ['color_space', 'resolution', 'format', 'bleed', 'safe_area'] as const;

/** Vendor-controlled fields a physical medium still needs; absent values stay UNKNOWN, never a "typical" default. */
export function unknownVendorFields(target: ProductionTarget): string[] {
  if (target.medium === 'DIGITAL') return [];
  const missing: string[] = VENDOR_CONTROLLED.filter((name) => target.export[name] === null);
  if (target.vendor_profile === null) missing.push('vendor_profile');
  if (target.medium === 'MERCH' && target.print_method === null) missing.push('print_method');
  return missing;
}

const AXIS_NAMES: readonly string[] = AXIS_PRIORITY;

function axisError(loc: Loc, issues: Issues): void {
  issues.push({ loc, type: 'enum', msg: `Input should be ${AXIS_PRIORITY.map((axis) => `'${axis}'`).join(', ')}` });
}

const variationAxes: Parser<ReadonlyMap<string, readonly string[]>> = (value, loc, issues) => {
  const entries = dictEntries(value);
  if (entries === null) {
    issues.push({ loc, type: 'dict_type', msg: 'Input should be a valid dictionary' });
    return INVALID;
  }
  const before = issues.length;
  const out = new Map<string, readonly string[]>();
  const items = list(str());
  for (const [key, raw] of entries) {
    const parsed = items(raw, [...loc, key], issues);
    if (!AXIS_NAMES.includes(key)) axisError([...loc, key, '[key]'], issues);
    else if (parsed !== INVALID) out.set(key, parsed);
  }
  if (issues.length > before) return INVALID;
  if (out.size < 1) {
    issues.push({ loc, type: 'too_short', msg: 'Dictionary should have at least 1 item after validation, not 0' });
    return INVALID;
  }
  return out;
};

const FAMILY_FIELDS = model({
  family_id: { parse: str({ min: 1, pattern: /^[a-z0-9][a-z0-9._-]*$/ }) },
  version: { parse: str({ min: 1 }) },
  niche: optText,
  business_objective: { parse: str({ min: 1 }) },
  audience: { parse: str({ min: 1 }) },
  surface_family: { parse: enumOf(PROMPT_FAMILIES) },
  asset_type: { parse: str({ min: 1 }) },
  channel: { parse: str({ min: 1 }) },
  destination: { parse: str({ min: 1 }) },
  campaign: { parse: nullable(CAMPAIGN_ANCHOR), default: (): CampaignAnchor | null => null },
  invariants: { parse: INVARIANT_SET, default: defaultsOf(INVARIANT_SET) },
  variation_axes: { parse: variationAxes },
  emotional_function: optText,
  content_requirements: strings,
  exact_text: strings,
  negative_constraints: strings,
  references: { parse: list(REFERENCE_SPEC), default: (): ReadonlyArray<ParsedOf<typeof REFERENCE_SPEC>> => [] },
  production: { parse: PRODUCTION_TARGET, default: defaultsOf(PRODUCTION_TARGET) },
  instance_count: { parse: int({ ge: 1, le: 24 }), default: () => 3 },
  // Advisory configuration from the source spec, not probabilities.
  series_consistency: { parse: float({ ge: 0, le: 1 }), default: () => pyFloat(0.7) },
  novelty_budget: { parse: float({ ge: 0, le: 1 }), default: () => pyFloat(0.3) },
});

/** `math.isclose(a, b, abs_tol=1e-9)` (the default `rel_tol=1e-9` still applies). */
function isClose(a: number, b: number): boolean {
  return Math.abs(a - b) <= Math.max(1e-9 * Math.max(Math.abs(a), Math.abs(b)), 1e-9);
}

type FamilyFields = ParsedOf<typeof FAMILY_FIELDS>;

function axesAreUsable(spec: FamilyFields): string | null {
  for (const [axis, options] of spec.variation_axes) {
    if (options.length === 0 || options.some((item) => pyStrip(item) === '')) return `variation axis ${axis} needs non-empty options`;
    if (new Set(options).size !== options.length) return `variation axis ${axis} has duplicate options`;
  }
  const total = spec.series_consistency.value + spec.novelty_budget.value;
  return isClose(total, 1) ? null : 'series_consistency and novelty_budget must sum to 1.0';
}

export const PROMPT_FAMILY_SPEC = refine(FAMILY_FIELDS, [axesAreUsable]);
export type PromptFamilySpec = ParsedOf<typeof PROMPT_FAMILY_SPEC>;

export const CONCEPT_SIGNATURE = model({
  primary_metaphor: { parse: str(), default: () => '' },
  composition: { parse: str(), default: () => '' },
  subject: { parse: str(), default: () => '' },
  graphic_device: { parse: str(), default: () => '' },
  signature_hash: { parse: str() },
});
export type ConceptSignature = ParsedOf<typeof CONCEPT_SIGNATURE>;

export const CONCEPT_LEDGER_ENTRY = model({
  family_id: { parse: str() },
  instance_id: { parse: str() },
  signature: { parse: CONCEPT_SIGNATURE },
  status: { parse: enumOf(LEDGER_STATUSES) },
  variation: { parse: dict(str()), default: (): ReadonlyMap<string, string> => new Map() },
});
export type ConceptLedgerEntry = ParsedOf<typeof CONCEPT_LEDGER_ENTRY>;

export const CONCEPT_LEDGER = model({
  entries: { parse: list(CONCEPT_LEDGER_ENTRY), default: (): readonly ConceptLedgerEntry[] => [] },
  rejected_patterns: strings,
});
export type ConceptLedger = ParsedOf<typeof CONCEPT_LEDGER>;

export interface PromptFamilyInstance {
  readonly family_id: string;
  readonly instance_id: string;
  readonly concept_thesis: string;
  readonly variation: ReadonlyMap<string, string>;
  readonly signature: ConceptSignature;
  readonly status: LedgerStatus;
  readonly repairs: readonly string[];
}

export const PERFORMANCE_OBSERVATION = model({
  metric: { parse: str({ min: 1 }) },
  value: { parse: float() },
  window_start: { parse: str({ min: 1 }) },
  window_end: { parse: str({ min: 1 }) },
  sample_size: { parse: nullable(int({ ge: 0 })), default: (): number | null => null },
  source: { parse: str({ min: 1 }) },
});
export type PerformanceObservation = ParsedOf<typeof PERFORMANCE_OBSERVATION>;

const HOOK_FIELDS = model({
  hook_id: { parse: str({ min: 1 }) },
  territory: { parse: str({ min: 1 }) },
  text: { parse: str({ min: 1 }) },
  status: { parse: enumOf(HOOK_STATUSES), default: () => 'CANDIDATE' as (typeof HOOK_STATUSES)[number] },
  creative_score: { parse: nullable(float({ ge: 0, le: 1 })), default: (): CanonicalFloat | null => null },
  approval_ref: optText,
  winner_metric: optText,
  observations: { parse: list(PERFORMANCE_OBSERVATION), default: (): readonly PerformanceObservation[] => [] },
});

type Hook = ParsedOf<typeof HOOK_FIELDS>;

/** Lifecycle rules: a hook's creative score is never observed performance. */
function hookNeedsEvidence(hook: Hook): string | null {
  const tested = ['APPROVED_FOR_TEST', 'MEASURED', 'WINNER_BY_METRIC'];
  if (tested.includes(hook.status) && (hook.approval_ref === null || hook.approval_ref === '')) {
    return `${hook.status} requires a human approval_ref for testing`;
  }
  const measured = hook.status === 'MEASURED' || hook.status === 'WINNER_BY_METRIC';
  if (measured && hook.observations.length === 0) return `${hook.status} requires at least one performance observation`;
  if (hook.status !== 'WINNER_BY_METRIC') return null;
  if (hook.winner_metric === null || hook.winner_metric === '') return 'WINNER_BY_METRIC requires the comparison metric';
  if (!hook.observations.some((item) => item.metric === hook.winner_metric)) {
    return 'WINNER_BY_METRIC requires an observation of the declared metric';
  }
  return null;
}

export const HOOK_CANDIDATE = refine(HOOK_FIELDS, [hookNeedsEvidence]);
export type HookCandidate = ParsedOf<typeof HOOK_CANDIDATE>;

/** Preconditions any future provider mutation path must satisfy. None is performed here. */
export const PAID_MEDIA_MUTATION_PRECONDITIONS: readonly string[] = [
  'resolve account',
  'resolve campaign',
  'resolve ad group',
  'resolve creative type',
  'resolve selected artwork',
  'generate and validate platform preview',
  'show the exact proposed mutation',
  'obtain explicit human confirmation',
  'write with an idempotency key',
  'read back the written object',
  'reconcile ambiguous results',
  'preserve successful intermediate ids',
  'retry only safe idempotent operations',
];

export const PAID_MEDIA_CREATIVE_SPEC = model({
  objective: { parse: str({ min: 1 }) },
  audience: { parse: str({ min: 1 }) },
  campaign_context: optText,
  hook: optText,
  title: optText,
  body: optText,
  cta: optText,
  landing_page_alignment: optText,
  image_prompt_ref: optText,
  exact_artwork_ref: optText,
  claims: strings,
  disclosures: strings,
  measurement_intent: optText,
  execution: { parse: literal('SPEC_ONLY' as const), default: () => 'SPEC_ONLY' as const },
  platform_mutation: { parse: literal(false as const), default: () => false as const },
});
export type PaidMediaCreativeSpec = ParsedOf<typeof PAID_MEDIA_CREATIVE_SPEC>;

export const PROMPT_FAMILY_REQUEST = model({
  project_name: { parse: str({ min: 1 }) },
  family: { parse: PROMPT_FAMILY_SPEC },
  brand_core: { parse: BRAND_CORE },
  ledger: { parse: CONCEPT_LEDGER, default: defaultsOf(CONCEPT_LEDGER) },
  content: { parse: str(), default: () => '' },
  claims: { parse: list(CLAIM_SEED), default: (): ReadonlyArray<ParsedOf<typeof CLAIM_SEED>> => [] },
  evidence: { parse: list(SOURCE_EVIDENCE), default: (): ReadonlyArray<ParsedOf<typeof SOURCE_EVIDENCE>> => [] },
  computations: { parse: list(COMPUTATION_EVIDENCE), default: (): ReadonlyArray<ParsedOf<typeof COMPUTATION_EVIDENCE>> => [] },
  providers: { parse: list(PROVIDER_CAPABILITY), default: (): ReadonlyArray<ParsedOf<typeof PROVIDER_CAPABILITY>> => [] },
  hooks: { parse: list(HOOK_CANDIDATE), default: (): readonly HookCandidate[] => [] },
  paid_media: { parse: list(PAID_MEDIA_CREATIVE_SPEC), default: (): readonly PaidMediaCreativeSpec[] => [] },
});
export type PromptFamilyRequest = ParsedOf<typeof PROMPT_FAMILY_REQUEST>;

export interface PromptFamilyEvaluation {
  readonly invariants_held: boolean;
  readonly exact_text_preserved: boolean;
  readonly accepted_instances: number;
  readonly rejected_duplicates: number;
  readonly repairs: number;
  readonly varied_axis_fraction: CanonicalFloat;
  readonly novelty_budget: CanonicalFloat;
  readonly series_consistency: CanonicalFloat;
  readonly hard_failures: readonly string[];
  readonly advisory_notes: readonly string[];
}
