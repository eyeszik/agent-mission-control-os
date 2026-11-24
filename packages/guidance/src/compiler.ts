/**
 * The prompt-package half of the compiler (twin of `agency/prompt_compiler.py`):
 * asset spec, prompt context, prompt IR, the serialized master prompt, provider
 * adapters, package validation and the orchestration that ends at
 * `PROMPT_PACKAGE_READY`, `BLOCKED`, `RESEARCH_INCOMPLETE` or
 * `BRAND_SYSTEM_INCOMPLETE`. There is deliberately no generated-assets state: the
 * compiler never invokes a provider, writes an asset, publishes or spends.
 *
 * Guidance routing needs the loaded registry, and UI_UX assets need the UI/UX
 * compiler (`agency/ui_ux`, ported separately); both are passed in. A UI_UX asset
 * without an adapter fails closed.
 */
import { CanonicalFloat } from '@amc/canonical';
import { floatRepr } from '@amc/kernel';
import {
  applyComputations,
  assessComputations,
  buildResearchBackfill,
  evidenceDirectives,
  huntGaps,
  intakeClaims,
  MATERIAL_TYPES,
  soundDerivedClaimIds,
  validateClaims,
} from './claims';
import {
  COMPILER_VERSION,
  GENERATION_FIREWALL,
  REFERENCE_PRECEDENCE,
  TEMPORAL_REFERENCE_ROLES,
  type AcceptanceReport,
  type AcceptanceStatus,
  type AssetRequirement,
  type AssetSpec,
  type BrandCore,
  type ClaimRecord,
  type CompilerState,
  type CompletenessReport,
  type ConfidenceBand,
  type GapRecord,
  type PassResult,
  type PromptCompilerRequest,
  type PromptCompilerResult,
  type PromptContext,
  type PromptFamily,
  type PromptIR,
  type PromptPackage,
  type PromptValidationResult,
  type ProviderCapability,
  type ProviderCapabilityName,
  type ProviderPrompt,
  type ReferenceSpec,
} from './compiler-models';
import { UiUxAdapterMissingError } from './errors';
import { type GuidanceSelection } from './guidance-models';
import { type GuidanceRegistry } from './registry';
import { routeGuidance } from './router';
import { compareCodePoints, roundTo, sortedStrings } from './pytext';
import { canonicalJson, stableHash, type PyValue } from './pyvalue';

/** The slice of the UI/UX compiler's output the prompt compiler reads (replayed from Python in the fixtures). */
export interface UiUxFinding {
  readonly engine: string;
  readonly severity: string;
  readonly subject: string;
  readonly message: string;
  readonly repaired: boolean;
}

export interface UiUxCompiled {
  readonly dump: PyValue;
  readonly spec_hash: string;
  readonly terminal: string;
  readonly evaluation: readonly UiUxFinding[];
  readonly approval_required: readonly string[];
  readonly directive_buckets: Readonly<Record<string, readonly string[]>>;
  readonly spec_section: readonly string[];
}

export type UiUxCompile = (requirement: AssetRequirement, brand: BrandCore) => UiUxCompiled;

export interface CompileOptions {
  readonly registry: GuidanceRegistry;
  readonly uiux?: UiUxCompile;
}

const DEFAULT_DOMAINS: Readonly<Record<PromptFamily, readonly string[]>> = {
  IMAGE: ['strategy', 'visual'],
  UI_UX: ['strategy', 'visual', 'verbal', 'motion'],
  COPY: ['strategy', 'verbal'],
  MOTION: ['strategy', 'visual', 'motion'],
  VIDEO: ['strategy', 'visual', 'verbal', 'motion'],
  STORYBOARD: ['strategy', 'visual', 'motion'],
  PRINT: ['strategy', 'visual', 'verbal'],
  PRESENTATION: ['strategy', 'visual', 'verbal'],
};

const DEFAULT_CAPABILITIES: Readonly<Record<PromptFamily, readonly ProviderCapabilityName[]>> = {
  IMAGE: ['TEXT_TO_IMAGE'],
  UI_UX: ['UI_GENERATION'],
  COPY: ['STRUCTURED_TEXT'],
  MOTION: ['TEXT_TO_VIDEO'],
  VIDEO: ['TEXT_TO_VIDEO'],
  STORYBOARD: ['TEXT_TO_IMAGE'],
  PRINT: ['TEXT_TO_IMAGE'],
  PRESENTATION: ['STRUCTURED_TEXT'],
};

