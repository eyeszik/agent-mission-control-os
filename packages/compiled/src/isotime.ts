/**
 * Python 3.11 `date.fromisoformat` / `datetime.fromisoformat`, as the compiled
 * planner uses them (`evidence._constraint_instant`, `measurement._ts`).
 *
 * Python accepts many ISO 8601 spellings. The twin accepts: calendar dates
 * (`YYYY-MM-DD`, `YYYYMMDD`), the extended week date `YYYY-Www-D`, any single
 * separator character, times `HH`, `HH:MM`, `HHMM`, `HH:MM:SS`, `HHMMSS` with
 * an optional `.`/`,` fraction (extra digits truncate to microseconds), and
 * offsets `Z`, `±HH`, `±HH:MM`, `±HHMM`, `±HH:MM:SS`, `±HHMMSS`. Anything else
 * is refused with `IsoFormatError`, a ValueError like Python's, so a Python-valid
 * spelling outside this subset reads as "invalid" here. The parity fixture
 * fuzzes this against Python and pins every such gap.
 */
import { CompiledValueError } from './errors';

export class IsoFormatError extends CompiledValueError {
  override name = 'IsoFormatError';
}

const DAY_US = 86_400_000_000n;

function isLeap(year: number): boolean {
  return (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0;
}

function daysInMonth(year: number, month: number): number {
  return [31, isLeap(year) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1] ?? 0;
}

/** Days since 1970-01-01 for a proleptic Gregorian date. */
function daysFromCivil(year: number, month: number, day: number): bigint {
  const y = month <= 2 ? year - 1 : year;
  const era = Math.floor(y / 400);
  const yoe = y - era * 400;
  const doy = Math.floor((153 * (month + (month > 2 ? -3 : 9)) + 2) / 5) + day - 1;
  const doe = yoe * 365 + Math.floor(yoe / 4) - Math.floor(yoe / 100) + doy;
  return BigInt(era * 146097 + doe - 719468);
}

const MIN_INSTANT = daysFromCivil(1, 1, 1) * DAY_US;
const MAX_INSTANT = (daysFromCivil(9999, 12, 31) + 1n) * DAY_US - 1n;

function calendarDays(year: number, month: number, day: number): bigint {
  if (year < 1) throw new IsoFormatError(`year ${year} is out of range`);
  if (month < 1 || month > 12) throw new IsoFormatError('month must be in 1..12');
  if (day < 1 || day > daysInMonth(year, month)) throw new IsoFormatError('day is out of range for month');
  return daysFromCivil(year, month, day);
}

function isoWeeksInYear(year: number): number {
  const jan1 = Number((((daysFromCivil(year, 1, 1) + 4n) % 7n) + 7n) % 7n); // 0 = Sunday
  return jan1 === 4 || (jan1 === 3 && isLeap(year)) ? 53 : 52;
}

function weekDays(year: number, week: number, weekday: number): bigint {
  if (year < 1) throw new IsoFormatError(`year ${year} is out of range`);
  if (week < 1 || week > isoWeeksInYear(year)) throw new IsoFormatError(`Invalid week: ${week}`);
  if (weekday < 1 || weekday > 7) throw new IsoFormatError(`Invalid weekday: ${weekday} (range is [1, 7])`);
  const jan4 = daysFromCivil(year, 1, 4);
  const jan4Weekday = Number((((jan4 + 3n) % 7n) + 7n) % 7n); // 0 = Monday
  return jan4 - BigInt(jan4Weekday) + BigInt((week - 1) * 7 + weekday - 1);
}

const CAL_EXT = /^(\d{4})-(\d{2})-(\d{2})$/;
const CAL_BASIC = /^(\d{4})(\d{2})(\d{2})$/;
const WEEK_EXT = /^(\d{4})-W(\d{2})-(\d)$/;
const ASCII_DIGITS = /^[0-9]+$/;

/** A date in one of the supported spellings, as days since the epoch. */
export function parseDatePart(text: string): bigint {
  const ascii = (re: RegExp): RegExpExecArray | null => (/^[\x00-\x7f]*$/.test(text) ? re.exec(text) : null);
  const ext = ascii(CAL_EXT) ?? ascii(CAL_BASIC);
  if (ext) return calendarDays(Number(ext[1]), Number(ext[2]), Number(ext[3]));
  const week = ascii(WEEK_EXT);
  if (week) return weekDays(Number(week[1]), Number(week[2]), Number(week[3]));
  throw new IsoFormatError(`Invalid isoformat string: ${JSON.stringify(text)}`);
}

/** `date.fromisoformat(text)` for a 10-character value: days since the epoch. */
export function parseIsoDate(text: string): bigint {
  if (Array.from(text).length !== 10) throw new IsoFormatError(`Invalid isoformat string: ${JSON.stringify(text)}`);
  return parseDatePart(text);
}

export interface ParsedDateTime {
  /** Local wall-clock microseconds since 1970-01-01T00:00:00 (offset not applied). */
  readonly local: bigint;
  /** UTC offset in microseconds, or null for a naive datetime. */
  readonly offset: bigint | null;
}

const TIME_RE = /^(\d{2})(?::?(\d{2})(?::?(\d{2})(?:[.,](\d+))?)?)?$/;
const TZ_RE = /^([+-])(\d{2})(?::?(\d{2})(?::?(\d{2}))?)?$/;

function timeOfDay(h: number, m: number, s: number, fraction: string): bigint {
  if (h > 23) throw new IsoFormatError('hour must be in 0..23');
  if (m > 59) throw new IsoFormatError('minute must be in 0..59');
  if (s > 59) throw new IsoFormatError('second must be in 0..59');
  const micros = BigInt(fraction.slice(0, 6).padEnd(6, '0') || '0');
  return BigInt(h * 3600 + m * 60 + s) * 1_000_000n + micros;
}

function parseOffset(text: string): bigint {
  const m = TZ_RE.exec(text);
  if (!m) throw new IsoFormatError(`Invalid isoformat string: ${JSON.stringify(text)}`);
  const [h, min, sec] = [Number(m[2]), Number(m[3] ?? 0), Number(m[4] ?? 0)];
  if (min > 59 || sec > 59) throw new IsoFormatError('offset minute/second out of range');
  const total = BigInt(h * 3600 + min * 60 + sec) * 1_000_000n;
  if (total >= DAY_US) throw new IsoFormatError('offset must be strictly between -24h and 24h');
  return m[1] === '-' ? -total : total;
}

function splitTime(text: string): { time: string; tz: string | null } {
  const cut = text.search(/[+-]/);
  return cut < 0 ? { time: text, tz: null } : { time: text.slice(0, cut), tz: text.slice(cut) };
}

/** Where the date ends: 8 characters for `YYYYMMDD`, else 10. Python's rule, for the supported date shapes. */
function dateLength(text: string): number {
  return text.length >= 5 && text[4] === '-' ? 10 : 8;
}

/** `datetime.fromisoformat(text)`; a trailing `Z` is the caller's job (as in the planner). */
export function parseIsoDateTime(text: string): ParsedDateTime {
  if (!/^[\x00-\x7f]*$/.test(text.slice(0, 8)) && Array.from(text).length < 10) {
    throw new IsoFormatError(`Invalid isoformat string: ${JSON.stringify(text)}`);
  }
  const points = Array.from(text);
  const cut = dateLength(text);
  const datePart = points.slice(0, cut).join('');
  const days = parseDatePart(datePart);
  if (points.length === cut) return { local: days * DAY_US, offset: null };
  const rest = points.slice(cut + 1).join('');
  const { time, tz } = splitTime(rest);
  const m = TIME_RE.exec(time);
  if (!m || !ASCII_DIGITS.test(time.replace(/[:.,]/g, ''))) throw new IsoFormatError(`Invalid isoformat string: ${JSON.stringify(text)}`);
  const local = days * DAY_US + timeOfDay(Number(m[1]), Number(m[2] ?? 0), Number(m[3] ?? 0), m[4] ?? '');
  return { local, offset: tz === null ? null : parseOffset(tz) };
}

/** `_constraint_instant`: UTC microseconds. Date-only values (10 code points) are midnight UTC. */
export function constraintInstant(value: string): bigint {
  if (Array.from(value).length === 10) return parseIsoDate(value) * DAY_US;
  const normalized = value.endsWith('Z') ? `${value.slice(0, -1)}+00:00` : value;
  const parsed = parseIsoDateTime(normalized);
  if (parsed.offset === null) throw new CompiledValueError('constraint datetimes require an explicit timezone');
  if (parsed.local < MIN_INSTANT || parsed.local > MAX_INSTANT) throw new IsoFormatError('year is out of range');
  const instant = parsed.local - parsed.offset;
  if (instant < MIN_INSTANT || instant > MAX_INSTANT) throw new IsoFormatError('date value out of range');
  return instant;
}
