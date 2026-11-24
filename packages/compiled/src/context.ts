/**
 * Twin of `agency/compiled/context.py` (T08/T09): the CompanyGenome
 * projection and ContextLens capsules. The genome stores refs and hashes,
 * keeps contradictions and unknowns, and has no write path back.
 */
import type { EpistemicStatus, PyFloat } from '@amc/kernel';
import { semanticHash, type HashValue } from './hashing';
import { compareTuples, pySlice, sortStrings, uniqueSorted } from './python';

export const GENOME_EPISTEMICS = [
  'VERIFIED_FACT', 'INFERENCE', 'ASSUMPTION', 'HYPOTHESIS', 'PROPOSAL', 'CONFLICT', 'STALE', 'UNKNOWN',
] as const;
export type GenomeEpistemic = (typeof GENOME_EPISTEMICS)[number];

/** Bridge to the kernel's evidence vocabulary; the kernel enum stays authoritative. */
export const KERNEL_EPISTEMIC_MAP: ReadonlyMap<GenomeEpistemic, EpistemicStatus> = new Map<GenomeEpistemic, EpistemicStatus>([
  ['VERIFIED_FACT', 'verified'],
  ['INFERENCE', 'inferred'],
  ['ASSUMPTION', 'assumption'],
  ['HYPOTHESIS', 'hypothesis'],
  ['PROPOSAL', 'unverified'],
  ['CONFLICT', 'conflict'],
  ['STALE', 'stale'],
  ['UNKNOWN', 'unverified'],
]);

export interface GenomeAssertion {
  readonly key: string;
  readonly domain: string;
  readonly value_or_ref: string;
  readonly source_refs: readonly string[];
  readonly epistemic_status: GenomeEpistemic;
  readonly confidence: PyFloat | null;
  readonly freshness: string | null;
  readonly sensitivity: string;
  readonly owner_ref: string | null;
  readonly decision_refs: readonly string[];
  readonly artifact_refs: readonly string[];
}

export function assertionHash(a: GenomeAssertion): string {
  return semanticHash(a as unknown as HashValue);
}

export function assertionRef(a: GenomeAssertion): string {
  return `${a.key}@${pySlice(assertionHash(a), 0, 16)}`;
}

export interface CompanyGenome {
  readonly assertions: readonly GenomeAssertion[];
  readonly conflicts: readonly string[];
  readonly unknowns: readonly string[];
  readonly genome_hash: string;
}

const VALUED: ReadonlySet<GenomeEpistemic> = new Set(['VERIFIED_FACT', 'INFERENCE', 'ASSUMPTION']);

function conflictKeys(ordered: readonly GenomeAssertion[]): string[] {
  const values = new Map<string, Set<string>>();
  for (const a of ordered) {
    if (!VALUED.has(a.epistemic_status)) continue;
    values.set(a.key, (values.get(a.key) ?? new Set<string>()).add(a.value_or_ref));
  }
  const conflicts = [...values].filter(([, vals]) => vals.size > 1).map(([key]) => key);
  conflicts.push(...ordered.filter((a) => a.epistemic_status === 'CONFLICT').map((a) => a.key));
  return uniqueSorted(conflicts);
}

/** `project_genome`: deterministic; unsourced "facts" are downgraded to UNKNOWN; conflicts are kept. */
export function projectGenome(assertions: Iterable<GenomeAssertion>): CompanyGenome {
  const unique = new Map<string, GenomeAssertion>();
  for (const raw of assertions) {
    const a: GenomeAssertion = raw.epistemic_status === 'VERIFIED_FACT' && !raw.source_refs.length
      ? { ...raw, epistemic_status: 'UNKNOWN' } : raw;
    unique.set(assertionHash(a), a);
  }
  const ordered = [...unique].sort(([ha, a], [hb, b]) => compareTuples([a.key, ha], [b.key, hb])).map(([, a]) => a);
  const conflicts = conflictKeys(ordered);
  const unknowns = uniqueSorted(ordered.filter((a) => a.epistemic_status === 'UNKNOWN').map((a) => a.key));
  const body = { assertions: ordered.map(assertionHash), conflicts, unknowns };
  return { assertions: ordered, conflicts, unknowns, genome_hash: semanticHash(body) };
}

