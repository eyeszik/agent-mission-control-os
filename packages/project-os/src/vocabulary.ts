/**
 * Project OS vocabulary: twin of `agency/project_os/vocabulary.py`.
 *
 * Everything `@amc/shared` already carries (and `verify_ontology_parity.py`
 * already checks against Python) is re-exported, not redefined. What shared
 * lacks is defined here, and `tests/parity.test.ts` compares the whole set
 * against a Python snapshot.
 */
import {
  ACTIVITY_TYPES,
  APPROVAL_BOUND_CONTENT_STATES,
  CALENDAR_HORIZON_DAYS,
  CAPABILITY_STATUSES,
  CONTENT_KINDS,
  CONTENT_STATES,
  CONTENT_TRANSITIONS,
  KNOWLEDGE_STAGES,
  KNOWLEDGE_STATUSES,
  LEARNING_PROMOTION_STAGES,
  MEMORY_AUTHORITY_ORDER,
  MEMORY_SCOPES,
  MEMORY_STATUSES,
  PROJECT_LIFECYCLE_STATES,
  PROJECT_OS_VERSION,
  PROJECT_TRANSITIONS,
  PROVIDER_MODES,
  PUBLICATION_STATES,
  RIGHTS_CLASSES,
  ROUTING_TIERS,
  SCHEDULED_JOB_KINDS,
  SCHEDULED_JOB_STATUSES,
  STORAGE_BACKENDS,
  STORAGE_OBJECT_STATUSES,
  SYSTEM_FOLDERS,
  WORKSPACE_FOLDERS,
  WORKSPACE_SCHEMA_VERSION,
  type ContentKind,
  type MemoryScope,
} from '@amc/shared';
import { pyRepr } from '@amc/kernel';
import { PyValueError } from './errors';

export {
  ACTIVITY_TYPES,
  APPROVAL_BOUND_CONTENT_STATES,
  CALENDAR_HORIZON_DAYS,
  CAPABILITY_STATUSES,
  CONTENT_KINDS,
  CONTENT_STATES,
  CONTENT_TRANSITIONS,
  KNOWLEDGE_STAGES,
  KNOWLEDGE_STATUSES,
  LEARNING_PROMOTION_STAGES,
  MEMORY_AUTHORITY_ORDER,
  MEMORY_SCOPES,
  MEMORY_STATUSES,
  PROJECT_LIFECYCLE_STATES,
  PROJECT_OS_VERSION,
  PROJECT_TRANSITIONS,
  PROVIDER_MODES,
  PUBLICATION_STATES,
  RIGHTS_CLASSES,
  ROUTING_TIERS,
  SCHEDULED_JOB_KINDS,
  SCHEDULED_JOB_STATUSES,
  STORAGE_BACKENDS,
  STORAGE_OBJECT_STATUSES,
  SYSTEM_FOLDERS,
  WORKSPACE_FOLDERS,
  WORKSPACE_SCHEMA_VERSION,
};

/** Relational canon, bytes in object storage, a mirror for humans. */
export const STORAGE_LAYERS = ['RELATIONAL', 'OBJECT', 'MIRROR'] as const;

export const UNKNOWN = 'UNKNOWN';

export type TransitionTable = Readonly<Record<string, readonly string[]>>;

export const PUBLICATION_TRANSITIONS: TransitionTable = {
  SPEC: ['VALIDATED', 'BLOCKED', 'FAILED'],
  VALIDATED: ['AUTHORIZED', 'BLOCKED'],
  AUTHORIZED: ['APPROVED', 'BLOCKED'],
  APPROVED: ['EXECUTING', 'BLOCKED'],
  EXECUTING: ['READBACK', 'FAILED', 'UNCERTAIN'],
  READBACK: ['RECONCILED', 'UNCERTAIN', 'FAILED'],
  UNCERTAIN: ['RECONCILED', 'FAILED'],
  RECONCILED: ['VERIFIED', 'FAILED'],
  VERIFIED: [],
  BLOCKED: [],
  FAILED: [],
};

/** Every content kind is exactly one N1 artifact type + owner; kinds are subtypes, never new types. */
export const CONTENT_KIND_ARTIFACT: Readonly<Record<ContentKind, readonly [string, string]>> = {
  article: ['copy_variant', 'copy'],
  email: ['copy_variant', 'copy'],
  newsletter: ['copy_variant', 'copy'],
  carousel: ['creative_concept', 'creative'],
  social_post: ['copy_variant', 'copy'],
  thread: ['copy_variant', 'copy'],
  video_script: ['copy_variant', 'copy'],
  short_video: ['media_asset', 'creative'],
  reel: ['media_asset', 'creative'],
  story: ['creative_concept', 'creative'],
  podcast_episode: ['media_asset', 'creative'],
  faq: ['copy_variant', 'copy'],
  landing_section: ['copy_variant', 'copy'],
  ai_search_answer: ['copy_variant', 'copy'],
  paid_creative: ['creative_concept', 'creative'],
};

/** Which authority classes a record in each scope may legitimately claim. */
export const MEMORY_SCOPE_AUTHORITIES: Readonly<Record<MemoryScope, readonly string[]>> = {
  M0_AGENCY: ['WORKING_CONTEXT'],
  M1_BRAND_CANON: ['BRAND_CANON'],
  M2_PROJECT: ['APPROVED_PROJECT_DECISION', 'WORKING_CONTEXT'],
  M3_CONVERSATION: ['WORKING_CONTEXT'],
  M4_EVIDENCE: ['VERIFIED_EVIDENCE', 'WORKING_CONTEXT'],
  M5_PERFORMANCE: ['VERIFIED_EVIDENCE', 'WORKING_CONTEXT'],
  M6_LEARNING: ['LEARNING_SIGNAL'],
};

/** Scopes that never leave their project/brand in portfolio-level reads. */
export const PRIVATE_MEMORY_SCOPES: readonly string[] = [
  'M1_BRAND_CANON',
  'M2_PROJECT',
  'M3_CONVERSATION',
  'M4_EVIDENCE',
  'M5_PERFORMANCE',
];

/** `Enum(value)`: the member's value, or `ValueError` like Python's. */
export function parseEnum<T extends string>(name: string, members: readonly T[], value: string): T {
  const found = members.find((member) => member === value);
  if (found === undefined) throw new PyValueError(`${pyRepr(value)} is not a valid ${name}`);
  return found;
}

/** `mapping.get(key)` for a plain record: own keys only (`constructor` is not a key). */
export function own<T>(record: Readonly<Record<string, T>>, key: string): T | undefined {
  return Object.hasOwn(record, key) ? record[key] : undefined;
}

/** `value in transitions.get(current, ())`. */
export function canTransition(table: TransitionTable, current: string, target: string): boolean {
  return (own(table, current) ?? []).includes(target);
}

/** Higher number = higher authority. Unknown authority ranks lowest. */
export function authorityRank(authority: string): number {
  const index = (MEMORY_AUTHORITY_ORDER as readonly string[]).indexOf(authority);
  return index < 0 ? 0 : MEMORY_AUTHORITY_ORDER.length - index;
}
