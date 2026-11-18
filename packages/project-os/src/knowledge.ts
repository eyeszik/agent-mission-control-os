/**
 * Twin of `agency/project_os/knowledge.py`: a deterministic evidence pipeline
 *
 *     DISCOVER -> FETCH -> SANITIZE -> INJECTION_SCAN -> RIGHTS_CLASSIFY
 *     -> CLAIM_EXTRACT -> DATE/FRESHNESS -> DEDUPE -> TRIANGULATE
 *     -> CONTRADICTION_CHECK -> EVIDENCE_SCORE -> CAPSULE -> REVIEW -> PROMOTE
 *
 * It runs already-fetched text through every stage up to REVIEW. Fetching is
 * the caller's job (an external action) and promotion is a human decision:
 * nothing here promotes anything or touches a network. Third-party text never
 * becomes prompt authority: only short claims are kept, never the source body.
 */
import { z } from 'zod';
import { KnowledgeClaimSchema } from '@amc/shared';
import { compareCodePoints } from '@amc/kernel';
import { sanitizeInput } from '@amc/pii';
import { canonicalSha256 } from './json';
import { parseTs } from './calendar';
import { addTimedelta, compareDateTimes, type PyDateTime } from './pydatetime';
import {
  PY_BOUNDARY,
  PY_SPACE,
  ignoreCase,
  pyRegExp,
  pySearch,
  pySplit,
} from './pyre';
import { lowerView, pySplitWhitespace, pyStrip, roundTo, sliceCodePoints } from './pytext';
import { own } from './vocabulary';

export type KnowledgeClaim = z.infer<typeof KnowledgeClaimSchema>;
export type RightsClass = 'OPEN_LICENSE' | 'LICENSED' | 'SUMMARY_ONLY' | 'PROPRIETARY_NO_COPY' | 'UNKNOWN';

export const MAX_CLAIMS = 20;
export const MAX_CLAIM_CHARS = 280;
export const PROMOTION_SCORE_FLOOR = 0.6;
export const DEFAULT_FRESHNESS_DAYS = 365;

/** Freshness windows per research domain. Fast-moving domains go stale sooner. */
export const FRESHNESS_DAYS: Readonly<Record<string, number>> = {
  provider_cost: 30,
  provider_capability: 45,
  models: 60,
  social: 90,
  search: 120,
  aeo_geo: 90,
  advertising: 180,
  production_tooling: 180,
};

const alt = (...parts: string[]): string => `(?:${parts.join('|')})`;
const B = PY_BOUNDARY;

/** Python's pattern source (reported in rejection reasons) paired with its JS twin. */
const INJECTION_PATTERNS: readonly (readonly [string, RegExp])[] = [
  [
    'ignore (all |any )?(previous|prior|above) (instructions|prompts)',
    pyRegExp(
      `${ignoreCase('ignore ')}${alt(ignoreCase('all '), ignoreCase('any '))}?` +
        `${alt(ignoreCase('previous'), ignoreCase('prior'), ignoreCase('above'))} ` +
        alt(ignoreCase('instructions'), ignoreCase('prompts')),
    ),
  ],
  [
    'disregard (the )?(system|previous) (prompt|instructions)',
    pyRegExp(
      `${ignoreCase('disregard ')}${alt(ignoreCase('the '))}?${alt(ignoreCase('system'), ignoreCase('previous'))} ` +
        alt(ignoreCase('prompt'), ignoreCase('instructions')),
    ),
  ],
  [
    'you are now (?:a|an|the) ',
    pyRegExp(`${ignoreCase('you are now ')}${alt(ignoreCase('a'), ignoreCase('an'), ignoreCase('the'))} `),
  ],
  ['\\bsystem prompt\\b', pyRegExp(`${B}${ignoreCase('system prompt')}${B}`)],
  ['<\\s*script\\b', pyRegExp(`<${PY_SPACE}*${ignoreCase('script')}${B}`)],
  [
    '\\bBEGIN (?:SYSTEM|INSTRUCTIONS)\\b',
    pyRegExp(`${B}${ignoreCase('BEGIN ')}${alt(ignoreCase('SYSTEM'), ignoreCase('INSTRUCTIONS'))}${B}`),
  ],
  [
    '\\bact as (?:an? )?(?:admin|developer|root)\\b',
    pyRegExp(
      `${B}${ignoreCase('act as ')}(?:${ignoreCase('a')}${ignoreCase('n')}? )?` +
        `${alt(ignoreCase('admin'), ignoreCase('developer'), ignoreCase('root'))}${B}`,
    ),
  ],
];