const VISUAL_TEXT_FAMILIES: ReadonlySet<PromptFamily> = new Set<PromptFamily>(['IMAGE', 'PRINT', 'PRESENTATION']);
const TEMPORAL_FAMILIES: ReadonlySet<PromptFamily> = new Set<PromptFamily>(['VIDEO', 'MOTION', 'STORYBOARD']);

export { stableHash };

export function confidenceBand(score: number): ConfidenceBand {
  if (score >= 0.9) return 'VERIFIED_HIGH';
  if (score >= 0.8) return 'VERIFIED';
  if (score >= 0.65) return 'PROVISIONAL_WITH_FLAGS';
  return 'BLOCKING_UNCERTAINTY';
}

export function compileAssetSpec(requirement: AssetRequirement, brand: BrandCore): AssetSpec {
  const rules = [
    'Preserve canonical brand authority.',
    'Do not invent missing facts, claims, logos, or production requirements.',
    'Respect destination, accessibility, and production constraints.',
    'Return a result suitable for independent downstream validation.',
  ];
  if (requirement.exact_text.length > 0) rules.push('Reproduce every exact_text string character-for-character.');
  if (requirement.series !== null) rules.push('Hold series invariants fixed; vary only the declared variation axes.');
  const domains = requirement.required_brand_domains;
  const capabilities = requirement.required_capabilities;
  return {
    asset_id: requirement.asset_id,
    family: requirement.family,
    asset_type: requirement.asset_type,
    objective: requirement.objective,
    audience: requirement.audience,
    channel: requirement.channel,
    destination: requirement.destination,
    brand_hash: stableHash(brand as unknown as PyValue),
    required_brand_domains: domains.length > 0 ? [...domains] : [...DEFAULT_DOMAINS[requirement.family]],
    required_capabilities: capabilities.length > 0 ? [...capabilities] : [...DEFAULT_CAPABILITIES[requirement.family]],
    content_requirements: [...requirement.content_requirements],
    negative_constraints: [...requirement.negative_constraints],
    quality_constraints: [...requirement.quality_constraints],
    production: requirement.production,
    validation_rules: rules,
    exact_text: [...requirement.exact_text],
    references: [...requirement.references],
    series: requirement.series,
  };
}

function brandDomain(domain: string, brand: BrandCore): PyValue {
  if (domain === 'strategy') return { brand_name: brand.brand_name, positioning_essence: brand.positioning_essence };
  if (domain === 'verbal') return brand.voice as unknown as PyValue;
  if (domain === 'visual') {
    return {
      color_story: brand.color_story,
      typography_direction: brand.typography_direction,
      imagery_style: brand.imagery_style,
      logo_lockups: brand.logo_lockups,
    } as unknown as PyValue;
  }
  if (domain === 'motion') return brand.motion as unknown as PyValue;
  return { status: '[VOID_DETECTED:BRAND_DOMAIN]' };
}

const KNOWN_DOMAINS = ['strategy', 'verbal', 'visual', 'motion'];

export function resolvePromptContext(spec: AssetSpec, brand: BrandCore, guidance: GuidanceSelection | null): PromptContext {
  const included = new Map<string, PyValue>();
  for (const domain of spec.required_brand_domains) included.set(domain, brandDomain(domain, brand));
  const guidanceContext = guidance === null ? new Map<string, PyValue>() : guidance.guidance_context;
  const guidanceHash = guidance === null ? '' : guidance.guidance_hash;
  const payload = new Map<string, PyValue>([
    ['brand_context', included],
    ['guidance_hash', guidanceHash],
    ['guidance_context', guidanceContext],
  ]);
  return {
    brand_context: included,
    included_domains: sortedStrings(spec.required_brand_domains),
    excluded_domains: sortedStrings(KNOWN_DOMAINS.filter((domain) => !spec.required_brand_domains.includes(domain))),
    guidance_context: guidanceContext,
    included_guidance: guidance === null ? [] : [...guidance.selected_section_ids],
    excluded_guidance: guidance === null ? [] : [...guidance.rejected_pack_ids],
    guidance_hash: guidanceHash,
    activation_reasons: guidance === null ? [] : [...guidance.activation_reasons],
    registry_version: guidance === null ? null : guidance.registry_version,
    router_version: guidance === null ? null : guidance.router_version,
    context_hash: stableHash(payload),
  };
}

function flattenGuidanceValue(value: unknown, prefix = ''): string[] {
  if (typeof value === 'string') return [prefix !== '' ? `${prefix}${value}` : value];
  if (Array.isArray(value)) return value.flatMap((item: unknown) => flattenGuidanceValue(item, prefix));
  if (value instanceof Map) {
    const entries = value as ReadonlyMap<string, unknown>;
    return sortedStrings(entries.keys()).flatMap((key) => flattenGuidanceValue(entries.get(key), `${prefix}${key}: `));
  }
  return [];
}

