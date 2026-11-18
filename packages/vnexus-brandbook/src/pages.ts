/**
 * Page builders (`compiler._page_content`, `_contents`, `_release`): what each of the 24 template pages prints.
 * One function per page so each stays short; the dispatch table mirrors Python's `if pid == ...` chain.
 */
import type { MarkAsset } from './assets';
import {
  COLOR_ROLES, contrastRows, known, markBlock, palette, two, wordmark,
  type BookContext, type CheckResult, type PageBuilder, type PagePackage,
} from './compiler';
import { printable, stateOf, type States } from './fields';
import { applicabilityKey, type PageSpec } from './manifest';
import { cpSlice, pyStr, type PyValue } from './python';

type Builder = (p: PageBuilder, ctx: BookContext, states: States) => void;

function cover(p: PageBuilder, ctx: BookContext): void {
  p.text(ctx.brand_name, { role: 'title', source: 'brand.display_name' });
  p.text('Brand guidelines', { role: 'subtitle' });
  p.text(`Template ${ctx.manifest.template_id} ${ctx.manifest.template_version}`, { role: 'meta' });
  p.text(ctx.mode === 'PRODUCTION' ? 'Production build: approval is recorded on the build, not on this page'
    : 'Draft for review: not approved for release', { role: 'meta' });
  markBlock(p, ctx.mark, { size: 200 });
}

const PREMISE = ['strategy.positioning.statement', 'strategy.audience.primary', 'strategy.positioning.promise',
  'strategy.audience.needs', 'strategy.differentiation.statement', 'strategy.values.list', 'strategy.competitive_territory.summary'];
const VOICE = ['verbal.voice.tone', 'verbal.voice.register', 'verbal.tone.channels', 'verbal.vocabulary.prefer',
  'verbal.vocabulary.avoid', 'verbal.content_rules.claims'];

function fieldsIfDeclaredOrKnown(p: PageBuilder, states: States, paths: readonly string[]): void {
  for (const path of paths) {
    if (p.spec.required_paths.includes(path) || known(states, path)) p.field(path);
  }
}

function voice(p: PageBuilder, _ctx: BookContext, states: States): void {
  fieldsIfDeclaredOrKnown(p, states, VOICE);
  for (const [path, head] of [['verbal.messaging.write', 'Write'], ['verbal.messaging.avoid', 'Avoid']] as const) {
    if (known(states, path)) p.field(path, head);
  }
}

function joined(items: readonly string[]): string {
  return items.join('; ') || '-';
}

function evidence(p: PageBuilder, ctx: BookContext): void {
  if (ctx.evidence.length === 0) {
    p.blocks.push({ t: 'status', status: 'UNKNOWN', text: 'No intake evidence recorded for this brand.' });
  }
  const rows: PyValue[] = ctx.evidence.map((e) => [e.source_id, e.locator, e.evidence_class, joined(e.observations),
    joined(e.inferences), joined(e.unknowns), e.reuse, e.privacy]);
  if (rows.length > 0) {
    p.blocks.push({ t: 'table', columns: ['Source', 'Locator', 'Class', 'Observations', 'Inferences', 'Unknowns', 'Reuse', 'Privacy'],
      rows });
  }
  p.note('User-reported statements are not independent inspection. [PII] stays redacted; source compositions are evidence only.', false);
}

function overview(p: PageBuilder, ctx: BookContext, states: States): void {
  markBlock(p, ctx.mark, { size: 180 });
  wordmark(p, ctx.brand_name);
  for (const [role, [value, approved]] of palette(states)) p.blocks.push({ t: 'swatch', role, value, approved });
  for (const path of ['visual.typography.display', 'visual.typography.body']) p.field(path);
  p.note('Calibration page: approve this page first; later pages reuse its assets and layout.');
}

function primaryLogo(p: PageBuilder, ctx: BookContext, states: States): void {
  const mark = ctx.mark;
  markBlock(p, mark, { size: 320, caption: 'Master mark' });
  const sha = mark.sha256 ? ` · sha256 ${cpSlice(mark.sha256, 0, 16)}` : '';
  p.blocks.push({ t: 'asset_meta', text: `${mark.kind} · ${mark.source}${sha}` });
  wordmark(p, ctx.brand_name);
  if (known(states, 'visual.logo.placement')) p.field('visual.logo.placement');
}

function construction(p: PageBuilder, ctx: BookContext, states: States): void {
  markBlock(p, ctx.mark, { variant: 'construction', size: 320 });
  if (known(states, 'visual.logo.construction')) {
    p.field('visual.logo.construction');
    return;
  }
  p.note('Shown: the master\'s canvas boundary and centre axes. Optical construction is not recorded in the approved genome.', false);
}

