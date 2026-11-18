/**
 * Twin of `agency/compiled/work_orders.py` (T14): Proof-Carrying Work Orders.
 * A PCWO wraps the canonical work-order compiler output (see `roleos.ts`); it
 * does not re-implement role resolution, stable ids or the consequential-work
 * blockers. Without a valid PCWO a node is not execution-ready.
 */
import { CompiledIndexError } from './errors';
import { semanticHash, type HashValue } from './hashing';
import { afterFirst, sortStrings, uniqueSorted } from './python';
import { N3_SPECIALISTS, type SpecialistBinding } from './authority';
import type { BackchainNode } from './backchain';
import { compileWorkOrder, type RoleOSRegistry } from './roleos';
import { WorkOrderError } from './errors';

export const IDEMPOTENCY_CLASS: Readonly<Record<string, string>> = {
  PURE: 'RETRY_SAFE', DRAFT: 'RETRY_SAFE_VERSIONED', REVERSIBLE_WRITE: 'COMPENSATABLE', IRREVERSIBLE_WRITE: 'NON_RETRYABLE',
};

export interface RetryPolicy {
  readonly max_attempts: number;
  readonly on_unknown_result?: string;
  readonly on_partial?: string;
  readonly on_repeat_same_cause: string;
}

/** Retry ≤3; never blind-retry non-retryable work; unknown results reconcile. */
export function retryPolicyFor(sideEffectClass: string): RetryPolicy {
  if (sideEffectClass === 'IRREVERSIBLE_WRITE') {
    return { max_attempts: 1, on_unknown_result: 'RECONCILE', on_repeat_same_cause: 'HUMAN_REVIEW_REQUIRED' };
  }
  if (sideEffectClass === 'REVERSIBLE_WRITE') {
    return {
      max_attempts: 3, on_unknown_result: 'RECONCILE', on_partial: 'COMPENSATE', on_repeat_same_cause: 'HUMAN_REVIEW_REQUIRED',
    };
  }
  return { max_attempts: 3, on_repeat_same_cause: 'HUMAN_REVIEW_REQUIRED' };
}

const MEDIUM_RISK = new Set(['positioning_statement', 'brand_platform', 'creative_concept', 'release_record', 'media_plan']);

export function riskLevelFor(node: BackchainNode): string {
  if (node.side_effect_class === 'REVERSIBLE_WRITE' || node.side_effect_class === 'IRREVERSIBLE_WRITE') return 'high';
  return node.artifact_type !== null && MEDIUM_RISK.has(node.artifact_type) ? 'medium' : 'low';
}

export interface PCWO {
  readonly work_order_id: string;
  readonly logical_operation_id: string;
  readonly plan_hash: string | null;
  readonly causal_node_id: string;
  readonly objective: string;
  readonly deliverable_refs: readonly string[];
  readonly acceptance_criteria: readonly string[];
  readonly accountable_specialist: string | null;
  readonly contributor_specialists: readonly string[];
  readonly runtime_authority_binding: string;
  readonly capability_requirements: readonly string[];
  readonly context_capsule_ref: string | null;
  readonly input_refs: readonly string[];
  readonly dependency_refs: readonly string[];
  readonly evidence_requirements: readonly string[];
  readonly decision_refs: readonly string[];
  readonly artifact_contracts: readonly string[];
  readonly tool_plan: readonly string[];
  readonly validation_obligations: readonly string[];
  readonly side_effect_class: string;
  readonly idempotency_class: string;
  readonly mutation_targets: readonly string[];
  readonly resource_locks: readonly string[];
  readonly approval_scope: string | null;
  readonly retry_policy: RetryPolicy;
  readonly provenance_refs: readonly string[];
  readonly source_skill_hashes: readonly string[];
  readonly output_schema: string;
  readonly completion_checks: readonly string[];
  readonly execution_ready: boolean;
  readonly blockers: readonly string[];
  readonly work_order_hash: string;
}

export interface PcwoInput {
  readonly project_id: string;
  readonly mission_id: string;
  readonly node: BackchainNode;
  readonly binding: SpecialistBinding;
  readonly deliverable_refs: Iterable<string>;
  readonly acceptance_criteria: Iterable<string>;
  readonly validation_obligations: Iterable<string>;
  readonly evidence_requirements: Iterable<string>;
  readonly decision_refs: Iterable<string>;
  readonly contributor_specialists: Iterable<string>;
  readonly context_capsule_hash: string | null;
  readonly authority_refs: Iterable<string>;
  readonly approval_refs: Iterable<string>;
  readonly approval_scope_hash: string | null;
  readonly extra_blockers?: Iterable<string>;
}