const BUCKET_NAMES = [
  'strategy', 'verbal', 'visual', 'composition', 'typography', 'interaction', 'motion', 'camera', 'audio',
  'accessibility', 'trend', 'tokens', 'engineering', 'governance', 'quality', 'production',
] as const;
type Buckets = Record<(typeof BUCKET_NAMES)[number], string[]>;

function asMap(value: unknown): ReadonlyMap<string, unknown> {
  return value instanceof Map ? (value as ReadonlyMap<string, unknown>) : new Map();
}

function asStrings(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item: unknown) => pyStr(item)) : [];
}

function pyStr(value: unknown): string {
  return typeof value === 'string' ? value : canonicalPyStr(value);
}

function canonicalPyStr(value: unknown): string {
  if (value === null || value === undefined) return 'None';
  if (typeof value === 'boolean') return value ? 'True' : 'False';
  if (value instanceof CanonicalFloat) return floatRepr(value.value);
  return String(value);
}

function bucketFor(sectionId: string, directives: readonly string[], targets: readonly string[], buckets: Buckets): void {
  if (targets.length > 0) {
    for (const target of targets) {
      if (Object.hasOwn(buckets, target)) buckets[target as keyof Buckets].push(...directives);
    }
  } else if (sectionId.includes('strategy') || sectionId.includes('positioning')) buckets.strategy.push(...directives);
  else if (sectionId.includes('verbal') || sectionId.includes('naming')) buckets.verbal.push(...directives);
  else if (sectionId.includes('motion')) buckets.motion.push(...directives);
  else {
    buckets.visual.push(...directives);
    if (sectionId.includes('creative_direction')) buckets.composition.push(...directives);
  }
}

function visualIdentity(section: ReadonlyMap<string, unknown>, buckets: Buckets): void {
  const identity = asMap(asMap(section.get('subsections')).get('visual_identity'));
  for (const [name, value] of identity) {
    const flattened = flattenGuidanceValue(value);
    if (name === 'typography') buckets.typography.push(...flattened);
    else if (['imagery', 'geometry', 'iconography', 'color', 'logo'].includes(name)) buckets.visual.push(...flattened);
  }
}

function addSection(section: ReadonlyMap<string, unknown>, buckets: Buckets): void {
  const sectionId = pyStr(section.get('id') ?? '').toLowerCase();
  bucketFor(sectionId, asStrings(section.get('directives')), asStrings(section.get('directive_targets')), buckets);
  for (const criterion of asStrings(section.get('evaluation_criteria'))) buckets.quality.push(`Evaluate: ${criterion}`);
  for (const antiPattern of asStrings(section.get('anti_patterns'))) buckets.quality.push(`Avoid: ${antiPattern}`);
  for (const need of asStrings(section.get('evidence_requirements'))) buckets.governance.push(`Evidence requirement: ${need}`);
  visualIdentity(section, buckets);
}

function dedupe(values: readonly string[]): string[] {
  return Array.from(new Set(values));
}

export function guidanceDirectiveBuckets(context: PromptContext): Buckets {
  const buckets = Object.fromEntries(BUCKET_NAMES.map((name) => [name, [] as string[]])) as Buckets;
  for (const key of sortedStrings(context.guidance_context.keys())) {
    addSection(asMap(asMap(context.guidance_context.get(key)).get('section')), buckets);
  }
  for (const name of BUCKET_NAMES) buckets[name] = dedupe(buckets[name]);
  return buckets;
}

const UI_UX_BUCKET_MAP = ['composition', 'interaction', 'accessibility', 'tokens', 'motion', 'engineering', 'quality', 'governance'] as const;

export function renderStagesFor(spec: AssetSpec): string[] {
  if (spec.exact_text.length === 0) return [];
  if (VISUAL_TEXT_FAMILIES.has(spec.family)) {
    return [
      'GENERATIVE_VISUAL: produce imagery only; render no lettering; reserve copy-safe zones for the exact text.',
      'DETERMINISTIC_LAYOUT: typeset exact text, logos and disclosures in a layout tool; verify character-for-character and against safe areas.',
    ];
  }
  if (TEMPORAL_FAMILIES.has(spec.family)) {
    return [
      'GENERATIVE_MOTION: produce footage or motion without rendered lettering.',
      'EDIT_COMPOSITING: apply exact on-screen text in the edit or compositing stage; verify character-for-character.',
    ];
  }
  return ['VERBATIM_COPY: include every exact text string unchanged in the delivered copy.'];
}

