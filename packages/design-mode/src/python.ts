/**
 * The Python string behaviour Design Mode depends on: `str.strip()`,
 * `str.capitalize()` and the `\d` class of a `re` str pattern. The Unicode
 * tables come from Python (`python-unicode.ts`), so the JS engine's Unicode
 * version never decides an id match or a title-cased letter.
 */
import { DIGIT_RANGES, TITLE_EXCEPTIONS, type CodePointRange } from './python-unicode';

// Python str.isspace(): JS \s minus U+FEFF, plus U+001C..U+001F and U+0085.
const PY_SPACE = '\\t\\n\\v\\f\\r\\x1c-\\x20\\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000';
const PY_STRIP = new RegExp(`^[${PY_SPACE}]+|[${PY_SPACE}]+$`, 'g');

/** Python `str.strip()` with no arguments. */
export function pyStrip(text: string): string {
  return text.replace(PY_STRIP, '');
}

function codePointEscape(cp: number): string {
  return `\\u{${cp.toString(16)}}`;
}

/** A `u`-flag character-class body for a list of code-point ranges. */
export function classBody(ranges: readonly CodePointRange[]): string {
  return ranges.map(([a, b]) => (a === b ? codePointEscape(a) : `${codePointEscape(a)}-${codePointEscape(b)}`)).join('');
}

/** Python's `\d` for a str pattern. */
export const PY_DIGIT = `[${classBody(DIGIT_RANGES)}]`;

/**
 * Python `str.capitalize()`: the first character title-cased, the rest
 * lower-cased in the context of the whole string (final sigma included).
 */
export function pyCapitalize(text: string): string {
  const first = text.codePointAt(0);
  if (first === undefined) return '';
  const head = String.fromCodePoint(first);
  const title = TITLE_EXCEPTIONS.get(first) ?? head.toUpperCase();
  return title + text.toLowerCase().slice(head.toLowerCase().length);
}
