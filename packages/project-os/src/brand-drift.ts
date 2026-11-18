/**
 * Twin of `agency/project_os/brand_drift.py`: detect drift, propose
 * refreshes, never overwrite.
 *
 * Each check is deterministic and reports evidence. A category with no input
 * to judge it goes to `not_evaluated` instead of being reported clean, so the
 * report never claims more coverage than it has. `autonomous_overwrites` is
 * the literal 0: a report cannot change an artifact.
 */
import type { BrandDriftReport } from '@amc/shared';
import { compareCodePoints } from '@amc/kernel';
import { canonicalSha256, type PyJson } from './json';
import { PY_BOUNDARY, PY_DIGIT, PY_DIGIT_BODY, PY_SPACE, pyFindall, pyRegExp, pySearch, wholeWordIgnoreCase } from './pyre';
import { lowerView, strOf, truthy } from './pytext';

const HEX = pyRegExp(`#[0-9a-fA-F]{6}${PY_BOUNDARY}`);
const PRICE = pyRegExp(`[$€£]${PY_SPACE}?${PY_DIGIT}[${PY_DIGIT_BODY},]*(?:\\.${PY_DIGIT}{2})?`);

export const ALL_CATEGORIES = [
  'logo_misuse', 'colors', 'typography', 'voice', 'naming', 'claims', 'stale_product_facts', 'old_pricing',
  'old_screenshots', 'expired_rights', 'accessibility', 'duplicate_content', 'creative_repetition',
] as const;

type Category = (typeof ALL_CATEGORIES)[number];
type Severity = 'info' | 'warning' | 'blocking';
type Finding = BrandDriftReport['findings'][number];

const SEVERITY_ORDER: Readonly<Record<Severity, number>> = { blocking: 0, warning: 1, info: 2 };

export interface BrandFacts {
  readonly palette?: readonly string[];
  readonly banned_terms?: readonly string[];
  /** old -> current */
  readonly deprecated_names?: Readonly<Record<string, string>>;
  readonly current_prices?: readonly string[];
  readonly brand_core_ref?: string | null;
}

export interface DriftSubject {
  readonly artifact_id: string;
  readonly status: string;
  readonly text?: string | null;
  readonly content_hash?: string | null;
  readonly variant_of?: string | null;
  readonly prompt_refs?: readonly string[];
  readonly rights?: Readonly<Record<string, PyJson>> | null;
  readonly unverified_claims?: readonly string[];
}

function finding(category: Category, severity: Severity, subject: DriftSubject, detail: string, evidence: readonly string[] = []): Finding {
  return { category, severity, artifact_id: subject.artifact_id, detail, evidence: [...evidence] };
}

const sortedUnique = (values: Iterable<string>): string[] => [...new Set(values)].sort(compareCodePoints);
const without = (values: Iterable<string>, drop: ReadonlySet<string>): string[] => sortedUnique([...values].filter((v) => !drop.has(v)));

type Check = (subjects: readonly DriftSubject[], texts: readonly (DriftSubject & { text: string })[], facts: BrandFacts) => Finding[] | undefined;

function colors(_subjects: readonly DriftSubject[], texts: readonly (DriftSubject & { text: string })[], facts: BrandFacts): Finding[] | undefined {
  const palette = new Set((facts.palette ?? []).map(lowerView));
  if (palette.size === 0 || texts.length === 0) return undefined;
  return texts.flatMap((subject) => {
    const off = without(pyFindall(HEX, subject.text).map((c) => c.toLowerCase()), palette);
    return off.length ? [finding('colors', 'warning', subject, `colors outside the approved palette: ${off.join(', ')}`, off)] : [];
  });
}

function voice(_subjects: readonly DriftSubject[], texts: readonly (DriftSubject & { text: string })[], facts: BrandFacts): Finding[] | undefined {
  const terms = facts.banned_terms ?? [];
  if (terms.length === 0 || texts.length === 0) return undefined;
  return texts.flatMap((subject) => {
    const hits = sortedUnique(terms.filter((term) => pySearch(wholeWordIgnoreCase(term), subject.text)));
    return hits.length ? [finding('voice', 'warning', subject, `off-voice terms: ${hits.join(', ')}`, hits)] : [];
  });
}

function naming(_subjects: readonly DriftSubject[], texts: readonly (DriftSubject & { text: string })[], facts: BrandFacts): Finding[] | undefined {
  const names = facts.deprecated_names ?? {};
  if (Object.keys(names).length === 0 || texts.length === 0) return undefined;
  return texts.flatMap((subject) => {
    const hits = Object.keys(names).filter((old) => pySearch(wholeWordIgnoreCase(old), subject.text)).sort(compareCodePoints);
    const detail = `deprecated names: ${hits.map((h) => `${h} → ${names[h]}`).join(', ')}`;
    return hits.length ? [finding('naming', 'warning', subject, detail, hits)] : [];
  });
}

