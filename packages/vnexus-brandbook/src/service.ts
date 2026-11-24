/**
 * The pure parts of `brandbook/service.py`: artifact key digests, page and package record bytes, the build status
 * rule, the grouped gap report and the identity-guidelines projection. Authorization, Project OS storage, the
 * process cache, Chromium measurement, approval and release stay in Python (they are I/O and authority).
 */
import { markAsset } from './assets';
import { compileBook } from './compile';
import { bookContext, type BookContext, type BookPackage, type CheckResult, type PagePackage } from './compiler';
import { bookHtml, pageHtml } from './html';
import { sha256, canonicalHash } from './hash';
import type { Gap } from './fields';
import type { Mode } from './manifest';
import { compareCodePoints, cpLen, pyJsonDumps, pyRepr, type PyValue } from './python';
import { css, pageFormat, styleValues } from './render';

export type Section = readonly [string, string];

export class ArtifactKeyError extends Error {
  override name = 'ValueError';
}

/** `hashlib.sha256(f"{brand}|{scope}|{ref}")[:12]`. */
export function scopeSlug(brandId: string, scope: string, scopeRef: string): string {
  return sha256(`${brandId}|${scope}|${scopeRef}`).slice(0, 12);
}

/** Project OS slugs keys to 64 characters, so keys are a short digest of (brand, scope, ref, mode). */
export function buildBase(brandId: string, scope: string, scopeRef: string, mode: Mode): string {
  return `vbb-${sha256(`${brandId}|${scope}|${scopeRef}|${mode}`).slice(0, 16)}`;
}

export function intakeName(brandId: string): string {
  return `vbb-${sha256(brandId).slice(0, 16)}-intake`;
}

/** `_put`'s refusal of a key whose `foundry-` form would be truncated and could collide. */
export function assertArtifactKey(name: string): void {
  if (cpLen(`foundry-${name}`) > 64) {
    throw new ArtifactKeyError(`artifact key ${pyRepr(name)} would be truncated by Project OS and could collide`);
  }
}

export function sectionsSha(sections: readonly Section[]): string {
  return canonicalHash(sections.map(([k, html]) => [k, html]));
}

/** One versioned record per page: its rendered sections and the checks measured on exactly those sections. */
export function pageRecord(page: PagePackage, sections: readonly Section[], checks: readonly CheckResult[], options: {
  readonly rendererVersion: string; readonly validatorVersion: string; readonly measured: boolean;
}): string {
  const doc = { schema_version: 'amc-vnexus-brandbook-page/v1', page_id: page.page_id, dependency_hash: page.dependency_hash,
    package_hash: page.package_hash, renderer_version: options.rendererVersion, validator_version: options.validatorVersion,
    measured: options.measured, sections: sections.map(([k, html]) => [k, html]), sections_sha256: sectionsSha(sections), checks };
  return pyJsonDumps(doc, { sortKeys: true, indent: 1, ensureAscii: false }) + '\n';
}

export function packageRecord(book: BookPackage): string {
  return pyJsonDumps(book, { sortKeys: true, indent: 2, ensureAscii: false }) + '\n';
}

export type BuildStatus = 'BLOCKED' | 'READY_FOR_APPROVAL' | 'PREVIEW_ONLY' | 'DRAFT';

/** The build status: only a PRODUCTION book that is READY with no blocking check is READY_FOR_APPROVAL. */
export function buildStatus(bookStatus: string, mode: Mode, blockingChecks: readonly CheckResult[]): BuildStatus {
  if (bookStatus === 'BLOCKED' || (mode === 'PRODUCTION' && blockingChecks.length > 0)) return 'BLOCKED';
  if (mode === 'PRODUCTION' && bookStatus === 'READY') return 'READY_FOR_APPROVAL';
  return mode === 'PREVIEW' ? 'PREVIEW_ONLY' : 'DRAFT';
}

export interface GapDecision {
  path: string;
  status: string;
  severity: string;
  pages: string[];
  consequence: string;
  next_action: string;
}

/** Field-level gaps grouped into decisions: what to answer, why it matters, which pages it unblocks. */
export function groupGaps(gaps: readonly Gap[]): GapDecision[] {
  const byPath = new Map<string, GapDecision>();
  for (const g of gaps) {
    const entry = byPath.get(g.path) ?? { path: g.path, status: g.status, severity: g.severity, pages: [],
      consequence: g.consequence, next_action: g.next_action };
    byPath.set(g.path, entry);
    entry.pages.push(g.page_id);
    if (g.severity === 'BLOCKING') entry.severity = 'BLOCKING';
  }
  return [...byPath.values()].sort((a, b) => Number(a.severity !== 'BLOCKING') - Number(b.severity !== 'BLOCKING')
    || b.pages.length - a.pages.length || compareCodePoints(a.path, b.path));
}

/**
 * The identity system's guidelines deliverable, rendered from the same compiler (approved values only).
 * Returns [html, width, height, status].
 */
export function guidelinesForIdentity(values: { readonly [path: string]: PyValue | undefined }, options: {
  readonly brandName: string; readonly brandId: string; readonly genomeRef: string; readonly resolutionHash: string;
  readonly markSvg: string | null;
}): [string, number, number, string] {
  const mark = options.markSvg
    ? markAsset({ kind: 'VECTOR', sha256: sha256(options.markSvg), svg: options.markSvg, approved: true, source: 'identity production master' })
    : markAsset({ kind: 'MISSING', source: 'no master' });
  const ctx: BookContext = bookContext({ brand_id: options.brandId, brand_name: options.brandName, genome_ref: options.genomeRef,
    resolution_hash: options.resolutionHash, approved: values, mode: 'PREVIEW', mark });
  const book = compileBook(ctx);
  const fields = styleValues(book);
  const [, width, height] = pageFormat(fields);
  const sections = book.pages.flatMap((pg) => pageHtml(pg, { mark, brandName: options.brandName, fields, width, height,
    total: book.pages.length }).map(([, s]) => s));
  return [bookHtml(sections, `${options.brandName} brand guidelines`, css(fields, width, height)), width, height, book.status];
}
