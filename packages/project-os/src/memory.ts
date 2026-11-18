/**
 * Twin of `agency/project_os/memory.py`: scoped memory with an explicit
 * authority order
 *
 *     BRAND_CANON > APPROVED_PROJECT_DECISION > VERIFIED_EVIDENCE
 *                 > WORKING_CONTEXT > LEARNING_SIGNAL
 *
 * A scope may only hold the authority classes it lists; a write with lower
 * authority than the active record for the same subject is quarantined, never
 * silently applied; resolution returns the highest-authority fresh record and
 * reports every shadowed or stale alternative. Promotion is an explicit act.
 */
import type { MemoryRecord } from '@amc/shared';
import { compareCodePoints, pyRepr } from '@amc/kernel';
import { MemoryPolicyError } from './errors';
import { compareDateTimes, fromIsoFormat, type PyDateTime } from './pydatetime';
import {
  MEMORY_SCOPE_AUTHORITIES,
  PRIVATE_MEMORY_SCOPES,
  authorityRank,
  own,
} from './vocabulary';

export function validatePlacement(args: {
  readonly scope: string;
  readonly authority: string;
  readonly project_id: string | null;
  readonly thread_id: string | null;
}): void {
  const { scope, authority, project_id: projectId, thread_id: threadId } = args;
  const allowed = own(MEMORY_SCOPE_AUTHORITIES, scope);
  if (allowed === undefined) throw new MemoryPolicyError(`unknown memory scope ${pyRepr(scope)}`);
  if (!allowed.includes(authority)) {
    throw new MemoryPolicyError(`scope ${scope} cannot hold ${authority} memory (allowed: ${allowed.join(', ')})`);
  }
  if (scope === 'M0_AGENCY' && projectId !== null) {
    throw new MemoryPolicyError('M0_AGENCY memory is tenant-wide and must not name a project');
  }
  if (scope !== 'M0_AGENCY' && scope !== 'M6_LEARNING' && projectId === null) {
    throw new MemoryPolicyError(`${scope} memory must belong to a project`);
  }
  if (scope === 'M3_CONVERSATION' && !threadId) {
    throw new MemoryPolicyError('M3_CONVERSATION memory must name its thread');
  }
}

export interface WriteDecision {
  readonly status: 'ACTIVE' | 'QUARANTINED' | 'DUPLICATE';
  readonly supersedes: string | null;
  readonly reason: string | null;
}

/** Highest authority first; equal authority keeps its input order (Python's stable `reverse=True`). */
function byAuthority(records: readonly MemoryRecord[]): MemoryRecord[] {
  return [...records].sort((a, b) => authorityRank(b.authority) - authorityRank(a.authority));
}

/** How a new record for a subject relates to the active records for it. */
export function decideWrite(args: {
  readonly authority: string;
  readonly content_hash: string;
  readonly active: readonly MemoryRecord[];
}): WriteDecision {
  const ranked = byAuthority(args.active);
  const top = ranked[0];
  if (top === undefined) return { status: 'ACTIVE', supersedes: null, reason: null };
  if (top.content_hash === args.content_hash && top.authority === args.authority) {
    return { status: 'DUPLICATE', supersedes: top.memory_id, reason: 'identical content already active' };
  }
  const rank = authorityRank(args.authority);
  if (rank < authorityRank(top.authority)) {
    const reason = `${args.authority} cannot override active ${top.authority} memory ${top.memory_id}`;
    return { status: 'QUARANTINED', supersedes: null, reason };
  }
  const sameOrLower = ranked.find((record) => authorityRank(record.authority) <= rank);
  return { status: 'ACTIVE', supersedes: sameOrLower?.memory_id ?? null, reason: null };
}

function isFresh(record: MemoryRecord, now: PyDateTime): boolean {
  if (!record.fresh_until) return true;
  return compareDateTimes(fromIsoFormat(record.fresh_until), now) >= 0;
}

function compareForResolution(a: MemoryRecord, b: MemoryRecord): number {
  // Authority first; at equal authority project-scoped memory beats tenant-wide
  // agency memory (M0 only fills gaps); then the newest record. Descending.
  const byRank = authorityRank(b.authority) - authorityRank(a.authority);
  if (byRank !== 0) return byRank;
  const byProject = Number(b.project_id != null) - Number(a.project_id != null);
  return byProject !== 0 ? byProject : compareCodePoints(b.created_at, a.created_at);
}

export interface MemoryResolution {
  readonly winner: MemoryRecord | null;
  readonly authority: string | null;
  readonly shadowed: string[];
  readonly stale: string[];
  readonly resolved: boolean;
}

export function resolveMemory(records: readonly MemoryRecord[], now: PyDateTime): MemoryResolution {
  const candidates = records.filter((record) => record.status === 'ACTIVE');
  const fresh = candidates.filter((record) => isFresh(record, now));
  const stale = candidates.filter((record) => !isFresh(record, now)).map((record) => record.memory_id);
  fresh.sort(compareForResolution);
  const winner = fresh[0] ?? null;
  const shadowed = fresh
    .slice(1)
    .filter((record) => winner !== null && record.content_hash !== winner.content_hash)
    .map((record) => record.memory_id);
  return { winner, authority: winner?.authority ?? null, shadowed, stale, resolved: winner !== null };
}

/** Promotion to a higher authority is an explicit, attributed act; it must raise authority. */
export function canPromote(args: { readonly scope: string; readonly from_authority: string; readonly to_authority: string }): void {
  const allowed = own(MEMORY_SCOPE_AUTHORITIES, args.scope) ?? [];
  if (!allowed.includes(args.to_authority)) {
    throw new MemoryPolicyError(`${args.scope} memory cannot be promoted to ${args.to_authority}`);
  }
  if (authorityRank(args.to_authority) <= authorityRank(args.from_authority)) {
    throw new MemoryPolicyError('promotion must raise authority');
  }
}

/** Only generalized agency memory crosses project/brand boundaries. */
export function portfolioVisible(scope: string): boolean {
  return !PRIVATE_MEMORY_SCOPES.includes(scope) && scope !== 'M6_LEARNING';
}
