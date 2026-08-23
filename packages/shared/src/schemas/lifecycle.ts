import { z } from 'zod';

/**
 * N2 — lifecycle transition matrices, mirrored from
 * services/langgraph/agency/kernel/lifecycle.py.
 *
 * Verified against the Python source by scripts/verify_ontology_parity.py.
 * Edit both halves together or the parity gate will block CI.
 */

export const LIFECYCLE_VERSION = 'amc-agency-lifecycle/n2-v1';

export const ENGAGEMENT_STATES = ['blocked', 'brand', 'build', 'cancelled', 'complete', 'degraded', 'discovery', 'failed', 'growth', 'intake', 'launch_ready', 'launched', 'optimizing', 'paused', 'product', 'research', 'review_required', 'strategy'] as const;
export const EngagementStateSchema = z.enum(ENGAGEMENT_STATES);
export type EngagementState = z.infer<typeof EngagementStateSchema>;

export const ENGAGEMENT_TRANSITIONS: Record<EngagementState, readonly EngagementState[]> = {
  blocked: ['brand', 'build', 'cancelled', 'discovery', 'failed', 'product', 'research', 'strategy'],
  brand: ['blocked', 'build', 'cancelled', 'degraded', 'failed', 'paused', 'product', 'review_required'],
  build: ['blocked', 'cancelled', 'degraded', 'failed', 'launch_ready', 'paused', 'review_required'],
  cancelled: [],
  complete: [],
  degraded: ['brand', 'build', 'cancelled', 'failed', 'product', 'research', 'review_required', 'strategy'],
  discovery: ['blocked', 'cancelled', 'degraded', 'failed', 'paused', 'research', 'review_required'],
  failed: [],
  growth: ['blocked', 'cancelled', 'complete', 'degraded', 'failed', 'optimizing', 'paused', 'review_required'],
  intake: ['blocked', 'cancelled', 'degraded', 'discovery', 'failed', 'paused', 'review_required'],
  launch_ready: ['blocked', 'cancelled', 'degraded', 'failed', 'launched', 'paused', 'review_required'],
  launched: ['blocked', 'cancelled', 'degraded', 'failed', 'growth', 'paused', 'review_required'],
  optimizing: ['blocked', 'cancelled', 'complete', 'degraded', 'failed', 'growth', 'paused', 'review_required'],
  paused: ['brand', 'build', 'cancelled', 'discovery', 'growth', 'product', 'research', 'strategy'],
  product: ['blocked', 'build', 'cancelled', 'degraded', 'failed', 'paused', 'review_required'],
  research: ['blocked', 'cancelled', 'degraded', 'failed', 'paused', 'review_required', 'strategy'],
  review_required: ['blocked', 'brand', 'build', 'cancelled', 'failed', 'launch_ready', 'product', 'strategy'],
  strategy: ['blocked', 'brand', 'cancelled', 'degraded', 'failed', 'paused', 'product', 'review_required'],
};

export const ENGAGEMENT_CLIENT_VISIBLE: readonly EngagementState[] = ['launched'];
export const ENGAGEMENT_DEPENDENCY_GATED: readonly EngagementState[] = ['build', 'launch_ready'];

export const WORKSTREAM_STATES = ['approved', 'blocked', 'cancelled', 'degraded', 'executing', 'failed', 'ready', 'rejected', 'released', 'review', 'validating'] as const;
export const WorkstreamStateSchema = z.enum(WORKSTREAM_STATES);
export type WorkstreamState = z.infer<typeof WorkstreamStateSchema>;

export const WORKSTREAM_TRANSITIONS: Record<WorkstreamState, readonly WorkstreamState[]> = {
  approved: ['cancelled', 'rejected', 'released'],
  blocked: ['cancelled', 'failed', 'ready'],
  cancelled: [],
  degraded: ['cancelled', 'executing', 'failed'],
  executing: ['blocked', 'cancelled', 'degraded', 'failed', 'validating'],
  failed: [],
  ready: ['blocked', 'cancelled', 'executing'],
  rejected: [],
  released: [],
  review: ['approved', 'cancelled', 'executing', 'rejected'],
  validating: ['cancelled', 'degraded', 'executing', 'failed', 'review'],
};

export const WORKSTREAM_CLIENT_VISIBLE: readonly WorkstreamState[] = ['released'];
export const WORKSTREAM_DEPENDENCY_GATED: readonly WorkstreamState[] = ['executing'];

export const ARTIFACT_STATES = ['approved', 'archived', 'draft', 'invalidated', 'release_eligible', 'released', 'review_required', 'validating'] as const;
export const ArtifactStateSchema = z.enum(ARTIFACT_STATES);
export type ArtifactState = z.infer<typeof ArtifactStateSchema>;

export const ARTIFACT_TRANSITIONS: Record<ArtifactState, readonly ArtifactState[]> = {
  approved: ['invalidated', 'release_eligible', 'review_required'],
  archived: [],
  draft: ['archived', 'invalidated', 'validating'],
  invalidated: ['archived', 'draft'],
  release_eligible: ['invalidated', 'released', 'review_required'],
  released: ['archived', 'invalidated', 'review_required'],
  review_required: ['archived', 'draft', 'invalidated', 'validating'],
  validating: ['approved', 'draft', 'invalidated', 'review_required'],
};

export const ARTIFACT_CLIENT_VISIBLE: readonly ArtifactState[] = ['release_eligible', 'released'];
export const ARTIFACT_DEPENDENCY_GATED: readonly ArtifactState[] = ['release_eligible'];

export const DEGRADED_PROVENANCE_MODES = ['FALLBACK_DEGRADED'] as const;

/** True when generation provenance must not reach a client-visible state. */
export function isDegradedProvenance(mode: string | null | undefined): boolean {
  return (DEGRADED_PROVENANCE_MODES as readonly string[]).includes(mode ?? '');
}
