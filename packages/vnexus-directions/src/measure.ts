/**
 * Measurement shapes and the pure arithmetic of `directions/measure.py`. Decoding PNG, rasterising SVG in Chromium,
 * parsing SVG (ElementTree) and the Lab colour distance (`t ** (1/3)`, whose last bit differs between libm and V8)
 * stay in Python: the twin takes their results as `CandidateMeasurement`.
 */
import { CanonicalFloat } from '@amc/canonical';
import { pyRepr, type PyValue } from '@amc/vnexus-brandbook';

export const MEASURE_VERSION = 'amc-vnexus-directions-measure/1.0.0';
export const OFF_PALETTE_DELTA_E = 10.0;

export type Num = number | CanonicalFloat;

export function n(value: Num): number {
  return value instanceof CanonicalFloat ? value.value : value;
}

export interface DominantColour {
  readonly hex: string;
  readonly share: Num;
  readonly nearest_role: string | null;
  readonly delta_e76: Num | null;
}

/** `measure.pixels(...)`: facts about decoded pixels. */
export interface Pixels {
  readonly nonblank: boolean;
  readonly dominant: readonly DominantColour[];
  readonly off_palette_share: Num;
  readonly dominant_pair_contrast: Num | null;
  readonly figure_share: Num;
  readonly aspect: Num;
  readonly retention_32: Num | null;
}

/** `measure.geometry(...)`: structural facts about an SVG. */
export interface Geometry {
  readonly parseable: boolean;
  readonly classification: string;
  readonly error?: string;
  readonly safe?: boolean;
  readonly safety_detail?: string;
  readonly vector?: boolean;
  readonly view_box?: string | null;
  readonly shapes?: number;
  readonly path_nodes?: number;
  readonly text_elements?: readonly string[];
  readonly external_refs?: readonly string[];
  readonly fills?: readonly string[];
  readonly clip_paths?: number;
  readonly gradients?: number;
  readonly pii_like_text?: readonly string[];
}

/** What `review._measure` returns for one candidate. */
export interface CandidateMeasurement {
  readonly sha256: string;
  readonly mime: string;
  readonly geometry?: Geometry;
  readonly pixel_source: string;
  readonly pixels: Pixels | null;
}

export class MeasureValueError extends Error {
  override name = 'ValueError';
}

/** `hex_rgb("#rrggbb")` (Python slices by position and `int(.., 16)`). */
export function hexRgb(h: string): [number, number, number] {
  const part = (a: number, b: number): number => {
    const text = h.slice(a, b);
    if (!/^[0-9a-fA-F]+$/.test(text)) throw new MeasureValueError(`invalid literal for int() with base 16: ${pyRepr(text)}`);
    return parseInt(text, 16);
  };
  return [part(1, 3), part(3, 5), part(5, 7)];
}

function popcount(value: bigint): number {
  let v = value;
  let count = 0;
  while (v > 0n) {
    count += Number(v & 1n);
    v >>= 1n;
  }
  return count;
}

/** `bin(int(a, 16) ^ int(b, 16)).count("1")` for two hex perceptual hashes. */
export function hamming(a: string, b: string): number {
  for (const t of [a, b]) if (!/^[0-9a-fA-F]+$/.test(t)) throw new MeasureValueError(`invalid literal for int() with base 16: ${pyRepr(t)}`);
  return popcount(BigInt(`0x${a}`) ^ BigInt(`0x${b}`));
}
