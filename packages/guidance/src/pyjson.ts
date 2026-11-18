/**
 * `json.loads` as Python's C scanner behaves, including its error messages and
 * positions (code points, not UTF-16 units), the `object_pairs_hook` call at the
 * end of each object, `NaN`/`Infinity`, lone surrogate escapes and the int/float
 * distinction JS `JSON.parse` loses (`1.0` is a `CanonicalFloat`, `12345678901234567890`
 * a `bigint`). Objects come back as insertion-ordered `Map`s, because a pack's
 * `patterns` and `subsections` are rendered in file order.
 */
import { CanonicalFloat } from '@amc/canonical';
import { JSONDecodeError } from './errors';
import type { PyValue } from './pyvalue';

export type PairsHook = (pairs: ReadonlyArray<readonly [string, PyValue]>) => PyValue;

const WS = new Set([' ', '\t', '\n', '\r']);
const ESCAPES: Readonly<Record<string, string>> = { '"': '"', '\\': '\\', '/': '/', b: '\b', f: '\f', n: '\n', r: '\r', t: '\t' };
const isDigit = (ch: string | undefined): boolean => ch !== undefined && ch >= '0' && ch <= '9';
const isHex = (ch: string | undefined): boolean => ch !== undefined && /^[0-9a-fA-F]$/.test(ch);

type Parsed<T> = readonly [T, number];

class Scanner {
  constructor(
    private readonly cps: readonly string[],
    private readonly hook: PairsHook,
  ) {}

  fail(msg: string, pos: number): never {
    const upto = this.cps.slice(0, pos);
    const lineno = upto.filter((ch) => ch === '\n').length + 1;
    const colno = pos - upto.lastIndexOf('\n');
    throw new JSONDecodeError(`${msg}: line ${lineno} column ${colno} (char ${pos})`);
  }

  skipWs(idx: number): number {
    let i = idx;
    while (i < this.cps.length && WS.has(this.cps[i] ?? '')) i += 1;
    return i;
  }

  literal(idx: number, word: string, value: PyValue): Parsed<PyValue> | null {
    return this.cps.slice(idx, idx + word.length).join('') === word ? [value, idx + word.length] : null;
  }

  scan(idx: number): Parsed<PyValue> {
    const ch = this.cps[idx];
    const found = ch === undefined ? null : this.scanByChar(ch, idx);
    return found ?? this.fail('Expecting value', idx);
  }

  private scanByChar(ch: string, idx: number): Parsed<PyValue> | null {
    if (ch === '"') return this.scanString(idx + 1);
    if (ch === '{') return this.scanObject(idx + 1);
    if (ch === '[') return this.scanArray(idx + 1);
    if (ch === 'n') return this.literal(idx, 'null', null);
    if (ch === 't') return this.literal(idx, 'true', true);
    if (ch === 'f') return this.literal(idx, 'false', false);
    if (ch === 'N') return this.literal(idx, 'NaN', new CanonicalFloat(Number.NaN));
    if (ch === 'I') return this.literal(idx, 'Infinity', new CanonicalFloat(Infinity));
    if (ch === '-' && this.cps.slice(idx + 1, idx + 9).join('') === 'Infinity') return [new CanonicalFloat(-Infinity), idx + 9];
    return this.scanNumber(idx);
  }

  private digitsFrom(idx: number): number {
    let i = idx;
    while (isDigit(this.cps[i])) i += 1;
    return i;
  }

  private scanNumber(start: number): Parsed<PyValue> | null {
    let i = this.cps[start] === '-' ? start + 1 : start;
    const first = this.cps[i];
    if (first === '0') i += 1;
    else if (isDigit(first)) i = this.digitsFrom(i);
    else return null;
    const intEnd = i;
    if (this.cps[i] === '.' && isDigit(this.cps[i + 1])) i = this.digitsFrom(i + 1);
    i = this.exponentEnd(i);
    const text = this.cps.slice(start, i).join('');
    if (i === intEnd) return [this.intValue(text), i];
    return [new CanonicalFloat(Number(text)), i];
  }

  private exponentEnd(idx: number): number {
    const mark = this.cps[idx];
    if (mark !== 'e' && mark !== 'E') return idx;
    let j = idx + 1;
    if (this.cps[j] === '+' || this.cps[j] === '-') j += 1;
    return isDigit(this.cps[j]) ? this.digitsFrom(j) : idx;
  }

  private intValue(text: string): PyValue {
    const value = Number(text);
    if (Number.isSafeInteger(value)) return value === 0 ? 0 : value;
    return BigInt(text);
  }

