import { describe, expect, it } from 'vitest';
import {
  ArtifactKeyError, COMPILER_VERSION, DEFAULT_MANIFEST, RENDERER_VERSION, SHARED_RULES, SHARED_RULES_HASH, STYLE_PATHS, TEMPLATE_ID,
  TEMPLATE_VERSION, VALIDATOR_VERSION, allPaths, applicabilityKey, assertArtifactKey, bookStates, buildBase, buildStatus, classifySvg,
  compileBook, compilePage, contextHash, dependencyPaths, fieldState, groupGaps, guidelinesForIdentity, hasActiveContent, hasRaster,
  hasUnresolvedToken, intakeName, manifestHash, manifestPage, markDataUri, markPublic, packageRecord, pageGaps, pageManifest, pageRecord,
  pageSpec, printable, resolveMark, scopeSlug, sectionsSha, sha256, standalonePrompt, unresolvedTokens,
  type BookPackage, type Gap, type Mode, type PagePackage, type PageSpec,
} from '../src/index';
import { contextFromSpec, dec, expectOutcome, fixture, list, manifestFromDump, markFromSpec, rec, str } from './helpers';

const compileCases = list(fixture['compile']).map(rec);

describe('manifest', () => {
  const m = rec(fixture['manifest']);

  it('is the same 24-page template, hash and dependency sets', () => {
    expect(DEFAULT_MANIFEST).toEqual(dec(m['default']));
    expect(manifestHash(DEFAULT_MANIFEST)).toBe(m['hash']);
    expect(DEFAULT_MANIFEST.pages).toHaveLength(24);
    for (const p of DEFAULT_MANIFEST.pages) {
      expect(dependencyPaths(p), p.id).toEqual(rec(m['dependency_paths'])[p.id]);
      expect(applicabilityKey(p), p.id).toBe(rec(m['applicability_keys'])[p.id]);
    }
    expect([...STYLE_PATHS]).toEqual(m['style_paths']);
    expect([TEMPLATE_ID, TEMPLATE_VERSION]).toEqual(rec(fixture['versions'])['template']);
  });

  it('applies the same validator and lookup rules', () => {
    for (const [name, pages, expected] of list(m['validation']).map((r) => r as [string, unknown[], unknown])) {
      const run = (): string => manifestHash(pageManifest('t', '1', pages.map((p) => pageSpec(p as PageSpec))));
      if (typeof expected === 'string') expect(run(), name).toBe(expected);
      else expectOutcome(run, expected, name, () => undefined);
    }
    for (const [id, outcome] of list(m['page_lookup']).map((r) => r as [string, unknown])) {
      expectOutcome(() => manifestPage(DEFAULT_MANIFEST, id).title, outcome, id, (a, e) => expect(a).toBe(e));
    }
  });

  it('reproduces a custom manifest and its hash', () => {
    const custom = manifestFromDump(m['custom']);
    expect(custom).toEqual(dec(m['custom']));
    expect(manifestHash(custom)).toBe(m['custom_hash']);
  });
});

describe('field states, tokens and gaps', () => {
  it('decodes every approved/proposed combination', () => {
    for (const c of list(fixture['fields']).map(rec)) {
      const approved = c['approved'] === null ? {} : { k: dec(c['approved']) };
      const label = JSON.stringify(c);
      if ('state_no_proposed' in c) {
        expect(fieldState('k', approved), label).toEqual(dec(c['state_no_proposed']));
        continue;
      }
      const proposed = c['proposed'] === null ? {} : { k: dec(c['proposed']) };
      const state = fieldState('k', approved, proposed, rec(c['sources']) as Record<string, string>);
      expect(state, label).toEqual(dec(c['state']));
      expect(printable(state), label).toBe(c['printable']);
    }
  });

  it('finds the same unresolved template tokens', () => {
    for (const c of list(fixture['tokens']).map(rec)) {
      expect(unresolvedTokens(str(c['text'])), str(c['text'])).toEqual(c['found']);
      expect(hasUnresolvedToken(str(c['text'])), str(c['text'])).toBe(c['has']);
    }
  });

  it('reproduces every page gap for every genome scenario and mode', () => {
    for (const c of list(fixture['gaps']).map(rec)) {
      const ctx = contextFromSpec(c['spec']);
      const states = bookStates(ctx);
      for (const page of ctx.manifest.pages) {
        expect(pageGaps(page, states, ctx.mode), `${ctx.mode} ${page.id}`).toEqual(rec(c['gaps'])[page.id]);
      }
    }
  }, 60000);

  it('enumerates the same state paths', () => {
    expect(allPaths(DEFAULT_MANIFEST, STYLE_PATHS)).toEqual(rec(fixture['manifest'])['all_paths']);
  });
});

