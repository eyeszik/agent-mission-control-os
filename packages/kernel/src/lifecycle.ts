/**
 * N2 — lifecycle transition matrices and release guards (twin of
 * `agency/kernel/lifecycle.py`).
 *
 * Closed transitions: a move absent from the matrix is rejected. Guarded
 * release: entering a client-visible state runs every release guard, and each
 * guard is fail-closed by absence — an unset fact in `TransitionContext` means
 * "unproven", never "fine to skip".
 */
import { KernelKeyError, TransitionError } from './errors';
import {
  ARTIFACT_STATUSES,
  ENGAGEMENT_STATUSES,
  WORKSTREAM_STATUSES,
  type ArtifactStatus,
  type EngagementStatus,
  type WorkstreamStatus,
} from './models';
import { pyRepr, pySorted, pyStr } from './pyformat';

export const LIFECYCLE_VERSION = 'amc-agency-lifecycle/n2-v1';

/** Provenance modes that must never reach a client-visible state. */
export const DEGRADED_PROVENANCE_MODES: ReadonlySet<string> = new Set(['FALLBACK_DEGRADED']);

export const LIFECYCLE_ENTITIES = ['engagement', 'workstream', 'artifact'] as const;
export type LifecycleEntity = (typeof LIFECYCLE_ENTITIES)[number];
export type LifecycleStatus = EngagementStatus | WorkstreamStatus | ArtifactStatus;

/** Facts a guard may consult. Every field is optional; an absent fact is treated as unproven. */
export interface TransitionContext {
  readonly generation_mode?: string | null;
  readonly approval_exists?: boolean;
  readonly approval_decision?: string | null;
  readonly approval_resolved?: boolean;
  readonly brand_safety_passed?: boolean | null;
  readonly external_side_effect?: boolean;
  readonly spend_authorized?: boolean;
  readonly unmet_hard_dependencies?: readonly string[];
  /** Whether a human approval discharges a failed brand-safety review. Default false: a hard gate. */
  readonly brand_safety_advisory?: boolean;
}

type Facts = Required<TransitionContext>;

function facts(context: TransitionContext | null | undefined): Facts {
  const c = context ?? {};
  return {
    generation_mode: c.generation_mode ?? null,
    approval_exists: c.approval_exists ?? false,
    approval_decision: c.approval_decision ?? null,
    approval_resolved: c.approval_resolved ?? false,
    brand_safety_passed: c.brand_safety_passed ?? null,
    external_side_effect: c.external_side_effect ?? false,
    spend_authorized: c.spend_authorized ?? false,
    unmet_hard_dependencies: c.unmet_hard_dependencies ?? [],
    brand_safety_advisory: c.brand_safety_advisory ?? false,
  };
}

export function isDegraded(context: TransitionContext | null | undefined): boolean {
  return DEGRADED_PROVENANCE_MODES.has(facts(context).generation_mode ?? '');
}

export function humanApproved(context: TransitionContext | null | undefined): boolean {
  const f = facts(context);
  return f.approval_exists && f.approval_resolved && f.approval_decision === 'approve';
}

/** A single failed guard, carrying a stable code for call-site mapping. */
export interface GuardFailure {
  readonly code: string;
  readonly message: string;
}

type Guard = (context: Facts) => string | null;

const guardNotDegraded: Guard = (c) =>
  isDegraded(c)
    ? 'generation provenance is FALLBACK_DEGRADED; degraded output cannot reach a client-visible state'
    : null;

const guardApprovalExists: Guard = (c) => (c.approval_exists ? null : 'no human approval exists for this run');

// Only meaningful once an approval exists; absence is reported by its own guard.
const guardApprovalResolved: Guard = (c) =>
  c.approval_exists && !c.approval_resolved ? 'human approval is unresolved' : null;

const guardApprovalDecision: Guard = (c) =>
  c.approval_exists && c.approval_resolved && c.approval_decision !== 'approve'
    ? `human approval decision is '${pyStr(c.approval_decision)}', not 'approve'`
    : null;

