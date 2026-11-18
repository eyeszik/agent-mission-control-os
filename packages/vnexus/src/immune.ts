/**
 * VNEXUS design immune system: the pure checks of `vnexus/immune.py`.
 *
 * Findings carry a severity and the evidence behind them. Remediation is only
 * offered for deterministic, reversible repairs (snapping a near-palette
 * colour); approved genome decisions are never changed here. Reading stored
 * outputs and writing revisions stay in Python.
 */
import { CanonicalFloat } from '@amc/canonical';
import { colorsIn, deltaE76, wcagContrastRatio } from './color';
import { VnexusDivergenceError } from './errors';
import type { Resolution } from './resolve';
import { DIGIT_ZEROS, PY_DIGIT_CLASS, PY_SPACE_CLASS } from './python-tables';
import { canonicalHashSync, floatRepr, formatFixed, pyFloat, pyStrip, roundTo, sortedStrings, sortedUnique, type PyData } from './python';

export const SNAP_DELTA_E = 6.0; // beyond a just-noticeable difference, below an obvious colour change

const FONT = /font-family="([^"]+)"/g;
const TEXT_FILL = new RegExp(`<text[^>]*${PY_SPACE_CLASS}fill="(#[0-9a-fA-F]{6})"`, 'gu');
const BG = new RegExp(`<rect width="(${PY_DIGIT_CLASS}+)" height="(${PY_DIGIT_CLASS}+)" fill="(#[0-9a-fA-F]{6})"/>`, 'u');
const DIMS = new RegExp(`<svg[^>]*${PY_SPACE_CLASS}width="(${PY_DIGIT_CLASS}+)"[^>]*${PY_SPACE_CLASS}height="(${PY_DIGIT_CLASS}+)"`, 'u');
const PALETTE_HEX = /^#[0-9a-f]{6}$/;

export type Finding = Record<string, PyData>;

export interface FindingOptions {
  readonly evidence?: Readonly<Record<string, PyData>>;
  readonly remediation?: Readonly<Record<string, PyData>> | null;
}

/** `finding`: the id is a hash of code, subject and detail only. */
export function finding(code: string, severity: string, subject: string, detail: string, options: FindingOptions = {}): Finding {
  const id = `fnd-${canonicalHashSync({ code, subject, detail }).slice(0, 16)}`;
  return {
    code, severity, subject, detail, evidence: (options.evidence ?? {}) as Record<string, PyData>,
    remediation: (options.remediation ?? null) as Record<string, PyData> | null, finding_id: id,
  };
}

/** `palette_from`: role -> colour for every `visual.color.*` value that is a `#rrggbb`. */
export function paletteFrom(resolution: Resolution): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(resolution.values)) {
    if (!key.startsWith('visual.color.') || typeof value !== 'string') continue;
    const lowered = value.toLowerCase();
    if (PALETTE_HEX.test(lowered)) out[key.split('.').at(-1) as string] = lowered;
  }
  return out;
}

/** `approved_fonts`. */
export function approvedFonts(resolution: Resolution): Set<string> {
  const out = new Set<string>();
  for (const [key, value] of Object.entries(resolution.values)) {
    if (key.startsWith('visual.typography.') && typeof value === 'string') out.add(value);
  }
  return out;
}

/** `genome_findings`. */
export function genomeFindings(resolution: Resolution): Finding[] {
  const out: Finding[] = [];
  for (const f of resolution.findings) {
    if (f.passed) continue;
    out.push(finding(`GENOME_${f.kind}`, f.severity, `genome:${f.key}`, f.detail, {
      evidence: { constraint_id: f.constraint_id, declared_by: f.declared_by },
    }));
  }
  for (const c of resolution.conflicts) {
    const severity = c.reason !== 'UNAPPROVED_OVERRIDE' ? 'ERROR' : 'INFO';
    out.push(finding(`INHERITANCE_${c.reason}`, severity, `genome:${c.key}`, c.detail || c.reason, {
      evidence: { scope_ref: c.scope_ref, constraint_id: c.constraint_id },
    }));
  }
  return out;
}

/** Python `int()` of a run of Unicode decimal digits. */
export function pyIntDigits(text: string): bigint {
  let value = 0n;
  for (const ch of text) {
    const cp = ch.codePointAt(0) as number;
    const zero = [...DIGIT_ZEROS].reverse().find((z) => z <= cp) as number;
    value = value * 10n + BigInt(cp - zero);
  }
  return value;
}

