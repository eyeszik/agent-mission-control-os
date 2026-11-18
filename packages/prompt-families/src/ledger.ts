/**
 * Deterministic concept signatures, duplicate detection and bounded repair
 * (twin of `agency/prompt_families/ledger.py`). The hard gate is structural, not
 * semantic: a signature is the SHA-256 of the canonical concept-level fields
 * (metaphor, composition, subject, graphic device). Two concepts are duplicates
 * when the signature matches, and duplicate-risk when three of the four concept
 * fields repeat an accepted concept.
 */
import { PY_SPACE, pyReprValue, pyRegExp, stableHash } from '@amc/guidance';
import {
  AXIS_PRIORITY,
  type ConceptLedger,
  type ConceptLedgerEntry,
  type ConceptSignature,
  type PromptFamilyInstance,
} from './models';

export const MAX_REPAIR_PASSES = 3;
export const NEAR_DUPLICATE_SHARED_FIELDS = 3;
const SPACE_RUN = pyRegExp(`${PY_SPACE}+`);

/** `" ".join(text.lower().split())`. */
export function normalizeField(text: string): string {
  return text.toLowerCase().split(SPACE_RUN).filter((part) => part !== '').join(' ');
}

export function conceptSignature(variation: ReadonlyMap<string, string>): ConceptSignature {
  const fields = {
    primary_metaphor: variation.get('concept_metaphor') ?? '',
    composition: variation.get('composition') ?? '',
    subject: variation.get('subject') ?? '',
    graphic_device: variation.get('graphic_device') ?? '',
  };
  const normalized = Object.fromEntries(Object.entries(fields).map(([key, value]) => [key, normalizeField(value)]));
  return { ...fields, signature_hash: stableHash(normalized) };
}

function signatureFields(signature: ConceptSignature): string[] {
  return [signature.primary_metaphor, signature.composition, signature.subject, signature.graphic_device].map(normalizeField);
}

/** Why `signature` repeats an accepted concept, or `null`. */
export function duplicateReason(signature: ConceptSignature, accepted: readonly ConceptSignature[]): string | null {
  for (const prior of accepted) {
    if (prior.signature_hash === signature.signature_hash) return 'exact concept signature already used';
    const mine = signatureFields(signature);
    const theirs = signatureFields(prior);
    const shared = mine.filter((item, index) => item !== '' && item === theirs[index]).length;
    if (shared >= NEAR_DUPLICATE_SHARED_FIELDS) return `${shared} of 4 concept fields repeat an accepted concept`;
  }
  return null;
}

interface Attempt {
  readonly variation: Map<string, string>;
  readonly entry: string;
}

function tryAxis(
  current: ReadonlyMap<string, string>,
  axis: string,
  options: readonly string[],
  accepted: readonly ConceptSignature[],
): Attempt | null {
  const currentValue = current.get(axis);
  const start = currentValue !== undefined && options.includes(currentValue) ? options.indexOf(currentValue) : -1;
  for (let step = 1; step < options.length; step += 1) {
    const next = options[(start + step) % options.length] as string;
    const candidate = new Map(current).set(axis, next);
    if (duplicateReason(conceptSignature(candidate), accepted) === null) {
      return { variation: candidate, entry: `${axis}: ${pyReprValue(currentValue ?? null)} -> ${pyReprValue(next)}` };
    }
  }
  return null;
}

function repairPass(
  current: ReadonlyMap<string, string>,
  axes: ReadonlyMap<string, readonly string[]>,
  accepted: readonly ConceptSignature[],
): Attempt | null {
  for (const axis of AXIS_PRIORITY) {
    const options = axes.get(axis);
    if (options === undefined || options.length < 2) continue;
    const attempt = tryAxis(current, axis, options, accepted);
    if (attempt !== null) return attempt;
  }
  return null;
}

/**
 * Change the highest-level concept variable first, bounded to three passes.
 * Cosmetic axes are only touched once every higher-level axis is exhausted.
 */
export function repairVariation(
  variation: ReadonlyMap<string, string>,
  axes: ReadonlyMap<string, readonly string[]>,
  accepted: readonly ConceptSignature[],
): { variation: Map<string, string>; log: string[] } {
  let current = new Map(variation);
  const log: string[] = [];
  for (let pass = 0; pass < MAX_REPAIR_PASSES; pass += 1) {
    if (duplicateReason(conceptSignature(current), accepted) === null) return { variation: current, log };
    const attempt = repairPass(current, axes, accepted);
    if (attempt === null) break;
    current = attempt.variation;
    log.push(attempt.entry);
  }
  return { variation: current, log };
}

/** Append instances to a new ledger value; the input ledger is not mutated. */
export function recordInstances(ledger: ConceptLedger, instances: readonly PromptFamilyInstance[]): ConceptLedger {
  const entries: ConceptLedgerEntry[] = [...ledger.entries];
  const rejected = [...ledger.rejected_patterns];
  for (const instance of instances) {
    entries.push({
      family_id: instance.family_id,
      instance_id: instance.instance_id,
      signature: instance.signature,
      status: instance.status,
      variation: new Map(instance.variation),
    });
    if (instance.status === 'REJECTED_DUPLICATE') rejected.push(instance.signature.signature_hash);
  }
  return { entries, rejected_patterns: Array.from(new Set(rejected)).sort() };
}
