/**
 * The slice of Python's `datetime` the Project OS policies use: a
 * timezone-aware-or-naive wall clock, `fromisoformat` (the CPython 3.11
 * C-implementation grammar, quirks included), `isoformat`, `weekday`,
 * `replace`, `+ timedelta` and comparisons.
 *
 * Only fixed UTC offsets exist (that is all `fromisoformat` can produce).
 * Arithmetic is wall-clock arithmetic like Python's: the offset is carried
 * along, never recomputed. Comparing a naive and an aware value raises
 * `TypeError`, as in Python.
 */
import { pyRepr } from '@amc/kernel';
import { PyOverflowError, PyTypeError, PyValueError } from './errors';

export interface PyDateTime {
  readonly year: number;
  readonly month: number;
  readonly day: number;
  readonly hour: number;
  readonly minute: number;
  readonly second: number;
  readonly microsecond: number;
  /** Offset from UTC in microseconds; `null` for a naive value. */
  readonly utcoffset_us: number | null;
}

const US_PER_DAY = 86_400_000_000;
const DAYS_BEFORE_MONTH = [0, 0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334];
const DI400Y = 146097;
const DI100Y = 36524;
const DI4Y = 1461;
const MAX_ORDINAL = 3652059;

function isLeap(year: number): boolean {
  return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
}

function daysInMonth(year: number, month: number): number {
  if (month === 2) return isLeap(year) ? 29 : 28;
  return [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1] as number;
}

function daysBeforeYear(year: number): number {
  const y = year - 1;
  return y * 365 + Math.trunc(y / 4) - Math.trunc(y / 100) + Math.trunc(y / 400);
}

function daysBeforeMonth(year: number, month: number): number {
  return (DAYS_BEFORE_MONTH[month] as number) + (month > 2 && isLeap(year) ? 1 : 0);
}

function ymdToOrdinal(year: number, month: number, day: number): number {
  return daysBeforeYear(year) + daysBeforeMonth(year, month) + day;
}

/** CPython `ord_to_ymd`. */
function ordinalToYmd(ordinalDay: number): { year: number; month: number; day: number } {
  let n = ordinalDay - 1;
  const n400 = Math.trunc(n / DI400Y);
  n %= DI400Y;
  let year = n400 * 400 + 1;
  const n100 = Math.trunc(n / DI100Y);
  n %= DI100Y;
  const n4 = Math.trunc(n / DI4Y);
  n %= DI4Y;
  const n1 = Math.trunc(n / 365);
  n %= 365;
  year += n100 * 100 + n4 * 4 + n1;
  if (n1 === 4 || n100 === 4) return { year: year - 1, month: 12, day: 31 };
  const leap = n1 === 3 && (n4 !== 24 || n100 === 3);
  let month = (n + 50) >> 5;
  let preceding = (DAYS_BEFORE_MONTH[month] as number) + (month > 2 && leap ? 1 : 0);
  if (preceding > n) {
    month -= 1;
    preceding -= daysInMonth(year, month);
  }
  return { year, month, day: n - preceding + 1 };
}

function ordinalOf(value: PyDateTime): number {
  return ymdToOrdinal(value.year, value.month, value.day);
}

function timeOfDayUs(value: PyDateTime): number {
  return ((value.hour * 60 + value.minute) * 60 + value.second) * 1_000_000 + value.microsecond;
}

// -- construction -----------------------------------------------------------------

function timedeltaRepr(totalUs: number): string {
  const days = Math.floor(totalUs / US_PER_DAY);
  const rest = totalUs - days * US_PER_DAY;
  const seconds = Math.floor(rest / 1_000_000);
  const micros = rest - seconds * 1_000_000;
  const parts = [
    days ? `days=${days}` : '',
    seconds ? `seconds=${seconds}` : '',
    micros ? `microseconds=${micros}` : '',
  ].filter((part) => part);
  return `datetime.timedelta(${parts.length ? parts.join(', ') : '0'})`;
}

function checkOffset(offsetUs: number): void {
  if (Math.abs(offsetUs) >= US_PER_DAY) {
    throw new PyValueError(
      'offset must be a timedelta strictly between -timedelta(hours=24) and timedelta(hours=24), ' +
        `not ${timedeltaRepr(offsetUs)}.`,
    );
  }
}

