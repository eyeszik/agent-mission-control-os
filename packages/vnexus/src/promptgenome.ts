/**
 * The pure helpers of `vnexus/prompt_genome.py`: constraint rendering, provider-family
 * formatting, source hashing and the original-prompt inventory.
 *
 * The 14 original VNEXUS prompts are absent from the repository and are never invented:
 * `inventory` reports how many were really imported and never fills the gap. The compiler
 * projection (`brand_core_from`, `compile_genome_prompt`, `compare`) needs BrandCore and
 * the prompt compiler and stays in Python.
 */
import { sha256Hex } from '@amc/kernel';
import { PyTypeError, PyValueError } from './errors';
import { canonicalHashSync, isPlainRecord, pyRepr, pyStr, pyTruthy, sortedUnique, type PyData } from './python';

export const PROMPT_GENOME_SCHEMA = 'amc-vnexus-prompt-genome/v1';
export const EXPECTED_ORIGINAL_SOURCES = 14; // referenced by the project brief; none are present in the repository

type Rec = { readonly [key: string]: PyData };

function rendered(c: Rec): string | null {
  const params = (c['params'] ?? {}) as Rec;
  if (c['kind'] === 'IMMUTABLE') return `Do not alter ${pyStr(c['key'])} (approved and locked)`;
  if (c['kind'] === 'ALLOWED_VALUES') return `${pyStr(c['key'])} must be one of ${pyRepr(params['values'])}`;
  if (c['kind'] === 'MIN_CONTRAST') return `Keep ${pyStr(c['key'])} against ${pyStr(params['against'])} at or above ${pyStr(params['ratio'])}:1`;
  return null;
}

/** `inherited_constraints`: brand constraints as plain-language negative constraints. */
export function inheritedConstraints(resolutionConstraints: readonly Rec[]): string[] {
  return sortedUnique(resolutionConstraints.map(rendered).filter((x): x is string => x !== null));
}

const PARAM_KEYS = ['width', 'height', 'aspect_ratio', 'duration_seconds', 'fps'] as const;

function typeName(value: PyData): string {
  if (value === null) return 'NoneType';
  if (typeof value === 'string') return 'str';
  if (typeof value === 'boolean') return 'bool';
  if (typeof value === 'number') return Number.isInteger(value) ? 'int' : 'float';
  return Array.isArray(value) ? 'list' : isPlainRecord(value) ? 'dict' : 'float';
}

function joinStrings(items: readonly PyData[]): string {
  items.forEach((x, i) => {
    if (typeof x !== 'string') throw new PyTypeError(`sequence item ${i}: expected str instance, ${typeName(x)} found`);
  });
  return items.join('; ');
}

function adaptBody(master: PyData, negatives: readonly PyData[], params: Record<string, PyData>, target: string): Record<string, PyData> {
  if (target === 'generic_text_to_image') return { prompt: master, negative_prompt: joinStrings(negatives), parameters: params };
  if (target === 'generic_text_to_video') {
    return { prompt: master, negative_prompt: joinStrings(negatives), parameters: params, note: "camera and timing come from the package's storyboard stages" };
  }
  if (target === 'structured_json') return { instruction: master, constraints: [...negatives], output: params };
  throw new PyValueError(`unknown adaptation target ${target}`);
}

/** `adapt`: provider-family rendering of a compiled package. Formatting only; no provider is called. */
export function adapt(pkg: Rec, target: string): Record<string, PyData> {
  const master = pkg['generic_master_prompt'] ?? '';
  const spec = pkg['asset_spec'] ?? {};
  const specRec = isPlainRecord(spec) ? spec : null;
  const production = specRec ? (specRec['production'] ?? {}) : {};
  const negatives = specRec ? ((specRec['negative_constraints'] || []) as readonly PyData[]) : [];
  const params: Record<string, PyData> = {};
  for (const k of PARAM_KEYS) {
    const v = isPlainRecord(production) ? production[k] : undefined;
    if (v !== undefined && pyTruthy(v)) params[k] = v;
  }
  const body = adaptBody(master, negatives, params, target);
  return { target, body, adapted_hash: canonicalHashSync(body), provider_called: false };
}

const LONE_SURROGATE = /[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/;

/** `source_hash`: SHA-256 of the exact UTF-8 text. */
export function sourceHash(text: string): string {
  if (LONE_SURROGATE.test(text)) throw new PyValueError('surrogates not allowed');
  return sha256Hex(new TextEncoder().encode(text));
}

/** `inventory`: how many of the 14 originals were actually imported; the gap is never reconstructed. */
export function inventory(imported: readonly Rec[]): Record<string, PyData> {
  const originals = imported.filter((r) => r['source_kind'] === 'ORIGINAL_IMPORT');
  const ids = sortedUnique(originals.map((r) => r['prompt_id'] as string));
  const missing = Math.max(0, EXPECTED_ORIGINAL_SOURCES - ids.length);
  return {
    expected_originals: EXPECTED_ORIGINAL_SOURCES, imported_originals: ids.length, imported_ids: ids, missing,
    status: missing === 0 ? 'COMPLETE' : ids.length > 0 ? 'PARTIAL_IMPORT' : 'SOURCE_REQUIRED',
    note: 'missing originals are never reconstructed; import the exact source text to fill a slot',
  };
}