function offPalette(name: string, svg: string, palette: Readonly<Record<string, string>>): Finding[] {
  const allowed = sortedUnique(Object.values(palette));
  if (allowed.length === 0) return [];
  const out: Finding[] = [];
  for (const colour of sortedUnique(colorsIn(svg))) {
    let nearest = allowed[0] as string;
    for (const p of allowed) if (deltaE76(colour, p) < deltaE76(colour, nearest)) nearest = p;
    const d = deltaE76(colour, nearest);
    if (d <= 2.3) continue;
    const rounded = pyFloat(roundTo(d, 2));
    const remediation = d <= SNAP_DELTA_E ? { kind: 'SNAP_COLOUR', from: colour, to: nearest, delta_e76: rounded } : null;
    out.push(finding('OFF_PALETTE_COLOUR', 'ERROR', name, `${colour} is ${formatFixed(d, 1)} dE76 from the nearest approved colour ${nearest}`, {
      evidence: { colour, nearest, delta_e76: rounded }, remediation,
    }));
  }
  return out;
}

function unapprovedFonts(name: string, svg: string, fonts: ReadonlySet<string>): Finding[] {
  if (fonts.size === 0) return [];
  const out: Finding[] = [];
  const generic = new Set(['sans-serif', 'serif', 'monospace']);
  for (const family of sortedUnique(Array.from(svg.matchAll(FONT), (m) => m[1] as string))) {
    const first = pyStrip(pyStrip(family.split(',')[0] as string), '\'"');
    if (!fonts.has(first) && !generic.has(first)) {
      out.push(finding('UNAPPROVED_TYPEFACE', 'ERROR', name, `'${first}' is not an approved typeface`, {
        evidence: { approved: sortedStrings(fonts), found: family },
      }));
    }
  }
  return out;
}

function textContrast(name: string, svg: string): Finding[] {
  const bg = BG.exec(svg);
  if (!bg) return [];
  const out: Finding[] = [];
  for (const fill of sortedUnique(Array.from(svg.matchAll(TEXT_FILL), (m) => m[1] as string))) {
    const ratio = wcagContrastRatio(fill.toLowerCase(), (bg[3] as string).toLowerCase());
    if (ratio < 3.0) {
      out.push(finding('TEXT_CONTRAST', 'ERROR', name, `text ${fill} on ${bg[3]} is ${floatRepr(ratio)}:1`, {
        evidence: { ratio: pyFloat(ratio), threshold: new CanonicalFloat(3) },
      }));
    }
  }
  return out;
}

function dimensions(name: string, svg: string, expected: readonly [number, number] | null): Finding[] {
  const dims = DIMS.exec(svg);
  if (!expected || !dims) return [];
  const w = pyIntDigits(dims[1] as string);
  const h = pyIntDigits(dims[2] as string);
  if (w === BigInt(expected[0]) && h === BigInt(expected[1])) return [];
  return [finding('ASSET_DIMENSIONS', 'ERROR', name, `${dims[1]}x${dims[2]} != expected ${expected[0]}x${expected[1]}`)];
}

export interface SvgCheckOptions {
  readonly palette: Readonly<Record<string, string>>;
  readonly fonts: ReadonlySet<string>;
  readonly expected?: readonly [number, number] | null;
}

/** `svg_findings`. */
export function svgFindings(name: string, svg: string, options: SvgCheckOptions): Finding[] {
  return [
    ...offPalette(name, svg, options.palette), ...unapprovedFonts(name, svg, options.fonts), ...textContrast(name, svg),
    ...dimensions(name, svg, options.expected ?? null),
  ];
}

const PNG_MAGIC = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];

function bigEndian(data: Uint8Array, start: number, end: number): number {
  return Array.from(data.slice(start, end)).reduce((n, b) => n * 256 + b, 0);
}

/** `png_dims`: width and height from the IHDR, or null when the bytes are not a PNG. */
export function pngDims(data: Uint8Array): [number, number] | null {
  const head = Array.from(data.slice(0, 8));
  if (head.length !== 8 || !head.every((b, i) => b === PNG_MAGIC[i])) return null;
  return [bigEndian(data, 16, 20), bigEndian(data, 20, 24)];
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function assertSnapSafe(text: string): void {
  if (/[^\x20-\x7e]/.test(text) || text.includes('\\')) {
    throw new VnexusDivergenceError('snapColours refuses non-ASCII text and backslashes (Python treats the replacement as a template)');
  }
}

/** `snap_colours`: replace exact colour literals, case-insensitively. Deterministic; reversible through artifact history. */
export function snapColours(svg: string, swaps: Readonly<Record<string, string>>): string {
  if (Object.keys(swaps).length > 0 && /[\u0130\u0131\u017f\u212a]/.test(svg)) {
    throw new VnexusDivergenceError('snapColours refuses text with U+0130, U+0131, U+017F or U+212A (Python IGNORECASE folds them onto i, s and k)');
  }
  let out = svg;
  for (const old of sortedStrings(Object.keys(swaps))) {
    const replacement = swaps[old] as string;
    assertSnapSafe(old);
    assertSnapSafe(replacement);
    out = out.replace(new RegExp(escapeRegExp(old), 'gi'), () => replacement);
  }
  return out;
}