function wordmarkPage(p: PageBuilder, ctx: BookContext, states: States): void {
  wordmark(p, ctx.brand_name);
  for (const path of ['visual.logo.wordmark_case', 'visual.logo.custom_lettering']) {
    if (known(states, path)) p.field(path);
  }
  p.note('Set in the approved display face as live text; custom lettering only if recorded above.');
}

function lockups(p: PageBuilder, ctx: BookContext, states: States): void {
  if (printable(stateOf(states, 'visual.logo.lockups'))) p.field('visual.logo.lockups');
  p.blocks.push({ t: 'lockup', arrangement: 'horizontal' });
  p.blocks.push({ t: 'lockup', arrangement: 'stacked' });
  wordmark(p, ctx.brand_name);
  markBlock(p, ctx.mark, { size: 120, caption: 'Symbol only' });
}

function clearSpace(p: PageBuilder, ctx: BookContext): void {
  const printed = p.field('visual.logo.clear_space');
  markBlock(p, ctx.mark, { variant: printed ? 'clearspace' : 'master', size: 220 });
  if (!printed) p.note('No clear-space rule is approved; no distance is shown or implied.', false);
  p.blocks.push({ t: 'example', kind: 'crowded', text: 'Incorrect: text crowding the mark' });
}

function scale(p: PageBuilder, ctx: BookContext): void {
  if (!p.field('visual.logo.min_size')) p.note('No minimum size is approved; sizes below are test renders, not a rule.', false);
  for (const size of [16, 32, 64, 128]) markBlock(p, ctx.mark, { variant: 'scale', size, caption: `${size} px` });
  p.note('Screen renders at CSS px. Physical-size print tests: NOT_RUN.', false);
}

function oneColour(p: PageBuilder, ctx: BookContext): void {
  markBlock(p, ctx.mark, { variant: 'silhouette', size: 160, caption: 'One colour' });
  markBlock(p, ctx.mark, { variant: 'reverse', size: 160, caption: 'Reverse' });
  p.note('Silhouettes are rendered from the master by a colour filter; no separate one-colour master is approved.', false);
}

const MISUSE: readonly (readonly [string, string])[] = [
  ['stretch', 'Do not stretch or squash'], ['rotate', 'Do not rotate'], ['recolor', 'Do not recolour outside the palette'],
  ['effect', 'Do not add effects'], ['busy', 'Do not place on busy backgrounds'], ['crowd', 'Do not crowd or rearrange'],
];

function misuse(p: PageBuilder, ctx: BookContext): void {
  const mark: MarkAsset = ctx.mark;
  if (mark.kind === 'MISSING') {
    markBlock(p, mark);
  } else {
    for (const [transform, text] of MISUSE) {
      const cap = p.caption(`Incorrect: ${text}`);
      p.blocks.push({ t: 'misuse', transform, sha256: mark.sha256, copy_id: cap.copy_id, text: cap.text });
    }
  }
  p.note('Misuse specimens are derived views for teaching; they are never stored or used as masters.', false);
}

function colour(p: PageBuilder, _ctx: BookContext, states: States): void {
  const pal = palette(states);
  for (const role of COLOR_ROLES) {
    const path = `visual.color.${role}`;
    const entry = pal.get(role);
    if (entry !== undefined) {
      p.blocks.push({ t: 'swatch', role, value: entry[0], approved: entry[1], path });
    } else if (p.spec.required_paths.includes(path) || known(states, path)) {
      p.field(path);
    }
  }
  const rows = contrastRows(pal);
  if (rows.length > 0) p.blocks.push({ t: 'table', columns: ['Foreground', 'Background', 'Contrast (WCAG 2.2)', 'Use'], rows });
  for (const path of ['visual.color.names', 'visual.color.usage']) {
    if (known(states, path)) p.field(path);
  }
}

function typography(p: PageBuilder, _ctx: BookContext, states: States): void {
  for (const [role, path] of [['display', 'visual.typography.display'], ['body', 'visual.typography.body']] as const) {
    const s = stateOf(states, path);
    if (printable(s)) p.blocks.push({ t: 'specimen', role, family: pyStr(s.value), approved: s.approved });
    p.field(path);
  }
  for (const path of ['visual.typography.license', 'visual.typography.fallback', 'visual.typography.languages', 'visual.typography.scale']) {
    if (path === 'visual.typography.license' || known(states, path)) p.field(path);
  }
  p.note('Font files are not embedded; previews use the installed face or a fallback, and say so in the release checks.', false);
}

