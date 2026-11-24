/**
 * Twin of `agency/project_os/paid_media.py`. Planning only: no account, no
 * budget, no mutation.
 *
 * The future mutation sequence is modelled so a plan always shows how far it
 * is from execution. Only PLAN runs; every later step reports NOT_AVAILABLE
 * (no reviewed provider adapter), or, for budget authorization, points at the
 * spend-authorization ledger, which records requests but never executes them.
 * `spend_authority_granted` and `execution_available` are the literal `false`
 * in every plan: planner output never grants spend authority.
 */
import { PyTypeError, PyValueError } from './errors';
import { canonicalSha256, type PyJson } from './json';
import { truthy } from './pytext';

export const MUTATION_SEQUENCE = [
  'PLAN',
  'ACCOUNT_RESOLUTION',
  'EXACT_MUTATION_PREVIEW',
  'BUDGET_AUTHORIZATION',
  'HUMAN_APPROVAL',
  'IDEMPOTENT_PROVIDER_WRITE',
  'READBACK',
  'RECONCILIATION',
  'RECEIPT',
  'ANALYTICS',
] as const;

// Planning defaults are labelled as such; they are not performance claims.
export const DEFAULT_FREQUENCY_CAP_PER_WEEK = 3;
export const CREATIVE_FATIGUE_REVIEW_DAYS = 14;

const SEARCH_CHANNELS = ['search', 'google_search', 'bing'];

export interface PaidMediaBrief {
  readonly objective: string;
  readonly offer: string;
  readonly audiences: readonly string[];
  readonly channels: readonly string[];
  readonly budget_minor: number;
  readonly currency: string;
  readonly flight_days: number;
  readonly creative_refs: readonly string[];
  readonly landing_page_ref?: string | null;
  readonly keywords?: readonly string[];
}

interface AdGroup {
  readonly ad_group_id: string;
  readonly channel: string;
  readonly audience: string;
  readonly keywords_or_context: string[];
}

function stepStatus(step: string): string {
  if (step === 'PLAN') return 'COMPLETE';
  if (step === 'BUDGET_AUTHORIZATION') return 'REQUEST_ONLY_VIA_SPEND_LEDGER';
  if (step === 'HUMAN_APPROVAL') return 'REQUIRED';
  return 'NOT_AVAILABLE';
}

function adGroups(brief: PaidMediaBrief): AdGroup[] {
  return brief.channels.flatMap((channel) =>
    brief.audiences.map((audience, index) => ({
      ad_group_id: `ag-${channel}-${index}`,
      channel,
      audience,
      keywords_or_context: SEARCH_CHANNELS.includes(channel) ? [...(brief.keywords ?? [])] : [],
    })),
  );
}

export interface CampaignPlan {
  readonly objective: string;
  readonly offer: string;
  readonly campaign_architecture: { readonly campaign: string; readonly ad_groups: readonly AdGroup[] };
  readonly creative_matrix: readonly { readonly ad_group_id: string; readonly creative_ref: string; readonly variant: string }[];
  readonly landing_page_ref: string | null;
  readonly tracking: { readonly utm_template: string; readonly conversion_event: string };
  readonly budget: Readonly<Record<string, number | string>>;
  readonly frequency: { readonly cap_per_week: number; readonly basis: 'PLANNING_DEFAULT' };
  readonly retargeting: { readonly enabled: false; readonly reason: string };
  readonly experiments: readonly { readonly experiment: string; readonly arms: readonly string[]; readonly metric: string }[];
  readonly creative_fatigue: { readonly review_every_days: number; readonly basis: 'PLANNING_DEFAULT' };
  readonly mutation_sequence: readonly { readonly step: string; readonly status: string }[];
  readonly paid_media_mode: string;
  readonly spend_authority_granted: false;
  readonly execution_available: false;
  readonly plan_hash: string;
}

