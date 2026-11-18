/**
 * Typed contracts of the claims-audit prompt compiler (twin of the models in
 * `agency/prompt_compiler.py`). Input models are strict (`extra="forbid"`);
 * `BrandCore` ignores extra keys, as in Python. Parsed values are exactly what
 * `model_dump(mode="json")` would give: defaults filled in, floats as
 * `CanonicalFloat`, dicts as `Map`.
 *
 * Nothing here executes: the compiler stops at validated prompt packages and
 * there is deliberately no generated-assets state.
 */
import { CanonicalFloat } from '@amc/canonical';
import { pyRepr } from '@amc/kernel';
import { pyLen, pyStrip, formatFixed, sortedStrings } from './pytext';
import { GUIDANCE_OVERRIDE } from './guidance-models';
import {
  bool,
  defaultsOf,
  dict,
  enumOf,
  float,
  int,
  list,
  model,
  nullable,
  refine,
  str,
  type Parser,
} from './schema';

export const CLAIM_TYPES = [
  'FACT', 'OPINION', 'PROMISE', 'METRIC', 'API_CLAIM', 'LEGAL_CLAIM', 'MARKET_CLAIM', 'USER_ASSERTION',
  'BRAND_RULE', 'DESIGN_RULE', 'REQUIREMENT', 'ASSUMPTION', 'INFERENCE',
] as const;
export const CLAIM_STATUSES = [
  'VERIFIED', 'PARTIALLY_VERIFIED', 'USER_ASSERTED', 'DERIVED', 'SPECULATIVE', 'CONFLICTED', 'STALE', 'VOID', 'UNVERIFIED',
] as const;
export const GAP_CATEGORIES = [
  'MISSING_PREMISE', 'MISSING_SOURCE', 'MISSING_PRIMARY_SOURCE', 'UNDOCUMENTED_API', 'UNDECLARED_STAKEHOLDER',
  'UNSTATED_ASSUMPTION', 'MISSING_FAILURE_MODE', 'COMPLIANCE_GAP', 'SCOPE_GAP', 'TEMPORAL_GAP', 'CONTRADICTION',
  'AMBIGUITY', 'DEPENDENCY_GAP', 'BRAND_GAP', 'PRODUCTION_GAP', 'PROVIDER_GAP',
] as const;
export const MATERIALITIES = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'] as const;
export const CONFIDENCE_BANDS = ['VERIFIED_HIGH', 'VERIFIED', 'PROVISIONAL_WITH_FLAGS', 'BLOCKING_UNCERTAINTY'] as const;
export const COMPILER_STATES = [
  'CONTENT_RECEIVED', 'CLAIMS_EXTRACTED', 'GAPS_IDENTIFIED', 'RESEARCH_BACKFILLED', 'KNOWLEDGE_VALIDATED',
  'BRAND_SYSTEM_INCOMPLETE', 'BRAND_SYSTEM_COMPILED', 'BRAND_SYSTEM_VALIDATED', 'ASSET_REQUIREMENTS_RESOLVED',
  'ASSET_SPECS_COMPILED', 'PROMPT_CONTEXT_RESOLVED', 'PROMPT_IR_COMPILED', 'GENERATION_PROMPTS_COMPILED',
  'PROMPTS_VALIDATED_AGAINST_BRAND', 'PROMPT_PACKAGE_READY', 'RESEARCH_INCOMPLETE', 'BLOCKED',
] as const;
export const PROMPT_FAMILIES = ['IMAGE', 'UI_UX', 'COPY', 'MOTION', 'VIDEO', 'STORYBOARD', 'PRINT', 'PRESENTATION'] as const;
export const PROVIDER_CAPABILITY_NAMES = [
  'TEXT_TO_IMAGE', 'IMAGE_TO_IMAGE', 'EDIT', 'INPAINT', 'OUTPAINT', 'MULTI_REFERENCE', 'VECTOR', 'TEXT_TO_VIDEO',
  'IMAGE_TO_VIDEO', 'ELEMENT_TO_VIDEO', 'REFERENCE_TO_VIDEO', 'FIRST_FRAME', 'LAST_FRAME', 'MULTISHOT',
  'CAMERA_CONTROL', 'AUDIO', 'UI_GENERATION', 'CODE_GENERATION', 'STRUCTURED_TEXT',
] as const;
export const ADAPTER_STATUSES = ['GENERIC_COMPATIBLE', 'VERIFIED_ADAPTER', 'UNVERIFIED', 'BLOCKED'] as const;
export const VALIDATION_STATUSES = ['PASS', 'REPAIR', 'BLOCK'] as const;
export const ACCEPTANCE_STATUSES = ['PASS', 'PARTIAL', 'BLOCKED', 'FAIL'] as const;
export const SOURCE_CLASSES = ['PRIMARY', 'OFFICIAL', 'SECONDARY', 'COMMUNITY', 'USER'] as const;
export const FRESHNESS_CLASSES = ['STATIC', 'SLOW_CHANGING', 'VOLATILE', 'REALTIME'] as const;
export const REFERENCE_ROLES = ['IDENTITY', 'CONTENT', 'COMPOSITION', 'STYLE', 'START_FRAME', 'END_FRAME', 'MOTION', 'AUDIO'] as const;
export const COMPUTATION_STATUSES = ['DERIVED_FROM_VERIFIED_INPUTS', 'NO_EMPIRICAL_INPUTS', 'PREMISES_UNVERIFIED', 'INVALID_REFERENCE'] as const;