const OPEN_LICENSES = ['cc0', 'cc-by', 'cc by', 'public domain', 'mit', 'apache-2.0', 'apache 2.0', 'ogl', 'open government licence'];
const SENTENCE = pyRegExp(`(?<=[.!?])${PY_SPACE}+`);
const TOKEN = /[a-z0-9]+/g;
const NEGATION = new Set(["not", "no", "never", "none", "cannot", "isn't", "aren't", "doesn't", "don't", "won't"]);

export interface SourceDocument {
  readonly domain: string;
  readonly source_uri: string;
  readonly text: string;
  readonly license?: string | null;
  readonly rights_declared?: RightsClass | null;
  readonly published_at?: string | null;
  readonly fetched_at?: string | null;
}

export interface PipelineOutcome {
  readonly stage: string;
  readonly status: 'REJECTED' | 'AWAITING_REVIEW';
  readonly rights_class: RightsClass;
  readonly claims: KnowledgeClaim[];
  readonly evidence_score: number;
  readonly rejection_reasons: string[];
  readonly content_hash: string;
  readonly stage_log: string[];
}

export function classifyRights(document: SourceDocument): RightsClass {
  if (document.rights_declared !== undefined && document.rights_declared !== null) return document.rights_declared;
  const license = lowerView(pyStrip(document.license ?? ''));
  if (!license) return 'UNKNOWN';
  if (OPEN_LICENSES.some((token) => license.includes(token))) return 'OPEN_LICENSE';
  if (license.includes('all rights reserved') || license.includes('no derivatives')) return 'PROPRIETARY_NO_COPY';
  return 'LICENSED';
}

/** The Python source text of every injection pattern that matches. */
export function injectionFindings(text: string): string[] {
  return INJECTION_PATTERNS.filter(([, pattern]) => pySearch(pattern, text)).map(([source]) => source);
}

export function extractClaims(text: string): string[] {
  const claims: string[] = [];
  for (const piece of pySplit(SENTENCE, text)) {
    const words = pySplitWhitespace(piece);
    const sentence = words.join(' ');
    if (words.length < 6 || words.length > 60 || sentence.endsWith('?')) continue;
    claims.push(sliceCodePoints(sentence, MAX_CLAIM_CHARS));
    if (claims.length >= MAX_CLAIMS) break;
  }
  return claims;
}

function tokens(text: string): Set<string> {
  return new Set(lowerView(text).match(TOKEN) ?? []);
}

function withoutNegation(text: string): Set<string> {
  return new Set([...tokens(text)].filter((token) => !NEGATION.has(token)));
}

/** Jaccard overlap of the two texts' tokens, negation words ignored. */
export function similarity(a: string, b: string): number {
  const ta = withoutNegation(a);
  const tb = withoutNegation(b);
  if (ta.size === 0 || tb.size === 0) return 0;
  const shared = [...ta].filter((token) => tb.has(token)).length;
  return shared / new Set([...ta, ...tb]).size;
}

function isNegated(text: string): boolean {
  return [...tokens(text)].some((token) => NEGATION.has(token)) || lowerView(text).includes("n't");
}

export function freshnessDeadline(document: SourceDocument): PyDateTime | null {
  const stamp = document.published_at || document.fetched_at;
  if (!stamp) return null;
  return addTimedelta(parseTs(stamp), own(FRESHNESS_DAYS, document.domain) ?? DEFAULT_FRESHNESS_DAYS, 0);
}

function reject(stage: string, rights: RightsClass, reasons: string[], hash: string, log: string[]): PipelineOutcome {
  return { stage, status: 'REJECTED', rights_class: rights, claims: [], evidence_score: 0, rejection_reasons: reasons, content_hash: hash, stage_log: log };
}

function triangulate(text: string, corpus: readonly (readonly [string, string])[]): { supporting: string[]; opposing: string[] } {
  const related = corpus.filter(([, other]) => similarity(text, other) >= 0.6);
  const negated = isNegated(text);
  const uris = (agree: boolean): string[] =>
    [...new Set(related.filter(([, other]) => (isNegated(other) === negated) === agree).map(([uri]) => uri))].sort(compareCodePoints);
  return { supporting: uris(true), opposing: uris(false) };
}

