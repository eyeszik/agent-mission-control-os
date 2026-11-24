/**
 * Block and page HTML (`render.block_html`, `_body`, `page_html`, `book_html`, `page_key_hash`), byte for byte.
 */
import { markDataUri, type MarkAsset } from './assets';
import { HEX_COLOR, two, type Block, type PagePackage } from './compiler';
import { canonicalHash } from './hash';
import { CanonicalFloat } from '@amc/canonical';
import { KeyError } from './fields';
import { escapeHtml, escapeStrict, pyStr, type PyValue } from './python';
import { MISUSE_STYLE, RENDERER_VERSION, clearspace, fontName, markImg, paginate, type StyleFields } from './render';

interface Ctx {
  readonly mark: MarkAsset;
  readonly brandName: string;
  readonly fields: StyleFields;
}

/** `b[key]`: Python's KeyError for a block that lacks the key. */
function get(b: Block, key: string): PyValue {
  const v = b[key];
  if (v === undefined) throw new KeyError(key);
  return v;
}

function s(b: Block, key: string): string {
  return pyStr(get(b, key));
}

/** `escape(b[key])`: `html.escape` raises on a value that is not a str. */
function esc(b: Block, key: string): string {
  return escapeStrict(get(b, key));
}

const COPY_CLASS: Readonly<Record<string, string>> = {
  title: 'title', subtitle: 'subtitle', meta: 'meta', item: 'item', wordmark: 'wm', caption: 'note',
};

function copyHtml(b: Block): string {
  const role = s(b, 'role');
  const tag = role === 'title' ? 'h1' : 'p';
  const flag = get(b, 'proposed') === true ? ' data-proposed="true"' : '';
  return `<${tag} class="${COPY_CLASS[role] ?? 'text'}" data-copy="${s(b, 'copy_id')}"${flag}>${esc(b, 'text')}</${tag}>`;
}

function pairs(value: PyValue | undefined): Array<[PyValue, PyValue]> {
  return (Array.isArray(value) ? value : []).map((item: PyValue) => {
    const pair = Array.isArray(item) ? item : [];
    return [pair[0] ?? null, pair[1] ?? null];
  });
}