export type ClaimType = (typeof CLAIM_TYPES)[number];
export type ClaimStatus = (typeof CLAIM_STATUSES)[number];
export type GapCategory = (typeof GAP_CATEGORIES)[number];
export type Materiality = (typeof MATERIALITIES)[number];
export type ConfidenceBand = (typeof CONFIDENCE_BANDS)[number];
export type CompilerState = (typeof COMPILER_STATES)[number];
export type PromptFamily = (typeof PROMPT_FAMILIES)[number];
export type ProviderCapabilityName = (typeof PROVIDER_CAPABILITY_NAMES)[number];
export type AdapterStatus = (typeof ADAPTER_STATUSES)[number];
export type PromptValidationStatus = (typeof VALIDATION_STATUSES)[number];
export type AcceptanceStatus = (typeof ACCEPTANCE_STATUSES)[number];
export type SourceClass = (typeof SOURCE_CLASSES)[number];
export type FreshnessClass = (typeof FRESHNESS_CLASSES)[number];
export type ReferenceRole = (typeof REFERENCE_ROLES)[number];
export type ComputationStatus = (typeof COMPUTATION_STATUSES)[number];

/** Precedence when references conflict (source spec section 14). */
export const REFERENCE_PRECEDENCE: readonly ReferenceRole[] = [
  'IDENTITY', 'CONTENT', 'COMPOSITION', 'STYLE', 'START_FRAME', 'END_FRAME', 'MOTION', 'AUDIO',
];
export const TEMPORAL_REFERENCE_ROLES: ReadonlySet<ReferenceRole> = new Set<ReferenceRole>(['START_FRAME', 'END_FRAME', 'MOTION', 'AUDIO']);

export const COMPILER_VERSION = 'amc-prompt-compiler/v1';
export const GENERATION_FIREWALL = 'PROMPT_PACKAGE_READY';

type ParsedOf<P> = P extends Parser<infer T> ? T : never;

const strings = { parse: list(str()), default: (): readonly string[] => [] };
const optText = { parse: nullable(str()), default: (): string | null => null };

export const REFERENCE_SPEC = model({
  ref_id: { parse: str({ min: 1 }) },
  role: { parse: enumOf(REFERENCE_ROLES) },
  priority: { parse: int({ ge: 1, le: 10 }), default: () => 1 },
  note: optText,
});

export const SERIES_BINDING = model({
  family_id: { parse: str({ min: 1 }) },
  family_version: { parse: str({ min: 1 }) },
  instance_id: { parse: str({ min: 1 }) },
  campaign_ref: optText,
  concept_thesis: { parse: str({ min: 1 }) },
  emotional_function: optText,
  signature_devices: strings,
  series_invariants: strings,
  variation: { parse: dict(str()), default: (): ReadonlyMap<string, string> => new Map() },
  concept_signature: { parse: str({ min: 1 }) },
});

export const CLAIM_SEED = model({
  text: { parse: str({ min: 1 }) },
  claim_type: { parse: enumOf(CLAIM_TYPES), default: (): ClaimType => 'USER_ASSERTION' },
  source_ref: optText,
  stakeholder: optText,
  temporal_scope: optText,
});

