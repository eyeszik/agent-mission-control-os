/**
 * Tiered DTCG token system for a UI spec plus its contrast checks (twin of
 * `ui_ux/tokens.py`). WCAG 2.2 decides pass/fail; APCA Lc is advisory only and
 * never merged with it. DTCG structure is compiled by `@amc/design-tokens`,
 * the one repository compiler; nothing here re-implements it.
 */
import { compileCss, hexToColor } from '@amc/design-tokens';
import { roundTo } from './python';
import type { BrandContext } from './models';
import type { ContrastCheck, DesignGenome, SourceKind, TokenSystemSpec, WCAGRequirement } from './types';

export const CSS_PREFIX = 'ui';
// Python `^#[0-9a-fA-F]{6}$`: `$` also matches before a final newline.
const HEX = /^#[0-9a-fA-F]{6}\n?$/;

const WCAG_THRESHOLDS: Readonly<Record<WCAGRequirement, number>> = {
  AAA_NORMAL: 7.0, AAA_LARGE: 4.5, AA_NORMAL: 4.5, AA_LARGE: 3.0, NON_TEXT: 3.0,
};

type Scheme = 'dark' | 'light';

/** The AMC Zinc baseline: structure comes from it, brand color is layered on as accent. */
const NEUTRAL: Readonly<Record<string, string>> = {
  '50': '#fafafa', '100': '#f4f4f5', '200': '#e4e4e7', '300': '#d4d4d8', '400': '#a1a1aa',
  '500': '#71717a', '600': '#52525b', '700': '#3f3f46', '800': '#27272a', '900': '#18181b', '950': '#09090b',
};
const STATUS: Readonly<Record<Scheme, Readonly<Record<string, string>>>> = {
  dark: { success: '#34d399', warning: '#fbbf24', danger: '#f87171', info: '#38bdf8' },
  light: { success: '#047857', warning: '#b45309', danger: '#b91c1c', info: '#0369a1' },
};
const FALLBACK_ACCENT: Readonly<Record<Scheme, string>> = { dark: '#10b981', light: '#047857' };
const SCHEME_ROLES: Readonly<Record<Scheme, Readonly<Record<string, string>>>> = {
  dark: {
    background: '950', surface: '900', 'surface-raised': '800', border: '800',
    'border-strong': '500', foreground: '300', 'foreground-strong': '50', 'foreground-muted': '400',
  },
  light: {
    background: '50', surface: '100', 'surface-raised': '200', border: '200',
    'border-strong': '500', foreground: '700', 'foreground-strong': '950', 'foreground-muted': '600',
  },
};

