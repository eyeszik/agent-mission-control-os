/** Design territories and the design genome (Python `_territories`, `_genome`). */
import { formatFixed, roundTo, sortedStrings, compareCodePoints } from './python';
import { TERRITORY_TEMPLATES } from './catalog';
import type { DesignGenome, SurfaceMode, Territory } from './types';

interface Scored {
  readonly score: number;
  readonly id: string;
  readonly name: string;
  readonly thesis: string;
  readonly affinities: readonly string[];
}

function toneTokens(tones: readonly string[]): Set<string> {
  return new Set(tones.flatMap((tone) => tone.toLowerCase().match(/[a-z]+/g) ?? []));
}

function score(template: (typeof TERRITORY_TEMPLATES)[number], mode: SurfaceMode, tokens: ReadonlySet<string>, features: ReadonlySet<string>): number {
  const matches = template.affinities.filter((word) => tokens.has(word)).length;
  let value = 0.5 * Number(template.modes.includes(mode)) + 0.1 * Math.min(matches, 3);
  if (template.id === 'operational-clarity' && features.has('high_density')) value += 0.2;
  return roundTo(Math.min(value, 1.0), 3);
}

function describe(item: Scored, tokens: ReadonlySet<string>, best: string): Territory {
  const matched = sortedStrings(item.affinities.filter((word) => tokens.has(word)));
  const shown = matched.length > 0 ? `[${matched.map((word) => `'${word}'`).join(', ')}]` : 'none';
  return {
    id: item.id,
    name: item.name,
    thesis: item.thesis,
    score: item.score,
    fit_rationale: `surface fit=${item.score >= 0.5 ? 'yes' : 'no'}; tone matches=${shown}`,
    selected: item.id === best,
    rejection_reason: item.id === best ? null : `lower fit (${formatFixed(item.score, 2)}) than the selected territory`,
  };
}

/** Score every territory against the surface, tone and features; the best is selected. */
export function territories(mode: SurfaceMode, tones: readonly string[], features: ReadonlySet<string>): Territory[] {
  const tokens = toneTokens(tones);
  const scored: Scored[] = TERRITORY_TEMPLATES.map((t) => ({ ...t, score: score(t, mode, tokens, features) }));
  scored.sort((a, b) => b.score - a.score || compareCodePoints(a.id, b.id));
  const best = (scored[0] as Scored).id;
  return scored.map((item) => describe(item, tokens, best));
}

type GenomeBase = readonly [string, string, string, string, string];

const GENOME_BASES: Readonly<Record<string, GenomeBase>> = {
  'quiet-precision': [
    'strict typographic hierarchy; one focal element per view',
    '4px-based radius, hairline borders, no shadows as decoration',
    'neutral surfaces; accent reserved for the P0 action',
    'flat surfaces separated by borders and space',
    'short, purposeful state transitions only',
  ],
  'editorial-warmth': [
    'large display type leading a single narrative column',
    'generous radius on media, square text blocks',
    'brand color used in imagery and the primary action, neutral text',
    'content and real imagery as the material',
    'gentle entrance of content, never looping decoration',
  ],
  'operational-clarity': [
    'status first, then values, then context',
    'tight grid, tabular alignment, small radius',
    'neutral data surfaces; status colors always paired with icon + text',
    'bordered panels on a single surface level',
    'instant feedback, no ornamental motion',
  ],
};

export function genomeBase(territoryId: string): GenomeBase {
  const base = GENOME_BASES[territoryId];
  if (base === undefined) throw new Error(`unknown territory ${territoryId}`);
  return base;
}

function densityFor(mode: SurfaceMode, features: ReadonlySet<string>): DesignGenome['density'] {
  if (features.has('high_density')) return 'HIGH';
  return mode === 'LANDING_PAGE' ? 'LOW' : 'MEDIUM';
}

export interface GenomeInput {
  readonly mode: SurfaceMode;
  readonly territory: Territory;
  readonly brandTypography: string | null;
  readonly features: ReadonlySet<string>;
  readonly brandName: string;
}

/** The genome without its hash (the compiler fills `genome_hash` after the principles ran). */
export function buildGenome(input: GenomeInput): DesignGenome {
  const base = genomeBase(input.territory.id);
  return {
    hierarchy: base[0],
    density: densityFor(input.mode, input.features),
    geometry: base[1],
    // `brand_typography or <default>`: an empty string falls back too.
    typography: input.brandTypography || 'system sans for UI, monospace for data; scale by role not by page',
    color: base[2],
    material: base[3],
    motion: base[4],
    interaction: 'native controls, explicit states, keyboard-complete',
    signature: `one product-specific element derived from ${input.brandName}'s thesis (not generic decoration)`,
    genome_hash: '',
  };
}