function checkDate(year: number, month: number, day: number): void {
  if (year < 1 || year > 9999) throw new PyValueError(`year ${year} is out of range`);
  if (month < 1 || month > 12) throw new PyValueError('month must be in 1..12');
  if (day < 1 || day > daysInMonth(year, month)) throw new PyValueError('day is out of range for month');
}

function checkTime(hour: number, minute: number, second: number, microsecond: number): void {
  if (hour < 0 || hour > 23) throw new PyValueError('hour must be in 0..23');
  if (minute < 0 || minute > 59) throw new PyValueError('minute must be in 0..59');
  if (second < 0 || second > 59) throw new PyValueError('second must be in 0..59');
  if (microsecond < 0 || microsecond > 999_999) throw new PyValueError('microsecond must be in 0..999999');
}

export interface DateTimeFields {
  readonly year: number;
  readonly month: number;
  readonly day: number;
  readonly hour?: number;
  readonly minute?: number;
  readonly second?: number;
  readonly microsecond?: number;
  readonly utcoffset_us?: number | null;
}

/** `datetime(...)` with Python's range checks. */
export function makeDateTime(fields: DateTimeFields): PyDateTime {
  const value: PyDateTime = {
    year: fields.year,
    month: fields.month,
    day: fields.day,
    hour: fields.hour ?? 0,
    minute: fields.minute ?? 0,
    second: fields.second ?? 0,
    microsecond: fields.microsecond ?? 0,
    utcoffset_us: fields.utcoffset_us ?? null,
  };
  if (value.utcoffset_us !== null) checkOffset(value.utcoffset_us);
  checkDate(value.year, value.month, value.day);
  checkTime(value.hour, value.minute, value.second, value.microsecond);
  return value;
}

// -- fromisoformat (CPython 3.11 C implementation) -----------------------------------

class IsoParseError extends Error {}

/** UTF-8 bytes read like a NUL-terminated C buffer: past the end is 0. */
class Cursor {
  constructor(
    readonly bytes: Uint8Array,
    public pos: number,
    readonly end: number,
  ) {}

  at(index: number = this.pos): number {
    return this.bytes[index] ?? 0;
  }
}

const isDigit = (byte: number): boolean => byte >= 0x30 && byte <= 0x39;
const CH = (text: string): number => text.charCodeAt(0);

function parseDigits(cursor: Cursor, count: number): number {
  let value = 0;
  for (let i = 0; i < count; i += 1) {
    const byte = cursor.at();
    if (!isDigit(byte)) throw new IsoParseError();
    value = value * 10 + (byte - 0x30);
    cursor.pos += 1;
  }
  return value;
}

function findSeparator(bytes: Uint8Array): number {
  const len = bytes.length;
  if (len === 7) return 7;
  if (bytes[4] === CH('-')) {
    if (bytes[5] !== CH('W')) return 10;
    if (len < 8) throw new IsoParseError();
    if (len > 8 && bytes[8] === CH('-')) {
      if (len === 9) throw new IsoParseError();
      return len > 10 && isDigit(bytes[10] as number) ? 8 : 10;
    }
    return 8;
  }
  if (bytes[4] !== CH('W')) return 8;
  let idx = 7;
  while (idx < len && isDigit(bytes[idx] as number)) idx += 1;
  if (idx < 9) return idx;
  return idx % 2 === 0 ? 7 : 8;
}

function isoWeekStart(year: number): number {
  const first = ymdToOrdinal(year, 1, 1);
  const weekday = (first + 6) % 7;
  return first - weekday + (weekday > 3 ? 7 : 0);
}

function isoToYmd(year: number, week: number, day: number): { year: number; month: number; day: number } {
  if (week <= 0 || week >= 53) {
    const firstWeekday = (ymdToOrdinal(year, 1, 1) + 6) % 7;
    const longYear = week === 53 && (firstWeekday === 3 || (firstWeekday === 2 && isLeap(year)));
    if (!longYear) throw new IsoParseError();
  }
  if (day <= 0 || day >= 8) throw new IsoParseError();
  // CPython feeds a pre-year-1 ordinal to ord_to_ymd and reads garbage; the
  // observable result is this error for every in-range week of year 0000.
  if (year === 0) throw new PyValueError('month must be in 1..12');
  return ordinalToYmd(isoWeekStart(year) + (week - 1) * 7 + day - 1);
}