/** The provider tool a node falls back to when no permitted tool exists; Python indexes blindly here. */
function providerTool(node: BackchainNode): string {
  const target = node.mutation_targets[0];
  if (target === undefined) throw new CompiledIndexError('tuple index out of range');
  return `provider:${afterFirst(target, ':')}`;
}

function resourceLocks(node: BackchainNode): string[] {
  const providers = node.mutation_targets.filter((t) => t.startsWith('external:')).map((t) => `provider:${afterFirst(t, ':')}`);
  return uniqueSorted([...node.mutation_targets, ...providers]);
}

/** `compile_pcwo`: returns `[pcwo | null, blockers]`; null when no valid order can be compiled. */
export function compilePcwo(registry: RoleOSRegistry, input: PcwoInput): [PCWO | null, string[]] {
  const { node, binding } = input;
  const query = N3_SPECIALISTS.get(node.runtime_role_id ?? '');
  const blockers = [...(input.extra_blockers ?? [])];
  if (query === undefined || !node.phase_compatibility.length) return [null, [...blockers, 'NO_VALID_PCWO:no specialist query or phase']];
  const accepted = [...input.acceptance_criteria];
  const acceptance = accepted.length ? accepted : [`${node.artifact_type ?? node.id} passes its validation obligations`];
  const toolPlan = binding.permitted_tools.length ? [...binding.permitted_tools] : [providerTool(node)];
  const obligations = [...input.validation_obligations];
  const evidence = [...input.evidence_requirements];
  let wo;
  try {
    wo = compileWorkOrder(registry, {
      project_id: input.project_id, mission_id: input.mission_id, phase_id: node.phase_compatibility[0] as string,
      objective: node.purpose, required_capabilities: [query.skill_name], acceptance_criteria: acceptance,
      input_refs: [...node.hard_dependencies], dependency_refs: [...node.dependencies],
      required_artifact_refs: node.hard_dependencies.filter((d) => d.startsWith('accept:') || d.startsWith('ref:')).map((d) => afterFirst(d, ':')),
      required_evidence: evidence, risk_level: riskLevelFor(node), side_effect_class: node.side_effect_class,
      department_hint: query.department, authority_refs: [...input.authority_refs], approval_refs: [...input.approval_refs],
      tool_plan: toolPlan, context_capsule_hash: input.context_capsule_hash, next_route: 'VALIDATE',
    });
  } catch (error) {
    if (error instanceof WorkOrderError) return [null, [...blockers, `NO_VALID_PCWO:${error.message}`]];
    throw error;
  }
  blockers.push(...wo._runtime.blockers);
  if (wo.accountable_role_id !== binding.specialist_role_id) blockers.push('PCWO_SPECIALIST_MISMATCH');
  blockers.push(...binding.blockers);
  if (input.context_capsule_hash === null) blockers.push('MISSING_CONTEXT_CAPSULE');
  const body = {
    work_order_id: wo.work_order_id, logical_operation_id: wo.idempotency.logical_operation_id, plan_hash: null,
    causal_node_id: node.id, objective: node.purpose, deliverable_refs: sortStrings(input.deliverable_refs),
    acceptance_criteria: acceptance, accountable_specialist: binding.specialist_role_id,
    contributor_specialists: uniqueSorted(input.contributor_specialists), runtime_authority_binding: binding.binding_hash,
    capability_requirements: binding.required_capabilities, context_capsule_ref: input.context_capsule_hash,
    input_refs: node.hard_dependencies, dependency_refs: node.dependencies, evidence_requirements: evidence,
    decision_refs: sortStrings(input.decision_refs), artifact_contracts: node.artifact_type ? [node.artifact_type] : [],
    tool_plan: toolPlan, validation_obligations: obligations, side_effect_class: node.side_effect_class,
    idempotency_class: IDEMPOTENCY_CLASS[node.side_effect_class] ?? '', mutation_targets: node.mutation_targets,
    resource_locks: resourceLocks(node), approval_scope: input.approval_scope_hash,
    retry_policy: retryPolicyFor(node.side_effect_class),
    provenance_refs: [`roleos:${wo._runtime.registry_hash}`, `cwg:${node.semantic_hash}`],
    source_skill_hashes: binding.source_skill_hashes,
    output_schema: node.artifact_type ? `n1:${node.artifact_type}` : 'n2:release_record',
    completion_checks: [
      'all validation obligations PASS', 'independent reviewer for medium/high risk', 'output hash recorded in N4 registry',
      'execution receipt/proof recorded',
    ],
    execution_ready: !blockers.length && wo._runtime.execution_ready, blockers: uniqueSorted(blockers),
  };
  return [{ ...body, work_order_hash: semanticHash(body as unknown as HashValue) }, uniqueSorted(blockers)];
}
