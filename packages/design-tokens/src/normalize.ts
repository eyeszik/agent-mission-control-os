/** TYPECHECK / NORMALIZE: Python `normalize_value`, `hex_to_color` and `_fmt`. */
import { CanonicalFloat } from '@amc/canonical';
import { TokenTypeError } from './errors';
import {
  formatFixed,
  inStringSet,
  isMapping,
  isNumber,
  numeric,
  pyGet,
  pyRepr,
  pyStrip,
  roundHalfEven,
  roundTo,
  sortedStrings,
  toFloat,
  type Mapping,
  type PyNumber,
} from './python';

// Python `$` (no MULTILINE) also matches just before a trailing "\n"; `\n?$` reproduces that.
export const HEX = /^#[0-9a-fA-F]{6}\n?$/;
const SIMPLE_FAMILY = /^[A-Za-z-]+$/;

const DIMENSION_UNITS: ReadonlySet<string> = new Set(['px', 'rem']);
const DURATION_UNITS: ReadonlySet<string> = new Set(['ms', 's']);
const COLOR_SPACES: ReadonlySet<string> = new Set(['srgb', 'display-p3', 'oklch']);
const COLOR_KEYS: ReadonlySet<string> = new Set(['colorSpace', 'components', 'alpha', 'hex']);
const FONT_WEIGHT_NAMES: ReadonlySet<string> = new Set([
  'thin', 'hairline', 'extra-light', 'ultra-light', 'light', 'normal', 'regular', 'book',
  'medium', 'semi-bold', 'demi-bold', 'bold', 'extra-bold', 'ultra-bold', 'black', 'heavy',
  'extra-black', 'ultra-black',
]);

/** A DTCG 2025.10 sRGB color value, as `hex_to_color` returns it. */
export interface DtcgColor {
  readonly colorSpace: 'srgb';
  /** Python floats: integral ones (0.0, 1.0) are `CanonicalFloat` so they hash as floats. */
  readonly components: readonly (number | CanonicalFloat)[];
  readonly hex: string;
}

/** Python `_fmt`: 4 decimals, trailing zeros and point stripped, "-0" is "0". */
export function fmt(value: PyNumber): string {
  const text = formatFixed(toFloat(value), 4).replace(/0+$/, '').replace(/\.+$/, '');
  return text === '' || text === '-0' ? '0' : text;
}

function pyFloat(value: number): number | CanonicalFloat {
  return Number.isInteger(value) ? new CanonicalFloat(value) : value;
}

/** Convert '#rrggbb' to a DTCG 2025.10 sRGB color value (with hex fallback). */
export function hexToColor(hexValue: unknown): DtcgColor {
  if (typeof hexValue !== 'string' || !HEX.test(pyStrip(hexValue))) {
    throw new TokenTypeError(`not a 6-digit hex color: ${pyRepr(hexValue)}`);
  }
  const clean = pyStrip(hexValue).toLowerCase();
  const components = [1, 3, 5].map((i) => pyFloat(roundTo(parseInt(clean.slice(i, i + 2), 16) / 255, 4)));
  return { colorSpace: 'srgb', components, hex: clean };
}

function channel(component: PyNumber): number {
  return Math.max(0, Math.min(255, roundHalfEven(Number(numeric(component)) * 255)));
}

function srgbHex(components: readonly PyNumber[]): string {
  return `#${components.map((c) => channel(c).toString(16).padStart(2, '0')).join('')}`;
}

function inUnitRange(value: PyNumber): boolean {
  const n = numeric(value);
  return n >= 0 && n <= 1;
}

interface ColorParts {
  readonly space: unknown;
  readonly comps: unknown;
  readonly alpha: unknown;
  readonly hexFallback: unknown;
}

function colorParts(value: unknown, path: string): ColorParts {
  if (!isMapping(value)) {
    throw new TokenTypeError('color $value must be a DTCG color object {colorSpace, components, alpha?, hex?}', path);
  }
  const extra = sortedStrings(Object.keys(value).filter((key) => !COLOR_KEYS.has(key)));
  if (extra.length > 0) throw new TokenTypeError(`unknown color properties ${pyRepr(extra)}`, path);
  return {
    space: pyGet(value, 'colorSpace'),
    comps: pyGet(value, 'components'),
    alpha: pyGet(value, 'alpha', 1),
    hexFallback: pyGet(value, 'hex'),
  };
}

function checkColor(parts: ColorParts, path: string): readonly PyNumber[] {
  if (!inStringSet(COLOR_SPACES, parts.space)) {
    throw new TokenTypeError(`unsupported colorSpace ${pyRepr(parts.space)}`, path);
  }
  const comps = parts.comps;
  if (!(Array.isArray(comps) && comps.length === 3 && comps.every((c: unknown) => isNumber(c)))) {
    throw new TokenTypeError('color components must be 3 numbers', path);
  }
  if (!isNumber(parts.alpha) || !inUnitRange(parts.alpha)) {
    throw new TokenTypeError('color alpha must be within [0, 1]', path);
  }
  const fallback = parts.hexFallback;
  if (fallback !== null && !(typeof fallback === 'string' && HEX.test(fallback))) {
    throw new TokenTypeError("color hex fallback must be '#rrggbb'", path);
  }
  return comps as readonly PyNumber[];
}

