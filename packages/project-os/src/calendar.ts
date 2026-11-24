/**
 * Twin of `agency/project_os/calendar.py`: the content state-machine guard,
 * the scheduler's due gate, deterministic slot planning, adaptive
 * rescheduling and the content-supply forecaster.
 *
 * Scheduler invariant (the Python docstring's, kept): DUE -> dependency
 * check -> evidence/freshness check -> rights check -> exact approval check
 * -> enqueue outbox -> adapter -> read-back -> reconciliation -> receipt.
 * This module owns the checks and the planning maths only. It never calls a
 * provider and grants nothing: a clear gate is a precondition, not approval.
 */
import { z } from 'zod';
import { ScheduleCadenceSchema } from '@amc/shared';
import { compareCodePoints } from '@amc/kernel';
import { ContentTransitionError, PyValueError } from './errors';
import {
  addTimedelta,
  compareDateTimes,
  fromIsoFormat,
  isoformat,
  replaceTime,
  weekday,
  type PyDateTime,
  makeDateTime,
} from './pydatetime';
import type { PyJson } from './json';
import { roundTo, strOf, truthy } from './pytext';
import {
  APPROVAL_BOUND_CONTENT_STATES,
  CALENDAR_HORIZON_DAYS,
  CONTENT_KINDS,
  CONTENT_KIND_ARTIFACT,
  CONTENT_STATES,
  CONTENT_TRANSITIONS,
  UNKNOWN,
  canTransition,
  parseEnum,
} from './vocabulary';

export type ScheduleCadence = z.infer<typeof ScheduleCadenceSchema>;

const US_PER_MINUTE = 60_000_000;
const BLOCKING_DEPENDENCY_STATUSES = ['invalidated', 'review_required', 'archived'];

/** `parse_ts`: a datetime or ISO text; a naive value is read as UTC. */
export function parseTs(value: string | PyDateTime): PyDateTime {
  const moment = typeof value === 'string' ? fromIsoFormat(value) : value;
  return moment.utcoffset_us === null ? { ...moment, utcoffset_us: 0 } : moment;
}

export interface ContentTransitionFacts {
  readonly version: number;
  readonly approved_version: number | null;
  readonly release_blockers?: readonly string[];
}

function approvalProblem(target: string, facts: ContentTransitionFacts): string {
  const state = facts.approved_version === null ? 'missing' : `for v${facts.approved_version}`;
  return `${target} requires an approval bound to v${facts.version}; approval is ${state}`;
}

/** Throws `ContentTransitionError` unless `current -> target` is legal and its guards hold. */
export function assertContentTransition(current: string, target: string, facts: ContentTransitionFacts): void {
  const from = parseEnum('ContentState', CONTENT_STATES, current);
  const to = parseEnum('ContentState', CONTENT_STATES, target);
  if (!canTransition(CONTENT_TRANSITIONS, from, to)) {
    throw new ContentTransitionError(`cannot move content from ${from} to ${to}`);
  }
  // Entering APPROVED is the approval decision itself; the caller records it with separation of duties.
  if (to === 'APPROVED') return;
  if ((APPROVAL_BOUND_CONTENT_STATES as readonly string[]).includes(to) && facts.approved_version !== facts.version) {
    throw new ContentTransitionError(approvalProblem(to, facts));
  }
  const blockers = [...(facts.release_blockers ?? [])];
  if ((to === 'READY' || to === 'SCHEDULED') && blockers.length > 0) {
    throw new ContentTransitionError(`release blocked: ${blockers.join(', ')}`);
  }
}

export function requiresRights(kind: string): boolean {
  const [artifactType] = CONTENT_KIND_ARTIFACT[parseEnum('ContentKind', CONTENT_KINDS, kind)];
  return artifactType === 'media_asset' || artifactType === 'creative_concept';
}

export interface GateInput {
  readonly state: string;
  readonly version: number;
  readonly approved_version: number | null;
  readonly approval_ref: string | null;
  readonly release_blockers?: readonly string[];
  readonly evidence_fresh_until?: string | null;
  readonly dependency_statuses?: Readonly<Record<string, string>>;
  readonly rights_required?: boolean;
  readonly rights?: Readonly<Record<string, PyJson>> | null;
}

function dependencyReasons(statuses: Readonly<Record<string, string>>): string[] {
  return Object.keys(statuses)
    .sort(compareCodePoints)
    .filter((id) => BLOCKING_DEPENDENCY_STATUSES.includes(statuses[id] as string))
    .map((id) => `DEPENDENCY_${(statuses[id] as string).toUpperCase()}:${id}`);
}

