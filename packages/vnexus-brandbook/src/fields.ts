/**
 * Field states, intake evidence and the gap register (`brandbook/fields.py`). FieldState (what is known about a key)
 * is separate from `approved` (governance) and from EvidenceClass (how a source statement is known).
 */
import { applicabilityKey, dependencyPaths, sortedUnique, type Mode, type PageManifest, type PageSpec } from './manifest';
import { PY_WORD, cpSlice, isPyEmpty, pyRepr, pyStrip, type PyValue } from './python';

export const NONE_SENTINEL = '@none';
export const NA_PREFIX = '@not_applicable:';

/**
 * A raw template token that must never reach production output. Python's `\b` after `@none` is Unicode-aware, so the
 * boundary is spelled out with Python's own `\w` class.
 */
export const UNRESOLVED_TOKEN_SOURCE = `\\{\\{[^}]*\\}\\}|\\[GAP[^\\]]*\\]|@none(?![${PY_WORD}])|@not_applicable:`;

export function unresolvedTokens(text: string): string[] {
  return [...text.matchAll(new RegExp(UNRESOLVED_TOKEN_SOURCE, 'gu'))].map((m) => m[0]);
}

export function hasUnresolvedToken(text: string): boolean {
  return new RegExp(UNRESOLVED_TOKEN_SOURCE, 'u').test(text);
}

export const FIELD_STATUSES = ['VALUE', 'NONE', 'NOT_APPLICABLE', 'PROPOSED', 'UNKNOWN'] as const;
export type FieldStatus = (typeof FIELD_STATUSES)[number];
export const EVIDENCE_CLASSES = ['OBSERVED', 'USER_REPORTED', 'INFERRED', 'UNKNOWN', 'PROPOSED'] as const;
export type EvidenceClass = (typeof EVIDENCE_CLASSES)[number];

/** How the genome's provenance kinds read on the evidence axis. */
export const PROVENANCE_EVIDENCE: Readonly<Record<string, EvidenceClass>> = {
  USER_SUPPLIED: 'USER_REPORTED', IMPORTED: 'OBSERVED', INFERRED: 'INFERRED', DEFAULTED: 'PROPOSED', UNRESOLVED: 'UNKNOWN',
};

export interface FieldState {
  readonly path: string;
  readonly status: FieldStatus;
  readonly value: PyValue;
  readonly reason: string;
  readonly approved: boolean;
  readonly source_scope: string;
}

export function printable(state: FieldState): boolean {
  return (state.status === 'VALUE' || state.status === 'PROPOSED') && !isPyEmpty(state.value);
}

export type GenomeValues = { readonly [path: string]: PyValue | undefined };

function decode(path: string, value: PyValue, approved: boolean, sources: Readonly<Record<string, string>>): FieldState {
  const source_scope = sources[path] ?? '';
  const base = { path, value: null, reason: '', approved, source_scope };
  if (typeof value === 'string' && pyStrip(value).toLowerCase() === NONE_SENTINEL) return { ...base, status: 'NONE' };
  if (typeof value === 'string' && value.toLowerCase().startsWith(NA_PREFIX)) {
    return { ...base, status: 'NOT_APPLICABLE', reason: cpSlice(pyStrip(cpSlice(value, NA_PREFIX.length)), 0, 300) };
  }
  return { ...base, status: approved ? 'VALUE' : 'PROPOSED', value };
}

function present(values: GenomeValues | undefined, path: string): PyValue | undefined {
  const value = values?.[path];
  return value === undefined || value === null ? undefined : value;
}

/** State of one key: approved values win; a proposal only fills what is not approved. */
export function fieldState(path: string, approved: GenomeValues, proposed?: GenomeValues, sources?: Readonly<Record<string, string>>): FieldState {
  const fromApproved = present(approved, path);
  if (fromApproved !== undefined) return decode(path, fromApproved, true, sources ?? {});
  const fromProposal = present(proposed, path);
  if (fromProposal !== undefined) return decode(path, fromProposal, false, sources ?? {});
  return { path, status: 'UNKNOWN', value: null, reason: '', approved: false, source_scope: '' };
}

export type EvidenceKind = 'document' | 'image' | 'interview' | 'website' | 'existing_asset' | 'other';

/** One intake source (`EvidenceRecord.model_dump(mode="json")`). Text is evidence, never instructions. */
export interface EvidenceRecord {
  readonly source_id: string;
  readonly locator: string;
  readonly kind: EvidenceKind;
  readonly evidence_class: EvidenceClass;
  readonly observations: readonly string[];
  readonly inferences: readonly string[];
  readonly unknowns: readonly string[];
  readonly contradictions: readonly string[];
  readonly reuse: 'evidence_only' | 'licensed_reuse' | 'owned' | 'unknown';
  readonly privacy: 'none' | 'contains_pii_redacted' | 'restricted';
}