function orderedReferences(references: readonly ReferenceSpec[]): ReferenceSpec[] {
  const rank = (role: string): number => REFERENCE_PRECEDENCE.indexOf(role as (typeof REFERENCE_PRECEDENCE)[number]);
  return [...references].sort(
    (a, b) => rank(a.role) - rank(b.role) || b.priority - a.priority || compareCodePoints(a.ref_id, b.ref_id),
  );
}

function productionLines(spec: AssetSpec): string[] {
  return Object.entries(spec.production)
    .filter(([, value]) => value !== null)
    .map(([key, value]) => `${key}=${value instanceof CanonicalFloat ? floatRepr(value.value) : String(value)}`);
}

function mergeUiUx(buckets: Buckets, uiux: UiUxCompiled): void {
  for (const name of UI_UX_BUCKET_MAP) buckets[name] = dedupe([...buckets[name], ...(uiux.directive_buckets[name] ?? [])]);
}

export function compilePromptIr(
  spec: AssetSpec,
  context: PromptContext,
  uiux: UiUxCompiled | null = null,
  evidenceLines: readonly string[] = [],
): PromptIR {
  const brandDirectives = context.included_domains.map(
    (domain) => `Canonical brand context (${domain}): ${canonicalJson(context.brand_context.get(domain))}`,
  );
  const guidance = guidanceDirectiveBuckets(context);
  const provenance = [spec.brand_hash, context.context_hash];
  if (context.guidance_hash !== '') provenance.push(context.guidance_hash);
  if (spec.series !== null) provenance.push(spec.series.concept_signature);
  if (uiux !== null) {
    mergeUiUx(guidance, uiux);
    provenance.push(uiux.spec_hash);
  }
  return buildIr(spec, brandDirectives, guidance, provenance, evidenceLines);
}

function buildIr(spec: AssetSpec, brandDirectives: string[], g: Buckets, provenance: string[], evidenceLines: readonly string[]): PromptIR {
  return {
    asset_id: spec.asset_id,
    family: spec.family,
    objective: spec.objective,
    audience: spec.audience,
    channel: spec.channel,
    destination: spec.destination,
    brand_directives: brandDirectives,
    strategy_directives: g.strategy,
    verbal_directives: g.verbal,
    visual_directives: g.visual,
    composition_directives: g.composition,
    typography_directives: g.typography,
    interaction_directives: g.interaction,
    motion_directives: g.motion,
    camera_directives: g.camera,
    audio_directives: g.audio,
    accessibility_directives: g.accessibility,
    trend_directives: g.trend,
    token_directives: g.tokens,
    engineering_directives: g.engineering,
    governance_directives: g.governance,
    qa_directives: g.quality,
    production_guidance_directives: g.production,
    content_directives: [...spec.content_requirements],
    production_directives: productionLines(spec),
    negative_constraints: [...spec.negative_constraints],
    quality_constraints: [...spec.quality_constraints],
    required_capabilities: [...spec.required_capabilities],
    provenance_refs: provenance,
    exact_text: [...spec.exact_text],
    references: orderedReferences(spec.references),
    render_stages: renderStagesFor(spec),
    series: spec.series,
    evidence_directives: [...evidenceLines],
  };
}

const SECTIONS: ReadonlyArray<readonly [string, keyof PromptIR]> = [
  ['Canonical brand directives', 'brand_directives'],
  ['Selected advisory strategy guidance', 'strategy_directives'],
  ['Selected advisory verbal guidance', 'verbal_directives'],
  ['Selected advisory visual guidance', 'visual_directives'],
  ['Selected advisory composition guidance', 'composition_directives'],
  ['Selected advisory typography guidance', 'typography_directives'],
  ['Selected advisory interaction guidance', 'interaction_directives'],
  ['Selected advisory motion guidance', 'motion_directives'],
  ['Selected advisory camera guidance', 'camera_directives'],
  ['Selected advisory audio guidance', 'audio_directives'],
  ['Selected advisory accessibility guidance', 'accessibility_directives'],
  ['Selected advisory trend guidance', 'trend_directives'],
  ['Selected advisory token-system guidance', 'token_directives'],
  ['Selected advisory engineering guidance', 'engineering_directives'],
  ['Selected advisory governance guidance', 'governance_directives'],
  ['Selected advisory QA guidance', 'qa_directives'],
  ['Selected advisory production guidance', 'production_guidance_directives'],
];

