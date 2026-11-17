/**
 * The pure parts of `vnexus/art_director.py`: the evaluation rubric, the
 * platform presets and `score`. Scores are produced only for measured criteria;
 * subjective criteria return HUMAN_REQUIRED and are never folded into a number.
 * `compile_brief` reads the genome projection (foundry grammars) and stays in Python.
 */
import { CanonicalFloat } from '@amc/canonical';
import { PyKeyError, PyTypeError } from './errors';
import { isPlainRecord, pyRepr, type PyData } from './python';

export const ART_DIRECTOR_VERSION = 'amc-vnexus-art-director/v1';
export const MEDIUMS = ['POSTER', 'SOCIAL', 'WEB', 'VIDEO', 'PACKAGING', 'PRESENTATION', 'IDENTITY'] as const;
export type Medium = (typeof MEDIUMS)[number];

export interface PlatformSpec {
  readonly name: string;
  readonly width: number;
  readonly height: number;
  readonly formats: readonly string[];
  readonly safe_margin: number;
  readonly max_bytes: number | null;
}

function spec(name: string, width: number, height: number, formats: readonly string[] = ['png'], margin = 0.06): PlatformSpec {
  return { name, width, height, formats, safe_margin: margin, max_bytes: null };
}

/** Commonly published platform presets (they change; a request-supplied spec always wins). */
export const PLATFORM_PRESETS: Readonly<Record<string, PlatformSpec>> = {
  'social.portrait_4x5': spec('social.portrait_4x5', 1080, 1350),
  'social.square': spec('social.square', 1080, 1080),
  'social.story_9x16': spec('social.story_9x16', 1080, 1920, ['png'], 0.12),
  'web.open_graph': spec('web.open_graph', 1200, 630),
  'video.landscape_16x9': spec('video.landscape_16x9', 1920, 1080, ['mp4']),
  'print.poster_a_ratio': spec('print.poster_a_ratio', 1200, 1697, ['svg', 'pdf']),
  'presentation.16x9': spec('presentation.16x9', 1920, 1080, ['svg', 'pdf']),
};

type Rec = { readonly [key: string]: PyData };
type Row = Record<string, PyData>;

function measured(criterion: string, how: string): Row {
  return { criterion, method: 'MEASURED', how };
}

function human(criterion: string, how: string): Row {
  return { criterion, method: 'HUMAN_REQUIRED', how };
}

/** `rubric`: what can be measured versus what needs a person (the same for every medium). */
export function rubric(_medium: Medium): Row[] {
  return [
    measured('brand_fidelity', 'every fill/stroke in the palette; approved typefaces declared'),
    measured('legibility', 'WCAG 2.2 contrast of text/background pairs; minimum text size'),
    measured('accessibility', 'text alternative present; reduced-motion variant for motion'),
    measured('platform_suitability', 'dimensions and format match the specification'),
    measured('production_feasibility', 'every required renderer is available locally'),
    human('visual_coherence', 'a reviewer judges consistency with the brand'),
    human('distinctiveness', 'a reviewer judges; computed diversity between candidates is shown as context, not as a score'),
  ];
}

function item(value: PyData, what: string): Rec {
  if (!isPlainRecord(value)) throw new PyTypeError(`${what} must be a mapping`);
  return value;
}

function need(record: Rec, key: string): PyData {
  if (!Object.prototype.hasOwnProperty.call(record, key)) throw new PyKeyError(pyRepr(key));
  return record[key] as PyData;
}

function scoreOne(entry: Rec, evidence: Rec): Row {
  const name = need(entry, 'criterion') as string;
  if (need(entry, 'method') === 'HUMAN_REQUIRED') return { criterion: name, status: 'HUMAN_REQUIRED', value: null };
  if (!Object.prototype.hasOwnProperty.call(evidence, name)) return { criterion: name, status: 'NOT_RUN', value: null };
  const e = item(evidence[name] as PyData, 'evidence');
  const detail = Object.prototype.hasOwnProperty.call(e, 'detail') ? (e['detail'] as PyData) : '';
  return { criterion: name, status: 'MEASURED', value: new CanonicalFloat(need(e, 'passed') ? 1 : 0), detail };
}

/** `score`: scores only what was measured. `evidence` maps criterion -> `{passed, detail}` from real checks. */
export function score(brief: Rec, evidence: Rec): Row {
  const results = (need(brief, 'rubric') as readonly PyData[]).map((r) => scoreOne(item(r, 'rubric item'), evidence));
  const done = results.filter((r) => r['status'] === 'MEASURED');
  return {
    criteria: results, measured: done.length, measured_passed: done.filter((r) => (r['value'] as CanonicalFloat).value === 1).length,
    human_required: results.filter((r) => r['status'] === 'HUMAN_REQUIRED').map((r) => r['criterion'] as string),
    not_run: results.filter((r) => r['status'] === 'NOT_RUN').map((r) => r['criterion'] as string),
    note: 'pass counts over measured criteria only; there is no overall quality score',
  };
}
