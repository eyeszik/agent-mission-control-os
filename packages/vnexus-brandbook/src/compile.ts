/**
 * `compile_page` / `compile_book` / `page_dependency_hash` / `standalone_prompt` (`brandbook/compiler.py`).
 * Each page carries its dependency hash; unchanged hashes are what the incremental build reuses.
 */
import { markPublic } from './assets';
import {
  COMPILER_VERSION, PageBuilder, SHARED_RULES, SHARED_RULES_HASH, contextHash,
  type BookContext, type BookPackage, type BookStatus, type CheckResult, type PagePackage, type PageStatus,
} from './compiler';
import { allPaths, fieldState, hasUnresolvedToken, pageGaps, stateOf, type FieldState, type Gap, type States } from './fields';
import { canonicalHash } from './hash';
import { STYLE_PATHS, applicabilityKey, dependencyPaths, manifestHash, sortedUnique, type PageSpec } from './manifest';
import { contents, pageContent, release } from './pages';

function copyLine(c: { copy_id: string; text: string; proposed: boolean }): string {
  return `  - [${c.copy_id}] "${c.text}"` + (c.proposed ? ' (proposed)' : '');
}

function instructions(spec: PageSpec, page: PageBuilder, ctx: BookContext, gaps: readonly Gap[]): string {
  const lines = [`PAGE ${spec.id} · ${spec.title} (${spec.order} of ${ctx.manifest.pages.length}) — brand book for ${ctx.brand_name}`,
    `Template ${ctx.manifest.template_id} ${ctx.manifest.template_version}; mode ${ctx.mode}; genome ${ctx.genome_ref}`,
    `Objective: ${spec.objective}`, 'Exact copy (verbatim, in this order):'];
  lines.push(...(page.copy.length > 0 ? page.copy.map(copyLine) : ['  (none)']));
  const placed = page.blocks.filter((b) => b['t'] === 'asset' || b['t'] === 'misuse');
  if (placed.length > 0) {
    lines.push(`Assets: canonical master mark ${ctx.mark.kind} sha256:${ctx.mark.sha256 ?? 'None'} (${ctx.mark.source}); `
      + `${placed.length} placement(s). Place it; do not redraw it.`);
  }
  if (spec.prohibitions.length > 0) lines.push('Prohibitions: ' + spec.prohibitions.join('; '));
  if (gaps.length > 0) lines.push('Gaps (label them; do not fill them): ' + gaps.map((g) => `${g.path} ${g.status}`).join('; '));
  lines.push(`Layout: ${spec.layout}. Checks: ${spec.checks.join(', ')}.`);
  return lines.join('\n');
}

/** A self-contained prompt for one page: the shared rules inlined, nothing that depends on conversation memory. */
export function standalonePrompt(page: PagePackage): string {
  return page.instructions + '\nRules:\n' + SHARED_RULES.map((r, i) => `  ${i + 1}. ${r}`).join('\n');
}

export function bookStates(ctx: BookContext): States {
  const proposed = ctx.mode !== 'PRODUCTION' ? ctx.proposed : {};
  return new Map(allPaths(ctx.manifest, STYLE_PATHS).map((path) => [path, fieldState(path, ctx.approved, proposed, ctx.sources)]));
}

export function pageDependencyHash(spec: PageSpec, ctx: BookContext, states: States, extra: unknown = null): string {
  const assets = spec.asset_refs.length > 0;
  const paths = sortedUnique([...dependencyPaths(spec), ...STYLE_PATHS, ...(assets ? ['visual.logo.wordmark'] : [])]);
  const fields: Record<string, FieldState> = {};
  for (const p of paths) fields[p] = stateOf(states, p);
  return canonicalHash({
    template: [ctx.manifest.template_id, ctx.manifest.template_version], spec, compiler: COMPILER_VERSION, mode: ctx.mode,
    locale: ctx.locale, brand_name: ctx.brand_name, fields, mark: assets ? markPublic(ctx.mark) : null,
    evidence: spec.evidence_refs ? ctx.evidence : null, extra,
  });
}

function tokenGap(spec: PageSpec): Gap {
  return { page_id: spec.id, path: 'copy', status: 'UNKNOWN', severity: 'BLOCKING', consequence: 'unresolved template token in copy',
    source: 'compiler', next_action: 'resolve the token' };
}

function pageStatus(spec: PageSpec, page: PageBuilder, ctx: BookContext, gaps: readonly Gap[]): PageStatus {
  const decision = spec.gap_behavior === 'DECIDE' ? stateOf(page.states, applicabilityKey(spec)) : undefined;
  if (decision !== undefined && decision.status === 'NOT_APPLICABLE' && (decision.approved || ctx.mode !== 'PRODUCTION')) {
    return 'NOT_APPLICABLE';
  }
  if (gaps.some((g) => g.severity === 'BLOCKING')) return 'BLOCKED';
  const draftAsset = spec.asset_refs.length > 0 && ctx.mark.kind !== 'VECTOR';
  return gaps.length > 0 || page.copy.some((c) => c.proposed) || draftAsset ? 'DRAFT' : 'READY';
}

function withHash<T extends object>(body: T): T & { package_hash: string } {
  return { ...body, package_hash: canonicalHash(body) };
}

function finish(spec: PageSpec, page: PageBuilder, ctx: BookContext, gaps: Gap[], dep: string): PagePackage {
  if (ctx.mode === 'PRODUCTION' && page.copy.some((c) => hasUnresolvedToken(c.text))) gaps.push(tokenGap(spec));
  return withHash({
    page_id: spec.id, order: spec.order, title: spec.title, status: pageStatus(spec, page, ctx, gaps), blocks: [...page.blocks],
    copy_blocks: [...page.copy], fields: dependencyPaths(spec).map((p) => stateOf(page.states, p)), gaps: [...gaps],
    assets: spec.asset_refs.length > 0 ? [{ asset: 'mark' as const, ...markPublic(ctx.mark) }] : [], dependency_hash: dep,
    instructions: instructions(spec, page, ctx, gaps),
  });
}