// Under advisory policy an explicit approval discharges the flag; under the default hard gate it never does.
const guardBrandSafety: Guard = (c) => {
  if (c.brand_safety_passed === true) return null;
  if (c.brand_safety_advisory && humanApproved(c)) return null;
  return 'brand safety review has not passed';
};

const guardDependenciesMet: Guard = (c) =>
  c.unmet_hard_dependencies.length > 0
    ? `unmet hard dependencies: ${pySorted(c.unmet_hard_dependencies).join(', ')}`
    : null;

const guardSpendAuthorized: Guard = (c) =>
  c.external_side_effect && !c.spend_authorized
    ? 'external side effect requires an explicit spend/publication authorization'
    : null;

/** Guards applied to any transition entering a client-visible state, in evaluation order. */
const RELEASE_GUARDS: ReadonlyArray<readonly [string, Guard]> = [
  ['degraded_release_block', guardNotDegraded],
  ['approval_missing', guardApprovalExists],
  ['approval_pending', guardApprovalResolved],
  ['approval_not_approved', guardApprovalDecision],
  ['brand_safety_failed', guardBrandSafety],
  ['spend_unauthorized', guardSpendAuthorized],
];

export const RELEASE_GUARD_CODES: readonly string[] = RELEASE_GUARDS.map(([code]) => code);
export const DEPENDENCY_GUARD_CODE = 'unmet_hard_dependencies';

/** Evaluate every release guard, returning structured failures in order. */
export function releaseGuardFailures(context: TransitionContext | null | undefined): GuardFailure[] {
  const f = facts(context);
  const failures: GuardFailure[] = [];
  for (const [code, guard] of RELEASE_GUARDS) {
    const message = guard(f);
    if (message) failures.push({ code, message });
  }
  return failures;
}

// --------------------------------------------------------------------------
// Transition matrices
// --------------------------------------------------------------------------

const ENGAGEMENT_INTERRUPTS: readonly EngagementStatus[] = [
  'blocked', 'degraded', 'review_required', 'paused', 'failed', 'cancelled',
];

function withInterrupts(...states: EngagementStatus[]): EngagementStatus[] {
  return [...states, ...ENGAGEMENT_INTERRUPTS];
}

export const ENGAGEMENT_TRANSITIONS: Readonly<Record<EngagementStatus, readonly EngagementStatus[]>> = {
  intake: withInterrupts('discovery'),
  discovery: withInterrupts('research'),
  research: withInterrupts('strategy'),
  strategy: withInterrupts('brand', 'product'),
  brand: withInterrupts('product', 'build'),
  product: withInterrupts('build'),
  build: withInterrupts('launch_ready'),
  launch_ready: withInterrupts('launched'),
  launched: withInterrupts('growth'),
  growth: withInterrupts('optimizing', 'complete'),
  optimizing: withInterrupts('growth', 'complete'),
  // Interrupt states resume into the phases that can legitimately continue work.
  blocked: ['discovery', 'research', 'strategy', 'brand', 'product', 'build', 'cancelled', 'failed'],
  degraded: ['research', 'strategy', 'brand', 'product', 'build', 'review_required', 'failed', 'cancelled'],
  review_required: ['strategy', 'brand', 'product', 'build', 'launch_ready', 'blocked', 'failed', 'cancelled'],
  paused: ['discovery', 'research', 'strategy', 'brand', 'product', 'build', 'growth', 'cancelled'],
  complete: [],
  failed: [],
  cancelled: [],
};

export const WORKSTREAM_TRANSITIONS: Readonly<Record<WorkstreamStatus, readonly WorkstreamStatus[]>> = {
  blocked: ['ready', 'cancelled', 'failed'],
  ready: ['executing', 'blocked', 'cancelled'],
  executing: ['validating', 'degraded', 'failed', 'blocked', 'cancelled'],
  validating: ['review', 'executing', 'degraded', 'failed', 'cancelled'],
  review: ['approved', 'rejected', 'executing', 'cancelled'],
  approved: ['released', 'rejected', 'cancelled'],
  degraded: ['executing', 'failed', 'cancelled'],
  released: [],
  failed: [],
  rejected: [],
  cancelled: [],
};