export function genomeByKey(genome: CompanyGenome, key: string): GenomeAssertion[] {
  return genome.assertions.filter((a) => a.key === key);
}

export interface ContextCapsule {
  readonly objective: string;
  readonly acceptance_criteria: readonly string[];
  readonly relevant_genome_refs: readonly string[];
  readonly approved_decision_refs: readonly string[];
  readonly artifact_refs: readonly string[];
  readonly dependency_refs: readonly string[];
  readonly hard_constraints: readonly string[];
  readonly authority_refs: readonly string[];
  readonly tool_permissions: readonly string[];
  readonly open_questions: readonly string[];
  readonly freshness_deadlines: readonly string[];
  readonly dependency_hashes: readonly (readonly [string, string])[];
  readonly capsule_hash: string;
}

export interface CapsuleInputs {
  readonly objective: string;
  readonly acceptance_criteria: Iterable<string>;
  readonly domains: Iterable<string>;
  readonly genome_keys?: Iterable<string>;
  readonly approved_decision_refs?: Iterable<string>;
  readonly artifact_refs?: Iterable<string>;
  readonly dependency_hashes?: ReadonlyMap<string, string>;
  readonly hard_constraints?: Iterable<string>;
  readonly authority_refs?: Iterable<string>;
  readonly tool_permissions?: Iterable<string>;
}

const OPEN_STATUSES: ReadonlySet<GenomeEpistemic> = new Set(['UNKNOWN', 'STALE', 'HYPOTHESIS']);

function openQuestions(genome: CompanyGenome, selected: readonly GenomeAssertion[]): string[] {
  const conflicts = new Set(genome.conflicts);
  return uniqueSorted([
    ...selected.filter((a) => conflicts.has(a.key)).map((a) => `CONFLICT:${a.key}`),
    ...selected.filter((a) => OPEN_STATUSES.has(a.epistemic_status)).map((a) => `${a.epistemic_status}:${a.key}`),
  ]);
}

/** `project_capsule`: minimum sufficient context, only assertions in the node's domains or named keys. */
export function projectCapsule(genome: CompanyGenome, inputs: CapsuleInputs): ContextCapsule {
  const domains = new Set(inputs.domains);
  const keys = new Set(inputs.genome_keys ?? []);
  const selected = genome.assertions.filter((a) => domains.has(a.domain) || keys.has(a.key));
  const deps = [...(inputs.dependency_hashes ?? new Map<string, string>())]
    .map(([ref, digest]): [string, string] => [ref, digest]).sort(compareTuples);
  const body = {
    objective: inputs.objective,
    acceptance_criteria: sortStrings(inputs.acceptance_criteria),
    relevant_genome_refs: sortStrings(selected.map(assertionRef)),
    approved_decision_refs: sortStrings(inputs.approved_decision_refs ?? []),
    artifact_refs: sortStrings(inputs.artifact_refs ?? []),
    dependency_refs: deps.map(([ref]) => ref),
    hard_constraints: sortStrings(inputs.hard_constraints ?? []),
    authority_refs: sortStrings(inputs.authority_refs ?? []),
    tool_permissions: sortStrings(inputs.tool_permissions ?? []),
    open_questions: openQuestions(genome, selected),
    freshness_deadlines: uniqueSorted(selected.filter((a) => a.freshness).map((a) => `${a.key}:${a.freshness ?? ''}`)),
    dependency_hashes: deps,
  };
  return { ...body, capsule_hash: semanticHash(body) };
}

export type CapsuleFreshness = 'FRESH' | 'INVALIDATED_CONTEXT';

export function capsuleFreshness(capsule: ContextCapsule, currentHashes: ReadonlyMap<string, string>): CapsuleFreshness {
  for (const [ref, digest] of capsule.dependency_hashes) {
    if (currentHashes.get(ref) !== digest) return 'INVALIDATED_CONTEXT';
  }
  return 'FRESH';
}

/** Genome refs every capsule needs: loaded once rather than per specialist. */
export function hoistSharedRefs(capsules: Iterable<ContextCapsule>): string[] {
  const sets = [...capsules].map((c) => new Set(c.relevant_genome_refs));
  const first = sets[0];
  if (first === undefined) return [];
  return sortStrings([...first].filter((ref) => sets.every((s) => s.has(ref))));
}
