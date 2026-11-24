/**
 * Regex building blocks that make a JS `RegExp` (always `u`) match what Python's
 * `re` matches for a `str` pattern: Unicode-aware `\w`, `\d`, `\s`, `\b`, and
 * IGNORECASE letter equivalents (`ſ`, `K`, `İ`, `ı`). JS `\w`, `\d`, `\s`, `\b`
 * and the `i` flag all differ from Python's, so none of them is used. The tables
 * come from `python-unicode.ts`.
 */
import { DIGIT_RANGES, IGNORECASE_EXTRAS, SPACE_RANGES, WORD_RANGES, type CodePointRange } from './python-unicode';

function cp(codePoint: number): string {
  return `\\u{${codePoint.toString(16)}}`;
}

function classBody(ranges: readonly CodePointRange[]): string {
  return ranges.map(([lo, hi]) => (lo === hi ? cp(lo) : `${cp(lo)}-${cp(hi)}`)).join('');
}

export const PY_WORD = `[${classBody(WORD_RANGES)}]`;
export const PY_DIGIT = `[${classBody(DIGIT_RANGES)}]`;
export const PY_SPACE = `[${classBody(SPACE_RANGES)}]`;
export const PY_BOUNDARY = `(?:(?<=${PY_WORD})(?!${PY_WORD})|(?<!${PY_WORD})(?=${PY_WORD}))`;

function letterClass(letter: string): string {
  const lower = letter.toLowerCase();
  const extras = (IGNORECASE_EXTRAS[lower] ?? []).map(cp).join('');
  return `[${lower}${lower.toUpperCase()}${extras}]`;
}

/** An ASCII-letter literal (spaces and hyphens allowed) as Python's IGNORECASE matches it. */
export function ignoreCase(literal: string): string {
  return Array.from(literal, (ch) => {
    if (/^[A-Za-z]$/.test(ch)) return letterClass(ch);
    if (ch === ' ' || ch === '-') return ch;
    throw new Error(`ignoreCase() only takes ASCII letters, spaces and hyphens, got ${JSON.stringify(ch)}`);
  }).join('');
}

/** Alternation of IGNORECASE literals. */
export function ignoreCaseAny(literals: readonly string[]): string {
  return literals.map(ignoreCase).join('|');
}

/** Compile with `u` only; callers use `search`/`split`, never a stateful global. */
export function pyRegExp(source: string): RegExp {
  return new RegExp(source, 'u');
}
