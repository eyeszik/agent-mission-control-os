/**
 * Python `str.lower()`, independent of the JS engine's Unicode version.
 *
 * `String#toLowerCase` follows whatever Unicode version the engine ships, and
 * CPython follows its own `unicodedata` version. The mapping and the two
 * classes CPython's final-sigma rule consults are therefore read from Python
 * (`python-casing.ts`, owned by `test_approval_framing_parity_fixture.py`).
 *
 * U+03A3 (capital sigma) is the one context-dependent mapping. CPython's
 * `handle_capital_sigma` scans back over case-ignorable code points; if the
 * first other one is cased, and scanning forward the same way reaches the end
 * or a code point that is not cased, the result is U+03C2 (final sigma),
 * otherwise U+03C3. This function mirrors that scan exactly.
 */
import { CASED_RANGES, CASE_IGNORABLE_RANGES, LOWER_MAP } from './python-casing';
import type { CodePointRange } from './python-unicode';

const CAPITAL_SIGMA = 0x3a3;
const SMALL_SIGMA = 'σ';
const FINAL_SIGMA = 'ς';
const LOWER = new Map<number, string>(LOWER_MAP.map(([cp, low]) => [cp, String.fromCodePoint(...low)]));

function inRanges(ranges: readonly CodePointRange[], cp: number): boolean {
  let lo = 0;
  let hi = ranges.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const range = ranges[mid];
    if (range === undefined) return false;
    if (cp < range[0]) hi = mid - 1;
    else if (cp > range[1]) lo = mid + 1;
    else return true;
  }
  return false;
}

function isIgnorable(cp: number): boolean {
  return inRanges(CASE_IGNORABLE_RANGES, cp);
}

function isCased(cp: number): boolean {
  return inRanges(CASED_RANGES, cp);
}

/** Index of the first non-ignorable code point from `start` moving by `step`, or -1 / length. */
function skipIgnorable(cps: readonly number[], start: number, step: 1 | -1): number {
  let j = start;
  while (j >= 0 && j < cps.length && isIgnorable(cps[j] ?? -1)) j += step;
  return j;
}

function isFinalSigma(cps: readonly number[], i: number): boolean {
  const before = skipIgnorable(cps, i - 1, -1);
  if (before < 0 || !isCased(cps[before] ?? -1)) return false;
  const after = skipIgnorable(cps, i + 1, 1);
  return after === cps.length || !isCased(cps[after] ?? -1);
}

/** Python `text.lower()`. */
export function pyLower(text: string): string {
  const cps = Array.from(text, (ch) => ch.codePointAt(0) ?? 0);
  return cps
    .map((cp, i) => {
      if (cp === CAPITAL_SIGMA) return isFinalSigma(cps, i) ? FINAL_SIGMA : SMALL_SIGMA;
      return LOWER.get(cp) ?? String.fromCodePoint(cp);
    })
    .join('');
}