function section(title: string, values: readonly string[]): string[] {
  return values.length === 0 ? [] : [`## ${title}`, ...values.map((value) => `- ${value}`), ''];
}

/** `json.dumps(text, ensure_ascii=False)`: only `"`, `\`, and control characters are escaped. */
export function jsonRaw(text: string): string {
  const short: Readonly<Record<string, string>> = { '"': '\\"', '\\': '\\\\', '\b': '\\b', '\f': '\\f', '\n': '\\n', '\r': '\\r', '\t': '\\t' };
  const body = Array.from(text, (ch) => short[ch] ?? (ch < ' ' ? `\\u${ch.charCodeAt(0).toString(16).padStart(4, '0')}` : ch)).join('');
  return `"${body}"`;
}

function seriesLines(ir: PromptIR): string[] {
  const binding = ir.series;
  if (binding === null) return [];
  const lines = [`family=${binding.family_id}@${binding.family_version}; instance=${binding.instance_id}`, `concept thesis: ${binding.concept_thesis}`];
  if (binding.campaign_ref !== null && binding.campaign_ref !== '') lines.push(`campaign anchor: ${binding.campaign_ref}`);
  if (binding.emotional_function !== null && binding.emotional_function !== '') lines.push(`emotional function: ${binding.emotional_function}`);
  lines.push(...binding.signature_devices.map((item) => `signature device: ${item}`));
  lines.push(...binding.series_invariants.map((item) => `hold fixed: ${item}`));
  const axes = sortedStrings(binding.variation.keys());
  lines.push(...axes.map((axis) => `this instance varies ${axis}: ${binding.variation.get(axis)}`));
  lines.push(`concept signature: ${binding.concept_signature}`);
  return lines;
}

function referenceLines(ir: PromptIR): string[] {
  return ir.references.map((ref) => `${ref.ref_id}: ${ref.role} (priority ${ref.priority})${ref.note !== null && ref.note !== '' ? ` — ${ref.note}` : ''}`);
}

const EXECUTION_CONTRACT = [
  '## Execution contract',
  '- Treat canonical brand context and verified project constraints as authoritative.',
  '- Treat selected domain guidance as advisory methodology only.',
  '- Never let guidance override canonical BrandCore, evidence, accessibility, permissions, or provider capability truth.',
  '- Do not invent missing factual claims, logos, product details, credentials, or provider features.',
  '- Preserve the requested medium, hierarchy, destination, and accessibility constraints.',
  '- Produce the requested creative asset for downstream review; do not reinterpret the brand system.',
];

export function serializeGenericPrompt(ir: PromptIR, spec: AssetSpec, uiux: UiUxCompiled | null = null): string {
  const lines: string[] = [
    `# ${spec.asset_type} — production prompt`, '', '## Objective', ir.objective, '', '## Audience', ir.audience, '',
    '## Channel / destination', `${ir.channel} / ${ir.destination}`, '',
  ];
  if (uiux !== null) lines.push(...uiux.spec_section);
  for (const [title, key] of SECTIONS) lines.push(...section(title, ir[key] as readonly string[]));
  lines.push(...section('Series binding', seriesLines(ir)));
  lines.push(...section('Evidence ceiling', ir.evidence_directives));
  lines.push(...section('Required content', ir.content_directives));
  lines.push(...section('Exact text (reproduce character-for-character)', ir.exact_text.map(jsonRaw)));
  lines.push(...section('Render stages', ir.render_stages));
  lines.push(
    ...section('Reference roles (precedence: IDENTITY > CONTENT > COMPOSITION > STYLE > START/END FRAME > MOTION > AUDIO)', referenceLines(ir)),
  );
  lines.push(...section('Production specification', ir.production_directives));
  lines.push(...section('Quality constraints', ir.quality_constraints));
  lines.push(...section('Negative constraints', ir.negative_constraints));
  lines.push(...EXECUTION_CONTRACT);
  return `${lines.join('\n').trim()}\n`;
}

function adaptOne(provider: ProviderCapability, ir: PromptIR, generic: string): ProviderPrompt {
  const have = new Set<string>(provider.capabilities);
  const missing = sortedStrings(new Set(ir.required_capabilities.filter((item) => !have.has(item))));
  const status = !provider.verified ? 'UNVERIFIED' : missing.length > 0 ? 'BLOCKED' : 'GENERIC_COMPATIBLE';
  return {
    provider: provider.provider,
    model: provider.model,
    status,
    prompt: generic,
    required_references: [],
    unsupported_requirements: status === 'GENERIC_COMPATIBLE' ? [] : missing,
    source_ref: provider.source_ref,
  };
}

