/**
 * Twin of `agency/project_os/router.py`: cost x quality routing over provider
 * capability profiles.
 *
 * Priority, cheapest-to-justify first: reuse an approved asset, a
 * deterministic transform, local/free execution, a cheap draft, evaluate,
 * premium final (only when justified), post-process before regenerate.
 *
 * The objective is COST_PER_APPROVED_ARTIFACT = cost per unit / acceptance
 * rate, so a cheap model that is usually rejected is expensive. Both inputs
 * must be OBSERVED with an evidence ref; otherwise the objective is UNKNOWN
 * and the router says so instead of ranking on a guess.
 *
 * Routing is advice. It never activates a provider: a DISABLED profile is
 * never chosen, and running a LIVE cloud provider still passes its own gates.
 */
import type { ProviderCapabilityProfile } from '@amc/shared';
import { compareCodePoints } from '@amc/kernel';
import { roundTo, truthy } from './pytext';
import { UNKNOWN } from './vocabulary';

type Metric = ProviderCapabilityProfile['cost_per_unit'];

export interface RouteRequest {
  readonly task: string;
  readonly output_format: string;
  readonly reusable_approved_asset_ref?: string | null;
  readonly deterministic_transform?: boolean;
  readonly premium_justification?: string | null;
  readonly max_failure_rate?: number;
}

export interface RouteResult {
  readonly tier: string | null;
  readonly profile_id: string | null;
  readonly objective: number | 'UNKNOWN';
  readonly rationale: string;
  readonly asset_ref?: string;
  readonly provider?: string;
  readonly model?: string;
  readonly objective_name?: string;
  readonly then?: string[];
  readonly rejected?: Record<string, string>;
}

function observed(metric: Metric): number | null {
  const usable = metric.status === 'OBSERVED' && metric.value !== null && metric.value !== undefined && truthy(metric.evidence_ref);
  return usable ? Number(metric.value) : null;
}

export function costPerApprovedArtifact(profile: ProviderCapabilityProfile): number | 'UNKNOWN' {
  const cost = observed(profile.cost_per_unit);
  const acceptance = observed(profile.acceptance_rate);
  if (cost === null || acceptance === null || acceptance <= 0) return UNKNOWN;
  return roundTo(cost / acceptance, 6);
}

function ineligibility(profile: ProviderCapabilityProfile, request: RouteRequest): string | null {
  if (profile.mode === 'DISABLED') return 'PROVIDER_DISABLED';
  if (profile.task !== request.task) return 'TASK_MISMATCH';
  if (!profile.formats.includes(request.output_format)) return 'FORMAT_UNSUPPORTED';
  const failure = observed(profile.failure_rate);
  if (failure !== null && failure > (request.max_failure_rate ?? 0.25)) return 'FAILURE_RATE_ABOVE_LIMIT';
  return null;
}

/** Known objectives first, cheapest first; unknown ones last, by id. */
function rank(items: readonly ProviderCapabilityProfile[]): ProviderCapabilityProfile[] {
  const priced = items.map((profile) => ({ profile, cost: costPerApprovedArtifact(profile) }));
  const known = priced.filter((p) => p.cost !== UNKNOWN).sort((a, b) => (a.cost as number) - (b.cost as number) || compareCodePoints(a.profile.profile_id, b.profile.profile_id));
  const unknown = priced.filter((p) => p.cost === UNKNOWN).sort((a, b) => compareCodePoints(a.profile.profile_id, b.profile.profile_id));
  return [...known, ...unknown].map((p) => p.profile);
}

function rationale(tier: string): string {
  if (tier === 'local_free_execution') return 'local execution preferred';
  if (tier === 'premium_final') return 'premium tier requires a recorded justification';
  return 'cheapest observed cost per approved artifact; unknown costs ranked last';
}

export function route(request: RouteRequest, profiles: Iterable<ProviderCapabilityProfile>): RouteResult {
  if (request.reusable_approved_asset_ref) {
    return { tier: 'reuse_approved_asset', asset_ref: request.reusable_approved_asset_ref, profile_id: null, objective: 0, rationale: 'an approved asset already satisfies the request' };
  }
  if (request.deterministic_transform) {
    return { tier: 'deterministic_transform', profile_id: null, objective: 0, rationale: 'a deterministic transform (crop, resize, template) is sufficient' };
  }
  const rejected = new Map<string, string>();
  const considered: ProviderCapabilityProfile[] = [];
  for (const profile of profiles) {
    const reason = ineligibility(profile, request);
    if (reason) rejected.set(profile.profile_id, reason);
    else considered.push(profile);
  }
  const local = considered.filter((p) => p.locality === 'local');
  const cloud = considered.filter((p) => p.locality === 'cloud');
  const rejectedRecord = Object.fromEntries(rejected);
  if (local.length === 0 && cloud.length === 0) {
    return { tier: null, profile_id: null, objective: UNKNOWN, rejected: rejectedRecord, rationale: 'no eligible provider profile; nothing is routed' };
  }
  const choice = (local.length > 0 ? rank(local) : rank(cloud))[0] as ProviderCapabilityProfile;
  const tier = local.length > 0 ? 'local_free_execution' : truthy(request.premium_justification) ? 'premium_final' : 'cheap_draft';
  return {
    tier,
    profile_id: choice.profile_id,
    provider: choice.provider,
    model: choice.model,
    objective: costPerApprovedArtifact(choice),
    objective_name: 'COST_PER_APPROVED_ARTIFACT',
    then: tier === 'premium_final' ? ['evaluate'] : ['evaluate', 'post_process'],
    rejected: rejectedRecord,
    rationale: rationale(tier),
  };
}