export const SOURCE_EVIDENCE = model({
  source_id: { parse: str() },
  title: { parse: str() },
  source_class: { parse: enumOf(SOURCE_CLASSES) },
  claim_ids: strings,
  supports: { parse: bool, default: () => true },
  publisher: optText,
  uri: optText,
  published_at: optText,
  accessed_at: optText,
  summary: { parse: str({ min: 1 }) },
  query: optText,
  freshness_class: { parse: nullable(enumOf(FRESHNESS_CLASSES)), default: (): FreshnessClass | null => null },
});

const strMap = { parse: dict(str()), default: (): ReadonlyMap<string, string> => new Map() };

export const COMPUTATION_EVIDENCE = model({
  computation_id: { parse: str({ min: 1 }) },
  question: { parse: str({ min: 1 }) },
  expression_or_operation: { parse: str({ min: 1 }) },
  inputs: strMap,
  units: strMap,
  assumptions: strings,
  tool_or_engine: { parse: str({ min: 1 }) },
  engine_version: optText,
  result: { parse: str({ min: 1 }) },
  precision: optText,
  uncertainty: optText,
  executed_at: optText,
  provenance: { parse: str({ min: 1 }) },
  reproducible: { parse: bool, default: () => false },
  input_claim_ids: strings,
  derived_claim_ids: strings,
});

const optPositiveInt = { parse: nullable(int({ gt: 0 })), default: (): number | null => null };

export const PRODUCTION_SPEC = model({
  width: optPositiveInt,
  height: optPositiveInt,
  unit: { parse: str(), default: () => 'px' },
  aspect_ratio: optText,
  orientation: optText,
  format: optText,
  color_space: optText,
  resolution: optText,
  duration_seconds: { parse: nullable(float({ gt: 0 })), default: (): CanonicalFloat | null => null },
  fps: optPositiveInt,
  codec: optText,
  container: optText,
  safe_area: optText,
  bleed: optText,
});

export const ASSET_REQUIREMENT = model({
  asset_id: { parse: str({ min: 1 }) },
  family: { parse: enumOf(PROMPT_FAMILIES) },
  asset_type: { parse: str({ min: 1 }) },
  objective: { parse: str({ min: 1 }) },
  audience: { parse: str({ min: 1 }) },
  channel: { parse: str({ min: 1 }) },
  destination: { parse: str({ min: 1 }) },
  business_reason: optText,
  required_brand_domains: strings,
  required_capabilities: { parse: list(enumOf(PROVIDER_CAPABILITY_NAMES)), default: (): readonly ProviderCapabilityName[] => [] },
  content_requirements: strings,
  negative_constraints: strings,
  quality_constraints: strings,
  production: { parse: PRODUCTION_SPEC, default: defaultsOf(PRODUCTION_SPEC) },
  guidance_overrides: { parse: GUIDANCE_OVERRIDE, default: defaultsOf(GUIDANCE_OVERRIDE) },
  exact_text: strings,
  references: { parse: list(REFERENCE_SPEC), default: (): readonly ReferenceSpec[] => [] },
  series: { parse: nullable(SERIES_BINDING), default: (): SeriesBinding | null => null },
});

export const PROVIDER_CAPABILITY = model({
  provider: { parse: str({ min: 1 }) },
  model: { parse: str({ min: 1 }) },
  verified: { parse: bool, default: () => false },
  source_ref: optText,
  verified_at: optText,
  families: { parse: list(enumOf(PROMPT_FAMILIES)), default: (): readonly PromptFamily[] => [] },
  capabilities: { parse: list(enumOf(PROVIDER_CAPABILITY_NAMES)), default: (): readonly ProviderCapabilityName[] => [] },
  notes: strings,
});

const hexColor = /^#[0-9A-Fa-f]{6}\n?$/;
const hexError = (value: string | null): string | null =>
  value === null || hexColor.test(value) ? null : `reference_hex '${value}' is not a 6-digit hex color (e.g. '#1a2b4c')`;

