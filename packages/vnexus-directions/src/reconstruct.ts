/**
 * The pure rules of stage 7 (`directions/reconstruct.py`) and the storage keys of `directions/service.py`.
 *
 * Only roles that need editable paths enter reconstruction. Nothing is called "vector" unless it parses, passes the
 * SVG safety verifier, has native shapes and no embedded raster or external reference. Left in Python: the AVIC
 * region trace, PNG decoding, the palette snap (Lab distance, `t ** (1/3)`), Chromium fidelity measurement and
 * SVG parsing; the twin takes the SVG geometry facts (`measure.geometry`) as input.
 */
import {
  PY_DECIMAL, PY_SPACE, PyAttributeError, cpLen, cpSlice, escapeXml, fontName, formatFixed, pyRepr, pyRoundInt, pyRstrip, pyStr, type PyValue,
} from '@amc/vnexus-brandbook';
import { hamming, type Geometry } from './measure';
import type { AssetRole, CreativeIntent, GenerationCandidate } from './records';
import { LOGO_ROLES } from './records';

export const FIDELITY_MAX_DELTA_E = 8.0;
export const TRACE_BUDGETS = [256, 1024] as const;
export const TEXT_ROLES: ReadonlySet<AssetRole> = new Set<AssetRole>(['WORDMARK', 'LOCKUP']);
export const NEAR_DUPLICATE_BITS = 4;

/** RECONSTRUCT | OPTIONAL | NOT_REQUIRED | KEEP_RASTER, with the reason. */
export function decideReconstruction(intent: CreativeIntent, cand: Pick<GenerationCandidate, 'observed'>): [string, string] {
  if (intent.vector_need === 'KEEP_RASTER') return ['KEEP_RASTER', `${intent.asset_role} keeps its raster master; vectorization adds no value`];
  if (cand.observed.format_class === 'VECTOR') return ['NOT_REQUIRED', 'the selected candidate is already native vector'];
  if (intent.vector_need === 'REQUIRED') return ['RECONSTRUCT', 'the selected raster needs editable paths for this role'];
  return ['OPTIONAL', 'reconstruction is optional for this role and runs only on explicit request'];
}

const GRADIENT = new RegExp(`<linearGradient id="(g[${PY_DECIMAL}]+)"[^>]*>([\\s\\S]*?)</linearGradient>`, 'gu');
const STOP = /stop-color="(#[0-9a-fA-F]{6})"/g;
const EMPTY_DEFS = new RegExp(`<defs>[${PY_SPACE}]*</defs>|<defs[${PY_SPACE}]*/>`, 'gu');
const FILL_URL = new RegExp(`fill="url\\(#(g[${PY_DECIMAL}]+)\\)"`, 'gu');

function hexOf(rgb: readonly number[]): string {
  return '#' + rgb.map((c) => c.toString(16).padStart(2, '0')).join('');
}