export function adaptProviderPrompts(ir: PromptIR, generic: string, providers: readonly ProviderCapability[]): ProviderPrompt[] {
  return providers.filter((provider) => provider.families.includes(ir.family)).map((provider) => adaptOne(provider, ir, generic));
}

const BASE_DIMENSIONS = ['EVIDENCE', 'BRAND', 'CONTENT', 'PRODUCTION', 'PROVIDER', 'ACCESSIBILITY', 'SECURITY', 'GUIDANCE_AUTHORITY', 'PROVENANCE'];

function uiuxIssues(uiux: UiUxCompiled, generic: string): { issues: string[]; blocked: boolean } {
  const issues: string[] = [];
  const blocked = uiux.terminal === 'BLOCKED';
  if (blocked) {
    for (const f of uiux.evaluation) {
      if (f.severity === 'BLOCKING' && !f.repaired) issues.push(`UI/UX spec blocked: ${f.engine} ${f.subject}: ${f.message}`);
    }
  } else if (uiux.terminal === 'REQUIRES_APPROVAL') {
    for (const item of uiux.approval_required) if (item.startsWith('DECISION:')) issues.push(`UI/UX spec requires approval: ${item}`);
  }
  if (!generic.includes(uiux.spec_hash)) issues.push('UI/UX spec hash missing from serialized prompt');
  return { issues, blocked };
}

function exactTextIssues(spec: AssetSpec, generic: string): string[] {
  return spec.exact_text.filter((text) => !generic.includes(jsonRaw(text))).map((text) => `required text not preserved verbatim: ${text}`);
}

function referenceIssues(spec: AssetSpec): string[] {
  return spec.references
    .filter((ref) => TEMPORAL_REFERENCE_ROLES.has(ref.role) && !TEMPORAL_FAMILIES.has(spec.family))
    .map((ref) => `reference ${ref.ref_id} role ${ref.role} is temporal but family is ${spec.family}`);
}

export function validatePromptPackage(
  spec: AssetSpec,
  context: PromptContext,
  generic: string,
  providerPrompts: readonly ProviderPrompt[],
  uiux: UiUxCompiled | null = null,
): PromptValidationResult {
  const issues: string[] = [];
  if (spec.brand_hash === '') issues.push('brand hash missing');
  if (context.included_domains.length === 0) issues.push('no brand context selected');
  if (!generic.includes(spec.objective)) issues.push('objective missing from serialized prompt');
  if (!generic.includes(spec.audience)) issues.push('audience missing from serialized prompt');
  if (context.included_guidance.length > 0 && context.guidance_hash === '') issues.push('selected guidance missing deterministic hash');
  const textIssues = exactTextIssues(spec, generic);
  issues.push(...textIssues, ...referenceIssues(spec));
  for (const provider of providerPrompts) {
    if (provider.status === 'BLOCKED') issues.push(`${provider.provider}/${provider.model} lacks: ${provider.unsupported_requirements.join(', ')}`);
  }
  const dimensions = [...BASE_DIMENSIONS];
  let uiBlocked = false;
  if (uiux !== null) {
    dimensions.push('UI_UX_SPEC');
    const found = uiuxIssues(uiux, generic);
    uiBlocked = found.blocked;
    issues.push(...found.issues);
  }
  if (spec.exact_text.length > 0) dimensions.push('EXACT_TEXT');
  if (spec.references.length > 0) dimensions.push('REFERENCE_ROLES');
  const status = uiBlocked || textIssues.length > 0 ? 'BLOCK' : issues.length > 0 ? 'REPAIR' : 'PASS';
  return { status, issues, checked_dimensions: dimensions };
}

export function synthesizeReport(
  request: PromptCompilerRequest,
  validated: readonly ClaimRecord[],
  gaps: readonly GapRecord[],
): { completeness: CompletenessReport; confidence: number; band: ConfidenceBand } {
  const scores = validated.filter((claim) => MATERIAL_TYPES.has(claim.claim_type)).map((claim) => claim.confidence.value);
  const average = scores.reduce((total, value) => total + value, 0) / scores.length;
  const evidence = scores.length === 0 || average >= 0.8 ? 4 : 2;
  const blockers: string[] = [];
  if (request.brand_core === null) blockers.push('brand');
  if (request.asset_requirements.length === 0) blockers.push('production');
  if (gaps.some((gap) => gap.blocks_synthesis)) blockers.push('evidence');
  const ready = request.brand_core !== null && request.asset_requirements.length > 0;
  let confidence = scores.length > 0 ? average : ready ? 0.92 : 0.6;
  if (blockers.length > 0) confidence = Math.min(confidence, 0.64);
  const completeness: CompletenessReport = {
    evidence,
    brand: request.brand_core !== null ? 4 : 0,
    production: request.asset_requirements.length > 0 ? 4 : 0,
    provider: request.providers.some((provider) => provider.verified) ? 4 : 2,
    provenance: request.evidence.length > 0 || request.claims.length > 0 ? 4 : 2,
    blocking_domains: sortedStrings(new Set(blockers)),
  };
  return { completeness, confidence: roundTo(confidence, 3), band: confidenceBand(confidence) };
}

