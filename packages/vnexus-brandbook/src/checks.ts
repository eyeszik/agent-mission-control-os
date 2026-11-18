/**
 * Page checks (`brandbook/checks.py`): measured layout facts in, check results out. A check that could not run is
 * NOT_RUN, never PASSED. The Chromium measurement itself stays in Python; the twin takes its output as typed input.
 */
import type { MarkAsset } from './assets';
import { wcagContrastRatio } from './contrast';
import type { CheckResult, PagePackage } from './compiler';
import { unresolvedTokens } from './fields';
import type { Mode } from './manifest';
import { cpSlice, pyFloatStr, pyRepr, type PyValue } from './python';

export const VALIDATOR_VERSION = 'amc-brandbook-checks/1.0.0';

/** One part of a page as `browser_runner.cjs` `layout` mode reports it. */
export interface PageMeasurement {
  readonly id: string;
  readonly overflow_count: number;
  readonly overflow: readonly string[];
  readonly clipped: readonly string[];
  readonly small: readonly string[];
  readonly overlaps: readonly string[];
  readonly copies: { readonly [copyId: string]: string };
  readonly marks: ReadonlyArray<{ readonly sha: string | null; readonly misuse: boolean; readonly loaded: boolean }>;
  readonly status_labelled: boolean;
  readonly footer: string;
}

function check(pageId: string, name: string, status: string, detail: string, severity = 'ERROR'): CheckResult {
  return { page_id: pageId, check: name, status, detail: cpSlice(detail, 0, 400), severity };
}

function head<T>(items: readonly T[], n: number): T[] {
  return items.slice(0, n);
}

/** `f"{list[:5]}"` for a list of strings. */
function listRepr(items: readonly string[]): string {
  return pyRepr(items as PyValue);
}

function tokenCheck(page: PagePackage, tokens: readonly string[], mode: Mode): CheckResult {
  const pid = page.page_id;
  if (mode === 'PRODUCTION') {
    const bad = tokens.length > 0 || page.gaps.length > 0;
    return check(pid, 'no_unresolved_tokens', bad ? 'FAILED' : 'PASSED',
      bad ? `unresolved: ${listRepr(head(tokens, 5))}; gaps: ${listRepr(head(page.gaps.map((g) => g.path), 5))}` : 'none');
  }
  return check(pid, 'no_unresolved_tokens', tokens.length === 0 ? 'PASSED' : 'FAILED',
    `labelled gaps: ${page.gaps.length}; raw tokens: ${listRepr(head(tokens, 5))}`, 'WARNING');
}

/** Checks that need no browser: unresolved tokens, text contrast of the page colours, labelled status. */
export function staticChecks(page: PagePackage, sections: ReadonlyArray<readonly [string, string]>, options: {
  readonly mode: Mode; readonly palette: Readonly<Record<string, string>>; readonly neutral: boolean;
}): CheckResult[] {
  const html = sections.map(([, s]) => s).join('');
  const text = html.replace(/<[^>]+>/g, ' ');
  const ink = options.palette['ink'] ?? '';
  const paper = options.palette['paper'] ?? '';
  const ratio = wcagContrastRatio(ink, paper);
  return [tokenCheck(page, unresolvedTokens(text), options.mode),
    check(page.page_id, 'text_contrast', ratio >= 4.5 ? 'PASSED' : 'FAILED',
      `body text ${ink} on ${paper} = ${pyFloatStr(ratio)}:1 (WCAG 2.2 AA 4.5:1)`
      + (options.neutral ? '; neutral rendering colours (no approved palette)' : ''))];
}

const NOT_RUN_CHECKS = ['no_overflow', 'exact_copy', 'min_font', 'no_overlap', 'mark_continuity', 'status_labelled', 'footer'];

function overflowCheck(pid: string, measured: readonly PageMeasurement[]): CheckResult {
  const over = measured.filter((m) => m.overflow_count).map((m) => `${m.id}: ${m.overflow_count} element(s) ${listRepr(head(m.overflow, 3))}`);
  const clipped = measured.filter((m) => m.clipped.length > 0).map((m) => `${m.id}: ${listRepr(head(m.clipped, 3))}`);
  const failed = over.length > 0 || clipped.length > 0;
  return check(pid, 'no_overflow', failed ? 'FAILED' : 'PASSED',
    [...over, ...clipped].join('; ') || `${measured.length} part(s) inside the page body`);
}