export type Severity = 'BLOCKING' | 'MAJOR' | 'MINOR';

export interface Gap {
  readonly page_id: string;
  readonly path: string;
  readonly status: FieldStatus;
  readonly severity: Severity;
  readonly consequence: string;
  readonly source: string;
  readonly next_action: string;
}

function nextAction(path: string, status: FieldStatus, page: PageSpec): string {
  if (page.gap_behavior === 'DECIDE' && path === applicabilityKey(page)) {
    return `decide whether '${page.title}' applies: set ${path} to '@not_applicable: <reason>' or supply the section's keys, `
      + 'in a genome draft for review';
  }
  if (path === 'visual.logo.mark' || path === 'visual.logo.master_artifact') {
    return 'route to identity review: approve a master mark (visual.logo.mark or visual.logo.master_artifact)';
  }
  if (status === 'PROPOSED') return `submit the draft carrying ${path} for approval`;
  return `supply ${path} (or '@none' / '@not_applicable: <reason>') in a genome draft for review`;
}

export type States = ReadonlyMap<string, FieldState>;

/** `states[path]` with Python's KeyError for a key the manifest never declared. */
export function stateOf(states: States, path: string): FieldState {
  const state = states.get(path);
  if (state === undefined) throw new KeyError(path);
  return state;
}

export class KeyError extends Error {
  override name = 'KeyError';
  constructor(key: string) {
    super(pyRepr(key));
  }
}

function proposalGap(page: PageSpec, path: string, status: FieldStatus): Gap {
  return { page_id: page.id, path, status, severity: 'BLOCKING', consequence: 'a proposal cannot be printed in production',
    source: 'intake proposal', next_action: nextAction(path, status, page) };
}

function productionProposals(page: PageSpec, states: States): Gap[] {
  return page.optional_paths.filter((p) => stateOf(states, p).status === 'PROPOSED').map((p) => proposalGap(page, p, 'PROPOSED'));
}

function decideGaps(page: PageSpec, states: States, production: boolean): Gap[] {
  const key = applicabilityKey(page);
  const decision = stateOf(states, key);
  if (decision.status === 'NOT_APPLICABLE' && (decision.approved || !production)) return [];
  const gaps: Gap[] = [];
  const hasData = page.optional_paths.some((p) => printable(stateOf(states, p)));
  if (!hasData && decision.status !== 'VALUE') {
    gaps.push({ page_id: page.id, path: key, status: decision.status, severity: production ? 'BLOCKING' : 'MAJOR',
      consequence: 'the section cannot be written or omitted without a decision', source: 'manifest gap_behavior=DECIDE',
      next_action: nextAction(key, decision.status, page) });
  }
  return production ? [...gaps, ...productionProposals(page, states)] : gaps;
}

function requiredGap(page: PageSpec, path: string, state: FieldState, production: boolean): Gap | undefined {
  const resolved = ((state.status === 'VALUE' || state.status === 'NONE' || state.status === 'NOT_APPLICABLE') && state.approved)
    || (!production && state.status !== 'UNKNOWN');
  if (resolved) return undefined;
  const severity: Severity = production ? 'BLOCKING' : (page.gap_behavior === 'BLOCK' ? 'MAJOR' : 'MINOR');
  return { page_id: page.id, path, status: state.status, severity,
    consequence: production ? 'production refuses the page' : 'the page shows a labelled gap',
    source: state.status === 'UNKNOWN' ? 'approved genome' : 'intake proposal', next_action: nextAction(path, state.status, page) };
}

/** Gaps for one page. A DECIDE page with neither data nor a decision has one gap: the decision. */
export function pageGaps(page: PageSpec, states: States, mode: Mode): Gap[] {
  const production = mode === 'PRODUCTION';
  if (page.gap_behavior === 'DECIDE') return decideGaps(page, states, production);
  const gaps: Gap[] = [];
  for (const path of page.required_paths) {
    const gap = requiredGap(page, path, stateOf(states, path), production);
    if (gap !== undefined) gaps.push(gap);
  }
  return production ? [...gaps, ...productionProposals(page, states)] : gaps;
}

export function allPaths(manifest: PageManifest, stylePaths: readonly string[]): string[] {
  return sortedUnique([...manifest.pages.flatMap(dependencyPaths), ...stylePaths]);
}