function srgbCss(comps: readonly PyNumber[], alpha: PyNumber, path: string): string {
  if (!comps.every(inUnitRange)) throw new TokenTypeError('srgb components must be within [0, 1]', path);
  if (Number(numeric(alpha)) === 1) return srgbHex(comps);
  return `rgb(${comps.map((c) => String(channel(c))).join(' ')} / ${fmt(alpha)})`;
}

function normalizeColor(value: unknown, path: string): string {
  const parts = colorParts(value, path);
  const comps = checkColor(parts, path);
  if (parts.space === 'srgb') return srgbCss(comps, parts.alpha as PyNumber, path);
  // Wide-gamut / perceptual spaces require an sRGB fallback (edge case E04).
  if (typeof parts.hexFallback !== 'string') {
    throw new TokenTypeError(`${String(parts.space)} color requires an sRGB 'hex' fallback for engines without support`, path);
  }
  return parts.hexFallback.toLowerCase();
}

function hasExactKeys(value: Mapping, keys: readonly string[]): boolean {
  const own = Object.keys(value);
  return own.length === keys.length && keys.every((key) => Object.hasOwn(value, key));
}

function normalizeMeasure(tokenType: 'dimension' | 'duration', value: unknown, path: string): string {
  const units = tokenType === 'dimension' ? DIMENSION_UNITS : DURATION_UNITS;
  if (!(isMapping(value) && hasExactKeys(value, ['value', 'unit']))) {
    throw new TokenTypeError(`${tokenType} $value must be {value, unit}`, path);
  }
  const amount = value['value'];
  if (!isNumber(amount)) throw new TokenTypeError(`${tokenType} value must be a number`, path);
  if (!inStringSet(units, value['unit'])) {
    throw new TokenTypeError(`${tokenType} unit must be one of ${pyRepr(sortedStrings(units))}`, path);
  }
  if (tokenType === 'duration' && numeric(amount) < 0) throw new TokenTypeError('duration must be non-negative', path);
  return `${fmt(amount)}${String(value['unit'])}`;
}

function normalizeFontFamily(value: unknown, path: string): string {
  const families: unknown = typeof value === 'string' ? [value] : value;
  const valid =
    Array.isArray(families) && families.length > 0 && families.every((f: unknown) => typeof f === 'string' && f !== '');
  if (!valid) throw new TokenTypeError('fontFamily must be a non-empty string or string list', path);
  return (families as readonly string[]).map((f) => (SIMPLE_FAMILY.test(f) ? f : `"${f}"`)).join(', ');
}

function normalizeFontWeight(value: unknown, path: string): string {
  if (isNumber(value) && numeric(value) >= 1 && numeric(value) <= 1000) return fmt(value);
  if (typeof value === 'string' && FONT_WEIGHT_NAMES.has(value)) return value;
  throw new TokenTypeError('fontWeight must be 1..1000 or a DTCG weight name', path);
}

function normalizeCubicBezier(value: unknown, path: string): string {
  if (!(Array.isArray(value) && value.length === 4 && value.every((v: unknown) => isNumber(v)))) {
    throw new TokenTypeError('cubicBezier must be 4 numbers', path);
  }
  const points = value as readonly PyNumber[];
  if (!(inUnitRange(points[0] ?? 0) && inUnitRange(points[2] ?? 0))) {
    throw new TokenTypeError('cubicBezier x-coordinates must be within [0, 1]', path);
  }
  return `cubic-bezier(${points.map(fmt).join(', ')})`;
}

function normalizeNumber(value: unknown, path: string): string {
  if (!isNumber(value)) throw new TokenTypeError('number token must be numeric', path);
  return fmt(value);
}

/** Validate a literal DTCG value for its type and return its CSS form. */
export function normalizeValue(tokenType: string, value: unknown, path: string): string {
  if (tokenType === 'color') return normalizeColor(value, path);
  if (tokenType === 'dimension' || tokenType === 'duration') return normalizeMeasure(tokenType, value, path);
  if (tokenType === 'fontFamily') return normalizeFontFamily(value, path);
  if (tokenType === 'fontWeight') return normalizeFontWeight(value, path);
  if (tokenType === 'cubicBezier') return normalizeCubicBezier(value, path);
  if (tokenType === 'number') return normalizeNumber(value, path);
  throw new TokenTypeError(`unsupported $type ${pyRepr(tokenType)}`, path);
}
