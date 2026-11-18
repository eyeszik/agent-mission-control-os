/**
 * Deterministic selector for expert guidance (twin of `agency/guidance/router.py`).
 * The router uses typed metadata first and makes no LLM call, so identical inputs
 * and registry versions yield identical selections.
 *
 * Python 3.12 changed `sum()` of floats to compensated summation; this twin
 * follows 3.11 (what CI runs), where `sum()` adds left to right.
 */
import { REGISTRY_VERSION, stableGuidanceHash, type GuidanceRegistry } from './registry';
import {
  sectionDump,
  type GuidanceActivation,
  type GuidanceOverride,
  type GuidancePack,
  type GuidanceSection,
  type GuidanceSelection,
} from './guidance-models';
import { compareCodePoints, formatFixed, pyLen, roundTo, sortedStrings } from './pytext';
import { orderedMap, pyReprValue, type PyValue } from './pyvalue';

export const ROUTER_VERSION = 'amc-guidance-router/v1';
const SELECTION_THRESHOLD = 0.25;
const WEIGHTS = { family: 0.3, asset_type: 0.25, channel: 0.15, brand_domains: 0.1, capabilities: 0.1, task_tags: 0.1 } as const;
const TOKEN_RE = /[a-z0-9]+/g;

/** What routing reads from an `AssetRequirement`. */
export interface RoutingRequirement {
  readonly family: string;
  readonly asset_type: string;
  readonly channel: string;
  readonly objective: string;
  readonly business_reason: string | null;
  readonly required_brand_domains: readonly string[];
  readonly required_capabilities: readonly string[];
  readonly content_requirements: readonly string[];
  readonly quality_constraints: readonly string[];
}

const tokenList = (text: string): string[] => text.toLowerCase().match(TOKEN_RE) ?? [];
const norm = (value: string): string => tokenList(value).join(' ');
const tokens = (value: string): Set<string> => new Set(tokenList(value));
const listValues = (values: readonly string[]): Set<string> => new Set(values.map(norm));

function intersectionSize(left: ReadonlySet<string>, right: ReadonlySet<string>): number {
  return Array.from(left).filter((item) => right.has(item)).length;
}

function overlapFraction(left: ReadonlySet<string>, right: ReadonlySet<string>): number {
  if (left.size === 0 || right.size === 0) return 0;
  return intersectionSize(left, right) / left.size;
}

function textMatch(candidate: string, allowed: readonly string[]): number {
  if (allowed.length === 0) return 0;
  if (new Set(allowed.map(norm)).has(norm(candidate))) return 1;
  const candidateTokens = tokens(candidate);
  let best = 0;
  for (const item of allowed) {
    const itemTokens = tokens(item);
    if (itemTokens.size === 0) continue;
    best = Math.max(best, intersectionSize(candidateTokens, itemTokens) / itemTokens.size);
  }
  return best;
}

type Component = readonly [name: string, weight: number, value: number];

function taskHaystack(req: RoutingRequirement): string {
  return [req.objective, req.business_reason ?? '', ...req.content_requirements, ...req.quality_constraints].join(' ');
}

function components(req: RoutingRequirement, activation: GuidanceActivation): Component[] {
  const out: Component[] = [];
  if (activation.asset_families.length > 0) {
    out.push(['family', WEIGHTS.family, listValues(activation.asset_families).has(norm(req.family)) ? 1 : 0]);
  }
  if (activation.asset_types.length > 0) out.push(['asset_type', WEIGHTS.asset_type, textMatch(req.asset_type, activation.asset_types)]);
  if (activation.channels.length > 0) out.push(['channel', WEIGHTS.channel, textMatch(req.channel, activation.channels)]);
  if (activation.brand_domains.length > 0) {
    out.push(['brand_domains', WEIGHTS.brand_domains, overlapFraction(listValues(activation.brand_domains), listValues(req.required_brand_domains))]);
  }
  if (activation.capabilities.length > 0) {
    out.push(['capabilities', WEIGHTS.capabilities, overlapFraction(listValues(activation.capabilities), listValues(req.required_capabilities))]);
  }
  if (activation.task_tags.length > 0) {
    out.push(['task_tags', WEIGHTS.task_tags, overlapFraction(listValues(activation.task_tags), tokens(taskHaystack(req)))]);
  }
  return out;
}

