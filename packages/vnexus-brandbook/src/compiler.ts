/**
 * Brand book compiler (`brandbook/compiler.py`): authorized brand projection + page manifest -> per-page packages and
 * readable prompts. Pure and deterministic; identical pinned inputs give identical packages and hashes.
 */
import { markPublic, type MarkAsset, type MarkPublic } from './assets';
import { wcagContrastRatio } from './contrast';
import { printable, stateOf, type EvidenceRecord, type FieldState, type Gap, type GenomeValues, type States } from './fields';
import { canonicalHash } from './hash';
import { DEFAULT_MANIFEST, manifestHash, type Mode, type PageManifest, type PageSpec } from './manifest';
import { cpSlice, pyFloatStr, pyStr, type PyValue } from './python';

export const COMPILER_VERSION = 'amc-brandbook-compiler/1.0.0';
export const COLOR_ROLES = ['ink', 'paper', 'accent', 'accent_2', 'muted'] as const;
export const SHARED_RULES: readonly string[] = [
  'Use only the values and assets listed for this page; never invent names, slogans, dates, clients, contacts or claims.',
  'Render exact copy verbatim: same characters, punctuation and case; do not translate, abbreviate or restyle it.',
  'Place the canonical master by its hash; never redraw, regenerate, recolour or retype the logo.',
  'Misuse specimens are labelled examples, never masters.',
  'Meaning is never carried by colour alone; every status has a text label.',
  'If content does not fit: remove decoration, then optional annotations, then continue on a new page. Never shrink text '
    + 'below the minimum size and never drop required content silently.',
];
export const SHARED_RULES_HASH = canonicalHash(SHARED_RULES);

export type Block = { readonly [key: string]: PyValue };
export interface CopyBlock {
  readonly copy_id: string;
  readonly text: string;
  readonly source: string;
  readonly proposed: boolean;
}

export interface BookContext {
  readonly brand_id: string;
  readonly brand_name: string;
  readonly genome_ref: string;
  readonly resolution_hash: string;
  readonly approved: GenomeValues;
  readonly sources: Readonly<Record<string, string>>;
  readonly proposed: GenomeValues;
  readonly proposal_ref: string | null;
  readonly evidence: readonly EvidenceRecord[];
  readonly mode: Mode;
  readonly locale: string;
  readonly mark: MarkAsset;
  readonly manifest: PageManifest;
}

type ContextInput = Pick<BookContext, 'brand_id' | 'brand_name' | 'genome_ref' | 'resolution_hash' | 'approved' | 'mode' | 'mark'>
  & Partial<BookContext>;

/** A `BookContext` with Python's defaults filled in. */
export function bookContext(input: ContextInput): BookContext {
  return { ...input, sources: input.sources ?? {}, proposed: input.proposed ?? {}, proposal_ref: input.proposal_ref ?? null,
    evidence: input.evidence ?? [], locale: input.locale ?? 'en', manifest: input.manifest ?? DEFAULT_MANIFEST };
}

export function contextHash(ctx: BookContext): string {
  return canonicalHash({ brand_id: ctx.brand_id, brand_name: ctx.brand_name, genome_ref: ctx.genome_ref,
    resolution_hash: ctx.resolution_hash, proposal_ref: ctx.proposal_ref, proposed: ctx.proposed, evidence: ctx.evidence,
    mode: ctx.mode, locale: ctx.locale, mark: markPublic(ctx.mark), manifest: manifestHash(ctx.manifest), compiler: COMPILER_VERSION });
}

export type PageStatus = 'READY' | 'DRAFT' | 'BLOCKED' | 'NOT_APPLICABLE' | 'NOT_IN_MODE';

export interface PagePackage {
  readonly page_id: string;
  readonly order: number;
  readonly title: string;
  readonly status: PageStatus;
  readonly blocks: readonly Block[];
  readonly copy_blocks: readonly CopyBlock[];
  readonly fields: readonly FieldState[];
  readonly gaps: readonly Gap[];
  readonly assets: readonly ({ readonly asset: 'mark' } & MarkPublic)[];
  readonly dependency_hash: string;
  readonly instructions: string;
  readonly package_hash: string;
}

export type BookStatus = 'READY' | 'DRAFT' | 'BLOCKED' | 'SPEC_ONLY';

export interface BookPackage {
  readonly schema_version: 'amc-vnexus-brandbook-package/v1';
  readonly brand_id: string;
  readonly brand_name: string;
  readonly genome_ref: string;
  readonly resolution_hash: string;
  readonly mode: Mode;
  readonly locale: string;
  readonly template_id: string;
  readonly template_version: string;
  readonly manifest_hash: string;
  readonly compiler_version: string;
  readonly shared_rules_hash: string;
  readonly context_hash: string;
  readonly mark: MarkPublic;
  readonly pages: readonly PagePackage[];
  readonly gaps: readonly Gap[];
  readonly status: BookStatus;
  readonly package_hash: string;
}

/** A check result as `checks.py` records it. */
export interface CheckResult {
  readonly page_id: string;
  readonly check: string;
  readonly status: string;
  readonly detail: string;
  readonly severity: string;
}

// --------------------------------------------------------------------------- helpers

export function label(path: string): string {
  const tail = path.split('.').slice(1);
  const words = (tail.length > 1 ? tail.slice(-2) : tail).join(' ').replace(/_/g, ' ');
  return cpSlice(words, 0, 1).toUpperCase() + cpSlice(words, 1);
}