function rgbOf(h: string): number[] {
  return [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
}

/** Replace each region gradient by the mean of its stops (palette snapping follows); masters carry flat fills. */
export function flattenGradients(svg: string): string {
  const means = new Map<string, string>();
  for (const m of svg.matchAll(GRADIENT)) {
    const stops = [...(m[2] ?? '').matchAll(STOP)].map((s) => rgbOf(s[1] as string));
    if (stops.length > 0) means.set(m[1] as string, hexOf([0, 1, 2].map((i) => pyRoundInt(stops.reduce((a, c) => a + (c[i] as number), 0) / stops.length))));
  }
  const flat = svg.replace(GRADIENT, '').replace(EMPTY_DEFS, '');
  return flat.replace(FILL_URL, (_all, id: string) => `fill="${means.get(id) ?? '#000000'}"`);
}

export type Box = readonly [number, number, number, number];

/** Set the exact identity strings as editable `<text>` in the approved display face (never traced). */
export function withText(svg: string, texts: readonly string[], box: Box, face: PyValue | undefined, fill: string): string {
  const [x, y, w, h] = box;
  const size = Math.max(6, Math.trunc(h * 0.7 / Math.max(1, texts.length)));
  const name = face ? fontName(face) : 'sans-serif';
  if (name === null) throw new PyAttributeError("'NoneType' object has no attribute 'replace'");
  // `font_name` only passes letters, digits, space, dot, dash and underscore, so a quote cannot reach here;
  // escaping it anyway keeps the attribute safe if that rule ever loosens. Output is unchanged for every reachable name.
  const family = escapeXml(name).replace(/"/g, '&quot;');
  const lines = texts.map((t, i) => `<text x="${formatFixed(x + w / 2, 1)}" y="${formatFixed(y + (i + 1) * h / (texts.length + 0.5), 1)}" `
    + `font-family="${family}" font-size="${size}" text-anchor="middle" fill="${fill}">${escapeXml(t)}</text>`).join('');
  const trimmed = pyRstrip(pyRstrip(svg).replace(/<\/svg>$/, ''));
  return trimmed + lines + '</svg>\n';
}

export interface ReconstructionCheck {
  readonly check: string;
  readonly status: string;
  readonly detail: string;
}

function orText(a: string | undefined, b: string | undefined, fallback: string): string {
  return a || b || fallback;
}

function num(v: number | undefined): number {
  return v ?? 0;
}

/** Validation checks for a reconstructed or imported SVG, from its geometry facts. */
export function validateGeometry(geo: Geometry, intent: CreativeIntent): [string, ReconstructionCheck[]] {
  const checks: ReconstructionCheck[] = [];
  const check = (name: string, status: string, detail: string): void => void checks.push({ check: name, status, detail });
  const refs = (geo.external_refs ?? []).length > 0;
  check('svg_safety', geo.parseable && geo.safe && !refs ? 'PASS' : 'FAIL', orText(geo.safety_detail, geo.error, ''));
  check('native_geometry', geo.vector ? 'PASS' : 'FAIL', geo.classification === 'RASTER_IN_SVG'
    ? 'embedded raster is raster, not vector' : `${num(geo.shapes)} shapes, ${num(geo.path_nodes)} path commands`);
  check('view_box', geo.view_box ? 'PASS' : 'FAIL', geo.view_box || 'missing viewBox');
  const palette = new Set(Object.values(intent.vector_instructions.palette_roles).filter((v) => typeof v === 'string').map((v) => v.toLowerCase()));
  const off = (geo.fills ?? []).filter((f) => !palette.has(f));
  const role = intent.asset_role;
  if (TEXT_ROLES.has(role) || role === 'LOGO_MARK' || role === 'ICON') {
    const gradients = num(geo.gradients);
    check('palette_only_fills', off.length === 0 && gradients === 0 ? 'PASS' : 'FAIL',
      off.length > 0 ? `off-palette fills ${pyStr(off as unknown as PyValue)}` : (gradients ? `${gradients} gradients` : 'palette roles only'));
  }
  textCheck(check, geo, intent.vector_instructions.exact_text);
  check('clipping', geo.clip_paths ? 'NOT_VERIFIED' : 'PASS', `${num(geo.clip_paths)} clip paths`);
  check('self_intersections', 'NOT_VERIFIED', 'no geometry kernel is installed; inspect paths in an editor');
  check('curve_quality_and_nodes', 'NOT_VERIFIED', `${num(geo.path_nodes)} path commands; curve quality needs a designer`);
  const rejected = !(geo.parseable && geo.safe) || refs;
  return [rejected ? 'REJECTED' : (geo.classification === 'RASTER_IN_SVG' ? 'RASTER_IN_SVG' : 'VECTOR'), checks];
}

function textCheck(check: (n: string, s: string, d: string) => void, geo: Geometry, exact: readonly string[]): void {
  if (exact.length === 0) {
    check('editable_exact_text', 'NOT_APPLICABLE', 'no identity text in the brief');
    return;
  }
  const missing = exact.filter((t) => !(geo.text_elements ?? []).includes(t));
  check('editable_exact_text', missing.length > 0 ? 'FAIL' : 'PASS', missing.length > 0 ? `missing ${pyStr(missing as unknown as PyValue)}` : 'set verbatim as editable text');
}

// ------------------------------------------------------------------------------------------------ storage keys

export class StorageKeyError extends Error {
  override name = 'ValueError';
}

function removePrefix(text: string, prefix: string): string {
  return text.startsWith(prefix) ? text.slice(prefix.length) : text;
}

/** `vdx-<intent>-<suffix>`; refuses a key whose `foundry-` form Project OS would truncate to 64 characters. */
export function storageKey(intentId: string, suffix: string): string {
  const name = `vdx-${removePrefix(intentId, 'vdi-')}-${suffix}`;
  if (cpLen(`foundry-${name}`) > 64) throw new StorageKeyError(`artifact key ${pyRepr(name)} would be truncated by Project OS`);
  return name;
}

export function candidateName(intentId: string, candidateId: string, suffix = ''): string {
  return storageKey(intentId, `c${cpSlice(removePrefix(candidateId, 'vdc-'), 0, 12)}${suffix}`);
}

export function reconstructionName(intentId: string, reconstructionId: string): string {
  return storageKey(intentId, `v${cpSlice(removePrefix(reconstructionId, 'vdv-'), 0, 12)}`);
}

/** The genome keys a frozen master is pinned under: logo roles share the logo keys. */
export function masterKeys(intent: Pick<CreativeIntent, 'asset_role'>): [string, string] {
  if (LOGO_ROLES.has(intent.asset_role)) return ['visual.logo.master_artifact', 'visual.logo.master_sha256'];
  const base = `visual.assets.${intent.asset_role.toLowerCase()}`;
  return [`${base}.master_artifact`, `${base}.master_sha256`];
}

export interface KnownCandidate {
  readonly candidate_id: string;
  readonly sha256: string;
  readonly perceptual_hash: string | null;
}

/** The earlier candidate this one duplicates: identical bytes, or a perceptual hash within 4 bits. */
export function nearDuplicate(others: readonly KnownCandidate[], phash: string | null, sha: string): string | null {
  for (const other of others) {
    if (other.sha256 === sha) return other.candidate_id;
    if (phash && other.perceptual_hash && hamming(phash, other.perceptual_hash) <= NEAR_DUPLICATE_BITS) return other.candidate_id;
  }
  return null;
}

