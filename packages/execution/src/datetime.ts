/**
 * Pydantic v2 `datetime` validation and `model_dump(mode="json")` text, for strings.
 *
 * Accepts the RFC 3339 / ISO 8601 subset Pydantic (speedate) accepts: `T`, `t` or a
 * space as separator, optional seconds, a `.` or `,` fraction of any length
 * (truncated to microseconds), `Z`/`z` or a `±HH:MM`/`±HHMM` offset, or no offset
 * (naive), and a bare date (naive midnight). Output mirrors Pydantic exactly:
 * `YYYY-MM-DDTHH:MM:SS[.ffffff]` then `Z` for a zero offset, `±HH:MM` otherwise,
 * nothing for naive. Unix timestamps (numbers or numeric strings), which Pydantic's
 * lax mode also accepts, are refused here: see the package header.
 */

const PATTERN =
  /^(\d{4})-(\d{2})-(\d{2})(?:[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:[.,](\d+))?)?([Zz]|[+-]\d{2}:?\d{2})?)?$/;

export class DateTimeError extends Error {
  override name = 'DateTimeError';
}

function daysInMonth(year: number, month: number): number {
  const leap = (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0;
  return [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1] ?? 0;
}

function checkRange(label: string, value: number, low: number, high: number): void {
  if (value < low || value > high) throw new DateTimeError(`${label} value is outside expected range`);
}

function offsetText(raw: string | undefined): string {
  if (raw === undefined) return '';
  if (raw === 'Z' || raw === 'z') return 'Z';
  const digits = raw.slice(1).replace(':', '');
  const hours = Number(digits.slice(0, 2));
  const minutes = Number(digits.slice(2));
  checkRange('offset hour', hours, 0, 23);
  checkRange('offset minute', minutes, 0, 59);
  if (hours === 0 && minutes === 0) return 'Z';
  return `${raw[0] ?? '+'}${digits.slice(0, 2)}:${digits.slice(2)}`;
}

function fractionText(raw: string | undefined): string {
  const micros = (raw ?? '').slice(0, 6).padEnd(6, '0');
  return /^0+$/.test(micros) ? '' : `.${micros}`;
}

/** Validates `text` as Pydantic would and returns Pydantic's JSON dump of it; throws DateTimeError. */
export function normalizeDateTime(text: string): string {
  const match = PATTERN.exec(text);
  if (match === null) throw new DateTimeError('input is not a valid datetime or date');
  const [, year = '', month = '', day = '', hour = '00', minute = '00', second = '00', fraction, offset] = match;
  checkRange('year', Number(year), 1, 9999);
  checkRange('month', Number(month), 1, 12);
  checkRange('day', Number(day), 1, daysInMonth(Number(year), Number(month)));
  checkRange('hour', Number(hour), 0, 23);
  checkRange('minute', Number(minute), 0, 59);
  checkRange('second', Number(second), 0, 59);
  const time = `${hour}:${minute}:${second}${fractionText(fraction)}`;
  return `${year}-${month}-${day}T${time}${offsetText(offset)}`;
}

/** Python `utc_now()` as dumped by Pydantic (JS clocks have millisecond resolution). */
export function utcNow(): string {
  return normalizeDateTime(new Date().toISOString());
}
