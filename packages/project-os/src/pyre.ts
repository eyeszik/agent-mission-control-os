/**
 * Building blocks that make a JS `RegExp` (always compiled with the `u` flag)
 * match what Python's `re` matches for a `str` pattern.
 *
 * JS `\w`, `\d`, `\s`, `\b` and the `i` flag all disagree with Python, so none
 * of them are used. Word, digit and space classes are built from tables read
 * out of Python itself (`python-casefold.ts`). `re.IGNORECASE` is rebuilt from
 * `_sre.unicode_tolower` plus `re._casefix._EXTRA_CASES`: a pattern letter
 * matches a text character whose simple lowercase is the pattern letter's
 * lowercase or one of its extra equivalents.
 */
import {
  CASED_RANGES,
  DIGIT_RANGES,
  EXTRA_CASES,
  SIMPLE_LOWER,
  SPACE_RANGES,
  WORD_RANGES,
} from './python-casefold';
import { inRanges, type Ranges } from './pytext';

function esc(codePoint: number): string {
  return `\\u{${codePoint.toString(16)}}`;
}

/** Body (without brackets) of a character class covering `ranges`. */
export function classBody(ranges: Ranges): string {
  return ranges.map(([lo, hi]) => (lo === hi ? esc(lo) : `${esc(lo)}-${esc(hi)}`)).join('');
}

export const PY_WORD = `[${classBody(WORD_RANGES)}]`;
export const PY_DIGIT = `[${classBody(DIGIT_RANGES)}]`;
export const PY_SPACE = `[${classBody(SPACE_RANGES)}]`;
export const PY_DIGIT_BODY = classBody(DIGIT_RANGES);
export const PY_BOUNDARY = `(?:(?<=${PY_WORD})(?!${PY_WORD})|(?<!${PY_WORD})(?=${PY_WORD}))`;

const LOWER = new Map<number, number>();
const INVERSE = new Map<number, number[]>();
for (let i = 0; i < SIMPLE_LOWER.length; i += 2) {
  const from = SIMPLE_LOWER[i] as number;
  const to = SIMPLE_LOWER[i + 1] as number;
  LOWER.set(from, to);
  INVERSE.set(to, [...(INVERSE.get(to) ?? []), from]);
}

/** One pattern code point under `re.IGNORECASE` (a class when it is cased, a literal otherwise). */
export function ignoreCaseChar(codePoint: number): string {
  if (!inRanges(CASED_RANGES, codePoint)) return esc(codePoint);
  const lower = LOWER.get(codePoint) ?? codePoint;
  const equivalents = [lower, ...(EXTRA_CASES.get(lower) ?? [])];
  const members = new Set<number>();
  for (const letter of equivalents) {
    members.add(letter);
    for (const text of INVERSE.get(letter) ?? []) members.add(text);
  }
  return `[${[...members].map(esc).join('')}]`;
}

/** A literal string under `re.IGNORECASE`. */
export function ignoreCase(literal: string): string {
  return Array.from(literal, (ch) => ignoreCaseChar(ch.codePointAt(0) ?? 0)).join('');
}

/** A literal string, matched exactly. */
export function literal(text: string): string {
  return Array.from(text, (ch) => esc(ch.codePointAt(0) ?? 0)).join('');
}

/** Compile with `gu`: `u` for code-point semantics and `\u{...}`, `g` for finditer/sub. */
export function pyRegExp(source: string): RegExp {
  return new RegExp(source, 'gu');
}

/** Python `pattern.search(text) is not None`. `String#search` ignores `lastIndex`. */
export function pySearch(pattern: RegExp, text: string): boolean {
  return text.search(pattern) !== -1;
}

/** Python `pattern.findall(text)` for a pattern without groups. */
export function pyFindall(pattern: RegExp, text: string): string[] {
  return Array.from(text.matchAll(pattern), (match) => match[0]);
}

/** Python `pattern.split(text)` for a non-empty-matching pattern without groups. */
export function pySplit(pattern: RegExp, text: string): string[] {
  const pieces: string[] = [];
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    pieces.push(text.slice(last, match.index));
    last = (match.index ?? 0) + match[0].length;
  }
  pieces.push(text.slice(last));
  return pieces;
}

const TERM_CACHE = new Map<string, RegExp>();

/** `re.search(rf"\b{re.escape(term)}\b", text, re.IGNORECASE)` as a reusable pattern. */
export function wholeWordIgnoreCase(term: string): RegExp {
  let compiled = TERM_CACHE.get(term);
  if (!compiled) {
    compiled = pyRegExp(`${PY_BOUNDARY}${ignoreCase(term)}${PY_BOUNDARY}`);
    TERM_CACHE.set(term, compiled);
  }
  return compiled;
}
