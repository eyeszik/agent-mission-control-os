/**
 * The Python semantics the compiler leans on: `str.strip()`, `\b` in a str
 * pattern (Unicode `\w`, tables generated from Python itself), rounding and
 * float formatting (re-used from `@amc/design-tokens`, which owns them).
 */
import { compareCodePoints } from '@amc/kernel';
import { WORD_RANGES, type CodePointRange } from './python-unicode';

export { formatFixed, roundTo } from '@amc/design-tokens/dist/python';
export { compareCodePoints };

// Python str.isspace(): JS \s minus U+FEFF, plus U+001C..U+001F and U+0085.
const PY_SPACE = '\\t\\n\\v\\f\\r\\x1c-\\x20\\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000';
const PY_STRIP = new RegExp(`^[${PY_SPACE}]+|[${PY_SPACE}]+$`, 'g');

/** Python `str.strip()` with no arguments. */
export function pyStrip(text: string): string {
  return text.replace(PY_STRIP, '');
}

function escape(cp: number): string {
  return `\\u{${cp.toString(16)}}`;
}

function classBody(ranges: readonly CodePointRange[]): string {
  return ranges.map(([a, b]) => (a === b ? escape(a) : `${escape(a)}-${escape(b)}`)).join('');
}

const WORD = `[${classBody(WORD_RANGES)}]`;
const NOT_AFTER_WORD = `(?<!${WORD})`;
const NOT_BEFORE_WORD = `(?!${WORD})`;

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * `re.search(rf"\b({alternatives})\b", text)` for ASCII-alphanumeric-edged
 * literals: a Python `\b` is "not next to a Unicode word character" there.
 */
export function pyWordSearch(alternatives: readonly string[], text: string, trailingBoundary = true): boolean {
  const body = alternatives.map(escapeRegExp).join('|');
  const pattern = `${NOT_AFTER_WORD}(?:${body})${trailingBoundary ? NOT_BEFORE_WORD : ''}`;
  return new RegExp(pattern, 'u').test(text);
}

/** `a in b` over sets of strings, in `a`'s order. */
export function intersect(a: readonly string[], b: ReadonlySet<string>): string[] {
  return a.filter((item) => b.has(item));
}

/** Python `sorted(strings)`. */
export function sortedStrings(values: Iterable<string>): string[] {
  return [...values].sort(compareCodePoints);
}

/** Python `dict.fromkeys(items)`: first occurrences, in order. */
export function uniqueInOrder<T>(items: Iterable<T>): T[] {
  return [...new Set(items)];
}