function copyCheck(page: PagePackage, measured: readonly PageMeasurement[]): CheckResult {
  const rendered = new Map<string, string>();
  for (const m of measured) for (const [k, v] of Object.entries(m.copies)) rendered.set(k, v);
  const missing = page.copy_blocks.filter((c) => !rendered.has(c.copy_id)).map((c) => c.copy_id);
  const wrong = page.copy_blocks.filter((c) => rendered.has(c.copy_id) && rendered.get(c.copy_id) !== c.text).map((c) => c.copy_id);
  const bad = missing.length > 0 || wrong.length > 0;
  return check(page.page_id, 'exact_copy', bad ? 'FAILED' : 'PASSED', bad
    ? `missing ${listRepr(head(missing, 5))}, altered ${listRepr(head(wrong, 5))}` : `${page.copy_blocks.length} copy element(s) verbatim`);
}

function markCheck(pid: string, measured: readonly PageMeasurement[], mark: MarkAsset): CheckResult {
  const marks = measured.flatMap((m) => m.marks);
  const masters = marks.filter((x) => !x.misuse);
  let result: [string, string];
  if (mark.kind === 'MISSING') {
    result = marks.length === 0 ? ['PASSED', 'no master to place; none drawn'] : ['FAILED', 'a mark was drawn without an approved master'];
  } else {
    const bad = marks.filter((x) => x.sha !== mark.sha256 || !x.loaded);
    result = bad.length > 0 ? ['FAILED', `${bad.length} placement(s) not the canonical master or not loaded`]
      : ['PASSED', `${masters.length} master placement(s), ${marks.length - masters.length} labelled misuse view(s), `
        + `one source sha256 ${cpSlice(mark.sha256 ?? '', 0, 16)}`];
  }
  return check(pid, 'mark_continuity', result[0], result[1]);
}

function pad2(n: number): string {
  return String(n).padStart(2, '0');
}

/** Checks from the Chromium layout measurement of every part of one page. */
export function measuredChecks(page: PagePackage, measured: readonly PageMeasurement[], options: {
  readonly mark: MarkAsset; readonly total: number;
}): CheckResult[] {
  const pid = page.page_id;
  if (measured.length === 0) return NOT_RUN_CHECKS.map((name) => check(pid, name, 'NOT_RUN', 'page was not measured'));
  const small = measured.flatMap((m) => m.small);
  const overlaps = measured.flatMap((m) => m.overlaps);
  const footerText = `Page ${pad2(page.order)} of ${pad2(options.total)}`;
  const footersOk = measured.every((m) => m.footer.includes(footerText));
  return [overflowCheck(pid, measured), copyCheck(page, measured),
    check(pid, 'min_font', small.length > 0 ? 'FAILED' : 'PASSED', small.length > 0 ? `below minimum: ${listRepr(head(small, 5))}` : 'no text below the minimum'),
    check(pid, 'no_overlap', overlaps.length > 0 ? 'FAILED' : 'PASSED', overlaps.length > 0
      ? `overlapping blocks: ${listRepr(head(overlaps, 3))}` : 'no overlapping blocks'),
    markCheck(pid, measured, options.mark),
    check(pid, 'status_labelled', measured.every((m) => m.status_labelled) ? 'PASSED' : 'FAILED',
      'every status and gap has a text label (no colour-only meaning)'),
    check(pid, 'footer', footersOk ? 'PASSED' : 'FAILED', `footer reads page ${pad2(page.order)} of ${pad2(options.total)}`)];
}

export function summarize(checks: readonly CheckResult[]): Record<string, number> {
  const out: Record<string, number> = { PASSED: 0, FAILED: 0, NOT_RUN: 0, INCONCLUSIVE: 0 };
  for (const c of checks) out[c.status] = (out[c.status] ?? 0) + 1;
  return out;
}

export function blocking(checks: readonly CheckResult[]): CheckResult[] {
  return checks.filter((c) => (c.status === 'FAILED' || c.status === 'NOT_RUN') && c.severity === 'ERROR');
}

/** `measurement_for`: group the measured parts by page id (the part id before its first `-`). */
export function measurementFor(pageKeys: readonly string[], pages: readonly PageMeasurement[]): Map<string, PageMeasurement[]> {
  const by = new Map<string, PageMeasurement[]>();
  for (const m of pages) {
    const base = m.id.split('-')[0] ?? m.id;
    by.set(base, [...(by.get(base) ?? []), m]);
  }
  return new Map(pageKeys.map((k) => [k, by.get(k) ?? []] as const));
}
