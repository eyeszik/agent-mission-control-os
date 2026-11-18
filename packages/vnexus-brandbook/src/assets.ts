/**
 * Canonical identity assets for one build (`brandbook/assets.py`): resolved once, reused on every page, never
 * regenerated per page. Reading stored bytes and the SVG safety verifier stay in Python (I/O and an XML parser); the
 * twin takes them as typed callbacks.
 */
import type { FieldState, FieldStatus } from './fields';
import { sha256 } from './hash';
import { PY_SPACE, PY_WORD, base64, cpSlice, decodeReplace, utf8 } from './python';

const W = `[${PY_WORD}]`;
const I = '[iIİı]';
/** `_RASTER` with Python's IGNORECASE and Unicode `\b`. */
export const RASTER_SOURCE = `<${I}mage(?!${W})|data:${I}mage/(png|jpe?g|g${I}f|webp)`;
/** `_ACTIVE` with Python's IGNORECASE, Unicode `\b` and Python's `\s`. */
export const ACTIVE_SOURCE = `<scr${I}pt(?!${W})|<fore${I}gnObject(?!${W})|(?<!${W})on[a-zİı]+[${PY_SPACE}]*=|javascr${I}pt:|<!ENT${I}TY|<!DOCTYPE`;

export function hasRaster(svg: string): boolean {
  return new RegExp(RASTER_SOURCE, 'iu').test(svg);
}

export function hasActiveContent(svg: string): boolean {
  return new RegExp(ACTIVE_SOURCE, 'iu').test(svg);
}

export const ASSET_KINDS = ['VECTOR', 'RASTER_IN_SVG', 'PROPOSED_CONCEPT', 'MISSING'] as const;
export type AssetKind = (typeof ASSET_KINDS)[number];

export interface MarkAsset {
  readonly kind: AssetKind;
  readonly sha256: string | null;
  readonly svg: string | null;
  readonly source: string;
  readonly approved: boolean;
}

export interface MarkPublic {
  readonly kind: AssetKind;
  readonly sha256: string | null;
  readonly source: string;
  readonly approved: boolean;
}

export function markAsset(input: Partial<MarkAsset> & Pick<MarkAsset, 'kind' | 'source'>): MarkAsset {
  return { kind: input.kind, sha256: input.sha256 ?? null, svg: input.svg ?? null, source: input.source, approved: input.approved ?? false };
}

export function markDataUri(mark: MarkAsset): string | null {
  if (!mark.svg) return null;
  return `data:image/svg+xml;base64,${base64(utf8(mark.svg))}`;
}

export function markPublic(mark: MarkAsset): MarkPublic {
  return { kind: mark.kind, sha256: mark.sha256, source: mark.source, approved: mark.approved };
}

export function classifySvg(svg: string): AssetKind {
  return hasRaster(svg) ? 'RASTER_IN_SVG' : 'VECTOR';
}

export interface SvgSafetyVerdict {
  readonly passed: boolean;
  readonly detail: string;
}

export interface MarkSources {
  /** The deterministic SVG for an allowed mark id, or null (Python's `compose_mark`). */
  readonly composeMark: (markId: string) => string | null;
  /** The authorized stored bytes of an artifact, or null when absent or not readable (Python's `load_master`). */
  readonly loadMaster: (ref: string) => Uint8Array | null;
  /** `execution_fabric.verifiers.svg_safety(text)`; it parses XML, so it stays in Python and is passed in. */
  readonly svgSafety: (text: string) => SvgSafetyVerdict;
}

const SET: readonly FieldStatus[] = ['VALUE', 'PROPOSED'];

function usable(state: FieldState | undefined): state is FieldState & { readonly value: string } {
  return state !== undefined && SET.includes(state.status) && typeof state.value === 'string';
}

function fromMaster(master: FieldState & { readonly value: string }, pinned: FieldState | undefined, sources: MarkSources): MarkAsset {
  const data = sources.loadMaster(master.value);
  if (data === null) {
    return markAsset({ kind: 'MISSING', source: `master artifact ${master.value} is not readable here: identity review` });
  }
  const text = decodeReplace(data);
  const kind = classifySvg(text);
  const verdict = sources.svgSafety(text);
  const safe = verdict.passed || (kind === 'RASTER_IN_SVG' && !hasActiveContent(text));
  if (!safe) return markAsset({ kind: 'MISSING', source: `master artifact ${master.value} failed svg safety: ${verdict.detail}` });
  const digest = sha256(data);
  if (usable(pinned) && pinned.value.toLowerCase() !== digest) {
    return markAsset({ kind: 'MISSING', source: `master artifact ${master.value} no longer matches the pinned sha256 `
      + `${cpSlice(pinned.value, 0, 16)}: identity review` });
  }
  return markAsset({ kind: master.status === 'PROPOSED' ? 'PROPOSED_CONCEPT' : kind, sha256: digest, svg: text,
    approved: master.approved, source: `master artifact ${master.value}` });
}

/** The canonical master: an approved master artifact, else a deterministic composition of the mark key, else MISSING. */
export function resolveMark(states: ReadonlyMap<string, FieldState>, sources: MarkSources): MarkAsset {
  const master = states.get('visual.logo.master_artifact');
  if (usable(master)) return fromMaster(master, states.get('visual.logo.master_sha256'), sources);
  const mark = states.get('visual.logo.mark');
  if (usable(mark)) {
    const svg = sources.composeMark(mark.value);
    if (svg !== null) {
      return markAsset({ kind: mark.status === 'VALUE' ? 'VECTOR' : 'PROPOSED_CONCEPT', sha256: sha256(svg), svg,
        approved: mark.approved, source: `deterministic composition of visual.logo.mark=${mark.value}` });
    }
  }
  return markAsset({ kind: 'MISSING', source: 'no approved master: route to identity review' });
}