function tableHtml(b: Block): string {
  const columns = Array.isArray(b['columns']) ? b['columns'] : [];
  const rows = Array.isArray(b['rows']) ? b['rows'] : [];
  const head = columns.map((c: PyValue) => `<th scope='col'>${escapeStrict(c)}</th>`).join('');
  const body = rows.map((row: PyValue) => '<tr>' + (Array.isArray(row) ? row : [])
    .map((c: PyValue) => `<td>${escapeHtml(pyStr(c))}</td>`).join('') + '</tr>').join('');
  return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

function specimenHtml(b: Block): string {
  const safe = fontName(b['family']);
  const style = safe ? ` style="font-family:'${safe}', sans-serif"` : '';
  return `<div class="fig"><p class="spec"${style}>Aa Bb Cc 0123456789 &amp; ?!</p>`
    + `<span>${esc(b, 'role')}: ${esc(b, 'family')}${b['approved'] === true ? '' : ' (proposed)'}</span></div>`;
}

function swatchHtml(b: Block): string {
  const value = s(b, 'value');
  if (!HEX_COLOR.test(value)) {
    return `<p class="status" data-status="INVALID">${esc(b, 'role')}: ${escapeHtml(value)} is not a #rrggbb colour</p>`;
  }
  return `<div class="sw"><div style="background:${value}"></div><b>${esc(b, 'role')}</b> `
    + `<span>${escapeHtml(value)}</span>${b['approved'] === true ? '' : ' (proposed)'}</div>`;
}

function truthy(value: PyValue | undefined): boolean {
  if (value instanceof CanonicalFloat) return value.value !== 0;
  if (Array.isArray(value)) return value.length > 0;
  if (value !== null && typeof value === 'object') return Object.keys(value).length > 0;
  return !(value === undefined || value === null || value === false || value === '' || value === 0);
}

function lockupHtml(b: Block, c: Ctx): string {
  const wm = c.fields.get('visual.logo.wordmark');
  const word = escapeHtml(truthy(wm) ? pyStr(wm) : c.brandName);
  if (markDataUri(c.mark) === null) return '<p class="status" data-status="MISSING">Lockup not drawn: no approved master.</p>';
  const arrangement = s(b, 'arrangement');
  const flow = arrangement === 'horizontal' ? 'row' : 'column';
  return `<div class="fig" style="flex-direction:${flow};align-items:center;gap:16px">`
    + `${markImg(c.mark, 96, arrangement + ' lockup mark')}<span class="wm" style="font-size:32px">${word}</span>`
    + `<span class="note">${escapeHtml(arrangement)} lockup</span></div>`;
}

function clearspaceInner(mark: MarkAsset, size: number, fields: StyleFields): string {
  const pad = clearspace(fields.get('visual.logo.clear_space'));
  if (pad === null) {
    return markImg(mark, size, 'master mark')
      + '<span class="note">Clear-space diagram not drawn: the approved rule is not a number of px or mark heights.</span>';
  }
  return `<div style="--mh:${size}px;padding:${pad};outline:1px dashed currentColor;display:inline-block">`
    + `${markImg(mark, size, 'master with approved clear space')}</div>`;
}

function assetInner(variant: string, size: number, cap: string, c: Ctx): string {
  const mark = c.mark;
  if (variant === 'silhouette') return markImg(mark, size, 'one-colour silhouette of the master', 'filter:brightness(0)');
  if (variant === 'reverse') {
    return `<div class="reverse">${markImg(mark, size, 'reverse silhouette of the master', 'filter:brightness(0) invert(1)')}</div>`;
  }
  if (variant === 'construction') {
    return `<div style="position:relative;width:${size}px;height:${size}px;outline:1px dashed currentColor">`
      + `${markImg(mark, size, 'master with canvas boundary and centre axes')}`
      + '<div style="position:absolute;left:50%;top:0;bottom:0;border-left:1px dotted currentColor"></div>'
      + '<div style="position:absolute;top:50%;left:0;right:0;border-top:1px dotted currentColor"></div></div>';
  }
  if (variant === 'clearspace') return clearspaceInner(mark, size, c.fields);
  return markImg(mark, size, 'master mark' + (cap ? ' at ' + cap : ''));
}

function assetHtml(b: Block, c: Ctx): string {
  if (markDataUri(c.mark) === null) return '<p class="status" data-status="MISSING">Master mark not approved.</p>';
  const size = Math.trunc(Number(b['size']));
  const caption = b['caption'];
  const cap = escapeHtml(truthy(caption) ? pyStr(caption) : '');
  return `<figure class="fig" style="margin:0">${assetInner(s(b, 'variant'), size, cap, c)}<figcaption>${cap}</figcaption></figure>`;
}

function misuseHtml(b: Block, c: Ctx): string {
  const transform = s(b, 'transform');
  const style = MISUSE_STYLE[transform];
  if (style === undefined) throw new KeyError(transform);
  let image = markImg(c.mark, 96, 'incorrect use: ' + transform, style, ' data-misuse="true"');
  if (transform === 'busy') image = `<div class="busy">${image}</div>`;
  if (transform === 'crowd') {
    image = `<div style="position:relative">${image}<span style="position:absolute;left:24px;right:0;top:28px;font-size:14px;`
      + `line-height:1.2">${escapeHtml(c.brandName)}</span></div>`;
  }
  return `<figure class="fig" data-misuse-figure="${transform}" style="margin:0;width:180px">${image}`
    + `<figcaption data-copy="${s(b, 'copy_id')}">${esc(b, 'text')}</figcaption></figure>`;
}

function statusHtml(b: Block, t: string): string {
  const status = b['status'] === undefined ? t : s(b, 'status');
  return `<p class="status" data-status="${escapeHtml(status)}">${esc(b, 'text')}</p>`;
}

type Renderer = (b: Block, c: Ctx, t: string) => string;

const RENDERERS: Readonly<Record<string, Renderer>> = {
  copy: (b) => copyHtml(b),
  label: (b) => `<p class="lbl">${esc(b, 'text')}</p>`,
  note: (b) => `<p class="note${b['optional'] === true ? ' optional' : ''}">${esc(b, 'text')}</p>`,
  status: (b, _c, t) => statusHtml(b, t), asset_meta: (b, _c, t) => statusHtml(b, t),
  handoff: (b, _c, t) => statusHtml(b, t), asset_missing: (b, _c, t) => statusHtml(b, t),
  gap: (b) => `<p class="gap" data-gap="${esc(b, 'path')}">${esc(b, 'text')}</p>`,
  example: (b) => `<p class="status" data-example="${esc(b, 'kind')}">${esc(b, 'text')}</p>`,
  deco: () => '<div class="deco" aria-hidden="true"></div>',
  wordmark: () => '',
  legend: (b) => '<dl>' + pairs(b['items']).map(([k, v]) => `<dt>${escapeStrict(k)}</dt><dd>${escapeStrict(v)}</dd>`).join('') + '</dl>',
  table: (b) => tableHtml(b), specimen: (b) => specimenHtml(b), swatch: (b) => swatchHtml(b),
  lockup: (b, c) => lockupHtml(b, c), asset: (b, c) => assetHtml(b, c), misuse: (b, c) => misuseHtml(b, c),
};

export function blockHtml(b: Block, mark: MarkAsset, brandName: string, fields: StyleFields): string {
  const t = s(b, 't');
  const render = Object.hasOwn(RENDERERS, t) ? RENDERERS[t] : undefined;
  return render === undefined ? '' : render(b, { mark, brandName, fields }, t);
}

function groupKey(b: Block): string | null {
  const t = s(b, 't');
  return t === 'asset' || t === 'swatch' || t === 'misuse' ? t : null;
}

function bodyHtml(blocks: readonly Block[], c: Ctx): string {
  const out: string[] = [];
  let i = 0;
  while (i < blocks.length) {
    const key = groupKey(blocks[i] as Block);
    if (key === null) {
      out.push(blockHtml(blocks[i] as Block, c.mark, c.brandName, c.fields));
      i += 1;
      continue;
    }
    const run: string[] = [];
    while (i < blocks.length && groupKey(blocks[i] as Block) === key) {
      run.push(blockHtml(blocks[i] as Block, c.mark, c.brandName, c.fields));
      i += 1;
    }
    out.push(`<div class="group" data-group="${key}">${run.join('')}</div>`);
  }
  return out.join('');
}

export interface PageHtmlOptions {
  readonly mark: MarkAsset;
  readonly brandName: string;
  readonly fields: StyleFields;
  readonly width: number;
  readonly height: number;
  readonly total: number;
  /** 1 hides decoration, 2 also optional annotations. */
  readonly step?: number;
  readonly capacity?: number;
}

function sectionHtml(page: PagePackage, key: string, cont: string, classes: string, body: string, o: PageHtmlOptions): string {
  return `<section class="${classes}" data-page="${key}" data-order="${page.order}" data-status="${page.status}">`
    + `<header class="ph"><span>${two(page.order)}</span><span>${escapeHtml(page.title)}${cont}</span></header>`
    + `<div class="body">${body}</div>`
    + `<footer class="pf"><span>${escapeHtml(o.brandName)}</span><span>Page ${two(page.order)} of ${two(o.total)}${cont}</span>`
    + `<span>Status: ${escapeHtml(page.status)}</span></footer></section>`;
}

/** [(part_key, section_html)] for one page. */
export function pageHtml(page: PagePackage, o: PageHtmlOptions): Array<[string, string]> {
  const step = o.step ?? 0;
  const parts = paginate(page, o.width, o.height, o.capacity ?? 1.0);
  const classes = 'page' + (step >= 1 ? ' no-deco' : '') + (step >= 2 ? ' no-optional' : '');
  const c: Ctx = { mark: o.mark, brandName: o.brandName, fields: o.fields };
  return parts.map((blocks, i): [string, string] => {
    const n = i + 1;
    const key = n === 1 ? page.page_id : `${page.page_id}-${n}`;
    const cont = parts.length > 1 ? ` (continued ${n}/${parts.length})` : '';
    return [key, sectionHtml(page, key, cont, classes, bodyHtml(blocks, c), o)];
  });
}

export function bookHtml(sections: readonly string[], title: string, style: string): string {
  return `<!doctype html><html lang='en'><head><meta charset='utf-8'><title>${escapeHtml(title)}</title>`
    + `<style>${style}</style></head><body>${sections.join('')}</body></html>`;
}

export function pageKeyHash(section: string, style: string): string {
  return canonicalHash({ renderer: RENDERER_VERSION, section, style });
}