function rightsReason(item: GateInput): string | undefined {
  if (!(item.rights_required || (item.rights !== undefined && item.rights !== null))) return undefined;
  const rights = item.rights && truthy(item.rights) ? item.rights : { ok: false, reason: 'RIGHTS_MISSING' };
  if (truthy(rights.ok)) return undefined;
  return truthy(rights.reason) ? strOf(rights.reason) : 'RIGHTS_MISSING';
}

/** Every reason the item may not be published now (empty = clear). */
export function dueGate(item: GateInput, now: PyDateTime): string[] {
  const reasons = dependencyReasons(item.dependency_statuses ?? {});
  if (item.evidence_fresh_until && compareDateTimes(parseTs(item.evidence_fresh_until), now) < 0) {
    reasons.push('EVIDENCE_STALE');
  }
  reasons.push(...(item.release_blockers ?? []).map((blocker) => `RELEASE_BLOCKER:${blocker}`));
  const rights = rightsReason(item);
  if (rights !== undefined) reasons.push(rights);
  if (!item.approval_ref || item.approved_version !== item.version) {
    reasons.push('APPROVAL_NOT_BOUND_TO_CURRENT_VERSION');
  }
  return reasons;
}

// -- slot planning -----------------------------------------------------------------

export interface PlannedSlot {
  readonly channel: string;
  readonly kind: string;
  readonly scheduled_for: string;
}

function slotMoment(weekZero: PyDateTime, week: number, weekdays: readonly number[], index: number, hour: number): PyDateTime {
  const dayOfWeek = weekdays[index % weekdays.length] as number;
  const day = replaceTime(addTimedelta(weekZero, week * 7 + dayOfWeek, 0), { hour });
  return addTimedelta(day, 0, Math.floor(index / weekdays.length) * 90 * US_PER_MINUTE);
}

function cadenceSlots(cadence: ScheduleCadence, start: PyDateTime, end: PyDateTime, horizonDays: number): PlannedSlot[] {
  const weekdays = [...new Set(cadence.weekdays)].sort((a, b) => a - b);
  const days = weekdays.length > 0 ? weekdays : [0];
  const weekZero = addTimedelta(start, -weekday(start), 0);
  const slots: PlannedSlot[] = [];
  let accumulator = 0;
  for (let week = 0; week < Math.ceil(horizonDays / 7) + 1; week += 1) {
    accumulator += cadence.posts_per_week;
    const count = Math.trunc(accumulator);
    accumulator -= count;
    for (let index = 0; index < count; index += 1) {
      const moment = slotMoment(weekZero, week, days, index, cadence.hour_utc);
      if (compareDateTimes(start, moment) <= 0 && compareDateTimes(moment, end) < 0) {
        slots.push({ channel: cadence.channel, kind: cadence.kind, scheduled_for: isoformat(moment) });
      }
    }
  }
  return slots;
}

function compareSlots(a: PlannedSlot, b: PlannedSlot): number {
  return (
    compareCodePoints(a.scheduled_for, b.scheduled_for) ||
    compareCodePoints(a.channel, b.channel) ||
    compareCodePoints(a.kind, b.kind)
  );
}

export interface PlanHorizonArgs {
  readonly start: string | PyDateTime;
  readonly horizon_days: number;
  readonly cadences: readonly ScheduleCadence[];
}

/**
 * Deterministic slot plan for 14 days to 12 months ahead. Posts per week are
 * spread over the cadence's weekdays; fractional cadences (0.5/week) become
 * one slot every other eligible week.
 */
export function planHorizon(args: PlanHorizonArgs): PlannedSlot[] {
  if (!(CALENDAR_HORIZON_DAYS as readonly number[]).includes(args.horizon_days)) {
    throw new PyValueError(`horizon_days must be one of (${CALENDAR_HORIZON_DAYS.join(', ')})`);
  }
  const start = replaceTime(parseTs(args.start), { minute: 0, second: 0, microsecond: 0 });
  const end = addTimedelta(start, args.horizon_days, 0);
  const slots = args.cadences.flatMap((cadence) => cadenceSlots(cadence, start, end, args.horizon_days));
  return slots.sort(compareSlots);
}

/** The earliest open slot after both `now` and the blocked slot; null when no capacity is left. */
export function adaptiveReschedule(
  blockedAt: string | PyDateTime,
  openSlots: Iterable<string | PyDateTime>,
  now: PyDateTime,
): string | null {
  const blocked = parseTs(blockedAt);
  const floor = compareDateTimes(now, blocked) > 0 ? now : blocked;
  const candidates: PyDateTime[] = [];
  for (const slot of openSlots) {
    const moment = parseTs(slot);
    if (compareDateTimes(moment, floor) > 0) candidates.push(moment);
  }
  candidates.sort(compareDateTimes);
  const first = candidates[0];
  return first === undefined ? null : isoformat(first);
}

// -- content supply forecaster --------------------------------------------------------