const LOGO_TYPES = ['primary', 'secondary', 'icon_only', 'wordmark', 'horizontal', 'stacked', 'reversed', 'monochrome'] as const;
const LOGO_LOCKUP = model(
  {
    lockup_id: { parse: str({ min: 1 }) },
    lockup_type: { parse: enumOf(LOGO_TYPES) },
    usage_context: { parse: str({ min: 1 }) },
    minimum_size: { parse: str({ min: 1 }) },
    clear_space_rule: { parse: str({ min: 1 }) },
    placement_notes: { parse: str({ min: 1 }) },
    generation_reference: { parse: str({ min: 1 }) },
  },
  { extra: 'ignore' },
);
const BRAND_VOICE = model(
  { tone_attributes: { parse: list(str(), { min: 1 }) }, writing_dos: strings, writing_donts: strings },
  { extra: 'ignore' },
);
const COLOR_ROLE = model(
  {
    role: { parse: str({ min: 1 }) },
    description: { parse: str({ min: 1 }) },
    reference_hex: { parse: nullable(str()), default: (): string | null => null, check: hexError },
  },
  { extra: 'ignore' },
);
const MOTION_CHARACTER = model(
  {
    pace: { parse: str({ min: 1 }) },
    emphasis_moments: { parse: list(str(), { min: 1 }) },
    reduced_motion_fallback: { parse: str({ min: 1 }) },
  },
  { extra: 'ignore' },
);

type LogoLockup = ParsedOf<typeof LOGO_LOCKUP>;
type ColorRole = ParsedOf<typeof COLOR_ROLE>;

/** Below this two brand colors do not read as distinct roles: a heuristic, not a WCAG metric. */
export const MINIMUM_COLOR_STORY_DISTINCTION_RATIO = 1.5;

