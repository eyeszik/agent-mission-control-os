/**
 * Deterministic brand book rendering (`brandbook/render.py`): page packages -> self-contained HTML pages, byte for
 * byte. Nothing is clipped (no `overflow:hidden`); content is paginated by an estimate, and the Chromium measurement
 * and overflow ladder that follow stay in Python (they need a browser).
 */
import { markDataUri, type MarkAsset } from './assets';
import { HEX_COLOR, two, type Block, type BookPackage, type PagePackage } from './compiler';
import { printable } from './fields';
import { canonicalHash } from './hash';
import { PY_SPACE, cpLen, escapeHtml, formatG, pyStr, pyStrip, type PyValue } from './python';

export const RENDERER_VERSION = 'amc-brandbook-render/1.0.0';
export const PAGE_FORMATS: Readonly<Record<string, readonly [number, number]>> = {
  'a4-portrait': [794, 1123], 'a4-landscape': [1123, 794], 'letter-portrait': [816, 1056], 'letter-landscape': [1056, 816],
  '16x9': [1600, 900], square: [1080, 1080],
};
export const DEFAULT_FORMAT = 'a4-portrait';
export const MIN_FONT_PX = 10;
export const NEUTRAL: Readonly<Record<string, string>> = { ink: '#1a1a1a', paper: '#ffffff', accent: '#4a4a4a', muted: '#5c5c5c' };
const PAD = 56;
const HEAD = 64;
const FOOT = 44;

export type StyleFields = ReadonlyMap<string, PyValue>;

/** (name, width, height, provisional). */
export function pageFormat(fields: StyleFields): [string, number, number, boolean] {
  const value = fields.get('production.output.page_format');
  const known = typeof value === 'string' && Object.hasOwn(PAGE_FORMATS, value) ? PAGE_FORMATS[value] : undefined;
  if (typeof value === 'string' && known !== undefined) return [value, known[0], known[1], false];
  const [w, h] = PAGE_FORMATS[DEFAULT_FORMAT] ?? [794, 1123];
  return [DEFAULT_FORMAT, w, h, true];
}

/** Resolved style inputs, read from the pages' field states (first printable value per key wins). */
export function styleValues(book: BookPackage): Map<string, PyValue> {
  const fields = new Map<string, PyValue>();
  for (const page of book.pages) {
    for (const f of page.fields) {
      if (printable(f) && !fields.has(f.path)) fields.set(f.path, f.value);
    }
  }
  return fields;
}

const PALETTE_KEYS = ['ink', 'paper', 'accent', 'muted'] as const;

export function paletteFor(fields: StyleFields): [Record<string, string>, boolean] {
  const pal = new Map(PALETTE_KEYS.map((r) => [r, fields.get(`visual.color.${r}`)] as const));
  const hex = (v: PyValue | undefined): boolean => typeof v === 'string' && HEX_COLOR.test(v);
  if (!(hex(pal.get('ink')) && hex(pal.get('paper')))) return [{ ...NEUTRAL }, true];
  const out: Record<string, string> = {};
  for (const [r, v] of pal) out[r] = typeof v === 'string' ? v.toLowerCase() : (NEUTRAL[r] ?? '');
  return [out, false];
}

const FONT_NAME = /^[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}\n?$/;

/** A family name safe to place in CSS; anything else is not styled. */
export function fontName(name: unknown): string | null {
  return typeof name === 'string' && FONT_NAME.test(pyStrip(name)) ? pyStrip(name) : null;
}

function stack(name: unknown, generic: string): string {
  const safe = fontName(name);
  return safe ? `'${safe}', ${generic}` : generic;
}