const ACCEPTANCE_CHECKS = [
  'brand_authority_present',
  'asset_requirements_present',
  'blocking_evidence_gaps_resolved',
  'prompt_validation_executed',
  'generation_firewall_preserved',
];

function acceptanceReport(status: AcceptanceStatus, blocking: readonly string[] = [], limitations: readonly string[] = []): AcceptanceReport {
  return { status, blocking_criteria: [...blocking], limitations: [...limitations], checks: [...ACCEPTANCE_CHECKS] };
}

interface Audit {
  readonly passes: PassResult[];
  readonly claims: ClaimRecord[];
  readonly gaps: GapRecord[];
  readonly unresolved: Set<string>;
  readonly research: ReturnType<typeof buildResearchBackfill>;
  readonly assessments: ReturnType<typeof assessComputations>;
  readonly completeness: CompletenessReport;
  readonly confidence: number;
  readonly band: ConfidenceBand;
}

function pass(name: string, status: string, produced: number, notes: readonly string[] = []): PassResult {
  return { pass_name: name, status, produced, notes: [...notes] };
}

function runAudit(request: PromptCompilerRequest): Audit {
  const passes: PassResult[] = [];
  const claims = intakeClaims(request);
  passes.push(pass('INTAKE+CLAIMS', 'COMPLETE', claims.length));
  const gaps = huntGaps(claims);
  passes.push(pass('GAP_HUNT', 'COMPLETE', gaps.length));
  const unresolved = new Set(gaps.map((gap) => gap.gap_id));
  const withEvidence = new Set(request.evidence.flatMap((item) => item.claim_ids));
  // Computations resolve a derived claim's gap only when every empirical input is verified.
  const assessments = assessComputations(validateClaims(claims, request.evidence), request.computations);
  for (const id of soundDerivedClaimIds(assessments)) withEvidence.add(id);
  for (const gap of gaps) if (gap.claim_refs.some((ref) => withEvidence.has(ref))) unresolved.delete(gap.gap_id);
  const open = gaps.filter((gap) => unresolved.has(gap.gap_id));
  const research = buildResearchBackfill(open);
  passes.push(pass('RESEARCH_BACKFILL', research.length === 0 ? 'COMPLETE' : 'RETRIEVAL_REQUESTS_EMITTED', research.length, ['No retrieval result is fabricated; unresolved requests remain explicit.']));
  const validated = applyComputations(validateClaims(claims, request.evidence), assessments, request.computations);
  passes.push(pass('VALIDATE', 'COMPLETE', validated.length));
  const report = synthesizeReport(request, validated, open);
  passes.push(pass('SYNTH+REPORT', 'COMPLETE', 1));
  return { passes, claims: validated, gaps, unresolved, research, assessments, completeness: report.completeness, confidence: report.confidence, band: report.band };
}

function early(request: PromptCompilerRequest, audit: Audit, state: CompilerState, acceptance: AcceptanceReport, voids: readonly string[]): PromptCompilerResult {
  return result(request, audit, state, acceptance, [], voids);
}

function result(
  request: PromptCompilerRequest,
  audit: Audit,
  state: CompilerState,
  acceptance: AcceptanceReport,
  packages: readonly PromptPackage[],
  voids: readonly string[],
): PromptCompilerResult {
  return {
    compiler_version: COMPILER_VERSION,
    project_name: request.project_name,
    final_state: state,
    passes: audit.passes,
    claims: audit.claims,
    gaps: audit.gaps,
    research_requests: audit.research,
    evidence: request.evidence as PromptCompilerResult['evidence'],
    completeness: audit.completeness,
    confidence: new CanonicalFloat(audit.confidence),
    confidence_band: audit.band,
    acceptance,
    prompt_packages: [...packages],
    voids: [...voids],
    speculative_inferences: [],
    computations: audit.assessments,
    generation_firewall: GENERATION_FIREWALL,
  };
}

