/**
 * Kernel status vocabularies and record shapes (twin of `agency/kernel/models.py`).
 *
 * The arrays keep Python's declaration order. The record interfaces are plain
 * shapes: Pydantic's field constraints (`ge`/`le` on confidences, `version >= 1`)
 * are validated at the API boundary by the Zod twins in `@amc/shared`, not here.
 */

export const ENGAGEMENT_STATUSES = [
  'intake', 'discovery', 'research', 'strategy', 'brand', 'product', 'build', 'launch_ready', 'launched',
  'growth', 'optimizing', 'complete', 'blocked', 'degraded', 'review_required', 'paused', 'failed', 'cancelled',
] as const;
export type EngagementStatus = (typeof ENGAGEMENT_STATUSES)[number];

export const WORKSTREAM_STATUSES = [
  'blocked', 'ready', 'executing', 'validating', 'review', 'approved', 'released', 'degraded', 'failed',
  'rejected', 'cancelled',
] as const;
export type WorkstreamStatus = (typeof WORKSTREAM_STATUSES)[number];

export const ARTIFACT_STATUSES = [
  'draft', 'validating', 'approved', 'release_eligible', 'released', 'review_required', 'invalidated', 'archived',
] as const;
export type ArtifactStatus = (typeof ARTIFACT_STATUSES)[number];

export const DECISION_STATUSES = ['proposed', 'accepted', 'superseded', 'rejected'] as const;
export type DecisionStatus = (typeof DECISION_STATUSES)[number];

export const EPISTEMIC_STATUSES = [
  'verified', 'inferred', 'assumption', 'hypothesis', 'stale', 'conflict', 'unverified', 'blocked',
] as const;
export type EpistemicStatus = (typeof EPISTEMIC_STATUSES)[number];

export const DEPENDENCY_STRENGTHS = ['hard', 'soft'] as const;
export type DependencyStrength = (typeof DEPENDENCY_STRENGTHS)[number];

/** Narrow `value` to a member of `members` (exact string match, as a str-Enum lookup). */
export function isMember<T extends string>(members: readonly T[], value: unknown): value is T {
  return typeof value === 'string' && (members as readonly string[]).includes(value);
}

export interface ConfidenceVector {
  readonly evidence: number;
  readonly freshness: number;
  readonly contract: number;
  readonly execution: number;
  readonly safety: number;
  readonly strategic_coherence: number;
  readonly aggregate: number;
}

interface Scoped {
  readonly engagement_id: string;
  readonly tenant_id: string;
  readonly project_id: string;
}

export interface Engagement extends Scoped {
  readonly objective: string;
  readonly desired_outcome: string;
  readonly status: EngagementStatus;
  readonly constraints: Readonly<Record<string, unknown>>;
  readonly permissions: Readonly<Record<string, unknown>>;
  readonly metadata: Readonly<Record<string, unknown>>;
  readonly created_at: string;
  readonly updated_at: string;
}

export interface Workstream extends Scoped {
  readonly workstream_id: string;
  readonly department: string;
  readonly objective: string;
  readonly status: WorkstreamStatus;
  readonly dependencies: readonly string[];
  readonly acceptance_criteria: readonly string[];
  readonly permissions: readonly string[];
  readonly metadata: Readonly<Record<string, unknown>>;
  readonly created_at: string;
  readonly updated_at: string;
}

export interface Evidence extends Scoped {
  readonly evidence_id: string;
  readonly evidence_type: string;
  readonly source_ref: string | null;
  readonly claim: string;
  readonly epistemic_status: EpistemicStatus;
  readonly confidence: number;
  readonly collected_at: string;
  readonly freshness_seconds: number | null;
  readonly payload: Readonly<Record<string, unknown>>;
  readonly metadata: Readonly<Record<string, unknown>>;
}

export interface Decision extends Scoped {
  readonly decision_id: string;
  readonly question: string;
  readonly alternatives: readonly unknown[];
  readonly selected_option: unknown;
  readonly evidence_ids: readonly string[];
  readonly assumptions: readonly string[];
  readonly affected_artifact_ids: readonly string[];
  readonly confidence: ConfidenceVector;
  readonly status: DecisionStatus;
  readonly approver: string | null;
  readonly created_at: string;
  readonly updated_at: string;
}

export interface Artifact extends Scoped {
  readonly artifact_id: string;
  readonly workstream_id: string | null;
  readonly artifact_type: string;
  readonly subtype: string | null;
  readonly owner_department: string;
  readonly version: number;
  readonly status: ArtifactStatus;
  readonly content_location: string | null;
  readonly content_hash: string | null;
  readonly semantic_fingerprint: string | null;
  readonly assumptions: readonly string[];
  readonly validation: Readonly<Record<string, unknown>>;
  readonly approval: Readonly<Record<string, unknown>>;
  readonly metadata: Readonly<Record<string, unknown>>;
  readonly created_at: string;
  readonly updated_at: string;
}