export function css(fields: StyleFields, width: number, height: number): string {
  const [pal] = paletteFor(fields);
  const ink = pal['ink'] ?? '';
  const paper = pal['paper'] ?? '';
  const accent = pal['accent'] ?? '';
  const display = stack(fields.get('visual.typography.display'), 'sans-serif');
  const body = stack(fields.get('visual.typography.body'), 'sans-serif');
  return (
    `@page{size:${width}px ${height}px;margin:0}`
    + 'html,body{margin:0;background:#808080;}'
    + `.page{box-sizing:border-box;position:relative;width:${width}px;height:${height}px;margin:0 auto 24px;`
    + `padding:${HEAD}px ${PAD}px ${FOOT}px;background:${paper};color:${ink};font-family:${body};font-size:15px;`
    + 'line-height:1.5;page-break-after:always;break-after:page}'
    + `.ph{position:absolute;top:20px;left:${PAD}px;right:${PAD}px;display:flex;gap:12px;font-size:12px;letter-spacing:.04em}`
    + `.pf{position:absolute;bottom:14px;left:${PAD}px;right:${PAD}px;display:flex;justify-content:space-between;font-size:11px}`
    + '.body{position:relative;height:100%;display:flex;flex-direction:column;gap:10px}'
    + `h1,.title{font-family:${display};font-size:48px;line-height:1.1;margin:0}`
    + `.subtitle{font-family:${display};font-size:26px;margin:0}.meta{font-size:13px;margin:0}`
    + '.lbl{font-size:12px;font-weight:700;margin:6px 0 0}.item{margin:0 0 0 16px}.text{margin:0}'
    + `.note{font-size:12px;margin:0}.status,.gap{font-size:13px;margin:0;padding:4px 8px;border:1px solid ${ink}}`
    + `.gap{border-style:dashed}.deco{height:6px;width:96px;background:${accent}}`
    + '.group{display:flex;flex-wrap:wrap;gap:16px;align-items:flex-end}'
    + '.fig{display:flex;flex-direction:column;gap:4px;font-size:12px}'
    + `.sw{width:120px;font-size:12px}.sw div{height:72px;border:1px solid ${ink}}`
    + `table{border-collapse:collapse;font-size:12px;width:100%}th,td{border:1px solid ${ink};padding:3px 6px;`
    + 'text-align:left;vertical-align:top;overflow-wrap:anywhere}'
    + `.wm{font-family:${display};font-size:44px;margin:0}.spec{font-size:34px;margin:0}`
    + `.reverse{background:${ink};padding:12px}.busy{padding:12px;background:repeating-linear-gradient(45deg,`
    + `${accent} 0 8px,${paper} 8px 16px)}`
    + '.no-deco .deco{display:none}.no-optional .optional{display:none}'
    + '@media print{html,body{background:none}.page{margin:0}}'
  );
}

// --------------------------------------------------------------------------- estimation and pagination

function lines(text: string, size: number, width: number): number {
  return Math.max(1, Math.ceil(cpLen(text) * size * 0.56 / Math.max(width, 1)));
}

function str(block: Block, key: string): string {
  return pyStr(block[key]);
}

function arr(block: Block, key: string): readonly PyValue[] {
  const value = block[key];
  return Array.isArray(value) ? value : [];
}

const COPY_SIZE: Readonly<Record<string, number>> = { title: 48, subtitle: 26, wordmark: 44, meta: 13 };
const TEXT_BLOCKS = new Set(['note', 'status', 'gap', 'asset_meta', 'asset_missing', 'handoff', 'example']);
const FIXED: Readonly<Record<string, number>> = { label: 26, deco: 16, lockup: 140, specimen: 60 };

function tableHeight(block: Block, width: number): number {
  const cell = width / Math.max(1, arr(block, 'columns').length);
  const rows = arr(block, 'rows').map((row) => {
    const cells = Array.isArray(row) ? row : [];
    return Math.max(...cells.map((c: PyValue) => lines(pyStr(c), 12, cell - 12))) * 18 + 8;
  });
  return 26 + rows.reduce((a, b) => a + b, 0);
}

export function estimate(block: Block, width: number): number {
  const t = str(block, 't');
  if (t === 'copy') {
    const role = str(block, 'role');
    const size = COPY_SIZE[role] ?? 15;
    return lines(str(block, 'text'), size, width - (role === 'item' ? 16 : 0)) * size * 1.5 + 4;
  }
  if (TEXT_BLOCKS.has(t)) return lines(str(block, 'text'), 13, width) * 20 + 12;
  if (t === 'table') return tableHeight(block, width);
  if (t === 'legend') return 22 * arr(block, 'items').length;
  return FIXED[t] ?? 0;
}

function groupKey(block: Block): string | null {
  const t = str(block, 't');
  return t === 'asset' || t === 'swatch' || t === 'misuse' ? t : null;
}

function num(block: Block, key: string): number {
  const v = block[key];
  return typeof v === 'number' ? v : 0;
}

function assetRunHeight(run: readonly Block[], width: number): number {
  let rowW = 0;
  let rowH = 0;
  let height = 0;
  for (const b of run) {
    const w = num(b, 'size') + 16;
    if (rowW + w > width && rowW) {
      height += rowH + 16;
      rowW = 0;
      rowH = 0;
    }
    rowW += w;
    const variant = str(b, 'variant');
    rowH = Math.max(rowH, num(b, 'size') + 24 + (variant === 'clearspace' || variant === 'reverse' ? 24 : 0));
  }
  return height + rowH;
}