function evidenceScore(rights: RightsClass, dated: boolean, corroborated: number, total: number, contradicted: boolean): number {
  let score = 0.2;
  score += rights === 'OPEN_LICENSE' || rights === 'LICENSED' ? 0.2 : 0.0;
  score += dated ? 0.2 : 0.0;
  score += 0.3 * Math.min(1.0, (corroborated / Math.max(total, 1)) * 2);
  score -= contradicted ? 0.3 : 0.0;
  return roundTo(Math.max(0.0, Math.min(1.0, score)), 3);
}

/**
 * `corpus` is `[source_uri, claim_text]` pairs already in the tenant's
 * knowledge store, used for triangulation and contradiction checks.
 */
export function runPipeline(
  document: SourceDocument,
  options: { readonly now: PyDateTime; readonly known_hashes?: Iterable<string>; readonly corpus?: Iterable<readonly [string, string]> },
): PipelineOutcome {
  const log = ['DISCOVER', 'FETCH'];
  const rights = classifyRights(document);
  const sanitized = sanitizeInput({ value: document.text || '' }).value as string;
  log.push('SANITIZE');
  const digest = canonicalSha256({ uri: document.source_uri, text: sanitized });
  const findings = injectionFindings(document.text || '');
  log.push('INJECTION_SCAN');
  if (findings.length > 0) return reject('INJECTION_SCAN', rights, findings.map((f) => `INJECTION:${f}`), digest, log);
  log.push('RIGHTS_CLASSIFY');
  if (rights === 'PROPRIETARY_NO_COPY') return reject('RIGHTS_CLASSIFY', rights, ['RIGHTS_PROHIBIT_COPY'], digest, log);
  const rawClaims = extractClaims(sanitized);
  log.push('CLAIM_EXTRACT');
  if (rawClaims.length === 0) return reject('CLAIM_EXTRACT', rights, ['NO_EXTRACTABLE_CLAIMS'], digest, log);
  const deadline = freshnessDeadline(document);
  const stale = deadline !== null && compareDateTimes(deadline, options.now) < 0;
  log.push('DATE_FRESHNESS', 'DEDUPE');
  if (new Set(options.known_hashes ?? []).has(digest)) return reject('DEDUPE', rights, ['DUPLICATE_SOURCE'], digest, log);
  return capsule({ document, rights, rawClaims, deadline, stale, digest, log, corpus: options.corpus ?? [] });
}

function capsule(args: {
  document: SourceDocument;
  rights: RightsClass;
  rawClaims: string[];
  deadline: PyDateTime | null;
  stale: boolean;
  digest: string;
  log: string[];
  corpus: Iterable<readonly [string, string]>;
}): PipelineOutcome {
  const { document, rights, rawClaims, deadline, stale, digest, log } = args;
  const corpus = [...args.corpus].filter(([uri]) => uri !== document.source_uri);
  const claims: KnowledgeClaim[] = rawClaims.map((text) => {
    const { supporting, opposing } = triangulate(text, corpus);
    return {
      text,
      observed_date: (document.published_at || document.fetched_at) ?? null,
      corroborating_sources: supporting,
      contradicted_by: opposing,
    };
  });
  const corroborated = claims.filter((claim) => claim.corroborating_sources.length > 0).length;
  const contradicted = claims.some((claim) => claim.contradicted_by.length > 0);
  const score = evidenceScore(rights, deadline !== null && !stale, corroborated, claims.length, contradicted);
  const reasons = [...(stale ? ['SOURCE_STALE'] : []), ...(rights === 'UNKNOWN' ? ['RIGHTS_UNKNOWN_SUMMARY_ONLY'] : [])];
  return {
    stage: 'REVIEW',
    status: 'AWAITING_REVIEW',
    rights_class: rights === 'UNKNOWN' ? 'SUMMARY_ONLY' : rights,
    claims,
    evidence_score: score,
    rejection_reasons: reasons,
    content_hash: digest,
    stage_log: [...log, 'TRIANGULATE', 'CONTRADICTION_CHECK', 'EVIDENCE_SCORE', 'CAPSULE', 'REVIEW'],
  };
}

/** Promoted knowledge becomes evidence memory only above the score floor. */
export function promotionAuthority(evidenceScore: number): 'VERIFIED_EVIDENCE' | 'WORKING_CONTEXT' {
  return evidenceScore >= PROMOTION_SCORE_FLOOR ? 'VERIFIED_EVIDENCE' : 'WORKING_CONTEXT';
}