/** One approved master typically feeds this many channel cuts. */
export const DERIVATIVES_PER_MASTER = 3;

export interface ForecastInput {
  readonly horizon_days: number;
  readonly cadences: readonly ScheduleCadence[];
  readonly brands?: number;
  readonly campaigns?: number;
  readonly approval_batch_size?: number;
  readonly research_refresh_days?: number;
  /** kind -> observed cost per item. */
  readonly unit_costs?: Readonly<Record<string, number>>;
}

export interface SupplyForecast {
  readonly horizon_days: number;
  readonly items_by_kind: Readonly<Record<string, number>>;
  readonly by_category: Readonly<Record<string, number>>;
  readonly required_master_assets: number;
  readonly channel_derivatives: number;
  readonly approval_batches: number;
  readonly research_refreshes: number;
  readonly estimated_generation_jobs: number;
  readonly estimated_cost_by_kind: Readonly<Record<string, number | 'UNKNOWN'>>;
  readonly estimated_total_cost: number | 'UNKNOWN';
  readonly cost_basis: 'OBSERVED_UNIT_COSTS' | 'UNKNOWN_WHERE_UNOBSERVED';
}

// A Monday: the slot count is independent of the calendar anchor.
const FORECAST_ANCHOR: PyDateTime = makeDateTime({ year: 2026, month: 1, day: 5, utcoffset_us: 0 });

function itemsByKind(spec: ForecastInput): Map<string, number> {
  const perKind = new Map<string, number>();
  for (const cadence of spec.cadences) {
    const slots = planHorizon({ start: FORECAST_ANCHOR, horizon_days: spec.horizon_days, cadences: [cadence] });
    perKind.set(cadence.kind, (perKind.get(cadence.kind) ?? 0) + slots.length * (spec.brands ?? 1));
  }
  return perKind;
}

function costs(perKind: Map<string, number>, unitCosts: Readonly<Record<string, number>>) {
  const byKind: Record<string, number | 'UNKNOWN'> = {};
  let total: number | 'UNKNOWN' = 0;
  for (const kind of [...perKind.keys()].sort(compareCodePoints)) {
    const unit = Object.hasOwn(unitCosts, kind) ? unitCosts[kind] : undefined;
    if (unit === undefined) {
      byKind[kind] = UNKNOWN;
      total = UNKNOWN;
    } else {
      const cost = roundTo(unit * (perKind.get(kind) as number), 4);
      byKind[kind] = cost;
      if (total !== UNKNOWN) total += cost;
    }
  }
  return { byKind, total };
}

function categories(count: (kinds: readonly string[]) => number): Record<string, number> {
  return {
    articles: count(['article']),
    emails: count(['email', 'newsletter']),
    posts: count(['social_post', 'thread', 'carousel', 'story']),
    videos: count(['short_video', 'reel', 'video_script']),
    graphics: count(['carousel', 'story', 'paid_creative']),
    landing_pages: count(['landing_section']),
  };
}

/**
 * Required production volume from measurable inputs. A cost is computed only
 * from `unit_costs` the caller supplies as observed evidence: a kind without
 * one is UNKNOWN, and so is the total, rather than an invented price.
 */
export function forecastSupply(spec: ForecastInput): SupplyForecast {
  const perKind = itemsByKind(spec);
  const totalItems = [...perKind.values()].reduce((a, b) => a + b, 0);
  const masters = totalItems ? Math.ceil(totalItems / DERIVATIVES_PER_MASTER) : 0;
  const { byKind, total } = costs(perKind, spec.unit_costs ?? {});
  const derivatives = Math.max(totalItems - masters, 0);
  const sortedKinds = [...perKind.keys()].sort(compareCodePoints);
  return {
    horizon_days: spec.horizon_days,
    items_by_kind: Object.fromEntries(sortedKinds.map((kind) => [kind, perKind.get(kind) as number])),
    by_category: categories((kinds) => kinds.reduce((sum, kind) => sum + (perKind.get(kind) ?? 0), 0)),
    required_master_assets: masters,
    channel_derivatives: derivatives,
    approval_batches: totalItems ? Math.ceil(totalItems / Math.max(spec.approval_batch_size ?? 10, 1)) : 0,
    research_refreshes: Math.ceil(spec.horizon_days / Math.max(spec.research_refresh_days ?? 30, 1)) * (spec.brands ?? 1),
    estimated_generation_jobs: masters + derivatives,
    estimated_cost_by_kind: byKind,
    estimated_total_cost: total === UNKNOWN ? UNKNOWN : roundTo(total, 4),
    cost_basis: total === UNKNOWN ? 'UNKNOWN_WHERE_UNOBSERVED' : 'OBSERVED_UNIT_COSTS',
  };
}