describe('canonical master resolution', () => {
  const assets = rec(fixture['assets']);

  it('matches the raster and active-content regexes, including Python IGNORECASE folds', () => {
    for (const c of list(assets['regex']).map(rec)) {
      expect(hasRaster(str(c['text'])), str(c['text'])).toBe(c['raster']);
      expect(hasActiveContent(str(c['text'])), str(c['text'])).toBe(c['active']);
      expect(classifySvg(str(c['text'])), str(c['text'])).toBe(c['kind']);
    }
  });

  it('resolves every master scenario the same way', () => {
    const marks = rec(assets['marks']);
    const masters = new Map<string, Uint8Array>();
    for (const [k, v] of Object.entries(rec(marks['masters']))) masters.set(k, Uint8Array.from(atob(str(v)), (ch) => ch.charCodeAt(0)));
    for (const [k, pad] of Object.entries(rec(marks['generated_masters']))) {
      const svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 8"><circle cx="4" cy="4" r="3" fill="#112233"/></svg>';
      masters.set(k, new TextEncoder().encode(svg.replace('<circle', ' '.repeat(pad as number) + '<circle')));
    }
    const composed = rec(marks['composed']) as Record<string, string>;
    for (const c of list(marks['cases']).map(rec)) {
      const states = new Map(['visual.logo.master_artifact', 'visual.logo.master_sha256', 'visual.logo.mark']
        .map((p) => [p, fieldState(p, dec(c['approved']) as never, dec(c['proposed']) as never, {})] as const));
      const safety = rec(c['safety']);
      const mark = resolveMark(states, {
        composeMark: (id) => composed[id] ?? null, loadMaster: (ref) => masters.get(ref) ?? null,
        svgSafety: (text) => {
          const [passed, detail] = safety[sha256(text)] as [boolean, string];
          return { passed, detail };
        },
      });
      const label = JSON.stringify(c['approved']) + JSON.stringify(c['proposed']);
      expect(mark, label).toEqual(c['mark']);
      expect(markPublic(mark), label).toEqual(c['public']);
      expect(markDataUri(mark), label).toBe(c['data_uri']);
    }
  });
});

function bookOf(spec: unknown): { ctx: ReturnType<typeof contextFromSpec>; book: BookPackage } {
  const ctx = contextFromSpec(spec);
  return { ctx, book: compileBook(ctx) };
}

describe('page compiler', () => {
  it('reproduces every book: hashes, statuses, gaps, page rows and prompts', () => {
    for (const c of compileCases) {
      const { ctx, book } = bookOf(c['spec']);
      const plain = rec(c['plain']);
      const label = `${ctx.mode} ${ctx.manifest.template_id}`;
      expect(book.package_hash, label).toBe(plain['package_hash']);
      expect(contextHash(ctx), label).toBe(plain['context_hash']);
      expect(book.status, label).toBe(plain['status']);
      expect(book.gaps.length, label).toBe(plain['gap_count']);
      expect(book.pages.map((p) => [p.page_id, p.status, p.dependency_hash, p.package_hash, p.gaps.length, p.copy_blocks.length, p.blocks.length]), label)
        .toEqual(plain['pages']);
      expect(sha256(book.pages.map(standalonePrompt).join('\u0000')), label).toBe(plain['prompts_sha256']);
      if ('package' in plain) {
        expect(book, label).toEqual(dec(plain['package']));
        expect(book.pages.map(standalonePrompt), label).toEqual(plain['prompts']);
      }
    }
  }, 120000);

  it('feeds checks to the release page and reuses pages by dependency hash', () => {
    for (const c of compileCases.filter((x) => 'with_checks' in x)) {
      const { ctx, book } = bookOf(c['spec']);
      const checks = list(c['with_checks_input']) as never[];
      const withChecks = compileBook(ctx, { checks });
      expect(withChecks.package_hash).toBe(rec(c['with_checks'])['package_hash']);
      expect(withChecks.status).toBe(rec(c['with_checks'])['status']);
      const reuse = new Map(book.pages.map((p) => [p.dependency_hash, p] as const));
      expect(compileBook(ctx, { reuse }).package_hash).toBe(c['reuse_same']);
      const fake = new Map(list(c['reuse_fake_input']).map((r) => [(r as [string, unknown])[0], dec((r as [string, unknown])[1]) as unknown as PagePackage] as const));
      expect(compileBook(ctx, { reuse: fake }).package_hash).toBe(c['reuse_fake_hash']);
    }
  }, 120000);

  it('raises Python\'s KeyError for every missing declared key, and compiles when the key is not read', () => {
    const ctx = contextFromSpec(fixture['rich_preview_spec']);
    const states = bookStates(ctx);
    for (const c of list(fixture['missing_keys']).map(rec)) {
      const partial = new Map([...states].filter(([k]) => k !== c['missing']));
      const page = manifestPage(ctx.manifest, str(c['page_id']));
      expectOutcome(() => compilePage(page, ctx, partial).package_hash, c['result'], `${c['page_id']} without ${c['missing']}`,
        (actual, expected) => expect(actual).toBe(expected));
    }
  });

  it('fails the same way on a manifest page that does not declare the wordmark key', () => {
    for (const c of list(fixture['bad_manifest']).map(rec)) {
      expectOutcome(() => compileBook(contextFromSpec(c['spec'])).package_hash, c['result'], 'bad manifest',
        (actual, expected) => expect(actual).toBe(expected));
    }
  });

  it('carries the same versions, shared rules and hash', () => {
    const v = rec(fixture['versions']);
    expect(COMPILER_VERSION).toBe(v['compiler']);
    expect(RENDERER_VERSION).toBe(v['renderer']);
    expect(VALIDATOR_VERSION).toBe(v['validator']);
    expect([...SHARED_RULES]).toEqual(v['shared_rules']);
    expect(SHARED_RULES_HASH).toBe(v['shared_rules_hash']);
  });
});

