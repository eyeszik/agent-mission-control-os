/**
 * Hashing (Python `stable_hash`): SHA-256 of `json.dumps(value, sort_keys=True,
 * separators=(",", ":"), ensure_ascii=True)`. The encoder is `@amc/design-tokens`'
 * `canonicalJson`, which keeps Python's int/float distinction through
 * `CanonicalFloat` (re-exported by design-tokens so both share one class instance), so an integral float (a score of `1.0`) hashes as a float.
 */
import { CanonicalFloat, canonicalJson } from '@amc/design-tokens';
import { sha256Hex } from '@amc/kernel';
import type { DesignGenome, UIUXDesignIR } from './types';

export function stableHash(value: unknown): string {
  return sha256Hex(new TextEncoder().encode(canonicalJson(value)));
}

/** `stable_hash(genome.model_dump(exclude={"genome_hash"}))`. */
export function genomeHash(genome: DesignGenome): string {
  const { genome_hash: _omitted, ...rest } = genome;
  return stableHash(rest);
}

const float = (value: number): CanonicalFloat => new CanonicalFloat(value);

/** The IR as Python dumps it: every float-typed field wrapped so integral floats stay floats. */
export function hashView(ir: UIUXDesignIR): Record<string, unknown> {
  const { spec_hash: _omitted, ...rest } = ir;
  return {
    ...rest,
    territories: ir.territories.map((t) => ({ ...t, score: float(t.score) })),
    tokens: {
      ...ir.tokens,
      contrast: ir.tokens.contrast.map((c) => ({
        ...c,
        wcag_ratio: float(c.wcag_ratio),
        apca_lc_advisory: float(c.apca_lc_advisory),
      })),
    },
    confidence: { ...ir.confidence, value: float(ir.confidence.value) },
  };
}

/** `stable_hash(ir.model_dump(mode="json", exclude={"spec_hash"}))`. */
export function specHash(ir: UIUXDesignIR): string {
  return stableHash(hashView(ir));
}