export const ARTIFACT_TRANSITIONS: Readonly<Record<ArtifactStatus, readonly ArtifactStatus[]>> = {
  draft: ['validating', 'invalidated', 'archived'],
  validating: ['approved', 'review_required', 'draft', 'invalidated'],
  approved: ['release_eligible', 'review_required', 'invalidated'],
  release_eligible: ['released', 'review_required', 'invalidated'],
  released: ['review_required', 'invalidated', 'archived'],
  review_required: ['validating', 'draft', 'invalidated', 'archived'],
  invalidated: ['draft', 'archived'],
  archived: [],
};

interface EntityTables {
  readonly statuses: readonly LifecycleStatus[];
  readonly matrix: Readonly<Record<string, readonly LifecycleStatus[]>>;
  /** Entering any of these runs the full release-guard set. */
  readonly clientVisible: readonly LifecycleStatus[];
  /** Entering any of these additionally requires every hard dependency to be met. */
  readonly dependencyGated: readonly LifecycleStatus[];
}

const ENTITIES: Readonly<Record<LifecycleEntity, EntityTables>> = {
  engagement: { statuses: ENGAGEMENT_STATUSES, matrix: ENGAGEMENT_TRANSITIONS, clientVisible: ['launched'],
    dependencyGated: ['build', 'launch_ready'] },
  workstream: { statuses: WORKSTREAM_STATUSES, matrix: WORKSTREAM_TRANSITIONS, clientVisible: ['released'],
    dependencyGated: ['executing'] },
  artifact: { statuses: ARTIFACT_STATUSES, matrix: ARTIFACT_TRANSITIONS,
    clientVisible: ['release_eligible', 'released'], dependencyGated: ['release_eligible'] },
};

function isEntity(entity: string): entity is LifecycleEntity {
  return Object.prototype.hasOwnProperty.call(ENTITIES, entity);
}

/** Python indexes `_MATRICES[entity]` directly in some functions: an unknown entity is a KeyError there. */
function tablesOrKeyError(entity: string): EntityTables {
  if (!isEntity(entity)) throw new KernelKeyError(pyRepr(entity));
  return ENTITIES[entity];
}

function resolveStatus(entity: string, value: unknown): LifecycleStatus {
  if (!isEntity(entity)) throw new TransitionError(`Unknown lifecycle entity '${entity}'`);
  const statuses: readonly unknown[] = ENTITIES[entity].statuses;
  if (statuses.includes(value)) return value as LifecycleStatus;
  throw new TransitionError(`Unknown ${entity} status '${pyStr(value)}'`);
}

function targetsOf(tables: EntityTables, state: LifecycleStatus): readonly LifecycleStatus[] {
  return tables.matrix[state] ?? [];
}

/** States reachable from `current` in one legal move. */
export function allowedTransitions(entity: string, current: unknown): ReadonlySet<LifecycleStatus> {
  const tables = tablesOrKeyError(entity);
  return new Set(targetsOf(tables, resolveStatus(entity, current)));
}

function guardedFailures(tables: EntityTables, target: LifecycleStatus, context: Facts): GuardFailure[] {
  const failures: GuardFailure[] = [];
  if (tables.clientVisible.includes(target)) failures.push(...releaseGuardFailures(context));
  if (tables.dependencyGated.includes(target)) {
    const reason = guardDependenciesMet(context);
    if (reason) failures.push({ code: DEPENDENCY_GUARD_CODE, message: reason });
  }
  return failures;
}