function parseIsoDate(cursor: Cursor, length: number): { year: number; month: number; day: number } {
  const year = parseDigits(cursor, 4);
  const separated = cursor.at() === CH('-');
  if (separated) cursor.pos += 1;
  if (cursor.at() === CH('W')) {
    cursor.pos += 1;
    const week = parseDigits(cursor, 2);
    let day = 1;
    if (cursor.pos < length) {
      if (separated) {
        if (cursor.at() !== CH('-')) throw new IsoParseError();
        cursor.pos += 1;
      }
      day = parseDigits(cursor, 1);
    }
    return isoToYmd(year, week, day);
  }
  const month = parseDigits(cursor, 2);
  if (separated) {
    if (cursor.at() !== CH('-')) throw new IsoParseError();
    cursor.pos += 1;
  }
  return { year, month, day: parseDigits(cursor, 2) };
}

interface Clock {
  hour: number;
  minute: number;
  second: number;
  microsecond: number;
  /** CPython's return code: true when text is left over. */
  trailing: boolean;
}

const FRACTION_CORRECTION = [100000, 10000, 1000, 100, 10];

function parseFraction(cursor: Cursor): { microsecond: number; trailing: boolean } {
  const remaining = cursor.end - cursor.pos;
  const count = remaining >= 6 ? 6 : remaining;
  let microsecond = parseDigits(cursor, count);
  if (count < 6) microsecond *= FRACTION_CORRECTION[count - 1] as number;
  while (isDigit(cursor.at())) cursor.pos += 1;
  return { microsecond, trailing: cursor.at() !== 0 };
}

/** CPython `parse_hh_mm_ss_ff` over `[cursor.pos, cursor.end)`. */
function parseClock(cursor: Cursor): Clock {
  const clock: Clock = { hour: 0, minute: 0, second: 0, microsecond: 0, trailing: false };
  const keys = ['hour', 'minute', 'second'] as const;
  let separated = true;
  for (let i = 0; i < 3; i += 1) {
    clock[keys[i] as (typeof keys)[number]] = parseDigits(cursor, 2);
    const c = cursor.at();
    cursor.pos += 1;
    if (i === 0) separated = c === CH(':');
    if (cursor.pos >= cursor.end) return { ...clock, trailing: c !== 0 };
    if (separated && c === CH(':')) continue;
    if (c === CH('.') || c === CH(',')) break;
    if (!separated) cursor.pos -= 1;
    else throw new IsoParseError();
  }
  const fraction = parseFraction(cursor);
  return { ...clock, microsecond: fraction.microsecond, trailing: fraction.trailing };
}

function parseOffset(cursor: Cursor, tzPos: number): number | null {
  if (cursor.at(tzPos) === CH('Z')) {
    if (cursor.at(tzPos + 1) !== 0) throw new IsoParseError();
    return 0;
  }
  const sign = cursor.at(tzPos) === CH('-') ? -1 : 1;
  const tz = new Cursor(cursor.bytes, tzPos + 1, cursor.end);
  const parsed = parseClock(tz);
  if (parsed.trailing) throw new IsoParseError();
  return sign * ((parsed.hour * 3600 + parsed.minute * 60 + parsed.second) * 1_000_000 + parsed.microsecond);
}

function findTimezone(cursor: Cursor): number {
  let pos = cursor.pos;
  do {
    const byte = cursor.at(pos);
    if (byte === CH('Z') || byte === CH('+') || byte === CH('-')) break;
    pos += 1;
  } while (pos < cursor.end);
  return pos;
}

function parseIsoTime(cursor: Cursor): Clock & { offsetUs: number | null } {
  const tzPos = findTimezone(cursor);
  const clock = parseClock(new Cursor(cursor.bytes, cursor.pos, tzPos));
  if (tzPos === cursor.end) {
    if (clock.trailing) throw new IsoParseError();
    return { ...clock, offsetUs: null };
  }
  return { ...clock, offsetUs: parseOffset(cursor, tzPos) };
}

function utf8Skip(first: number): number {
  if ((first & 0x80) === 0) return 1;
  const kind = first & 0xf0;
  return kind === 0xe0 ? 3 : kind === 0xf0 ? 4 : 2;
}

function parseIsoBytes(bytes: Uint8Array): PyDateTime {
  if (bytes.length < 7) throw new IsoParseError();
  const separator = findSeparator(bytes);
  const date = parseIsoDate(new Cursor(bytes, 0, separator), separator);
  let clock: Clock & { offsetUs: number | null } = { hour: 0, minute: 0, second: 0, microsecond: 0, trailing: false, offsetUs: null };
  if (bytes.length > separator) {
    const start = separator + utf8Skip(bytes[separator] as number);
    clock = parseIsoTime(new Cursor(bytes, start, bytes.length));
  }
  return makeDateTime({ ...date, ...clock, utcoffset_us: clock.offsetUs });
}

