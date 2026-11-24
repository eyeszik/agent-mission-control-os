/**
 * Twin of `services/langgraph/security/approval_framing.py` (OWASP ASI09):
 * scores an approval summary for pressure patterns and omissions.
 *
 * Python is the reference, proven by `tests/fixtures/approval-framing-parity.json`
 * (owned by `services/langgraph/tests/test_approval_framing_parity_fixture.py`).
 * The Python patterns use `re.IGNORECASE` and `\b` on a `str` pattern, so they are
 * rebuilt from `pyre.ts` (Python's word table and IGNORECASE letter extras), never
 * from JS `\b` or the `i` flag. Target matching uses `pyLower`, not `toLowerCase`.
 *
 * Proof, not authority: this twin has no caller yet. The approval decision path
 * (`persistence/approvals.py`) still uses the Python module.
 */
import { IGNORECASE_ALPHA_EXTRAS, PY_BOUNDARY, PY_SPACE, ignoreCase as ic, pyRegExp, pySearch } from './pyre';
import { pyLower } from './pylower';

export type FramingLevel = 'NONE' | 'REVIEW' | 'HIGH';
export type FramingCode =
  | 'URGENCY'
  | 'PRESSURE_TO_APPROVE'
  | 'MINIMIZATION'
  | 'UNSUPPORTED_ASSURANCE'
  | 'OMITS_TARGET';

export interface FramingAssessment {
  readonly level: FramingLevel;
  readonly codes: readonly FramingCode[];
}

const HYPHEN_OR_SPACE = '[\\- ]';
const APOSTROPHE = "'?";

function words(alternatives: readonly string[]): RegExp {
  return pyRegExp(`${PY_BOUNDARY}(?:${alternatives.join('|')})${PY_BOUNDARY}`);
}

const URGENCY = words([
  `${ic('urgent')}(?:${ic('ly')})?`, ic('immediately'), ic('right now'), ic('asap'), ic('act now'),
  ic('deadline'), `${ic('time')}${HYPHEN_OR_SPACE}${ic('sensitive')}`,
  `${ic('before it')}${APOSTROPHE}${ic('s too late')}`, ic('no time'),
]);

const PRESSURE_TO_APPROVE = words([
  ic('just approve'), ic('simply approve'), `${ic('rubber')}${HYPHEN_OR_SPACE}?${ic('stamp')}`,
  ic('no need to review'), ic('trust me'), `${ic('the owner ')}(?:${ic('wants')}|${ic('asked')}|${ic('approved')})`,
  ic('already approved'), `${ic('everyone ')}(?:${ic('agreed')}|${ic('approved')})`,
  `${ic('don')}${APOSTROPHE}${ic('t ')}(?:${ic('need')}|${ic('bother')})${ic(' to ')}(?:${ic('check')}|${ic('review')})`,
]);

const MINIMIZATION = words([
  ic('harmless'), ic('minor'), ic('routine'), `${ic('low')}${HYPHEN_OR_SPACE}${ic('risk')}`, ic('no risk'),
  `${ic('nothing ')}(?:${ic('to see')}|${ic('will change')})`, ic('trivial'), ic('standard procedure'),
  ic('completely safe'),
]);

const UNSUPPORTED_ASSURANCE = words([
  ic('verified'), ic('audited'), ic('tested'), ic('guaranteed'), '100 ?%', ic('proven safe'),
]);

const EVIDENCE = pyRegExp(
  `(?:${ic('evidence')}|${ic('sha')}256|${ic('hash')}|${ic('sealed')}|${ic('ref')})[:= ]${PY_SPACE}*` +
    `[A-Za-z0-9_./:\\-${IGNORECASE_ALPHA_EXTRAS}]{6,}`,
);

const PATTERNS: ReadonlyArray<readonly [FramingCode, RegExp]> = [
  ['URGENCY', URGENCY],
  ['PRESSURE_TO_APPROVE', PRESSURE_TO_APPROVE],
  ['MINIMIZATION', MINIMIZATION],
  ['UNSUPPORTED_ASSURANCE', UNSUPPORTED_ASSURANCE],
];

function patternCodes(text: string): FramingCode[] {
  return PATTERNS.filter(([code, pattern]) => {
    if (!pySearch(pattern, text)) return false;
    return code !== 'UNSUPPORTED_ASSURANCE' || !pySearch(EVIDENCE, text);
  }).map(([code]) => code);
}

/** Python `targets and not any(t.lower() in text.lower() for t in targets if t)`. */
function omitsTarget(text: string, targets: readonly string[]): boolean {
  if (targets.length === 0) return false;
  const lowered = pyLower(text);
  return !targets.some((t) => t !== '' && lowered.includes(pyLower(t)));
}

/** Python `assess(summary, targets=...)`. A null or undefined summary reads as "" (`summary or ""`). */
export function assessFraming(summary: string | null | undefined, targets: readonly string[] = []): FramingAssessment {
  const text = summary ?? '';
  const codes = patternCodes(text);
  if (omitsTarget(text, targets)) codes.push('OMITS_TARGET');
  if (codes.length === 0) return { level: 'NONE', codes: [] };
  const high = codes.includes('PRESSURE_TO_APPROVE') || codes.length >= 2;
  return { level: high ? 'HIGH' : 'REVIEW', codes };
}

/** Python `FramingAssessment.codes_text`. */
export function framingCodesText(assessment: FramingAssessment): string {
  return assessment.codes.join(',');
}
