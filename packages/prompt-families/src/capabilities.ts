/**
 * External capability discovery record for the prompt-family integration (twin
 * of `agency/prompt_families/capabilities.py`). This is provenance about what
 * the integrating session could and could not discover, not runtime truth.
 * Nothing here wires, calls or authorizes an external tool. An unknown name
 * resolves to `NOT_AVAILABLE`; no endpoint, schema or command is inferred.
 */
import { PY_SPACE, pyRegExp } from '@amc/guidance';

export const DISCOVERED_ON = '2026-09-28';

export type CapabilityStatus = 'EVIDENCE_INTERFACE' | 'CONTRACT_ONLY' | 'PATTERN_ONLY' | 'NOT_AVAILABLE';

export interface ExternalCapability {
  readonly name: string;
  readonly status: CapabilityStatus;
  readonly repository_surface: string;
  readonly note: string;
}

const ROWS: readonly ExternalCapability[] = [
  {
    name: 'SEARCH',
    status: 'EVIDENCE_INTERFACE',
    repository_surface: 'prompt_compiler.ResearchRequest -> SourceEvidence(query, freshness_class)',
    note: 'Search is evidence acquisition; results enter as SourceEvidence and never mutate guidance or BrandCore.',
  },
  {
    name: 'WOLFRAM',
    status: 'CONTRACT_ONLY',
    repository_surface: 'prompt_compiler.ComputationEvidence',
    note: 'No computation tool was discoverable in the integrating session; only the provenance contract exists.',
  },
  {
    name: 'ADS_MANAGER',
    status: 'PATTERN_ONLY',
    repository_surface: 'prompt_families.PaidMediaCreativeSpec + PAID_MEDIA_MUTATION_PRECONDITIONS',
    note: 'Specification only; integrations/paid_media.py remains the fail-closed spend boundary.',
  },
  {
    name: 'PRINTIFY',
    status: 'PATTERN_ONLY',
    repository_surface: 'ProductionTarget(medium=MERCH) + pg.production_design_system.v1 pds.merch_artwork_vs_product',
    note: 'Artwork is compiled separately from product mockups; no product creation or ordering path exists.',
  },
  {
    name: 'OGENIC GOD TOOLKIT',
    status: 'NOT_AVAILABLE',
    repository_surface: 'none',
    note: 'No tool, plugin, server or repository by this name was exposed in the integrating session; no capability is assumed.',
  },
];

export const EXTERNAL_CAPABILITIES: ReadonlyMap<string, ExternalCapability> = new Map(ROWS.map((row) => [row.name, row]));
const SPACE_RUN = pyRegExp(`${PY_SPACE}+`);

/** `" ".join(name.upper().split())`. */
function capabilityKey(name: string): string {
  return name.toUpperCase().split(SPACE_RUN).filter((part) => part !== '').join(' ');
}

export function externalCapabilityStatus(name: string): ExternalCapability {
  const key = capabilityKey(name);
  return (
    EXTERNAL_CAPABILITIES.get(key) ?? {
      name: key,
      status: 'NOT_AVAILABLE',
      repository_surface: 'none',
      note: 'Unknown capability name; nothing is inferred from it.',
    }
  );
}