function notInMode(spec: PageSpec, dep: string): PagePackage {
  return { page_id: spec.id, order: spec.order, title: spec.title, status: 'NOT_IN_MODE', blocks: [], copy_blocks: [], fields: [],
    gaps: [], assets: [], dependency_hash: dep, instructions: '', package_hash: dep };
}

function missingMarkGap(spec: PageSpec, ctx: BookContext): Gap {
  return { page_id: spec.id, path: 'visual.logo.mark', status: 'UNKNOWN', severity: ctx.mode === 'PRODUCTION' ? 'BLOCKING' : 'MAJOR',
    consequence: 'no master to place', source: 'asset resolution', next_action: 'route to identity review: approve a master mark' };
}

export function compilePage(spec: PageSpec, ctx: BookContext, states: States): PagePackage {
  if (!spec.output_modes.includes(ctx.mode)) return notInMode(spec, pageDependencyHash(spec, ctx, states));
  const page = new PageBuilder(spec, states, ctx.mode);
  const gaps = pageGaps(spec, states, ctx.mode);
  if (spec.asset_refs.includes('mark') && ctx.mark.kind === 'MISSING' && spec.gap_behavior === 'BLOCK'
    && !gaps.some((g) => g.path === 'visual.logo.mark')) {
    gaps.push(missingMarkGap(spec, ctx));
  }
  pageContent(page, ctx, states);
  return finish(spec, page, ctx, gaps, pageDependencyHash(spec, ctx, states));
}

function bookHeader(ctx: BookContext): Omit<BookPackage, 'pages' | 'gaps' | 'status' | 'package_hash'> {
  return { schema_version: 'amc-vnexus-brandbook-package/v1', brand_id: ctx.brand_id, brand_name: ctx.brand_name,
    genome_ref: ctx.genome_ref, resolution_hash: ctx.resolution_hash, mode: ctx.mode, locale: ctx.locale,
    template_id: ctx.manifest.template_id, template_version: ctx.manifest.template_version, manifest_hash: manifestHash(ctx.manifest),
    compiler_version: COMPILER_VERSION, shared_rules_hash: SHARED_RULES_HASH, context_hash: contextHash(ctx), mark: markPublic(ctx.mark) };
}

function specOnly(ctx: BookContext, states: States): BookPackage {
  const gaps = ctx.manifest.pages.flatMap((spec) => pageGaps(spec, states, ctx.mode));
  return withHash({ ...bookHeader(ctx), pages: [], gaps, status: 'SPEC_ONLY' as const });
}

function summaryPage(spec: PageSpec, ctx: BookContext, states: States, others: readonly PagePackage[],
  checks: readonly CheckResult[] | null, dep: string): PagePackage {
  const page = new PageBuilder(spec, states, ctx.mode);
  const gaps = pageGaps(spec, states, ctx.mode);
  if (spec.id === 'p02') contents(page, others, ctx);
  else if (spec.id === 'p24') release(page, others, ctx, checks);
  else pageContent(page, ctx, states);
  return finish(spec, page, ctx, gaps, dep);
}

function bookStatus(ctx: BookContext, pages: readonly PagePackage[]): BookStatus {
  if (pages.some((pg) => pg.status === 'BLOCKED')) return 'BLOCKED';
  if (pages.some((pg) => pg.status === 'DRAFT') || ctx.mode !== 'PRODUCTION') return 'DRAFT';
  return 'READY';
}

export interface CompileOptions {
  /** Rendered check results for the release page (absent: NOT_RUN). */
  readonly checks?: readonly CheckResult[] | null;
  /** Dependency hash -> an already compiled package (identical inputs, so identical output). */
  readonly reuse?: ReadonlyMap<string, PagePackage>;
}

function summaryPages(ctx: BookContext, states: States, body: readonly PagePackage[], options: CompileOptions): PagePackage[] {
  const checks = options.checks ?? null;
  const others = [...body].sort((a, b) => a.order - b.order);
  const out: PagePackage[] = [];
  for (const spec of ctx.manifest.pages.filter((s) => s.reads_all_pages)) {
    const extra = { pages: others.map((pg) => [pg.page_id, pg.dependency_hash, pg.status]),
      checks: checks !== null && spec.id === 'p24' ? canonicalHash(checks) : null };
    const dep = pageDependencyHash(spec, ctx, states, extra);
    out.push(options.reuse?.get(dep) ?? summaryPage(spec, ctx, states, others, checks, dep));
  }
  return out;
}

/** Compile every page; contents and release pages are rebuilt from every other page's state. */
export function compileBook(ctx: BookContext, options: CompileOptions = {}): BookPackage {
  const states = bookStates(ctx);
  if (ctx.mode === 'SYSTEM_SPEC_ONLY') return specOnly(ctx, states);
  const body = ctx.manifest.pages.filter((s) => !s.reads_all_pages)
    .map((spec) => options.reuse?.get(pageDependencyHash(spec, ctx, states)) ?? compilePage(spec, ctx, states));
  const pages = [...body, ...summaryPages(ctx, states, body, options)].sort((a, b) => a.order - b.order);
  return withHash({ ...bookHeader(ctx), pages, gaps: pages.flatMap((pg) => pg.gaps), status: bookStatus(ctx, pages) });
}