function conditional(p: PageBuilder, _ctx: BookContext, states: States): void {
  const decision = stateOf(states, applicabilityKey(p.spec));
  if (decision.status === 'NOT_APPLICABLE') {
    p.blocks.push({ t: 'status', status: 'NOT_APPLICABLE', text: `Not applicable: ${decision.reason}` });
  }
  for (const path of p.spec.optional_paths) {
    if (known(states, path)) p.field(path);
  }
  if (p.spec.id === 'p22' && !known(states, 'visual.motion.reduced_motion') && decision.status !== 'NOT_APPLICABLE') {
    p.note('Reduced-motion rule not recorded.', false);
  }
}

function handoff(p: PageBuilder, ctx: BookContext, states: States): void {
  const mark = ctx.mark;
  p.note('Files below are the artifacts of this build; formats and licences come from the approved genome.', false);
  for (const path of p.spec.optional_paths) p.field(path);
  const rows: PyValue[] = [['Master mark', mark.kind, mark.sha256 ? cpSlice(mark.sha256, 0, 16) : 'missing', mark.source]];
  for (const [role, [value, approved]] of palette(states)) rows.push([`Colour ${role}`, 'token', value, approved ? 'approved' : 'proposed']);
  p.blocks.push({ t: 'table', columns: ['Item', 'Kind', 'Reference', 'Status'], rows });
  p.blocks.push({ t: 'handoff', text: 'Page artifacts and their hashes are listed in the build record.' });
}

const BUILDERS: Readonly<Record<string, Builder>> = {
  p01: (p, ctx) => cover(p, ctx),
  p03: (p, _ctx, states) => fieldsIfDeclaredOrKnown(p, states, PREMISE),
  p04: voice,
  p05: (p, ctx) => evidence(p, ctx),
  p06: overview, p07: primaryLogo, p08: construction, p09: wordmarkPage, p10: lockups,
  p11: (p, ctx) => clearSpace(p, ctx), p12: (p, ctx) => scale(p, ctx), p13: (p, ctx) => oneColour(p, ctx),
  p14: (p, ctx) => misuse(p, ctx), p15: colour, p16: typography,
  p17: conditional, p18: conditional, p19: conditional, p20: conditional, p21: conditional, p22: conditional,
  p23: handoff,
};

export function pageContent(p: PageBuilder, ctx: BookContext, states: States): void {
  BUILDERS[p.spec.id]?.(p, ctx, states);
}

export function contents(p: PageBuilder, pages: readonly PagePackage[], ctx: BookContext): void {
  const status = new Map(pages.map((pg) => [pg.page_id, pg.status] as const));
  const rows = ctx.manifest.pages.map((spec: PageSpec) => [two(spec.order), spec.title, status.get(spec.id) ?? 'ASSEMBLED']);
  p.blocks.push({ t: 'table', columns: ['Page', 'Section', 'Status'], rows });
  p.blocks.push({ t: 'legend', items: [['READY', 'all required values approved'], ['DRAFT', 'labelled gaps or proposals'],
    ['BLOCKED', 'a required value is missing'], ['NOT_APPLICABLE', 'approved decision']] });
  p.text(`Scope: genome ${ctx.genome_ref}`, { role: 'meta', source: 'build.genome_ref' });
}

function checkRows(checks: readonly CheckResult[]): PyValue[] {
  const rows: PyValue[] = checks.filter((c) => c.status !== 'PASSED').map((c) => [c.page_id, c.check, c.status, cpSlice(c.detail, 0, 120)]);
  return rows.length > 0 ? rows : [['all', `${checks.length} checks`, 'PASSED', 'no failing or unrun checks']];
}

export function release(p: PageBuilder, pages: readonly PagePackage[], ctx: BookContext, checks: readonly CheckResult[] | null): void {
  const gapRows: PyValue[] = pages.flatMap((pg) => pg.gaps).map((g) => [g.page_id, g.path, g.severity, g.next_action]);
  p.blocks.push({ t: 'table', columns: ['Page', 'Key', 'Severity', 'Next action'],
    rows: gapRows.length > 0 ? gapRows : [['-', '-', '-', 'No open gaps']] });
  if (checks === null) {
    p.blocks.push({ t: 'status', status: 'NOT_RUN', text: 'Checks: NOT_RUN (nothing rendered in this mode)' });
  } else {
    const failed = checks.filter((c) => c.status === 'FAILED').length;
    p.blocks.push({ t: 'table', columns: ['Page', 'Check', 'Status', 'Detail'], rows: checkRows(checks) });
    p.note(`${checks.length} checks, ${failed} failed.`, false);
  }
  p.text(`Genome ${ctx.genome_ref}`, { role: 'meta', source: 'build.genome_ref' });
  p.text(`Resolution ${cpSlice(ctx.resolution_hash, 0, 16)}`, { role: 'meta', source: 'build.resolution_hash' });
  p.note('Approval and release are recorded on the build, not printed here: a printed page is not an approval.', false);
}