function channelToLinear(channel255: number): number {
  const c = channel255 / 255;
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

function relativeLuminance(hex: string): number {
  const value = hex.replace(/^#+/, '');
  const [r, g, b] = [0, 2, 4].map((i) => channelToLinear(parseInt(value.slice(i, i + 2), 16)));
  return 0.2126 * (r ?? 0) + 0.7152 * (g ?? 0) + 0.0722 * (b ?? 0);
}

function contrastRatio(a: string, b: string): number {
  const [la, lb] = [relativeLuminance(a), relativeLuminance(b)];
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

function lockupIdError(value: readonly LogoLockup[]): string | null {
  const ids = value.map((lockup) => lockup.lockup_id);
  if (ids.length === new Set(ids).size) return null;
  const duplicates = sortedStrings(new Set(ids.filter((id) => ids.filter((other) => other === id).length > 1)));
  return `logo_lockups contains duplicate lockup_id(s): [${duplicates.map((id) => pyRepr(id)).join(', ')}]`;
}

function primaryError(brand: { readonly logo_lockups: readonly LogoLockup[] }): string | null {
  const count = brand.logo_lockups.filter((lockup) => lockup.lockup_type === 'primary').length;
  return count === 1 ? null : `logo_lockups must contain exactly one primary lockup, found ${count}`;
}

function distinctionError(brand: { readonly color_story: readonly ColorRole[] }): string | null {
  const swatches = brand.color_story.filter((role) => role.reference_hex !== null);
  for (let i = 0; i < swatches.length; i += 1) {
    for (const other of swatches.slice(i + 1)) {
      const first = swatches[i] as ColorRole;
      const ratio = contrastRatio(first.reference_hex as string, other.reference_hex as string);
      if (ratio < MINIMUM_COLOR_STORY_DISTINCTION_RATIO) {
        return `color_story roles '${first.role}' and '${other.role}' are not visually distinguishable (contrast ${formatFixed(ratio, 2)}:1, need at least ${MINIMUM_COLOR_STORY_DISTINCTION_RATIO}:1)`;
      }
    }
  }
  return null;
}

const BRAND_FIELDS = model(
    {
    brand_name: { parse: str({ min: 1 }) },
    positioning_essence: { parse: str({ min: 1 }) },
    voice: { parse: BRAND_VOICE },
    color_story: { parse: list(COLOR_ROLE, { min: 1 }) },
    typography_direction: { parse: str({ min: 1 }) },
    imagery_style: { parse: str({ min: 1 }) },
    motion: { parse: MOTION_CHARACTER },
    logo_lockups: { parse: list(LOGO_LOCKUP, { min: 1 }), check: lockupIdError },
    },
    { extra: 'ignore' },
);

export const BRAND_CORE = refine(BRAND_FIELDS, [primaryError, distinctionError]);

export type ReferenceSpec = ParsedOf<typeof REFERENCE_SPEC>;
export type SeriesBinding = ParsedOf<typeof SERIES_BINDING>;
export type ClaimSeed = ParsedOf<typeof CLAIM_SEED>;
export type SourceEvidence = ParsedOf<typeof SOURCE_EVIDENCE>;
export type ComputationEvidence = ParsedOf<typeof COMPUTATION_EVIDENCE>;
export type ProductionSpec = ParsedOf<typeof PRODUCTION_SPEC>;
export type AssetRequirement = ParsedOf<typeof ASSET_REQUIREMENT>;
export type ProviderCapability = ParsedOf<typeof PROVIDER_CAPABILITY>;
export type BrandCore = ParsedOf<typeof BRAND_CORE>;

function needsIntake(request: { readonly content: string; readonly claims: readonly unknown[]; readonly brand_core: unknown }): string | null {
  const empty = pyLen(pyStrip(request.content)) === 0;
  return empty && request.claims.length === 0 && request.brand_core === null ? 'request must include content, claims, or brand_core' : null;
}

const REQUEST_FIELDS = model({
    project_name: { parse: str({ min: 1 }) },
    content: { parse: str(), default: () => '' },
    claims: { parse: list(CLAIM_SEED), default: (): readonly ClaimSeed[] => [] },
    evidence: { parse: list(SOURCE_EVIDENCE), default: (): readonly SourceEvidence[] => [] },
    brand_core: { parse: nullable(BRAND_CORE), default: (): BrandCore | null => null },
    asset_requirements: { parse: list(ASSET_REQUIREMENT), default: (): readonly AssetRequirement[] => [] },
    providers: { parse: list(PROVIDER_CAPABILITY), default: (): readonly ProviderCapability[] => [] },
    computations: { parse: list(COMPUTATION_EVIDENCE), default: (): readonly ComputationEvidence[] => [] },
    extract_content_claims: { parse: bool, default: () => true },
});

export const PROMPT_COMPILER_REQUEST = refine(REQUEST_FIELDS, [needsIntake]);

export type PromptCompilerRequest = ParsedOf<typeof PROMPT_COMPILER_REQUEST>;

// ---- results (dump-shaped records) ------------------------------------------------

export interface ClaimRecord {
  readonly claim_id: string;
  readonly text: string;
  readonly claim_type: ClaimType;
  readonly source_ref: string | null;
  readonly stakeholder: string | null;
  readonly temporal_scope: string | null;
  readonly status: ClaimStatus;
  readonly confidence: CanonicalFloat;
}

export interface GapRecord {
  readonly gap_id: string;
  readonly claim_refs: readonly string[];
  readonly category: GapCategory;
  readonly description: string;
  readonly materiality: Materiality;
  readonly retrieval_target: string | null;
  readonly required_source_class: SourceClass | null;
  readonly blocks_synthesis: boolean;
}

export interface ResearchRequest {
  readonly request_id: string;
  readonly gap_id: string;
  readonly query: string;
  readonly required_source_class: SourceClass | null;
  readonly max_hops: number;
}

export interface ComputationAssessment {
  readonly computation_id: string;
  readonly status: ComputationStatus;
  readonly derived_claim_ids: readonly string[];
  readonly unverified_inputs: readonly string[];
  readonly notes: readonly string[];
}

export interface CompletenessReport {
  readonly evidence: number;
  readonly brand: number;
  readonly production: number;
  readonly provider: number;
  readonly provenance: number;
  readonly blocking_domains: readonly string[];
}

export interface AcceptanceReport {
  readonly status: AcceptanceStatus;
  readonly blocking_criteria: readonly string[];
  readonly limitations: readonly string[];
  readonly checks: readonly string[];
}

export interface PassResult {
  readonly pass_name: string;
  readonly status: string;
  readonly produced: number;
  readonly notes: readonly string[];
}

export interface AssetSpec {
  readonly asset_id: string;
  readonly family: PromptFamily;
  readonly asset_type: string;
  readonly objective: string;
  readonly audience: string;
  readonly channel: string;
  readonly destination: string;
  readonly brand_hash: string;
  readonly required_brand_domains: readonly string[];
  readonly required_capabilities: readonly ProviderCapabilityName[];
  readonly content_requirements: readonly string[];
  readonly negative_constraints: readonly string[];
  readonly quality_constraints: readonly string[];
  readonly production: ProductionSpec;
  readonly validation_rules: readonly string[];
  readonly exact_text: readonly string[];
  readonly references: readonly ReferenceSpec[];
  readonly series: SeriesBinding | null;
}

export interface PromptContext {
  readonly brand_context: ReadonlyMap<string, unknown>;
  readonly included_domains: readonly string[];
  readonly excluded_domains: readonly string[];
  readonly guidance_context: ReadonlyMap<string, unknown>;
  readonly included_guidance: readonly string[];
  readonly excluded_guidance: readonly string[];
  readonly guidance_hash: string;
  readonly activation_reasons: readonly string[];
  readonly registry_version: string | null;
  readonly router_version: string | null;
  readonly context_hash: string;
}

export interface PromptIR {
  readonly asset_id: string;
  readonly family: PromptFamily;
  readonly objective: string;
  readonly audience: string;
  readonly channel: string;
  readonly destination: string;
  readonly brand_directives: readonly string[];
  readonly strategy_directives: readonly string[];
  readonly verbal_directives: readonly string[];
  readonly visual_directives: readonly string[];
  readonly composition_directives: readonly string[];
  readonly typography_directives: readonly string[];
  readonly interaction_directives: readonly string[];
  readonly motion_directives: readonly string[];
  readonly camera_directives: readonly string[];
  readonly audio_directives: readonly string[];
  readonly accessibility_directives: readonly string[];
  readonly trend_directives: readonly string[];
  readonly token_directives: readonly string[];
  readonly engineering_directives: readonly string[];
  readonly governance_directives: readonly string[];
  readonly qa_directives: readonly string[];
  readonly production_guidance_directives: readonly string[];
  readonly content_directives: readonly string[];
  readonly production_directives: readonly string[];
  readonly negative_constraints: readonly string[];
  readonly quality_constraints: readonly string[];
  readonly required_capabilities: readonly ProviderCapabilityName[];
  readonly provenance_refs: readonly string[];
  readonly exact_text: readonly string[];
  readonly references: readonly ReferenceSpec[];
  readonly render_stages: readonly string[];
  readonly series: SeriesBinding | null;
  readonly evidence_directives: readonly string[];
}

export interface ProviderPrompt {
  readonly provider: string | null;
  readonly model: string | null;
  readonly status: AdapterStatus;
  readonly prompt: string;
  readonly required_references: readonly string[];
  readonly unsupported_requirements: readonly string[];
  readonly source_ref: string | null;
}

export interface PromptValidationResult {
  readonly status: PromptValidationStatus;
  readonly issues: readonly string[];
  readonly checked_dimensions: readonly string[];
}

export interface PromptPackage {
  readonly package_id: string;
  readonly package_version: string;
  readonly project_name: string;
  readonly asset_spec: AssetSpec;
  readonly prompt_ir: PromptIR;
  readonly generic_master_prompt: string;
  readonly provider_prompts: readonly ProviderPrompt[];
  readonly context_manifest: PromptContext;
  readonly validation: PromptValidationResult;
  readonly prompt_hash: string;
  readonly brand_hash: string;
  readonly unresolved_gaps: readonly string[];
  readonly ui_ux_design: unknown;
  readonly handoff_only: true;
  readonly terminal_state: 'PROMPT_PACKAGE_READY';
}

export interface PromptCompilerResult {
  readonly compiler_version: string;
  readonly project_name: string;
  readonly final_state: CompilerState;
  readonly passes: readonly PassResult[];
  readonly claims: readonly ClaimRecord[];
  readonly gaps: readonly GapRecord[];
  readonly research_requests: readonly ResearchRequest[];
  readonly evidence: readonly SourceEvidence[];
  readonly completeness: CompletenessReport;
  readonly confidence: CanonicalFloat;
  readonly confidence_band: ConfidenceBand;
  readonly acceptance: AcceptanceReport;
  readonly prompt_packages: readonly PromptPackage[];
  readonly voids: readonly string[];
  readonly speculative_inferences: readonly string[];
  readonly computations: readonly ComputationAssessment[];
  readonly generation_firewall: 'PROMPT_PACKAGE_READY';
}
