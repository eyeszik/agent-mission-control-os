/**
 * Twin of `agency/compiled/change_control.py` (T18/T19): causal invalidation
 * (BlastRadiusCertificate), ArtifactDNA and DeltaApproval scopes. Planning
 * projections only: nothing here writes to the persistence stores, and an
 * approval stays valid only while the exact protected state is unchanged.
 *
 * `scope_from_approval_record` (an adapter over a `persistence/approvals.py`
 * row) stays in Python with the persistence layer it reads.
 */
import type { CausalWorkGraph } from './backchain';
import type { ContextCapsule } from './context';
import { closureHash, semanticHash, type HashValue } from './hashing';
import { compareTuples, sortStrings, uniqueSorted } from './python';

/** Hash of everything the subjects causally rest on (content hash where known, else structural hash). */
export function dependencyClosureHash(
  graph: CausalWorkGraph, subjectRefs: Iterable<string>, artifactHashes: ReadonlyMap<string, string>,
): string {
  const closure = new Set<string>();
  for (const ref of subjectRefs) for (const anc of graph.ancestors(ref)) closure.add(anc);
  const pairs = sortStrings(closure).filter((ref) => graph.nodes.has(ref))
    .map((ref): [string, string] => [ref, artifactHashes.get(ref) ?? graph.node(ref).semantic_hash]);
  return closureHash(pairs);
}

export interface ApprovalScope {
  readonly approval_id: string;
  readonly subject_refs: readonly string[];
  readonly subject_hashes: readonly (readonly [string, string])[];
  readonly dependency_closure_hash: string;
  readonly preview_hash: string | null;
  readonly policy_version: string;
  readonly reviewer_class: string;
  readonly authenticated_reviewer_ref: string | null;
  readonly decision: string | null;
  readonly timestamp: string | null;
}

export function scopeHash(scope: ApprovalScope): string {
  return semanticHash(scope as unknown as HashValue, ['timestamp']);
}

export interface BuildScopeInputs {
  readonly approval_id: string;
  readonly subjects: ReadonlyMap<string, string>;
  readonly artifact_hashes: ReadonlyMap<string, string>;
  readonly policy_version: string;
  readonly reviewer_ref: string | null;
  readonly decision: string | null;
  readonly reviewer_class?: string;
  readonly preview_hash?: string | null;
  readonly timestamp?: string | null;
}

export function buildScope(graph: CausalWorkGraph, inputs: BuildScopeInputs): ApprovalScope {
  const pairs = [...inputs.subjects].map(([ref, digest]): [string, string] => [ref, digest]).sort(compareTuples);
  return {
    approval_id: inputs.approval_id,
    subject_refs: sortStrings(inputs.subjects.keys()),
    subject_hashes: pairs,
    dependency_closure_hash: dependencyClosureHash(graph, inputs.subjects.keys(), inputs.artifact_hashes),
    preview_hash: inputs.preview_hash ?? null,
    policy_version: inputs.policy_version,
    reviewer_class: inputs.reviewer_class ?? 'authenticated_human',
    authenticated_reviewer_ref: inputs.reviewer_ref,
    decision: inputs.decision,
    timestamp: inputs.timestamp ?? null,
  };
}

export const APPROVAL_VALIDITIES = [
  'VALID', 'STALE_APPROVAL', 'FULL_GATE_REPLAY', 'NOT_APPROVED', 'UNAUTHENTICATED_REVIEWER',
] as const;
export type ApprovalValidity = (typeof APPROVAL_VALIDITIES)[number];

export interface ScopeCheck {
  readonly current_subject_hashes: ReadonlyMap<string, string>;
  readonly current_closure_hash: string;
  readonly current_policy_version: string;
  readonly preservation_permitted?: boolean;
  readonly high_risk_change?: boolean;
}

/** `evaluate_scope`: valid only if the exact protected state is unchanged. */
export function evaluateScope(scope: ApprovalScope, check: ScopeCheck): ApprovalValidity {
  if (!scope.authenticated_reviewer_ref) return 'UNAUTHENTICATED_REVIEWER';
  if (scope.decision !== 'approve') return 'NOT_APPROVED';
  const unchanged = scope.subject_hashes.every(([ref, digest]) => check.current_subject_hashes.get(ref) === digest)
    && check.current_closure_hash === scope.dependency_closure_hash
    && check.current_policy_version === scope.policy_version;
  if (unchanged && (check.preservation_permitted ?? true)) return 'VALID';
  return check.high_risk_change ? 'FULL_GATE_REPLAY' : 'STALE_APPROVAL';
}

