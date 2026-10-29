/**
 * Twin of `services/langgraph/security/sanitize.py` (Python is the reference).
 *
 * Heuristic prompt-injection and `<script>` stripping. Python's `(?i)` and
 * `\b` are translated through `pyre.ts`, and `.` becomes `PY_DOT` (anything
 * but `\n`, as in Python, rather than JS's narrower `.`).
 *
 * Python's recursion shape is kept exactly, gaps included: strings inside
 * lists are NOT sanitized and nested lists are not walked; only dicts found
 * directly in a list are. Widening that belongs in the Python reference first.
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

function sanitizeString(value: string): string {
  let clean = value;
  for (const pattern of INJECTION_PATTERNS) {
    if (pySearch(pattern, clean)) clean = pySub(pattern, INJECTION_REPLACEMENT, clean);
  }
  // Basic XSS stripping: one pass each, exactly like Python's str.replace.
  return clean.replaceAll('<script>', '').replaceAll('</script>', '');
}

function sanitizeEntry(value: unknown): unknown {
  if (typeof value === 'string') return sanitizeString(value);
  if (isPlainObject(value)) return sanitizeInput(value);
  if (Array.isArray(value)) {
    return value.map((item: unknown) => (isPlainObject(item) ? sanitizeInput(item) : item));
  }
  return value;
}

/** Python `sanitize_input`: prompt-injection and `<script>` heuristics over a dict. */
export function sanitizeInput(data: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(data).map(([key, value]) => [key, sanitizeEntry(value)]));
}