function activationScore(req: RoutingRequirement, activation: GuidanceActivation): [number, string[]] {
  const parts = components(req, activation);
  if (parts.length === 0) return [0, []];
  const denominator = parts.reduce((total, [, weight]) => total + weight, 0);
  const score = parts.reduce((total, [, weight, value]) => total + weight * value, 0) / denominator;
  const reasons = parts.filter(([, , value]) => value > 0).map(([name, , value]) => `${name}=${formatFixed(value, 3)}`);
  return [roundTo(Math.max(0, Math.min(1, score)), 6), reasons];
}

function excludedReason(req: RoutingRequirement, excludes: GuidanceActivation): string | null {
  const checks: ReadonlyArray<readonly [string, string, readonly string[]]> = [
    ['family', norm(req.family), excludes.asset_families],
    ['asset_type', req.asset_type, excludes.asset_types],
    ['channel', req.channel, excludes.channels],
  ];
  for (const [label, value, rules] of checks) {
    if (rules.length > 0 && textMatch(value, rules) >= 1) return `${label} explicitly excluded`;
  }
  return null;
}

function sectionMatches(section: GuidanceSection, req: RoutingRequirement): boolean {
  const { any, all } = section.activate_when;
  if (any.length === 0 && all.length === 0) return true;
  const haystack = [req.asset_type, req.objective, req.channel, req.business_reason ?? '', ...req.content_requirements, ...req.quality_constraints]
    .join(' ')
    .toLowerCase();
  if (all.length > 0 && !all.every((term) => haystack.includes(term.toLowerCase()))) return false;
  if (any.length > 0 && !any.some((term) => haystack.includes(term.toLowerCase()))) return false;
  return true;
}

function sectionPayload(pack: GuidancePack, section: GuidanceSection): Map<string, PyValue> {
  return orderedMap([
    ['pack_id', pack.id],
    ['pack_version', pack.pack_version],
    ['domain', pack.domain],
    ['authority_class', pack.authority_class],
    ['section', sectionDump(section)],
    ['pack_hash', pack.content_hash],
  ]);
}

interface Candidate {
  readonly score: number;
  readonly pack: GuidancePack;
  readonly reasons: readonly string[];
}

interface Ranking {
  readonly selected: Map<string, Candidate>;
  readonly rejected: string[];
  readonly exclusionReasons: string[];
}

function rankPacks(req: RoutingRequirement, registry: GuidanceRegistry, include: ReadonlySet<string>, exclude: ReadonlySet<string>): Ranking {
  const selected = new Map<string, Candidate>();
  const rejected: string[] = [];
  const exclusionReasons: string[] = [];
  for (const pack of registry.packs) {
    if (exclude.has(pack.id)) {
      rejected.push(pack.id);
      exclusionReasons.push(`${pack.id}: explicit override exclusion`);
      continue;
    }
    const exclusion = excludedReason(req, pack.excludes);
    if (exclusion !== null) {
      rejected.push(pack.id);
      exclusionReasons.push(`${pack.id}: ${exclusion}`);
      continue;
    }
    const [scored, scoredReasons] = activationScore(req, pack.activation);
    const forced = include.has(pack.id);
    const score = forced ? 1 : scored;
    if (score < SELECTION_THRESHOLD) {
      rejected.push(pack.id);
      exclusionReasons.push(`${pack.id}: relevance=${formatFixed(score, 3)}`);
      continue;
    }
    selected.set(pack.id, { score, pack, reasons: forced ? ['explicit_include'] : scoredReasons });
  }
  return { selected, rejected, exclusionReasons };
}