  private hex4(idx: number, uPos: number): number {
    const digits = this.cps.slice(idx, idx + 4);
    if (digits.length < 4 || !digits.every(isHex)) this.fail('Invalid \\uXXXX escape', uPos);
    return parseInt(digits.join(''), 16);
  }

  private unicodeEscape(idx: number): Parsed<string> {
    if (idx + 4 >= this.cps.length) this.fail('Invalid \\uXXXX escape', idx - 1);
    const code = this.hex4(idx, idx - 1);
    const next = idx + 4;
    const room = next + 6 < this.cps.length;
    if (room && code >= 0xd800 && code <= 0xdbff && this.cps[next] === '\\' && this.cps[next + 1] === 'u') {
      const low = this.hex4(next + 2, next + 1);
      if ((low & 0xfc00) === 0xdc00) return [String.fromCharCode(code, low), next + 6];
    }
    return [String.fromCharCode(code), next];
  }

  private escape(idx: number, begin: number, backslash: number): Parsed<string> {
    const esc = this.cps[idx];
    if (esc === undefined) return this.fail(`Unterminated string starting at`, begin);
    if (esc === 'u') return this.unicodeEscape(idx + 1);
    const mapped = ESCAPES[esc];
    return mapped === undefined ? this.fail('Invalid \\escape', backslash) : [mapped, idx + 1];
  }

  private nextStop(idx: number): number {
    for (let i = idx; i < this.cps.length; i += 1) {
      const ch = this.cps[i] ?? '';
      if (ch === '"' || ch === '\\' || ch < ' ') return i;
    }
    return -1;
  }

  scanString(start: number): Parsed<string> {
    const begin = start - 1;
    let out = '';
    let idx = start;
    for (;;) {
      const stop = this.nextStop(idx);
      if (stop < 0) return this.fail('Unterminated string starting at', begin);
      out += this.cps.slice(idx, stop).join('');
      const term = this.cps[stop];
      if (term === '"') return [out, stop + 1];
      if (term !== '\\') return this.fail('Invalid control character at', stop);
      const [text, next] = this.escape(stop + 1, begin, stop);
      out += text;
      idx = next;
    }
  }

  private colon(idx: number): number {
    let end = idx;
    if (this.cps[end] !== ':') {
      end = this.skipWs(end);
      if (this.cps[end] !== ':') this.fail("Expecting ':' delimiter", end);
    }
    return this.skipWs(end + 1);
  }

  private firstKey(idx: number): number {
    let end = idx;
    if (this.cps[end] !== '"') end = this.skipWs(end);
    if (this.cps[end] === '"') return end;
    return this.cps[end] === '}' ? -1 - end : this.fail('Expecting property name enclosed in double quotes', end);
  }

  scanObject(idx: number): Parsed<PyValue> {
    const pairs: Array<readonly [string, PyValue]> = [];
    const first = this.firstKey(idx);
    if (first < 0) return [this.hook(pairs), -first];
    let end = first + 1;
    for (;;) {
      const [key, afterKey] = this.scanString(end);
      const [value, afterValue] = this.scan(this.colon(afterKey));
      pairs.push([key, value]);
      end = this.skipWs(afterValue);
      const sep = this.cps[end] ?? '';
      end += 1;
      if (sep === '}') return [this.hook(pairs), end];
      if (sep !== ',') this.fail("Expecting ',' delimiter", end - 1);
      end = this.skipWs(end);
      if ((this.cps[end] ?? '') !== '"') this.fail('Expecting property name enclosed in double quotes', end);
      end += 1;
    }
  }

  scanArray(idx: number): Parsed<PyValue> {
    const items: PyValue[] = [];
    let end = this.skipWs(idx);
    if (this.cps[end] === ']') return [items, end + 1];
    for (;;) {
      const [value, afterValue] = this.scan(end);
      items.push(value);
      end = this.skipWs(afterValue);
      const sep = this.cps[end] ?? '';
      end += 1;
      if (sep === ']') return [items, end];
      if (sep !== ',') this.fail("Expecting ',' delimiter", end - 1);
      end = this.skipWs(end);
    }
  }

  decode(): PyValue {
    if (this.cps[0] === '﻿') this.fail('Unexpected UTF-8 BOM (decode using utf-8-sig)', 0);
    const [value, end] = this.scan(this.skipWs(0));
    const tail = this.skipWs(end);
    if (tail !== this.cps.length) this.fail('Extra data', tail);
    return value;
  }
}

const defaultHook: PairsHook = (pairs) => new Map(pairs);

/** Python `json.loads(text, object_pairs_hook=hook)`. */
export function loads(text: string, hook: PairsHook = defaultHook): PyValue {
  return new Scanner(Array.from(text), hook).decode();
}