function channels(hexValue: string): [number, number, number] {
  const h = hexValue.replace(/^#+/, '');
  const at = (i: number): number => parseInt(h.slice(i, i + 2), 16) / 255;
  return [at(0), at(2), at(4)];
}

function linear(c: number): number {
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

/** WCAG 2.2 relative luminance (sRGB). */
export function relativeLuminance(hexValue: string): number {
  const [r, g, b] = channels(hexValue).map(linear) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function wcagContrastRatio(foreground: string, background: string): number {
  const a = relativeLuminance(foreground);
  const b = relativeLuminance(background);
  const [lighter, darker] = [Math.max(a, b), Math.min(a, b)];
  return roundTo((lighter + 0.05) / (darker + 0.05), 2);
}

function apcaY(hexValue: string): number {
  const [r, g, b] = channels(hexValue);
  const value = 0.2126729 * r ** 2.4 + 0.7151522 * g ** 2.4 + 0.072175 * b ** 2.4;
  return value > 0.022 ? value : value + (0.022 - value) ** 1.414;
}

function apcaOutput(txt: number, bg: number): number {
  if (bg > txt) {
    const sapc = (bg ** 0.56 - txt ** 0.57) * 1.14;
    return sapc < 0.1 ? 0.0 : sapc - 0.027;
  }
  const sapc = (bg ** 0.65 - txt ** 0.62) * 1.14;
  return sapc > -0.1 ? 0.0 : sapc + 0.027;
}

/** APCA-W3 0.0.98G-4g Lc. ADVISORY ONLY: not a WCAG 2.2 conformance measure. */
export function apcaLc(text: string, background: string): number {
  const [txt, bg] = [apcaY(text), apcaY(background)];
  if (Math.abs(bg - txt) < 0.0005) return 0.0;
  return roundTo(apcaOutput(txt, bg) * 100, 1);
}

export function contrastCheck(fgPath: string, bgPath: string, fg: string, bg: string, requirement: WCAGRequirement): ContrastCheck {
  const ratio = wcagContrastRatio(fg, bg);
  return {
    foreground: fgPath,
    background: bgPath,
    foreground_value: fg,
    background_value: bg,
    wcag_requirement: requirement,
    wcag_ratio: ratio,
    passes: ratio >= WCAG_THRESHOLDS[requirement],
    verification: 'VERIFIED_STATIC',
    apca_lc_advisory: apcaLc(fg, bg),
    apca_note: 'APCA Lc is advisory perceptual analysis, not WCAG 2.2 conformance.',
  };
}

function validPalette(brand: BrandContext | null): string[] {
  if (brand === null) return [];
  return brand.palette_hex.filter((value) => HEX.test(value)).map((value) => value.toLowerCase());
}

/** Light when the brand declares a near-white surface color, otherwise dark. */
export function chooseScheme(palette: readonly string[]): Scheme {
  return palette.length > 0 && Math.max(...palette.map(relativeLuminance)) > 0.85 ? 'light' : 'dark';
}

function spacing(density: DesignGenome['density']): Record<string, number> {
  const base = { LOW: 6, MEDIUM: 4, HIGH: 3 }[density];
  return { '1': base, '2': base * 2, '3': base * 3, '4': base * 4, '6': base * 6 };
}

type Doc = Record<string, unknown>;
const color = (hexValue: string): Doc => ({ $value: hexToColor(hexValue) });
const alias = (path: string): Doc => ({ $value: `{${path}}` });
const dimension = (value: number, unit: string): Doc => ({ $value: { value, unit } });

function mapValues(source: Readonly<Record<string, string>>, fn: (value: string) => Doc): Doc {
  return Object.fromEntries(Object.entries(source).map(([key, value]) => [key, fn(value)]));
}

function pickAccent(palette: readonly string[], background: string, scheme: Scheme, notes: string[]): string {
  const found = palette.find((value) => wcagContrastRatio(value, background) >= 3.0);
  if (found !== undefined) return found;
  notes.push(
    palette.length > 0
      ? 'No brand palette color reaches 3:1 non-text contrast against the background; ' +
          'baseline accent used pending design_token_set review.'
      : 'Brand palette unresolved (no reference hex); baseline accent used as a placeholder.',
  );
  return FALLBACK_ACCENT[scheme];
}

function primitiveColor(palette: readonly string[], scheme: Scheme, accent: string, onAccent: string): Doc {
  const doc: Doc = {
    $type: 'color',
    neutral: mapValues(NEUTRAL, color),
    status: mapValues(STATUS[scheme], color),
    accent: { base: color(accent), on: color(onAccent) },
  };
  if (palette.length > 0) {
    doc['brand'] = Object.fromEntries(palette.map((value, index) => [String(index + 1), color(value)]));
  }
  return doc;
}

function semanticColor(scheme: Scheme): Doc {
  const doc: Doc = { $type: 'color' };
  for (const [role, step] of Object.entries(SCHEME_ROLES[scheme])) doc[role] = alias(`primitive.color.neutral.${step}`);
  doc['accent'] = alias('primitive.color.accent.base');
  doc['on-accent'] = alias('primitive.color.accent.on');
  doc['focus-ring'] = alias('primitive.color.accent.base');
  doc['status'] = Object.fromEntries(Object.keys(STATUS[scheme]).map((key) => [key, alias(`primitive.color.status.${key}`)]));
  return doc;
}

function componentTokens(includeAi: boolean, includeData: boolean): Doc {
  const component: Doc = {
    button: {
      primary: { $type: 'color', background: alias('semantic.color.accent'), foreground: alias('semantic.color.on-accent') },
      radius: { $type: 'dimension', ...alias('semantic.radius.control') },
    },
    focus: { $type: 'color', ring: alias('semantic.color.focus-ring') },
  };
  if (includeAi) {
    component['ai-trust'] = {
      $type: 'color',
      border: alias('semantic.color.border-strong'),
      label: alias('semantic.color.foreground-strong'),
      degraded: alias('semantic.color.status.warning'),
      unavailable: alias('semantic.color.status.danger'),
    };
  }
  if (includeData) {
    component['metric'] = {
      $type: 'color',
      value: alias('semantic.color.foreground-strong'),
      'truth-label': alias('semantic.color.foreground'),
    };
  }
  return component;
}

function primitiveScales(density: DesignGenome['density']): Doc {
  return {
    space: { $type: 'dimension', ...Object.fromEntries(Object.entries(spacing(density)).map(([k, v]) => [k, dimension(v, 'px')])) },
    radius: { $type: 'dimension', sm: dimension(4, 'px'), md: dimension(6, 'px'), lg: dimension(10, 'px') },
    duration: { $type: 'duration', fast: dimension(120, 'ms'), base: dimension(200, 'ms') },
  };
}

function semanticScales(): Doc {
  return {
    space: {
      $type: 'dimension',
      inline: alias('primitive.space.2'), stack: alias('primitive.space.3'),
      panel: alias('primitive.space.4'), section: alias('primitive.space.6'),
    },
    radius: { $type: 'dimension', control: alias('primitive.radius.md'), panel: alias('primitive.radius.lg') },
    motion: { $type: 'duration', feedback: alias('primitive.duration.fast') },
  };
}

export interface TokenDocumentOptions {
  readonly includeAi: boolean;
  readonly includeData: boolean;
}

export interface TokenDocument {
  readonly document: Doc;
  readonly scheme: Scheme;
  readonly notes: readonly string[];
}

function firstMax(values: readonly string[], key: (value: string) => number): string {
  let best = values[0] as string;
  for (const value of values.slice(1)) if (key(value) > key(best)) best = value;
  return best;
}

export function buildTokenDocument(brand: BrandContext | null, genome: DesignGenome, options: TokenDocumentOptions): TokenDocument {
  const palette = validPalette(brand);
  const scheme = chooseScheme(palette);
  const background = NEUTRAL[SCHEME_ROLES[scheme]['background'] as string] as string;
  const notes: string[] = [];
  const accent = pickAccent(palette, background, scheme, notes);
  const onAccent = firstMax(['#fafafa', '#09090b'], (value) => wcagContrastRatio(value, accent));
  const base = primitiveScales(genome.density);
  const document: Doc = {
    primitive: { color: primitiveColor(palette, scheme, accent, onAccent), ...base },
    semantic: { color: semanticColor(scheme), ...semanticScales() },
    component: componentTokens(options.includeAi, options.includeData),
  };
  return { document, scheme, notes };
}

const CONTRAST_PAIRS: ReadonlyArray<readonly [string, string, WCAGRequirement]> = [
  ['semantic.color.foreground', 'semantic.color.background', 'AAA_NORMAL'],
  ['semantic.color.foreground-strong', 'semantic.color.background', 'AAA_NORMAL'],
  ['semantic.color.foreground', 'semantic.color.surface', 'AA_NORMAL'],
  ['semantic.color.foreground-muted', 'semantic.color.background', 'AA_NORMAL'],
  ['semantic.color.on-accent', 'semantic.color.accent', 'AA_NORMAL'],
  ['semantic.color.focus-ring', 'semantic.color.background', 'NON_TEXT'],
  ['semantic.color.border-strong', 'semantic.color.background', 'NON_TEXT'],
  ['semantic.color.status.warning', 'semantic.color.surface', 'AA_NORMAL'],
  ['semantic.color.status.danger', 'semantic.color.surface', 'AA_NORMAL'],
];

function paletteResolution(brand: BrandContext | null, scheme: Scheme, notes: readonly string[]): string {
  const palette = validPalette(brand);
  const source: SourceKind = brand ? brand.palette_source : 'COMPILER_DEFAULT';
  const base =
    palette.length > 0
      ? `${scheme} scheme; accent from ${source} palette (${palette.length} valid color(s))`
      : `${scheme} scheme; brand palette UNRESOLVED -- structural tokens only`;
  return notes.length > 0 ? `${base}; ${notes.join(' ')}` : base;
}

export function compileTokenSystem(brand: BrandContext | null, genome: DesignGenome, options: TokenDocumentOptions): TokenSystemSpec {
  const { document, scheme, notes } = buildTokenDocument(brand, genome, options);
  const [graph, css] = compileCss(document, { prefix: CSS_PREFIX, tiered: true, sourceLabel: 'uiux-compiler' });
  const contrast = CONTRAST_PAIRS.map(([fg, bg, requirement]) =>
    contrastCheck(fg, bg, graph.get(fg).css, graph.get(bg).css, requirement),
  );
  return {
    format: 'DTCG 2025.10',
    tiers: ['primitive', 'semantic', 'component'],
    css_prefix: CSS_PREFIX,
    document,
    source_hash: graph.sourceHash,
    token_count: graph.tokens.size,
    css,
    contrast,
    palette_resolution: paletteResolution(brand, scheme, notes),
  };
}