export interface BlastRadiusCertificate {
  readonly changed_refs: readonly string[];
  readonly old_hashes: readonly string[];
  readonly new_hashes: readonly string[];
  readonly causal_descendants: readonly string[];
  readonly preserved_refs: readonly string[];
  readonly stale_context_capsules: readonly string[];
  readonly stale_validation_refs: readonly string[];
  readonly stale_approvals: readonly string[];
  readonly preserved_approvals: readonly string[];
  readonly mandatory_full_replay_reasons: readonly string[];
  readonly certificate_hash: string;
}

const HIGH_RISK_PREFIXES = ['external:', 'decision:legal_security_policy', 'decision:release_go_no_go'];
const REGULATED = new Set(['PROFILE:SECURITY', 'PROFILE:PRIVACY', 'PROFILE:TRADEMARK']);

function replayReasons(graph: CausalWorkGraph, affected: ReadonlySet<string>): string[] {
  const replay: string[] = [];
  for (const ref of affected) {
    if (HIGH_RISK_PREFIXES.some((p) => ref.startsWith(p))) replay.push(`HIGH_RISK_NODE_AFFECTED:${ref}`);
    if (graph.node(ref).validation_obligations.some((o) => REGULATED.has(o))) replay.push(`REGULATED_VALIDATION_AFFECTED:${ref}`);
  }
  return uniqueSorted(replay);
}

function splitApprovals(graph: CausalWorkGraph, approvals: Iterable<ApprovalScope>, affected: ReadonlySet<string>) {
  const stale: string[] = [];
  const preserved: string[] = [];
  for (const scope of approvals) {
    const closure = new Set(scope.subject_refs);
    for (const ref of scope.subject_refs) for (const anc of graph.ancestors(ref)) closure.add(anc);
    ([...closure].some((r) => affected.has(r)) ? stale : preserved).push(scope.approval_id);
  }
  return { stale: sortStrings(stale), preserved: sortStrings(preserved) };
}

/** `compute_blast_radius`: new version → delta → descendant closure → invalidate affected → preserve the rest. */
export function computeBlastRadius(
  graph: CausalWorkGraph,
  changes: ReadonlyMap<string, readonly [string, string]>,
  approvals: Iterable<ApprovalScope> = [],
  capsules: ReadonlyMap<string, ContextCapsule> = new Map(),
): BlastRadiusCertificate {
  const changed = sortStrings([...changes].filter(([ref, [o, n]]) => o !== n && graph.nodes.has(ref)).map(([ref]) => ref));
  const changedSet = new Set(changed);
  const descendants = [...graph.descendants(changed)].filter((r) => !changedSet.has(r));
  const affected = new Set([...changed, ...descendants]);
  const staleCapsules = sortStrings([...capsules].filter(([id, c]) => affected.has(id)
    || c.dependency_hashes.some(([ref]) => changedSet.has(ref))).map(([id]) => id));
  const { stale, preserved } = splitApprovals(graph, approvals, affected);
  const body = {
    changed_refs: changed,
    old_hashes: changed.map((r) => changes.get(r)?.[0] ?? ''),
    new_hashes: changed.map((r) => changes.get(r)?.[1] ?? ''),
    causal_descendants: sortStrings(descendants),
    preserved_refs: sortStrings([...graph.nodes.keys()].filter((r) => !affected.has(r))),
    stale_context_capsules: staleCapsules,
    stale_validation_refs: sortStrings([...affected].filter((n) => graph.node(n).type === 'VALIDATION_OBLIGATION')),
    stale_approvals: stale,
    preserved_approvals: preserved,
    mandatory_full_replay_reasons: replayReasons(graph, affected),
  };
  return { ...body, certificate_hash: semanticHash(body) };
}

/** `artifact_dna`: trace an artifact back to its evidence, decisions, inputs and approvals. */
export function artifactDna(
  graph: CausalWorkGraph, nodeId: string, evidenceRefs: ReadonlyMap<string, Iterable<string>> = new Map(),
  approvals: Iterable<ApprovalScope> = [],
): Record<string, string[]> {
  const ancestry = new Set([...graph.ancestors(nodeId), nodeId]);
  const ofType = (t: string): string[] => sortStrings([...ancestry].filter((a) => graph.node(a).type === t));
  const evidence = new Set<string>();
  for (const anc of ancestry) {
    const artifact = graph.node(anc).artifact_type;
    if (artifact) for (const ref of evidenceRefs.get(artifact) ?? []) evidence.add(ref);
  }
  return {
    artifact: [nodeId],
    evidence_requirements: ofType('EVIDENCE_REQUIREMENT'),
    evidence_refs: sortStrings(evidence),
    decisions: ofType('MATERIAL_DECISION'),
    existing_inputs: ofType('EXISTING_REF'),
    producing_work: ofType('EXECUTABLE_WORK'),
    approvals: sortStrings([...approvals].filter((s) => s.subject_refs.some((r) => ancestry.has(r))).map((s) => s.approval_id)),
  };
}
