/**
 * Python codec behaviours the PII scanner depends on, rebuilt exactly:
 * - `bytes.decode('utf-8', errors='replace' | 'ignore')`. `TextDecoder` is not
 *   used: it strips a leading BOM by default and has no `ignore` mode, and
 *   dropping U+FFFD afterwards would also drop genuinely encoded U+FFFD.
 * - `urllib.parse.unquote(text, errors='replace')`.
 * - `base64.b64decode(fragment, validate=True)` for the fragments the scanner
 *   extracts.
 */

export type Utf8Errors = 'replace' | 'ignore';

/** [sequence length, lowest allowed second byte, highest allowed second byte]; length 0 = invalid lead. */
function leadInfo(lead: number): readonly [number, number, number] {
  if (lead >= 0xc2 && lead <= 0xdf) return [2, 0x80, 0xbf];
  if (lead === 0xe0) return [3, 0xa0, 0xbf];
  if (lead === 0xed) return [3, 0x80, 0x9f];
  if (lead >= 0xe1 && lead <= 0xef) return [3, 0x80, 0xbf];
  if (lead === 0xf0) return [4, 0x90, 0xbf];
  if (lead >= 0xf1 && lead <= 0xf3) return [4, 0x80, 0xbf];
  if (lead === 0xf4) return [4, 0x80, 0x8f];
  return [0, 0, 0];
}

/** Length of the valid prefix (lead included) of the sequence starting at `i`, and its code point. */
function scanSequence(bytes: Uint8Array, i: number): readonly [number, number, boolean] {
  const lead = bytes[i] ?? 0;
  const [length, lo, hi] = leadInfo(lead);
  if (length === 0) return [1, 0, false];
  let codePoint = lead & (0x7f >> length);
  let j = 1;
  for (; j < length && i + j < bytes.length; j += 1) {
    const next = bytes[i + j] ?? 0;
    if (next < (j === 1 ? lo : 0x80) || next > (j === 1 ? hi : 0xbf)) break;
    codePoint = (codePoint << 6) | (next & 0x3f);
  }
  return [j, codePoint, j === length];
}

/**
 * Python's UTF-8 decoder. An invalid sequence is its maximal valid prefix
 * (Unicode "maximal subpart" practice, which CPython follows): one U+FFFD for
 * `replace`, nothing for `ignore`.
 */
export function decodeUtf8(bytes: Uint8Array, errors: Utf8Errors): string {
  const out: string[] = [];
  let i = 0;
  while (i < bytes.length) {
    const lead = bytes[i] ?? 0;
    if (lead < 0x80) {
      out.push(String.fromCharCode(lead));
      i += 1;
      continue;
    }
    const [consumed, codePoint, valid] = scanSequence(bytes, i);
    if (valid) out.push(String.fromCodePoint(codePoint));
    else if (errors === 'replace') out.push('\uFFFD');
    i += consumed;
  }
  return out.join('');
}

const HEX_PAIR = /^[0-9A-Fa-f]{2}/;

/** `urllib.parse.unquote_to_bytes` for an ASCII-only run. */
function unquoteAsciiRunToBytes(run: string): Uint8Array {
  const [first = '', ...rest] = run.split('%');
  const out: number[] = Array.from(first, (ch) => ch.charCodeAt(0));
  for (const item of rest) {
    const pair = HEX_PAIR.exec(item);
    const tail = pair ? item.slice(2) : `%${item}`;
    if (pair) out.push(parseInt(pair[0], 16));
    for (const ch of tail) out.push(ch.charCodeAt(0));
  }
  return Uint8Array.from(out);
}

/**
 * `urllib.parse.unquote(text)` (UTF-8, errors='replace'): only ASCII runs are
 * unquoted, each decoded on its own, and non-ASCII text is kept as it is.
 */
export function unquote(text: string): string {
  if (!text.includes('%')) return text;
  return text.replace(/[\x00-\x7f]+/g, (run) => decodeUtf8(unquoteAsciiRunToBytes(run), 'replace'));
}

export type Base64Result = { readonly ok: true; readonly bytes: Uint8Array } | { readonly ok: false };

const FRAGMENT_SHAPE = /^([A-Za-z0-9+/]*)(={0,2})$/;

/**
 * `base64.b64decode(fragment, validate=True)` (binascii strict mode, Python
 * 3.11) for a string shaped `[A-Za-z0-9+/]*={0,2}`, the only shape the scanner
 * extracts. Any other shape is a programming error and throws.
 *
 * With n data characters and p padding characters, Python accepts exactly:
 * n % 4 == 0 (any p), n % 4 == 2 with p == 2, n % 4 == 3 with p == 1. Unused
 * trailing bits are ignored, as Python ignores them. Rejection is reported as
 * `{ ok: false }` (Python raises `binascii.Error`).
 */
export function decodeBase64Fragment(fragment: string): Base64Result {
  const shape = FRAGMENT_SHAPE.exec(fragment);
  if (!shape) throw new Error('decodeBase64Fragment() takes only [A-Za-z0-9+/]*={0,2}');
  const data = shape[1] ?? '';
  const pad = (shape[2] ?? '').length;
  const rem = data.length % 4;
  const ok = rem === 0 || (rem === 2 && pad === 2) || (rem === 3 && pad === 1);
  if (!ok) return { ok: false };
  return { ok: true, bytes: Uint8Array.from(atob(data), (ch) => ch.charCodeAt(0)) };
}
