/**
 * Twin of `services/langgraph/security/pii.py` (Python is the reference).
 *
 * Every pattern is the Python pattern translated escape by escape through
 * `pyre.ts`; see that file for why no JS `\b`, `\d`, `\s`, `.` or `i` flag is
 * used. One Python quirk is kept on purpose, because the twin must match
 * Python and must never be more permissive than it:
 * - `redactValue` returns non-string scalars and unknown objects unchanged.
 */
import { decodeBase64Fragment, decodeUtf8, unquote } from './pycodec';
import {
  IGNORECASE_ALPHA_EXTRAS as CI,
  PY_BOUNDARY as B,
  PY_DIGIT as D,
  PY_SPACE as S,
  ignoreCase,
  ignoreCaseSet,
  pyRegExp,
  pySearch,
  pySub,
} from './pyre';

export const PII_PATTERNS: ReadonlyArray<readonly [string, RegExp]> = [
  ['email', pyRegExp(String.raw`[a-zA-Z0-9_.+\-]+@[a-zA-Z0-9\-]+\.[a-zA-Z0-9\-.]+`)],
  ['phone', pyRegExp(String.raw`${B}(?:\+?1[\-.●]?)?\(?([0-9]{3})\)?[\-.●]?([0-9]{3})[\-.●]?([0-9]{4})${B}`)],
  ['ssn', pyRegExp(String.raw`${B}(?!000|666)[0-8][0-9]{2}-(?!00)[0-9]{2}-(?!0000)[0-9]{4}${B}`)],
  ['credit_card', pyRegExp(String.raw`${B}(?:${D}[ \-]*?){13,16}${B}`)],
  [
    'api_key_like',
    pyRegExp(String.raw`${B}(?:${ignoreCase('sk')}|${ignoreCase('api')}|${ignoreCase('key')})[\-_][A-Za-z0-9_\-${CI}]{12,}${B}`),
  ],
  ['bearer', pyRegExp(String.raw`${B}${ignoreCase('Bearer')}${S}+[A-Za-z0-9._~+/\-${CI}]{12,}=*`)],
];

const BASE64_FRAGMENT = pyRegExp(String.raw`(?<![A-Za-z0-9+/])(?:[A-Za-z0-9+/]{24,}={0,2})(?![A-Za-z0-9+/=])`);

export const EXTRA_SECRET_PATTERNS: readonly RegExp[] = [
  pyRegExp(String.raw`${B}gh[pousr]_[A-Za-z0-9_]{20,}${B}`),
  pyRegExp(String.raw`-----BEGIN [A-Z ]*PRIVATE KEY-----`),
];

const MAX_BASE64_FRAGMENT = 4096;

/** Logs may hold JSON-escaped `\n` / `\r`; scanning sees them as real line breaks. */
function unescapeLineBreaks(text: string): string {
  return text.replaceAll('\\n', '\n').replaceAll('\\r', '\r');
}

function plainSensitive(text: string): boolean {
  const normalized = unescapeLineBreaks(text);
  return (
    PII_PATTERNS.some(([, pattern]) => pySearch(pattern, normalized)) ||
    EXTRA_SECRET_PATTERNS.some((pattern) => pySearch(pattern, normalized))
  );
}

/** Up to two rounds of percent-decoding; any round that reveals a secret counts. */
function percentEncodedSensitive(text: string): boolean {
  if (!text.includes('%')) return false;
  let decoded = text;
  for (let round = 0; round < 2; round += 1) {
    const next = unquote(decoded);
    if (next === decoded) return false;
    decoded = next;
    if (plainSensitive(decoded)) return true;
  }
  return false;
}

function base64FragmentSensitive(fragment: string): boolean {
  if (fragment.length > MAX_BASE64_FRAGMENT) return false;
  const result = decodeBase64Fragment(fragment);
  // Python catches binascii.Error here and moves on to the next fragment:
  // a fragment that is not valid base64 is simply not treated as encoded data.
  if (!result.ok) return false;
  return plainSensitive(decodeUtf8(result.bytes, 'ignore'));
}

function encodedSensitive(text: string): boolean {
  if (percentEncodedSensitive(text)) return true;
  for (const match of text.matchAll(BASE64_FRAGMENT)) {
    if (base64FragmentSensitive(match[0])) return true;
  }
  return false;
}

/** Python `detect_pii`: plain or percent/base64-encoded PII or secrets. */
export function detectPii(text: string): boolean {
  return text.length > 0 && (plainSensitive(text) || encodedSensitive(text));
}

function redactString(value: string): string {
  if (encodedSensitive(value)) return '[REDACTED_ENCODED_SECRET]';
  let scrubbed = unescapeLineBreaks(value);
  for (const [name, pattern] of PII_PATTERNS) {
    scrubbed = pySub(pattern, `[REDACTED_${name.toUpperCase()}]`, scrubbed);
  }
  for (const pattern of EXTRA_SECRET_PATTERNS) scrubbed = pySub(pattern, '[REDACTED_SECRET]', scrubbed);
  return scrubbed;
}

export const SENSITIVE_KEYS: ReadonlySet<string> = new Set([
  'authorization',
  'proxy_authorization',
  'x_api_key',
  'api_key',
  'access_token',
  'refresh_token',
  'password',
  'secret',
  'client_secret',
  'private_key',
  'raw_prompt',
]);

/** Python `k.lower().replace("-", "_") in _SENSITIVE_KEYS` (full Unicode lowercase on both sides). */
export function isSensitiveKey(key: unknown): boolean {
  return typeof key === 'string' && SENSITIVE_KEYS.has(key.toLowerCase().replaceAll('-', '_'));
}

/** A Python `dict`: a plain object (or null-prototype object). */
export function isPlainObject(value: unknown): value is Record<string, unknown> {
  if (typeof value !== 'object' || value === null) return false;
  const proto: unknown = Object.getPrototypeOf(value);
  return proto === Object.prototype || proto === null;
}

function redactEntry(key: unknown, value: unknown): unknown {
  return isSensitiveKey(key) ? '[REDACTED_SENSITIVE_FIELD]' : redactValue(value);
}

/**
 * Recursively redact supported sensitive patterns from JSON-like values.
 * Plain objects play Python's `dict`, arrays its `list`/`tuple`; a `Map` is
 * treated as a dict too (and stays a `Map`) so it is never passed through
 * unredacted. Everything else is returned unchanged, as in Python.
 */
export function redactValue(value: unknown): unknown {
  if (typeof value === 'string') return redactString(value);
  if (Array.isArray(value)) return value.map((item: unknown) => redactValue(item));
  if (value instanceof Map) {
    return new Map(Array.from(value.entries(), ([k, v]: [unknown, unknown]) => [k, redactEntry(k, v)]));
  }
  if (isPlainObject(value)) {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, redactEntry(k, v)]));
  }
  return value;
}

/** Python `quarantine_payload`: a recursively redacted copy suitable for workflow state. */
export function quarantinePayload(payload: Record<string, unknown>): Record<string, unknown> {
  const redacted = redactValue(payload);
  if (!isPlainObject(redacted)) throw new TypeError('quarantinePayload() takes a plain object');
  return redacted;
}
