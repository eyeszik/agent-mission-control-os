/**
 * VNEXUS ACE v9 — pure, provider-neutral brand genome foundation.
 * No provider execution, payment, storage, or approval side effects.
 * Server-side authorization must precede persistence and access.
 */
export type GenomeAuthority = 'APPROVED' | 'PROVISIONAL' | 'EXPERIMENTAL';
export type GenomeScope = 'brand' | 'project' | 'page' | 'component' | 'asset';
export type GenomeChromosome = 'strategy' | 'visual' | 'verbal' | 'experience' | 'production';
export type GenomeValues = Readonly<Record<string, string | number | boolean | null>>;
export interface GenomeLayer {
  readonly scope: GenomeScope;
  readonly scopeId: string;
  readonly authority: GenomeAuthority;
  readonly values: GenomeValues;
  readonly immutableKeys?: readonly string[];
}
export interface GenomeConflict {
  readonly key: string;
  readonly reason: 'IMMUTABLE_OVERRIDE' | 'UNAPPROVED_OVERRIDE' | 'SCOPE_ORDER';
  readonly scopeId: string;
}
export interface GenomeResolution {
  readonly values: GenomeValues;
  readonly conflicts: readonly GenomeConflict[];
  readonly appliedScopes: readonly string[];
}
const ORDER: readonly GenomeScope[] = ['brand', 'project', 'page', 'component', 'asset'];
const OWN = Object.prototype.hasOwnProperty;
export function resolveGenome(layers: readonly GenomeLayer[]): GenomeResolution {
  const values: Record<string, string | number | boolean | null> = Object.create(null);
  const locked = new Set<string>();
  const conflicts: GenomeConflict[] = [];
  const appliedScopes: string[] = [];
  let lastOrder = -1;
  for (const layer of layers) {
    const order = ORDER.indexOf(layer.scope);
    if (order < lastOrder) {
      conflicts.push({ key: '*', reason: 'SCOPE_ORDER', scopeId: layer.scopeId });
      continue;
    }
    lastOrder = order;
    if (layer.authority !== 'APPROVED') {
      for (const key of Object.keys(layer.values)) {
        conflicts.push({ key, reason: 'UNAPPROVED_OVERRIDE', scopeId: layer.scopeId });
      }
      continue;
    }
    appliedScopes.push(layer.scopeId);
    for (const [key, value] of Object.entries(layer.values)) {
      if (locked.has(key) && OWN.call(values, key) && values[key] !== value) {
        conflicts.push({ key, reason: 'IMMUTABLE_OVERRIDE', scopeId: layer.scopeId });
        continue;
      }
      values[key] = value;
    }
    for (const key of layer.immutableKeys ?? []) locked.add(key);
  }
  return { values, conflicts, appliedScopes };
}
export interface CreativeBranch {
  readonly id: string;
  readonly parentId: string | null;
  readonly genomeHash: string;
  readonly changes: GenomeValues;
  readonly reviewState: 'DRAFT' | 'REVIEW' | 'APPROVED' | 'REJECTED';
}
export interface BranchComparison {
  readonly changedKeys: readonly string[];
  readonly addedKeys: readonly string[];
  readonly removedKeys: readonly string[];
}
export function compareBranches(a: CreativeBranch, b: CreativeBranch): BranchComparison {
  const keys = new Set([...Object.keys(a.changes), ...Object.keys(b.changes)]);
  const changedKeys: string[] = [], addedKeys: string[] = [], removedKeys: string[] = [];
  for (const key of [...keys].sort()) {
    const inA = OWN.call(a.changes, key), inB = OWN.call(b.changes, key);
    if (!inA) addedKeys.push(key);
    else if (!inB) removedKeys.push(key);
    else if (a.changes[key] !== b.changes[key]) changedKeys.push(key);
  }
  return { changedKeys, addedKeys, removedKeys };
}
export interface DependencyNode {
  readonly id: string;
  readonly dependsOn: readonly string[];
}
/** Returns only downstream nodes affected by a changed dependency. */
export function impactedNodes(nodes: readonly DependencyNode[], changedIds: readonly string[]): string[] {
  const affected = new Set(changedIds);
  let grew = true;
  while (grew) {
    grew = false;
    for (const node of nodes) {
      if (!affected.has(node.id) && node.dependsOn.some((dep) => affected.has(dep))) {
        affected.add(node.id);
        grew = true;
      }
    }
  }
  return nodes.map((node) => node.id).filter((id) => affected.has(id) && !changedIds.includes(id));
}
export type ProductionEvidence = 'SIMULATED' | 'SUBMITTED' | 'ARTIFACT_RECEIVED' | 'VALIDATED';
export function canClaimGenerated(evidence: ProductionEvidence, artifactHash?: string): boolean {
  return evidence === 'VALIDATED' && typeof artifactHash === 'string' && /^[a-f0-9]{64}$/i.test(artifactHash);
}