function pricing(_subjects: readonly DriftSubject[], texts: readonly (DriftSubject & { text: string })[], facts: BrandFacts): Finding[] | undefined {
  const prices = facts.current_prices ?? [];
  if (prices.length === 0 || texts.length === 0) return undefined;
  const current = new Set(prices.map((price) => price.replaceAll(' ', '')));
  return texts.flatMap((subject) => {
    const stale = without(pyFindall(PRICE, subject.text).map((p) => p.replaceAll(' ', '')), current);
    const detail = `prices not in the current price list: ${stale.join(', ')}`;
    return stale.length ? [finding('old_pricing', 'blocking', subject, detail, stale)] : [];
  });
}

const CHECKS: readonly (readonly [Category, Check])[] = [
  ['colors', colors],
  ['voice', voice],
  ['naming', naming],
  ['old_pricing', pricing],
];

function claims(subjects: readonly DriftSubject[]): Finding[] {
  return subjects
    .filter((s) => (s.unverified_claims ?? []).length > 0)
    .map((s) => finding('claims', 'blocking', s, 'uses unverified claims', s.unverified_claims));
}

function staleFacts(subjects: readonly DriftSubject[]): Finding[] {
  return subjects
    .filter((s) => s.status === 'invalidated' || s.status === 'review_required')
    .map((s) => finding('stale_product_facts', 'warning', s, `upstream changed; artifact is ${s.status}`));
}

function rights(subjects: readonly DriftSubject[]): Finding[] {
  return subjects.flatMap((s) => {
    const r = s.rights;
    if (r === undefined || r === null || truthy(r.ok)) return [];
    return [finding('expired_rights', 'blocking', s, strOf(r.reason))];
  });
}

function duplicates(subjects: readonly DriftSubject[]): Finding[] {
  const byHash = new Map<string, DriftSubject[]>();
  for (const s of subjects) if (s.content_hash) byHash.set(s.content_hash, [...(byHash.get(s.content_hash) ?? []), s]);
  return [...byHash.keys()].sort(compareCodePoints).flatMap((digest) => {
    const independent = (byHash.get(digest) as DriftSubject[]).filter((s) => !s.variant_of);
    return independent.length > 1
      ? independent.slice(1).map((s) => finding('duplicate_content', 'info', s, `identical content to ${(independent[0] as DriftSubject).artifact_id}`, [digest]))
      : [];
  });
}

function repetition(subjects: readonly DriftSubject[]): Finding[] {
  const uses = new Map<string, number>();
  for (const s of subjects) for (const ref of s.prompt_refs ?? []) uses.set(ref, (uses.get(ref) ?? 0) + 1);
  return [...uses.keys()].sort(compareCodePoints).flatMap((ref) => {
    const count = uses.get(ref) as number;
    if (count < 4) return [];
    const users = subjects.filter((s) => (s.prompt_refs ?? []).includes(ref));
    return [finding('creative_repetition', 'info', users[users.length - 1] as DriftSubject, `prompt ${ref} reused ${count} times; creative fatigue risk`, [ref])];
  });
}

function compareFindings(a: Finding, b: Finding): number {
  return (
    SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity] ||
    compareCodePoints(a.category, b.category) ||
    compareCodePoints(a.artifact_id, b.artifact_id)
  );
}

export function analyze(args: {
  readonly project_id: string;
  readonly tenant_id: string;
  readonly facts: BrandFacts;
  readonly subjects: Iterable<DriftSubject>;
}): BrandDriftReport {
  const subjects = [...args.subjects];
  const texts = subjects.filter((s): s is DriftSubject & { text: string } => Boolean(s.text));
  const findings: Finding[] = [];
  const evaluated = new Set<Category>(['claims', 'stale_product_facts', 'duplicate_content', 'creative_repetition']);
  for (const [category, check] of CHECKS) {
    const found = check(subjects, texts, args.facts);
    if (found !== undefined) evaluated.add(category);
    findings.push(...(found ?? []));
  }
  if (subjects.some((s) => s.rights !== undefined && s.rights !== null)) evaluated.add('expired_rights');
  findings.push(...claims(subjects), ...staleFacts(subjects), ...rights(subjects), ...duplicates(subjects), ...repetition(subjects));
  findings.sort(compareFindings);
  const refresh = sortedUnique(findings.filter((f) => f.severity !== 'info').map((f) => f.artifact_id));
  const notEvaluated = ALL_CATEGORIES.filter((category) => !evaluated.has(category));
  const body = { findings, refresh, not_evaluated: notEvaluated };
  return {
    project_id: args.project_id,
    tenant_id: args.tenant_id,
    brand_core_ref: args.facts.brand_core_ref ?? null,
    findings,
    refresh_candidates: refresh,
    not_evaluated: [...notEvaluated],
    autonomous_overwrites: 0,
    report_hash: canonicalSha256(body as unknown as PyJson),
  };
}
