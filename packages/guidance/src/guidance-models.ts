/**
 * Typed contracts for selectively retrieved expert guidance (twin of
 * `agency/guidance/models.py`). Guidance is advisory data: it can improve how a
 * prompt is compiled, but it never redefines runtime policy, verified facts,
 * canonical BrandCore state, permissions, provider capabilities or terminal-state
 * semantics. Authority classes are exactly ADVISORY and EVIDENCE_BOUND_ADVISORY.
 */
import { CanonicalFloat } from '@amc/canonical';
import {
  anyValue,
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
import { orderedMap, type PyValue } from './pyvalue';

export const GUIDANCE_DOMAINS = [
  'BRANDING', 'GRAPHIC_DESIGN', 'DESIGN_SYSTEM', 'UI_UX', 'WEB_DESIGN', 'WEB_DEVELOPMENT', 'MOTION', 'VIDEO',
  'STORYBOARD', 'MARKETING', 'ADVERTISING', 'SOCIAL', 'COPYWRITING', 'PRESENTATION', 'PRINT', 'PACKAGING',
  'CREATIVE_TECH', 'DESIGN_TRENDS',
] as const;
export const GUIDANCE_CLASSES = ['METHODOLOGY', 'TREND_INTELLIGENCE'] as const;
export const AUTHORITY_CLASSES = ['ADVISORY', 'EVIDENCE_BOUND_ADVISORY'] as const;
export const DIRECTIVE_CLASSES = [
  'ADVISORY_METHOD', 'EVIDENCE_BOUND_ADVISORY', 'QUALITY_CRITERION', 'ANTI_PATTERN', 'TREND_SUGGESTION',
] as const;
export const GUIDANCE_TARGETS = [
  'strategy', 'verbal', 'visual', 'composition', 'typography', 'interaction', 'motion', 'camera', 'audio',
  'accessibility', 'trend', 'tokens', 'engineering', 'governance', 'quality', 'production',
] as const;

export type GuidanceDomain = (typeof GUIDANCE_DOMAINS)[number];
export type GuidanceClass = (typeof GUIDANCE_CLASSES)[number];
export type AuthorityClass = (typeof AUTHORITY_CLASSES)[number];
export type DirectiveClass = (typeof DIRECTIVE_CLASSES)[number];
export type GuidanceTarget = (typeof GUIDANCE_TARGETS)[number];

type ParsedOf<P> = P extends Parser<infer T> ? T : never;

const strings = { parse: list(str()), default: (): readonly string[] => [] };

const ACTIVATION = model({
  asset_families: strings,
  asset_types: strings,
  channels: strings,
  brand_domains: strings,
  capabilities: strings,
  task_tags: strings,
});

const CONTEXT_BUDGET = model({
  max_sections: { parse: int({ ge: 1, le: 50 }), default: () => 5 },
  max_chars: { parse: int({ ge: 256, le: 100000 }), default: () => 12000 },
});

const PROVENANCE = model({
  source: { parse: str({ min: 1 }) },
  version: { parse: str({ min: 1 }) },
  author: { parse: nullable(str()), default: (): string | null => null },
  created_at: { parse: nullable(str()), default: (): string | null => null },
  updated_at: { parse: nullable(str()), default: (): string | null => null },
  evidence_refs: strings,
  license_or_ip_status: { parse: nullable(str()), default: (): string | null => null },
});

const PREDICATE = model({ any: strings, all: strings });

const hasContent = (section: {
  readonly directives: readonly string[];
  readonly evaluation_criteria: readonly string[];
  readonly anti_patterns: readonly string[];
  readonly patterns: ReadonlyMap<string, string>;
  readonly dimensions: readonly string[];
  readonly subsections: ReadonlyMap<string, unknown>;
}): boolean =>
  section.directives.length > 0 ||
  section.evaluation_criteria.length > 0 ||
  section.anti_patterns.length > 0 ||
  section.patterns.size > 0 ||
  section.dimensions.length > 0 ||
  section.subsections.size > 0;

const SECTION = refine(
  model({
    id: { parse: str({ min: 1 }) },
    purpose: { parse: str({ min: 1 }) },
    directive_class: { parse: enumOf(DIRECTIVE_CLASSES), default: (): DirectiveClass => 'ADVISORY_METHOD' },
    activate_when: { parse: PREDICATE, default: defaultsOf(PREDICATE) },
    directives: strings,
    evaluation_criteria: strings,
    anti_patterns: strings,
    evidence_requirements: strings,
    output_targets: strings,
    directive_targets: { parse: list(enumOf(GUIDANCE_TARGETS)), default: (): readonly GuidanceTarget[] => [] },
    patterns: { parse: dict(str()), default: (): ReadonlyMap<string, string> => new Map() },
    dimensions: strings,
    possible_outputs: strings,
    subsections: { parse: dict(anyValue), default: (): ReadonlyMap<string, unknown> => new Map() },
  }),
  [(section) => (hasContent(section) ? null : 'guidance section must contain actionable content')],
);

const TREND = model({
  observed_at: { parse: str() },
  expires_at: { parse: str() },
  source_refs: { parse: list(str(), { min: 1 }) },
  confidence: { parse: float({ ge: 0, le: 1 }) },
  trend_status: { parse: str({ min: 1 }) },
  applicability: strings,
  avoid_when: strings,
});

export type GuidanceActivation = ParsedOf<typeof ACTIVATION>;
export type GuidanceSection = ParsedOf<typeof SECTION>;
export type TrendMetadata = ParsedOf<typeof TREND>;
export type GuidanceProvenance = ParsedOf<typeof PROVENANCE>;
export type ContextBudget = ParsedOf<typeof CONTEXT_BUDGET>;

function packRules(pack: { readonly sections: readonly GuidanceSection[]; readonly guidance_class: GuidanceClass; readonly trend: unknown }): string | null {
  const ids = pack.sections.map((section) => section.id);
  if (ids.length !== new Set(ids).size) return 'guidance section ids must be unique within a pack';
  if (pack.guidance_class === 'TREND_INTELLIGENCE' && pack.trend === null) return 'TREND_INTELLIGENCE packs require trend freshness metadata';
  if (pack.guidance_class === 'METHODOLOGY' && pack.trend !== null) return 'METHODOLOGY packs cannot declare trend freshness metadata';
  return null;
}

const PACK_FIELDS = model({
    id: { parse: str({ min: 1 }) },
    schema_version: { parse: str({ min: 1 }) },
    pack_version: { parse: str({ min: 1 }) },
    domain: { parse: enumOf(GUIDANCE_DOMAINS) },
    guidance_class: { parse: enumOf(GUIDANCE_CLASSES), default: (): GuidanceClass => 'METHODOLOGY' },
    authority_class: { parse: enumOf(AUTHORITY_CLASSES) },
    description: { parse: str({ min: 1 }) },
    activation: { parse: ACTIVATION },
    excludes: { parse: ACTIVATION, default: defaultsOf(ACTIVATION) },
    dependencies: strings,
    conflicts_with: strings,
    context_budget: { parse: CONTEXT_BUDGET, default: defaultsOf(CONTEXT_BUDGET) },
    sections: { parse: list(SECTION, { min: 1 }) },
    provenance: { parse: PROVENANCE },
    trend: { parse: nullable(TREND), default: (): TrendMetadata | null => null },
    content_hash: { parse: str(), default: () => '' },
});

export const GUIDANCE_PACK = refine(PACK_FIELDS, [packRules]);

export type GuidancePack = ParsedOf<typeof GUIDANCE_PACK>;

export const GUIDANCE_OVERRIDE = model({ include: strings, exclude: strings });
export type GuidanceOverride = ParsedOf<typeof GUIDANCE_OVERRIDE>;

export interface GuidanceSelection {
  readonly registry_version: string;
  readonly router_version: string;
  readonly selected_pack_ids: readonly string[];
  readonly selected_section_ids: readonly string[];
  readonly activation_reasons: readonly string[];
  readonly rejected_pack_ids: readonly string[];
  readonly exclusion_reasons: readonly string[];
  readonly guidance_context: ReadonlyMap<string, PyValue>;
  readonly guidance_hash: string;
}

function strList(values: readonly string[]): PyValue {
  return [...values];
}

function activationDump(activation: GuidanceActivation): PyValue {
  return orderedMap([
    ['asset_families', strList(activation.asset_families)],
    ['asset_types', strList(activation.asset_types)],
    ['channels', strList(activation.channels)],
    ['brand_domains', strList(activation.brand_domains)],
    ['capabilities', strList(activation.capabilities)],
    ['task_tags', strList(activation.task_tags)],
  ]);
}

/** Pydantic's JSON mode turns non-finite floats inside `Any` values into null (`ser_json_inf_nan='null'`). */
function jsonMode(value: unknown): PyValue {
  if (value instanceof CanonicalFloat) return Number.isFinite(value.value) ? value : null;
  if (Array.isArray(value)) return value.map((item: unknown) => jsonMode(item));
  if (value instanceof Map) return new Map(Array.from(value as ReadonlyMap<string, unknown>, ([k, v]) => [k, jsonMode(v)] as const));
  return value as PyValue;
}

/** `section.model_dump(mode="json")`, keys in field order (the router renders it with `str()`). */
export function sectionDump(section: GuidanceSection): Map<string, PyValue> {
  return orderedMap([
    ['id', section.id],
    ['purpose', section.purpose],
    ['directive_class', section.directive_class],
    ['activate_when', orderedMap([['any', strList(section.activate_when.any)], ['all', strList(section.activate_when.all)]])],
    ['directives', strList(section.directives)],
    ['evaluation_criteria', strList(section.evaluation_criteria)],
    ['anti_patterns', strList(section.anti_patterns)],
    ['evidence_requirements', strList(section.evidence_requirements)],
    ['output_targets', strList(section.output_targets)],
    ['directive_targets', strList(section.directive_targets)],
    ['patterns', new Map(section.patterns)],
    ['dimensions', strList(section.dimensions)],
    ['possible_outputs', strList(section.possible_outputs)],
    ['subsections', jsonMode(section.subsections) as Map<string, PyValue>],
  ]);
}

function trendDump(trend: TrendMetadata | null): PyValue {
  if (trend === null) return null;
  return orderedMap([
    ['observed_at', trend.observed_at],
    ['expires_at', trend.expires_at],
    ['source_refs', strList(trend.source_refs)],
    ['confidence', trend.confidence as CanonicalFloat],
    ['trend_status', trend.trend_status],
    ['applicability', strList(trend.applicability)],
    ['avoid_when', strList(trend.avoid_when)],
  ]);
}

/** `pack.model_dump(mode="json")`, with or without `content_hash`. */
export function packDump(pack: GuidancePack, withHash: boolean): Map<string, PyValue> {
  const entries: Array<readonly [string, PyValue]> = [
    ['id', pack.id],
    ['schema_version', pack.schema_version],
    ['pack_version', pack.pack_version],
    ['domain', pack.domain],
    ['guidance_class', pack.guidance_class],
    ['authority_class', pack.authority_class],
    ['description', pack.description],
    ['activation', activationDump(pack.activation)],
    ['excludes', activationDump(pack.excludes)],
    ['dependencies', strList(pack.dependencies)],
    ['conflicts_with', strList(pack.conflicts_with)],
    ['context_budget', orderedMap([['max_sections', pack.context_budget.max_sections], ['max_chars', pack.context_budget.max_chars]])],
    ['sections', pack.sections.map(sectionDump)],
    ['provenance', provenanceDump(pack.provenance)],
    ['trend', trendDump(pack.trend)],
  ];
  if (withHash) entries.push(['content_hash', pack.content_hash]);
  return orderedMap(entries);
}

function provenanceDump(p: GuidanceProvenance): PyValue {
  return orderedMap([
    ['source', p.source],
    ['version', p.version],
    ['author', p.author],
    ['created_at', p.created_at],
    ['updated_at', p.updated_at],
    ['evidence_refs', strList(p.evidence_refs)],
    ['license_or_ip_status', p.license_or_ip_status],
  ]);
}

/** `selection.model_dump(mode="json")`. */
export function selectionDump(selection: GuidanceSelection): Map<string, PyValue> {
  return orderedMap([
    ['registry_version', selection.registry_version],
    ['router_version', selection.router_version],
    ['selected_pack_ids', strList(selection.selected_pack_ids)],
    ['selected_section_ids', strList(selection.selected_section_ids)],
    ['activation_reasons', strList(selection.activation_reasons)],
    ['rejected_pack_ids', strList(selection.rejected_pack_ids)],
    ['exclusion_reasons', strList(selection.exclusion_reasons)],
    ['guidance_context', new Map(selection.guidance_context)],
    ['guidance_hash', selection.guidance_hash],
  ]);
}