function buildPackage(requirement: AssetRequirement, request: PromptCompilerRequest, audit: Audit, options: CompileOptions): PromptPackage {
  const brand = request.brand_core as BrandCore;
  const spec = compileAssetSpec(requirement, brand);
  const guidance = routeGuidance(requirement, options.registry, requirement.guidance_overrides);
  const context = resolvePromptContext(spec, brand, guidance);
  const uiux = requirement.family === 'UI_UX' ? compileUiUx(requirement, brand, options) : null;
  const evidence = evidenceDirectives(audit.claims, request.evidence, audit.assessments);
  const ir = compilePromptIr(spec, context, uiux, evidence);
  const generic = serializeGenericPrompt(ir, spec, uiux);
  const providerPrompts = adaptProviderPrompts(ir, generic, request.providers);
  const idSource = new Map<string, PyValue>([['project', request.project_name], ['asset', spec.asset_id]]);
  return {
    package_id: `pkg_${stableHash(idSource).slice(0, 16)}`,
    package_version: COMPILER_VERSION,
    project_name: request.project_name,
    asset_spec: spec,
    prompt_ir: ir,
    generic_master_prompt: generic,
    provider_prompts: providerPrompts,
    context_manifest: context,
    validation: validatePromptPackage(spec, context, generic, providerPrompts, uiux),
    prompt_hash: stableHash(generic),
    brand_hash: spec.brand_hash,
    unresolved_gaps: sortedStrings(audit.unresolved),
    ui_ux_design: uiux === null ? null : uiux.dump,
    handoff_only: true,
    terminal_state: GENERATION_FIREWALL,
  };
}

function compileUiUx(requirement: AssetRequirement, brand: BrandCore, options: CompileOptions): UiUxCompiled {
  if (options.uiux === undefined) throw new UiUxAdapterMissingError('a UI_UX asset needs the UI/UX compiler adapter; none was supplied');
  return options.uiux(requirement, brand);
}

function finish(request: PromptCompilerRequest, audit: Audit, packages: readonly PromptPackage[]): PromptCompilerResult {
  const blocked = packages.some((item) => item.validation.status === 'BLOCK');
  const repairs = packages.some((item) => item.validation.status === 'REPAIR');
  const limitations: string[] = [];
  if (audit.unresolved.size > 0 && !blocked) limitations.push('Non-blocking evidence gaps remain explicit in the package.');
  if (repairs && !blocked) limitations.push('One or more prompt validation checks require bounded repair.');
  const status: AcceptanceStatus = blocked ? 'FAIL' : audit.unresolved.size > 0 || repairs ? 'PARTIAL' : 'PASS';
  const acceptance = acceptanceReport(status, blocked ? ['prompt_validation_blocked'] : [], limitations);
  const voids = sortedStrings(audit.unresolved).map((id) => `[VOID_DETECTED:${id}]`);
  return result(request, audit, blocked ? 'BLOCKED' : 'PROMPT_PACKAGE_READY', acceptance, packages, voids);
}

/** `compile_prompt_packages`: five audit passes, then packages. Ends at PROMPT_PACKAGE_READY or fails closed. */
export function compilePromptPackages(request: PromptCompilerRequest, options: CompileOptions): PromptCompilerResult {
  const audit = runAudit(request);
  if (request.brand_core === null) {
    const acceptance = acceptanceReport('BLOCKED', ['brand_core_missing'], ['Canonical BrandCore is required before prompt synthesis.']);
    return early(request, audit, 'BRAND_SYSTEM_INCOMPLETE', acceptance, sortedStrings(audit.unresolved));
  }
  if (request.asset_requirements.length === 0) {
    const acceptance = acceptanceReport('BLOCKED', ['asset_requirements_missing'], ['At least one typed AssetRequirement is required.']);
    return early(request, audit, 'BLOCKED', acceptance, ['[VOID_DETECTED:ASSET_REQUIREMENTS]']);
  }
  const blocking = audit.gaps.filter((gap) => audit.unresolved.has(gap.gap_id) && gap.blocks_synthesis);
  if (blocking.length > 0) {
    const acceptance = acceptanceReport('BLOCKED', blocking.map((gap) => gap.gap_id), ['Material evidence gaps block synthesis until resolved.']);
    return early(request, audit, 'RESEARCH_INCOMPLETE', acceptance, blocking.map((gap) => `[VOID_DETECTED:${gap.gap_id}]`));
  }
  const packages = request.asset_requirements.map((requirement) => buildPackage(requirement, request, audit, options));
  return finish(request, audit, packages);
}
