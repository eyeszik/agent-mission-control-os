import { describe, expect, it } from 'vitest';
import {
  PAGE_FORMATS, blockHtml, bookHtml, blocking, clearspace, compileBook, css, estimate, fontName, measuredChecks, measurementFor, pageFormat,
  pageHtml, pageKeyHash, paginate, paletteFor, pyJsonDumps, sha256, staticChecks, styleValues, summarize,
  type Block, type CheckResult, type MarkAsset, type Mode, type PageMeasurement, type PagePackage, type PyValue,
} from '../src/index';
import { contextFromSpec, dec, expectOutcome, fixture, list, markFromSpec, num, rec, specFields, str } from './helpers';

const compileCases = list(fixture['compile']).map(rec);

function rendered(spec: unknown, options: { step?: number; capacity?: number } = {}): { book: ReturnType<typeof compileBook>;
  sections: Map<string, Array<[string, string]>>; fields: Map<string, PyValue>; width: number; height: number; mark: MarkAsset } {
  const ctx = contextFromSpec(spec);
  const book = compileBook(ctx);
  const fields = styleValues(book);
  const [, width, height] = pageFormat(fields);
  const sections = new Map(book.pages.map((p) => [p.page_id, pageHtml(p, { mark: ctx.mark, brandName: ctx.brand_name, fields, width, height,
    total: book.pages.length, ...options })] as const));
  return { book, sections, fields, width, height, mark: ctx.mark };
}

describe('style helpers', () => {
  const style = rec(fixture['style']);

  it('parses clear space, font names, page formats and palettes the same way', () => {
    for (const [value, out] of list(style['clearspace']).map((r) => r as [unknown, unknown])) {
      expect(clearspace(dec(value)), JSON.stringify(value)).toBe(out);
    }
    for (const [value, out] of list(style['fonts']).map((r) => r as [unknown, unknown])) expect(fontName(dec(value)), JSON.stringify(value)).toBe(out);
    for (const [value, out] of list(style['formats']).map((r) => r as [unknown, unknown])) {
      expect(pageFormat(new Map([['production.output.page_format', dec(value)]])), JSON.stringify(value)).toEqual(out);
    }
    expect(pageFormat(new Map())).toEqual(style['no_format']);
    for (const [fields, out] of list(style['palettes']).map((r) => r as [Record<string, unknown>, unknown])) {
      expect(paletteFor(specFields(fields)), JSON.stringify(fields)).toEqual(dec(out));
    }
  });
});

describe('renderer', () => {
  it('reproduces CSS, page sections and the whole book HTML byte for byte', () => {
    for (const c of list(fixture['render']).map(rec)) {
      const spec = rec(compileCases[c['spec_index'] as number])['spec'];
      const { book, sections, fields, width, height } = rendered(spec);
      const label = `case ${c['spec_index']}`;
      expect(pageFormat(fields), label).toEqual(c['format']);
      expect(paletteFor(fields), label).toEqual(dec(c['palette']));
      const style = css(fields, width, height);
      expect(sha256(style), label).toBe(c['css_sha256']);
      expect(Object.fromEntries([...sections].map(([id, v]) => [id, v.map(([k, s]) => [k, sha256(s)])])), label).toEqual(c['sections']);
      const ctx = contextFromSpec(spec);
      const all = book.pages.flatMap((p) => (sections.get(p.page_id) ?? []).map(([, s]) => s));
      expect(sha256(bookHtml(all, `${ctx.brand_name} brand guidelines`, style)), label).toBe(c['book_sha256']);
      expect(all.slice(0, 3).map((s) => pageKeyHash(s, style)), label).toEqual(c['key_hashes']);
      if ('css' in c) {
        expect(style, label).toBe(c['css']);
        expect(Object.fromEntries(sections), label).toEqual(c['sections_full']);
      }
    }
  }, 120000);

  it('reproduces the overflow-ladder variants (decoration, optional notes, reduced capacity)', () => {
    const variants: Array<[string, { step?: number; capacity?: number }]> = [['step1', { step: 1 }], ['step2', { step: 2 }],
      ['cap', { capacity: 0.72 }], ['step3cap', { step: 2, capacity: 0.72 }]];
    for (const c of list(fixture['render']).map(rec).filter((x) => Object.keys(rec(x['variants'])).length > 0)) {
      const spec = rec(compileCases[c['spec_index'] as number])['spec'];
      for (const [name, options] of variants) {
        const { sections } = rendered(spec, options);
        expect(Object.fromEntries([...sections].map(([id, v]) => [id, v.map(([k, s]) => [k, sha256(s)])])), `${c['spec_index']} ${name}`)
          .toEqual(rec(c['variants'])[name]);
      }
    }
  }, 120000);

  it('paginates every page the same way at every format and capacity', () => {
    const p = rec(fixture['paginate']);
    const books = new Map(Object.entries(rec(p['specs'])).map(([g, spec]) => [g, compileBook(contextFromSpec(spec))] as const));
    for (const c of list(p['cases']).map(rec)) {
      const book = books.get(str(c['genome']));
      const [w, h] = PAGE_FORMATS[str(c['format'])] as readonly [number, number];
      const rows = (book?.pages ?? []).map((page) => {
        const parts = paginate(page, w, h, c['capacity'] as number);
        return [page.page_id, parts.map((x) => x.length), sha256(pyJsonDumps(parts as unknown as PyValue, { sortKeys: true }))];
      });
      expect(rows, `${c['genome']} ${c['format']} ${c['capacity']}`).toEqual(c['pages']);
    }
  }, 120000);

  it('estimates block heights exactly', () => {
    for (const c of list(fixture['estimate']).map(rec)) {
      for (const [w, out] of list(c['estimates']).map((r) => r as [number, unknown])) {
        expect(estimate(dec(c['block']) as Block, w), JSON.stringify(c['block'])).toBe(num(out));
      }
    }
  });

  it('renders each block type the same way, including unknown and hostile ones', () => {
    const rows = list(fixture['block_html']).map(rec);
    const sets = rec(rec(rows[0])['field_sets']);
    const marks: Record<string, MarkAsset> = {};
    for (const [name, m] of Object.entries(markSpecs())) marks[name] = markFromSpec(m);
    for (const c of rows.slice(1)) {
      const fields = specFields(rec(sets[str(c['fields'])]));
      expectOutcome(() => blockHtml(dec(c['block']) as Block, marks[str(c['mark'])] as MarkAsset, 'Brand <B>', fields), c['html'],
        JSON.stringify(c['block']), (actual, expected) => expect(actual).toBe(expected));
    }
  });
});