function runHeight(key: string, run: readonly Block[], width: number): number {
  if (key === 'asset') return assetRunHeight(run, width);
  const per = Math.max(1, Math.floor(width / (key === 'swatch' ? 136 : 196)));
  return Math.ceil(run.length / per) * (key === 'swatch' ? 124 : 196);
}

/** Consecutive blocks with the same group key; a block without one is a run of its own. */
function runs(blocks: readonly Block[]): Array<[string | null, Block[]]> {
  const out: Array<[string | null, Block[]]> = [];
  for (const block of blocks) {
    const key = groupKey(block);
    const last = out[out.length - 1];
    if (key !== null && last !== undefined && last[0] === key) last[1].push(block);
    else out.push([key, [block]]);
  }
  return out;
}

/** Blocks grouped into layout units: a run of figures is one wrapping row group. */
function units(blocks: readonly Block[], width: number): Array<[Block[], number]> {
  return runs(blocks).map(([key, run]): [Block[], number] =>
    [run, key === null ? estimate(run[0] as Block, width) : runHeight(key, run, width)]);
}

class Paginator {
  readonly parts: Block[][] = [[]];
  used = 0;

  constructor(readonly avail: number, readonly inner: number) {}

  private current(): Block[] {
    return this.parts[this.parts.length - 1] as Block[];
  }

  private newPart(): void {
    this.parts.push([]);
    this.used = 0;
  }

  table(table: Block): void {
    const rows = [...arr(table, 'rows')];
    while (rows.length > 0) {
      const chunk: PyValue[] = [];
      while (rows.length > 0) {
        if (chunk.length > 0 && estimate({ ...table, rows: [...chunk, rows[0] as PyValue] }, this.inner) > this.avail - this.used) break;
        chunk.push(rows.shift() as PyValue);
      }
      this.current().push({ ...table, rows: chunk });
      this.used += estimate({ ...table, rows: chunk }, this.inner) + 10;
      if (rows.length > 0) this.newPart();
    }
  }

  unit(unit: Block[], h: number): void {
    if (unit.length === 1 && str(unit[0] as Block, 't') === 'table' && h > this.avail - this.used) {
      this.table(unit[0] as Block);
      return;
    }
    if (this.used + h > this.avail && this.current().length > 0) this.newPart();
    this.current().push(...unit);
    this.used += h + 10;
  }
}

/** Split a page's blocks into parts whose estimated height fits; tables split by rows. Nothing is dropped. */
export function paginate(page: PagePackage, width: number, height: number, capacity = 1.0): Block[][] {
  const inner = width - 2 * PAD;
  const pager = new Paginator((height - HEAD - FOOT) * capacity, inner);
  for (const [unit, h] of units(page.blocks, inner)) pager.unit(unit, h);
  return pager.parts;
}

// --------------------------------------------------------------------------- HTML

function img(mark: MarkAsset, size: number, alt: string, style = '', attrs = ''): string {
  return `<img class="mark" data-sha="${pyStr(mark.sha256)}" src="${pyStr(markDataUri(mark))}" width="${size}" height="${size}" `
    + `alt="${escapeHtml(alt)}" style="${style}"${attrs}>`;
}

const MISUSE_STYLE: Readonly<Record<string, string>> = {
  stretch: 'transform:scaleX(1.5) scaleY(.7);margin:0 28px', rotate: 'transform:rotate(18deg)',
  recolor: 'filter:hue-rotate(140deg) saturate(3)', effect: 'filter:drop-shadow(6px 6px 4px rgba(0,0,0,.6)) blur(.6px)',
  busy: '', crowd: '',
};

const WS = `[${PY_SPACE}]*`;
const NUMBER = '([0-9]+(?:\\.[0-9]+)?)';
const CLEAR_PX = new RegExp(`^${WS}${NUMBER}${WS}px${WS}$`, 'u');
// `re.I` on "x", "the", "mark" and "height": Python also folds K (U+212A), İ and ı.
const CLEAR_MARK = new RegExp(`^${WS}${NUMBER}${WS}[x×]${WS}(?:the[${PY_SPACE}]+)?mar[kK][${PY_SPACE}]+he[iİı]ght${WS}$`, 'iu');

/** A CSS padding for the approved clear space, only when the value is a number of px or of mark heights. */
export function clearspace(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const px = CLEAR_PX.exec(value);
  if (px) return `${formatG(Number(px[1]))}px`;
  const mh = CLEAR_MARK.exec(value);
  if (mh) return `calc(${formatG(Number(mh[1]))} * var(--mh))`;
  return null;
}

export { MISUSE_STYLE, img as markImg, two as pad2 };
export type { Block };