const LONE_SURROGATE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/;

/**
 * `datetime.fromisoformat(text)` as CPython 3.11+ implements it (the C
 * module, not the documented grammar: junk between seconds and a UTC offset
 * is accepted, for instance). Python 3.10 accepts far less.
 */
export function fromIsoFormat(text: string): PyDateTime {
  const invalid = (): PyValueError => new PyValueError(`Invalid isoformat string: ${pyRepr(text)}`);
  if (LONE_SURROGATE.test(text)) throw invalid();
  try {
    return parseIsoBytes(new TextEncoder().encode(text));
  } catch (error) {
    if (error instanceof IsoParseError) throw invalid();
    throw error;
  }
}

// -- formatting -----------------------------------------------------------------------

const pad = (value: number, width: number): string => String(value).padStart(width, '0');

function formatOffset(offsetUs: number): string {
  const sign = offsetUs < 0 ? '-' : '+';
  const abs = Math.abs(offsetUs);
  const micros = abs % 1_000_000;
  const totalSeconds = (abs - micros) / 1_000_000;
  const seconds = totalSeconds % 60;
  const minutes = ((totalSeconds - seconds) / 60) % 60;
  const hours = (totalSeconds - seconds - minutes * 60) / 3600;
  let text = `${sign}${pad(hours, 2)}:${pad(minutes, 2)}`;
  if (seconds || micros) text += `:${pad(seconds, 2)}`;
  if (micros) text += `.${pad(micros, 6)}`;
  return text;
}

/** `datetime.isoformat()`. */
export function isoformat(value: PyDateTime): string {
  let text = `${pad(value.year, 4)}-${pad(value.month, 2)}-${pad(value.day, 2)}T`;
  text += `${pad(value.hour, 2)}:${pad(value.minute, 2)}:${pad(value.second, 2)}`;
  if (value.microsecond) text += `.${pad(value.microsecond, 6)}`;
  return value.utcoffset_us === null ? text : text + formatOffset(value.utcoffset_us);
}

// -- arithmetic and comparison ---------------------------------------------------------------

/** `datetime.weekday()`: Monday is 0. */
export function weekday(value: PyDateTime): number {
  return (ordinalOf(value) + 6) % 7;
}

/** `datetime.replace(...)` for the time fields. */
export function replaceTime(
  value: PyDateTime,
  fields: { hour?: number; minute?: number; second?: number; microsecond?: number },
): PyDateTime {
  return makeDateTime({ ...value, ...fields });
}

/** `value + timedelta(days=days, microseconds=microseconds)`; `OverflowError` outside years 1..9999. */
export function addTimedelta(value: PyDateTime, days: number, microseconds: number): PyDateTime {
  const total = timeOfDayUs(value) + microseconds;
  const carry = Math.floor(total / US_PER_DAY);
  const ordinal = ordinalOf(value) + days + carry;
  if (ordinal < 1 || ordinal > MAX_ORDINAL) throw new PyOverflowError('date value out of range');
  const rest = total - carry * US_PER_DAY;
  const ymd = ordinalToYmd(ordinal);
  const second = Math.floor(rest / 1_000_000);
  return {
    ...ymd,
    hour: Math.floor(second / 3600),
    minute: Math.floor(second / 60) % 60,
    second: second % 60,
    microsecond: rest - second * 1_000_000,
    utcoffset_us: value.utcoffset_us,
  };
}

/** Sort key of an aware value: (days, microseconds) of its UTC instant. */
function instant(value: PyDateTime): [number, number] {
  const total = timeOfDayUs(value) - (value.utcoffset_us ?? 0);
  const carry = Math.floor(total / US_PER_DAY);
  return [ordinalOf(value) + carry, total - carry * US_PER_DAY];
}

/** Three-way comparison; `TypeError` when exactly one side is naive. */
export function compareDateTimes(a: PyDateTime, b: PyDateTime): number {
  if ((a.utcoffset_us === null) !== (b.utcoffset_us === null)) {
    throw new PyTypeError("can't compare offset-naive and offset-aware datetimes");
  }
  const [ad, au] = instant(a);
  const [bd, bu] = instant(b);
  return ad !== bd ? ad - bd : au - bu;
}

export const UTC_OFFSET_US = 0;
