/**
 * Building blocks that make a JS `RegExp` (always compiled with the `u` flag)
 * match exactly what Python's `re` matches for a `str` pattern.
 *
 * JS and Python disagree on several escapes, so none of the JS ones are used:
 * - `\w` / `\b`: Python is Unicode-aware (`str.isalnum()` or `_`); JS is ASCII
 *   only, even with `u`. `PY_WORD` / `PY_BOUNDARY` use Python's table.
 * - `\d`: Python matches every Unicode decimal digit; JS only `0-9`.
 * - `\s`: Python's set includes U+001C..U+001F and U+0085 and excludes U+FEFF;
 *   JS is the other way round.
 * - `re.IGNORECASE`: Python also folds `i`/`İ`/`ı`, `s`/`ſ` and `k`/`K`
 *   (KELVIN SIGN). JS `i` without `u` folds none of them, and with `u` misses
 *   `İ` and `ı`. So no JS `i` flag is used; `ignoreCase()` expands letters.
 * - `.`: Python excludes only `\n`; JS also excludes `\r`, U+2028 and U+2029.
 *   Use `PY_DOT`.
 * The tables come from `python-unicode.ts`, generated from Python itself, so
 * the JS engine's own Unicode version never decides a match.
 */
import {
  DIGIT_RANGES,
  IGNORECASE_EXTRAS,
  SPACE_RANGES,
  WORD_RANGES,
  type CodePointRange,
} from './python-unicode';

function cp(codePoint: number): string {
  return `\\u{${codePoint.toString(16)}}`;
}

/** Body (without brackets) of a character class covering `ranges`. */
export function classBody(ranges: readonly CodePointRange[]): string {
  return ranges.map(([lo, hi]) => (lo === hi ? cp(lo) : `${cp(lo)}-${cp(hi)}`)).join('');
}

export const PY_WORD = `[${classBody(WORD_RANGES)}]`;
export const PY_DIGIT = `[${classBody(DIGIT_RANGES)}]`;
export const PY_SPACE = `[${classBody(SPACE_RANGES)}]`;
export const PY_DOT = '[^\\n]';
export const PY_BOUNDARY = `(?:(?<=${PY_WORD})(?!${PY_WORD})|(?<!${PY_WORD})(?=${PY_WORD}))`;

/** Extra characters Python's IGNORECASE adds to any class that holds A-Z/a-z. */
export const IGNORECASE_ALPHA_EXTRAS = Object.values(IGNORECASE_EXTRAS).flat().map(cp).join('');

/** Class body (no brackets) of everything Python's IGNORECASE equates with one ASCII letter. */
function ignoreCaseLetterBody(letter: string): string {
  const lower = letter.toLowerCase();
  const extras = (IGNORECASE_EXTRAS[lower] ?? []).map(cp).join('');
  return `${lower}${lower.toUpperCase()}${extras}`;
}

function ignoreCaseLetter(letter: string): string {
  return `[${ignoreCaseLetterBody(letter)}]`;
}

/** Python `[letters]` under IGNORECASE, for a class of ASCII letters only. */
export function ignoreCaseSet(letters: string): string {
  if (!/^[A-Za-z]+$/.test(letters)) throw new Error('ignoreCaseSet() only takes ASCII letters');
  return `[${Array.from(letters, ignoreCaseLetterBody).join('')}]`;
}

/**
 * A literal made of ASCII letters and spaces, matched the way Python's
 * IGNORECASE matches it. Anything else is a programming error and throws.
 */
export function ignoreCase(literal: string): string {
  return Array.from(literal, (ch) => {
    if (/^[A-Za-z]$/.test(ch)) return ignoreCaseLetter(ch);
    if (ch === ' ') return ' ';
    throw new Error(`ignoreCase() only takes ASCII letters and spaces, got ${JSON.stringify(ch)}`);
  }).join('');
}

/** Compile with `gu`: `u` for code-point semantics and `\u{...}`, `g` for sub/finditer. */
export function pyRegExp(source: string): RegExp {
  return new RegExp(source, 'gu');
}

/** Python `pattern.search(text) is not None`. `String#search` ignores `lastIndex`. */
export function pySearch(pattern: RegExp, text: string): boolean {
  return text.search(pattern) !== -1;
}

/** Python `pattern.sub(replacement, text)` with a literal replacement (no `$` expansion). */
export function pySub(pattern: RegExp, replacement: string, text: string): string {
  return text.replace(pattern, () => replacement);
}