describe('build service helpers', () => {
  const svc = rec(fixture['service']);

  it('derives the same artifact key digests and refuses over-long keys', () => {
    for (const c of list(svc['slugs']).map(rec)) {
      expect(scopeSlug(str(c['brand']), str(c['scope']), str(c['ref']))).toBe(c['slug']);
      expect(buildBase(str(c['brand']), str(c['scope']), str(c['ref']), c['mode'] as Mode)).toBe(c['base']);
      expect(intakeName(str(c['brand']))).toBe(c['intake']);
    }
    for (const [key, result] of list(svc['keys']).map((r) => r as [string, unknown])) {
      if (result === 'ok') expect(() => assertArtifactKey(key), key).not.toThrow();
      else expectOutcome(() => assertArtifactKey(key), { error: result }, key, () => undefined);
    }
    expect(() => assertArtifactKey('x'.repeat(60))).toThrow(ArtifactKeyError);
  });

  it('writes the same page records, section digests and package bytes', () => {
    const page = dec(svc['page_for_record']) as unknown as PagePackage;
    for (const c of list(svc['records']).map(rec)) {
      const sections = list(c['sections']) as Array<[string, string]>;
      expect(sectionsSha(sections)).toBe(c['sections_sha']);
      expect(pageRecord(page, sections, list(c['checks']) as never[], { rendererVersion: RENDERER_VERSION, validatorVersion: VALIDATOR_VERSION,
        measured: c['measured'] as boolean })).toBe(c['bytes']);
    }
    const { book } = bookOf(fixture['rich_preview_spec']);
    expect(sha256(packageRecord(book))).toBe(svc['package_bytes_sha256']);
  });

  it('renders the same identity guidelines', () => {
    for (const c of list(svc['guidelines']).map(rec)) {
      const [html, w, h, status] = guidelinesForIdentity(dec(c['values']) as never, { brandName: 'Brand <é>', brandId: 'b1', genomeRef: 'g1',
        resolutionHash: 'cd'.repeat(32), markSvg: (c['svg'] as string | null) || null });
      const [digest, length, width, height, st] = list(c['result']);
      expect([sha256(html), Array.from(html).length, w, h, status]).toEqual([digest, length, width, height, st]);
    }
  });

  it('applies the build status rule and groups gaps into decisions', () => {
    for (const c of list(fixture['status']).map(rec)) {
      const blocking = Array.from({ length: c['blocking'] as number }, () => ({}) as never);
      expect(buildStatus(str(c['book_status']), c['mode'] as Mode, blocking), JSON.stringify(c)).toBe(c['status']);
    }
    for (const c of list(fixture['gap_groups']).map(rec)) expect(groupGaps(list(c['gaps']) as Gap[])).toEqual(c['decisions']);
  });
});
