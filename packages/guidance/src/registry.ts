/**
 * Strict registry for repository-owned guidance packs (twin of
 * `agency/guidance/registry.py`). Pack files use the JSON-compatible subset of
 * YAML 1.2: duplicate keys are rejected, there are no custom tags or aliases.
 *
 * Python reads `packs/*.yaml` from disk; here the caller passes the already
 * loaded files (`{name, text}`), so this module does no I/O.
 */
import { pyRepr } from '@amc/kernel';
import { PyKeyError, PyValueError } from './errors';
import { GUIDANCE_PACK, packDump, type GuidancePack } from './guidance-models';
import { loads } from './pyjson';
import { compareCodePoints, sortedStrings } from './pytext';
import { orderedMap, stableHash, type PyValue } from './pyvalue';
import { parse } from './schema';

export const REGISTRY_VERSION = 'amc-guidance-registry/v1';

export interface PackFile {
  readonly name: string;
  readonly text: string;
}

/** `stable_guidance_hash`. */
export const stableGuidanceHash = stableHash;

export function noDuplicatePairs(pairs: ReadonlyArray<readonly [string, PyValue]>): PyValue {
  const result = new Map<string, PyValue>();
  for (const [key, value] of pairs) {
    if (result.has(key)) throw new PyValueError(`duplicate guidance key: ${key}`);
    result.set(key, value);
  }
  return result;
}

function listRepr(values: readonly string[]): string {
  return `[${values.map((value) => pyRepr(value)).join(', ')}]`;
}

export class GuidanceRegistry {
  private readonly byId: ReadonlyMap<string, GuidancePack>;

  constructor(packs: readonly GuidancePack[]) {
    const byId = new Map<string, GuidancePack>();
    for (const pack of packs) {
      if (byId.has(pack.id)) throw new PyValueError(`duplicate guidance pack id: ${pack.id}`);
      byId.set(pack.id, pack);
    }
    for (const pack of packs) GuidanceRegistry.checkLinks(pack, byId);
    this.byId = new Map(sortedStrings(byId.keys()).map((id) => [id, byId.get(id) as GuidancePack]));
  }

  private static checkLinks(pack: GuidancePack, known: ReadonlyMap<string, GuidancePack>): void {
    const missing = sortedStrings(new Set(pack.dependencies.filter((id) => !known.has(id))));
    if (missing.length > 0) throw new PyValueError(`${pack.id} has unresolved dependencies: ${listRepr(missing)}`);
    const conflicts = new Set(pack.conflicts_with);
    const overlap = sortedStrings(new Set(pack.dependencies.filter((id) => conflicts.has(id))));
    if (overlap.length > 0) throw new PyValueError(`${pack.id} both depends on and conflicts with: ${listRepr(overlap)}`);
  }

  /** `GuidanceRegistry.from_directory`: `*.yaml` files in code-point name order, dotfiles included. */
  static fromFiles(files: readonly PackFile[], directory = '<root>'): GuidanceRegistry {
    const named = files.filter((file) => file.name.endsWith('.yaml')).sort((a, b) => compareCodePoints(a.name, b.name));
    const packs = named.map(GuidanceRegistry.loadPack);
    if (packs.length === 0) throw new PyValueError(`no guidance packs found in ${directory}`);
    return new GuidanceRegistry(packs);
  }

  private static loadPack(file: PackFile): GuidancePack {
    // Python reads the file in text mode, which translates \r\n and \r to \n.
    const payload = loads(file.text.replace(/\r\n?/g, '\n'), noDuplicatePairs);
    const raw = parse(GUIDANCE_PACK, payload);
    const computed = stableGuidanceHash(packDump(raw, false));
    if (raw.content_hash !== '' && raw.content_hash !== computed) {
      throw new PyValueError(`${file.name} content_hash mismatch: expected ${raw.content_hash}, got ${computed}`);
    }
    return { ...raw, content_hash: computed };
  }

  get packs(): GuidancePack[] {
    return Array.from(this.byId.values());
  }

  get registryHash(): string {
    return stableGuidanceHash(
      orderedMap([
        ['version', REGISTRY_VERSION],
        ['packs', this.packs.map((pack) => orderedMap([['id', pack.id], ['content_hash', pack.content_hash]]))],
      ]),
    );
  }

  get(packId: string): GuidancePack {
    const pack = this.byId.get(packId);
    if (pack === undefined) throw new PyKeyError(pyRepr(packId));
    return pack;
  }
}