function budget(brief: PaidMediaBrief, groupCount: number): Record<string, number | string> {
  const daily = Math.floor(brief.budget_minor / brief.flight_days);
  return {
    total_minor: brief.budget_minor,
    currency: brief.currency.toUpperCase(),
    flight_days: brief.flight_days,
    daily_minor: daily,
    per_ad_group_daily_minor: Math.floor(daily / Math.max(groupCount, 1)),
    pacing: 'EVEN',
  };
}

export function planCampaign(brief: PaidMediaBrief, paidMediaMode = 'disabled'): CampaignPlan {
  if (brief.budget_minor < 0 || brief.flight_days <= 0) {
    throw new PyValueError('budget must be non-negative and the flight at least one day');
  }
  if (brief.audiences.length === 0 || brief.channels.length === 0) {
    throw new PyValueError('a paid plan needs at least one audience and one channel');
  }
  const groups = adGroups(brief);
  const body = {
    objective: brief.objective,
    offer: brief.offer,
    campaign_architecture: { campaign: `${brief.objective}:${brief.offer}`, ad_groups: groups },
    creative_matrix: groups.flatMap((g) =>
      brief.creative_refs.map((creative) => ({ ad_group_id: g.ad_group_id, creative_ref: creative, variant: `${g.ad_group_id}::${creative}` })),
    ),
    landing_page_ref: brief.landing_page_ref ?? null,
    tracking: {
      utm_template: 'utm_source={channel}&utm_medium=paid&utm_campaign={campaign}&utm_content={variant}',
      conversion_event: brief.objective,
    },
    budget: budget(brief, groups.length),
    frequency: { cap_per_week: DEFAULT_FREQUENCY_CAP_PER_WEEK, basis: 'PLANNING_DEFAULT' as const },
    retargeting: { enabled: false as const, reason: 'requires consented first-party audiences' },
    experiments:
      brief.creative_refs.length >= 2
        ? [{ experiment: 'creative_split', arms: brief.creative_refs.slice(0, 2), metric: brief.objective }]
        : [],
    creative_fatigue: { review_every_days: CREATIVE_FATIGUE_REVIEW_DAYS, basis: 'PLANNING_DEFAULT' as const },
    mutation_sequence: MUTATION_SEQUENCE.map((step) => ({ step, status: stepStatus(step) })),
    paid_media_mode: paidMediaMode,
    spend_authority_granted: false as const,
    execution_available: false as const,
  };
  return { ...body, plan_hash: canonicalSha256(body as unknown as PyJson) };
}

export interface DeliveryRow {
  readonly ad_group_id?: string | null;
  readonly impressions?: number | null;
  readonly clicks?: number | null;
  readonly frequency?: number | null;
  readonly baseline_ctr?: number | null;
}

function fatigued(row: DeliveryRow): boolean {
  const { impressions, clicks } = row;
  if (!impressions || clicks === null || clicks === undefined) return false;
  const ctr = clicks / impressions;
  if (!truthy(row.frequency) || (row.frequency as number) <= DEFAULT_FREQUENCY_CAP_PER_WEEK) return false;
  if ('baseline_ctr' in row && row.baseline_ctr === null) {
    throw new PyTypeError("'<' not supported between instances of 'float' and 'NoneType'");
  }
  return ctr < (row.baseline_ctr ?? ctr);
}

export interface DeliveryAnalysis {
  readonly status: 'NO_OBSERVED_DATA' | 'OBSERVED';
  readonly rows?: number;
  readonly recommendations: { readonly ad_group_id: string | null; readonly action: string; readonly reason: string }[];
}

/** Recommendations from *observed* delivery rows only; no row, no claim. */
export function analyzeDelivery(observations: Iterable<DeliveryRow>): DeliveryAnalysis {
  const rows = [...observations];
  if (rows.length === 0) return { status: 'NO_OBSERVED_DATA', recommendations: [] };
  const recommendations = rows.filter(fatigued).map((row) => ({
    ad_group_id: row.ad_group_id ?? null,
    action: 'REFRESH_CREATIVE',
    reason: 'fatigue: CTR below baseline at high frequency',
  }));
  return { status: 'OBSERVED', rows: rows.length, recommendations };
}