/** Every reason this move is illegal, with stable codes. Empty means legal. */
export function transitionFailures(
  entity: string,
  current: unknown,
  target: unknown,
  context?: TransitionContext | null,
): GuardFailure[] {
  const from = resolveStatus(entity, current);
  const to = resolveStatus(entity, target);
  const tables = ENTITIES[entity as LifecycleEntity];
  if (!targetsOf(tables, from).includes(to)) {
    // An illegal edge makes guard results meaningless; report the edge alone.
    return [{ code: 'illegal_transition', message: `${entity} cannot move from '${from}' to '${to}'` }];
  }
  return guardedFailures(tables, to, facts(context));
}

/** Human-readable form of `transitionFailures`. */
export function transitionBlockers(
  entity: string,
  current: unknown,
  target: unknown,
  context?: TransitionContext | null,
): string[] {
  return transitionFailures(entity, current, target, context).map((failure) => failure.message);
}

export function canTransition(
  entity: string,
  current: unknown,
  target: unknown,
  context?: TransitionContext | null,
): boolean {
  return transitionBlockers(entity, current, target, context).length === 0;
}

/** Fail closed on an illegal or unguarded move. */
export function assertTransition(
  entity: string,
  current: unknown,
  target: unknown,
  context?: TransitionContext | null,
): void {
  const blockers = transitionBlockers(entity, current, target, context);
  if (blockers.length > 0) {
    const from = resolveStatus(entity, current);
    const to = resolveStatus(entity, target);
    throw new TransitionError(`Illegal ${entity} transition ${from} -> ${to}: ${blockers.join('; ')}`);
  }
}

/** States with no outbound edges. */
export function terminalStates(entity: string): ReadonlySet<LifecycleStatus> {
  const tables = tablesOrKeyError(entity);
  // ⚡ Bolt: Use a zero-allocation reduce to avoid intermediate array allocation
  return tables.statuses.reduce((acc, state) => {
    if (targetsOf(tables, state).length === 0) acc.add(state);
    return acc;
  }, new Set<LifecycleStatus>());
}

function entityProblems(entity: LifecycleEntity): string[] {
  const { statuses, matrix, clientVisible } = ENTITIES[entity];
  const known: readonly string[] = statuses;
  const problems: string[] = [];
  for (const missing of pySorted(statuses.filter((s) => !(s in matrix)))) {
    problems.push(`${entity} status '${missing}' has no declared transitions`);
  }
  for (const extra of pySorted(Object.keys(matrix).filter((s) => !known.includes(s)))) {
    problems.push(`${entity} matrix declares unknown status '${extra}'`);
  }
  for (const [state, targets] of Object.entries(matrix)) {
    for (const target of targets.filter((t) => !known.includes(t))) {
      problems.push(`${entity} transition ${state} -> '${target}' targets an unknown status`);
    }
  }
  for (const visible of clientVisible.filter((s) => !known.includes(s))) {
    problems.push(`${entity} client-visible state '${visible}' is not a known status`);
  }
  return problems;
}

/** Structural self-check: every state declared, every target known. Returns all defects at once. */
export function validateMatrices(): string[] {
  return LIFECYCLE_ENTITIES.flatMap(entityProblems);
}

export interface EntitySnapshot {
  readonly transitions: Record<string, string[]>;
  readonly client_visible: string[];
  readonly dependency_gated: string[];
}

function entitySnapshot(entity: LifecycleEntity): EntitySnapshot {
  const { statuses, matrix, clientVisible, dependencyGated } = ENTITIES[entity];
  const transitions: Record<string, string[]> = {};
  for (const state of pySorted(statuses)) transitions[state] = pySorted(matrix[state] ?? []);
  return { transitions, client_visible: pySorted(clientVisible), dependency_gated: pySorted(dependencyGated) };
}

/** Serializable view, identical to Python's `lifecycle_snapshot()`. */
export function lifecycleSnapshot(): { lifecycle_version: string; entities: Record<LifecycleEntity, EntitySnapshot> } {
  return {
    lifecycle_version: LIFECYCLE_VERSION,
    entities: {
      engagement: entitySnapshot('engagement'),
      workstream: entitySnapshot('workstream'),
      artifact: entitySnapshot('artifact'),
    },
  };
}
