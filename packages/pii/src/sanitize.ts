/**
 * Twin of `services/langgraph/security/sanitize.py` (Python is the reference).
 *
 * Heuristic prompt-injection and `<script>` stripping. Python's `(?i)` and
 * `\\b` are translated through `pyre.ts`, and `.` becomes `PY_DOT` (anything
 * but `\\n`, as in Python, rather than JS's narrower `.`).
 *
 * Recursion matches the Python reference: every string inside nested dicts,
 * lists and lists-of-lists is sanitized. Script tags are stripped in any case
 * and until stable, so nested fragments cannot reassemble a tag.
 */
import { PY_BOUNDARY as B, PY_DOT, ignoreCase, pyRegExp, pySearch, pySub } from './pyre';
import { isPlainObject } from './pii';

export const INJECTION_PATTERNS: readonly RegExp[] = [
  pyRegExp(`${B}${ignoreCase('ignore all previous instructions')}${B}`),
  pyRegExp(`${B}${ignoreCase('you are now')}${B}`),
  pyRegExp(`${B}${ignoreCase('system prompt')}${B}`),
  pyRegExp(`${B}${ignoreCase('forget everything')}${B}`),
  pyRegExp(`${B}${ignoreCase('bypass')}${B}${PY_DOT}*${B}${ignoreCase('security')}${B}`),
];

export const INJECTION_REPLACEMENT = '[MALICIOUS_INTENT_REDACTED]';

/** Any script open/close tag, any case, with attributes (Python `_SCRIPT_TAG`). */
const SCRIPT_TAG = pyRegExp(`</?${ignoreCase('script')}${B}[^>]*>`);

function stripScriptTags(text: string): string {
  let previous: string | null = null;
  let current = text;
  while (previous !== current) {
    previous = current;
    current = pySub(SCRIPT_TAG, '', current);
  }
  return current;
}

function sanitizeString(value: string): string {
  let clean = value;
  for (const pattern of INJECTION_PATTERNS) {
    if (pySearch(pattern, clean)) clean = pySub(pattern, INJECTION_REPLACEMENT, clean);
  }
  return stripScriptTags(clean);
}

function sanitizeEntry(value: unknown): unknown {
  if (typeof value === 'string') return sanitizeString(value);
  if (isPlainObject(value)) return sanitizeInput(value);
  if (Array.isArray(value)) return value.map((item: unknown) => sanitizeEntry(item));
  return value;
}

/** Python `sanitize_input`: prompt-injection and `<script>` heuristics over a dict. */
export function sanitizeInput(data: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(data).map(([key, value]) => [key, sanitizeEntry(value)]));
}