function visitPack(packId: string, ranking: Ranking, registry: GuidanceRegistry, exclude: ReadonlySet<string>): boolean {
  const { selected, rejected, exclusionReasons } = ranking;
  const current = selected.get(packId) as Candidate;
  const blocked = current.pack.dependencies.find((dependency) => exclude.has(dependency));
  if (blocked !== undefined) {
    selected.delete(packId);
    rejected.push(packId);
    exclusionReasons.push(`${packId}: dependency ${blocked} explicitly excluded`);
    return true;
  }
  let changed = false;
  const marker = `dependency_of=${packId}`;
  for (const dependency of current.pack.dependencies) {
    const existing = selected.get(dependency);
    if (existing === undefined) {
      selected.set(dependency, { score: current.score, pack: registry.get(dependency), reasons: [marker] });
      changed = true;
    } else if (!existing.reasons.includes(marker)) {
      selected.set(dependency, { ...existing, reasons: [...existing.reasons, marker] });
    }
  }
  return changed;
}

function resolveDependencies(ranking: Ranking, registry: GuidanceRegistry, exclude: ReadonlySet<string>): void {
  let changed = true;
  while (changed) {
    changed = false;
    for (const packId of sortedStrings(ranking.selected.keys())) {
      if (visitPack(packId, ranking, registry, exclude)) changed = true;
    }
  }
}

function byScoreThenId(a: Candidate, b: Candidate): number {
  if (a.score !== b.score) return a.score > b.score ? -1 : 1;
  return compareCodePoints(a.pack.id, b.pack.id);
}

interface Context {
  readonly sectionIds: string[];
  readonly entries: Array<readonly [string, PyValue]>;
}

function fillContext(pack: GuidancePack, req: RoutingRequirement, exclusionReasons: string[]): Context {
  const matched = pack.sections.filter((section) => sectionMatches(section, req)).slice(0, pack.context_budget.max_sections);
  const context: Context = { sectionIds: [], entries: [] };
  let chars = 0;
  for (const section of matched) {
    const payload = sectionPayload(pack, section);
    const size = pyLen(pyReprValue(payload));
    if (chars + size > pack.context_budget.max_chars) {
      exclusionReasons.push(`${pack.id}:${section.id}: context budget exceeded`);
      continue;
    }
    chars += size;
    const key = `${pack.id}:${section.id}`;
    context.entries.push([key, payload]);
    context.sectionIds.push(key);
  }
  return context;
}

/** `route_guidance`: select packs and sections for a requirement. */
export function routeGuidance(
  requirement: RoutingRequirement,
  registry: GuidanceRegistry,
  override: GuidanceOverride = { include: [], exclude: [] },
): GuidanceSelection {
  const include = new Set(override.include);
  const exclude = new Set(override.exclude);
  const ranking = rankPacks(requirement, registry, include, exclude);
  resolveDependencies(ranking, registry, exclude);
  const ranked = Array.from(ranking.selected.values()).sort(byScoreThenId);
  const packIds: string[] = [];
  const sectionIds: string[] = [];
  const reasons: string[] = [];
  const context = new Map<string, PyValue>();
  for (const { score, pack, reasons: why } of ranked) {
    packIds.push(pack.id);
    reasons.push(`${pack.id}: relevance=${formatFixed(score, 3)}; ${why.join(', ') || 'typed match'}`);
    const filled = fillContext(pack, requirement, ranking.exclusionReasons);
    for (const [key, payload] of filled.entries) context.set(key, payload);
    sectionIds.push(...filled.sectionIds);
  }
  return {
    registry_version: REGISTRY_VERSION,
    router_version: ROUTER_VERSION,
    selected_pack_ids: packIds,
    selected_section_ids: sectionIds,
    activation_reasons: reasons,
    rejected_pack_ids: sortedStrings(new Set(ranking.rejected)),
    exclusion_reasons: ranking.exclusionReasons,
    guidance_context: context,
    guidance_hash: guidanceHash(registry, packIds, sectionIds, context),
  };
}

function guidanceHash(registry: GuidanceRegistry, packIds: readonly string[], sectionIds: readonly string[], context: ReadonlyMap<string, PyValue>): string {
  return stableGuidanceHash(
    orderedMap([
      ['registry_version', REGISTRY_VERSION],
      ['registry_hash', registry.registryHash],
      ['router_version', ROUTER_VERSION],
      ['selected_pack_ids', [...packIds]],
      ['selected_section_ids', [...sectionIds]],
      ['guidance_context', new Map(context)],
    ]),
  );
}