function markSpecs(): Record<string, Record<string, unknown>> {
  const byName: Record<string, Record<string, unknown>> = {};
  const wanted: Record<string, (m: Record<string, unknown>) => boolean> = {
    vector: (m) => m['kind'] === 'VECTOR', missing: (m) => m['kind'] === 'MISSING', proposed: (m) => m['kind'] === 'PROPOSED_CONCEPT',
    raster: (m) => m['kind'] === 'RASTER_IN_SVG',
  };
  for (const c of list(fixture['compile']).map(rec)) {
    const m = rec(rec(c['spec'])['mark']);
    for (const [name, test] of Object.entries(wanted)) if (!(name in byName) && test(m)) byName[name] = m;
  }
  return byName;
}

describe('page checks', () => {
  const ck = rec(fixture['checks']);
  const books = new Map<string, ReturnType<typeof rendered>>();
  const bookFor = (key: string): ReturnType<typeof rendered> => {
    const hit = books.get(key);
    if (hit) return hit;
    const made = rendered(rec(ck['specs'])[key]);
    books.set(key, made);
    return made;
  };
  const pageOf = (key: string, id: string): PagePackage => bookFor(key).book.pages.find((p) => p.page_id === id) as PagePackage;

  it('reproduces the static checks for every page', () => {
    for (const c of list(ck['static']).map(rec)) {
      const key = str(c['spec_key']);
      const mode = key.split('|')[1] as Mode;
      const sections = bookFor(key).sections.get(str(c['page_id'])) ?? [];
      expect(staticChecks(pageOf(key, str(c['page_id'])), sections, { mode, palette: c['palette'] as Record<string, string>,
        neutral: c['neutral'] as boolean }), `${key} ${c['page_id']}`).toEqual(c['result']);
    }
  }, 120000);

  it('reproduces the measured checks for every perturbed measurement', () => {
    for (const c of list(ck['measured']).map(rec)) {
      const key = str(c['spec_key']);
      const { mark } = bookFor(key);
      expect(measuredChecks(pageOf(key, str(c['page_id'])), dec(c['measured']) as unknown as PageMeasurement[], { mark, total: 24 }),
        `${key} ${c['page_id']} ${c['variant']}`).toEqual(c['result']);
    }
  }, 120000);

  it('reproduces static-check edge cases and the summary helpers', () => {
    const { book } = bookFor('minimal|PREVIEW');
    const stub = book.pages[0] as PagePackage;
    const texts = ['<p>{{x}}</p>', 'plain <b>@none</b>', 'ok'];
    let i = 0;
    for (const text of texts) {
      for (const mode of ['PRODUCTION', 'PREVIEW'] as Mode[]) {
        const outcome = list(ck['static_input_text'])[i++];
        expectOutcome(() => staticChecks(stub, [['p01', text]], { mode, palette: { ink: '#000000', paper: '#ffffff' }, neutral: false }), outcome,
          `${text} ${mode}`, (actual, expected) => expect(actual).toEqual(expected));
      }
    }
    const pairs = [['#777777', '#ffffff'], ['#767676', '#ffffff'], ['#000000', '#000000'], ['#ffffff', '#000000']];
    pairs.forEach(([ink, paper], n) => expectOutcome(() => staticChecks(stub, [], { mode: 'PREVIEW', palette: { ink: ink as string, paper: paper as string },
      neutral: true }), list(ck['static_contrast'])[n], `${ink} ${paper}`, (actual, expected) => expect(actual).toEqual(expected)));
    const misc = rec(fixture['misc_checks']);
    const rows: CheckResult[] = [];
    for (const status of ['PASSED', 'FAILED', 'NOT_RUN', 'INCONCLUSIVE', 'ODD']) {
      for (const severity of ['ERROR', 'WARNING']) rows.push({ page_id: 'p01', check: 'c', status, detail: 'd', severity });
    }
    expect(summarize(rows)).toEqual(misc['summary']);
    expect(blocking(rows)).toEqual(misc['blocking']);
    expect(summarize([])).toEqual(misc['summary_empty']);
    const [[keys, ids], expected] = misc['measurement_for'] as [[string[], string[]], Record<string, string[]>];
    const grouped = measurementFor(keys, ids.map((id) => ({ id }) as PageMeasurement));
    expect(Object.fromEntries([...grouped].map(([k, v]) => [k, v.map((m) => m.id)]))).toEqual(expected);
  });
});