export function two(n: number): string {
  return String(n).padStart(2, '0');
}

/** Accumulates blocks and copy for one page; copy ids are stable within the page. */
export class PageBuilder {
  readonly blocks: Block[] = [];
  readonly copy: CopyBlock[] = [];

  constructor(readonly spec: PageSpec, readonly states: States, readonly mode: Mode) {}

  private nextId(): string {
    return `${this.spec.id}-c${two(this.copy.length + 1)}`;
  }

  text(text: string, options: { role?: string; source?: string; proposed?: boolean } = {}): Block {
    const proposed = options.proposed ?? false;
    const cid = this.nextId();
    this.copy.push({ copy_id: cid, text, source: options.source ?? 'template', proposed });
    const block: Block = { t: 'copy', role: options.role ?? 'text', copy_id: cid, text, proposed };
    this.blocks.push(block);
    return block;
  }

  /** Copy that a figure block renders itself (so figures stay grouped). */
  caption(text: string): CopyBlock {
    const entry: CopyBlock = { copy_id: this.nextId(), text, source: 'template', proposed: false };
    this.copy.push(entry);
    return entry;
  }

  note(text: string, optional = true): void {
    this.blocks.push({ t: 'note', text, optional });
  }

  deco(): void {
    this.blocks.push({ t: 'deco' });
  }

  state(path: string): FieldState {
    return stateOf(this.states, path);
  }

  /** Print a key's value as copy, or its state as an annotation. Returns true when a value was printed. */
  field(path: string, heading?: string): boolean {
    const s = this.state(path);
    this.blocks.push({ t: 'label', text: heading || label(path), path });
    if (printable(s)) {
      this.printValue(path, s);
      return true;
    }
    this.annotate(path, s);
    return false;
  }

  private printValue(path: string, s: FieldState): void {
    const values: readonly PyValue[] = Array.isArray(s.value) ? s.value : [s.value];
    for (const v of values) this.text(pyStr(v), { role: values.length > 1 ? 'item' : 'text', source: path, proposed: !s.approved });
    if (!s.approved) this.blocks.push({ t: 'status', status: 'PROPOSED', text: 'Proposed, not approved' });
  }

  private annotate(path: string, s: FieldState): void {
    if (s.status === 'NONE') {
      this.blocks.push({ t: 'status', status: 'NONE', text: 'Decided: none' + (s.approved ? '' : ' (proposed)') });
    } else if (s.status === 'NOT_APPLICABLE') {
      this.blocks.push({ t: 'status', status: 'NOT_APPLICABLE', text: s.reason ? `Not applicable: ${s.reason}` : 'Not applicable' });
    } else if (this.mode !== 'PRODUCTION') {
      this.blocks.push({ t: 'gap', path, text: `Gap: ${path} is ${s.status.toLowerCase()}` });
    }
  }
}

export function markBlock(p: PageBuilder, mark: MarkAsset, options: { variant?: string; size?: number; caption?: string } = {}): void {
  if (mark.kind === 'MISSING') {
    p.blocks.push({ t: 'asset_missing', text: 'Master mark not approved: identity review required. Layout reserved; nothing drawn.' });
    return;
  }
  p.blocks.push({ t: 'asset', asset: 'mark', sha256: mark.sha256, variant: options.variant ?? 'master', size: options.size ?? 240,
    kind: mark.kind, caption: options.caption || '' });
}

export function wordmark(p: PageBuilder, brandName: string): void {
  const s = p.state('visual.logo.wordmark');
  if (printable(s)) {
    const block = p.text(pyStr(s.value), { role: 'wordmark', source: 'visual.logo.wordmark', proposed: !s.approved });
    p.blocks.push({ t: 'wordmark', copy_id: block['copy_id'] ?? null });
    return;
  }
  const block = p.text(brandName, { role: 'wordmark', source: 'brand.display_name' });
  p.blocks.push({ t: 'wordmark', copy_id: block['copy_id'] ?? null });
  p.note("Wordmark text is the brand's registered display name; no separate wordmark is approved.");
}

/** Python `^#[0-9a-fA-F]{6}$`: `$` also matches before one trailing newline. */
export const HEX_COLOR = /^#[0-9a-fA-F]{6}\n?$/;

/** Only well-formed #rrggbb values are colours; anything else is printed as text by `field` and never styled. */
export function palette(states: States): Map<string, [string, boolean]> {
  const out = new Map<string, [string, boolean]>();
  for (const role of COLOR_ROLES) {
    const s = stateOf(states, `visual.color.${role}`);
    if (printable(s) && typeof s.value === 'string' && HEX_COLOR.test(s.value)) out.set(role, [s.value.toLowerCase(), s.approved]);
  }
  return out;
}

export function known(states: States, path: string): boolean {
  return stateOf(states, path).status !== 'UNKNOWN';
}

export function contrastRows(pal: Map<string, [string, boolean]>): string[][] {
  const rows: string[][] = [];
  for (const [fg, [fgValue]] of pal) {
    for (const [bg, [bgValue]] of pal) {
      if (fg === bg) continue;
      const ratio = wcagContrastRatio(fgValue, bgValue);
      const verdict = ratio >= 4.5 ? 'AA text' : (ratio >= 3 ? 'AA large text only' : 'Fails AA: decoration only');
      rows.push([fg, bg, `${pyFloatStr(ratio)}:1`, verdict]);
    }
  }
  return rows;
}
