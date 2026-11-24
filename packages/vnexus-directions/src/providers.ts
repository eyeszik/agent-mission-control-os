/**
 * Route registry for the direction pipeline (`directions/providers.py`): what may generate, critique or research,
 * and on what terms. Every hosted route stays `adapter_implemented: false` and DISABLED; a disabled route is never
 * quoted, called or silently replaced by another model. Spend is governed by `AMC_VNEXUS_SPEND_MODE` (zero by
 * default): zero mode refuses unknown or non-zero prices and offers `manual.handoff`, which is offered, never run.
 *
 * Python reads `os.environ`, `media_fabric.mock_enabled()` and `probe_browser()`. The twin takes those facts as a
 * typed `RouteEnv` instead, so it has no ambient state.
 */
import { pyStrip } from '@amc/vnexus-brandbook';

export const REGISTRY_VERSION = 'amc-vnexus-direction-routes/v1';

export const TASKS = ['TEXT_TO_IMAGE', 'CONCEPT_COMPOSE', 'MANUAL_HANDOFF', 'IMAGE_CRITIQUE', 'LOCAL_MEASURE', 'VECTOR_RECONSTRUCT', 'RESEARCH',
  'TEXT', 'SIMULATED'] as const;
export type Task = (typeof TASKS)[number];
export type Health = 'AVAILABLE' | 'UNAVAILABLE' | 'DISABLED';

export interface RouteSpec {
  readonly route_id: string;
  readonly provider: string;
  readonly model: string | null;
  readonly model_pin: string | null;
  readonly tasks: readonly Task[];
  readonly formats_in: readonly string[];
  readonly formats_out: readonly string[];
  readonly credential_ref: string | null;
  readonly quota_scope: string;
  readonly quota_reset: string | null;
  readonly price_per_job_minor: number | null;
  readonly currency: string;
  readonly pricing_source: string | null;
  readonly pricing_checked_at: string | null;
  readonly data_policy: string;
  readonly max_requests_per_minute: number;
  readonly max_payload_bytes: number;
  readonly timeout_s: number;
  readonly reconciliation: string;
  readonly fallback_routes: readonly string[];
  readonly adapter_implemented: boolean;
  readonly note: string;
}

type RouteInput = Pick<RouteSpec, 'route_id' | 'provider' | 'tasks' | 'adapter_implemented'> & Partial<RouteSpec>;

function route(i: RouteInput): RouteSpec {
  return { route_id: i.route_id, provider: i.provider, model: i.model ?? null, model_pin: i.model_pin ?? null, tasks: i.tasks,
    formats_in: i.formats_in ?? [], formats_out: i.formats_out ?? [], credential_ref: i.credential_ref ?? null,
    quota_scope: i.quota_scope ?? 'UNVERIFIED', quota_reset: i.quota_reset ?? null, price_per_job_minor: i.price_per_job_minor ?? null,
    currency: i.currency ?? 'USD', pricing_source: i.pricing_source ?? null, pricing_checked_at: i.pricing_checked_at ?? null,
    data_policy: i.data_policy ?? 'UNVERIFIED', max_requests_per_minute: i.max_requests_per_minute ?? 0,
    max_payload_bytes: i.max_payload_bytes ?? 0, timeout_s: i.timeout_s ?? 0, reconciliation: i.reconciliation ?? 'none',
    fallback_routes: i.fallback_routes ?? [], adapter_implemented: i.adapter_implemented, note: i.note ?? '' };
}

export const UNVERIFIED_HOSTED: readonly string[] = ['ADAPTER_NOT_IMPLEMENTED',
  'ENTITLEMENT_UNVERIFIED: capabilities, quota, price, terms and data handling not rechecked against official sources for this account'];

export const ROUTES: readonly RouteSpec[] = [
  route({ route_id: 'local.foundry_compose', provider: 'local', model: 'foundry.compose', model_pin: 'amc-foundry-compose', tasks: ['CONCEPT_COMPOSE'],
    formats_out: ['image/svg+xml'], quota_scope: 'local compute', price_per_job_minor: 0, pricing_source: 'local renderer: no charge',
    data_policy: 'ELIGIBLE', max_requests_per_minute: 30, max_payload_bytes: 2_000_000, timeout_s: 10,
    reconciliation: 'media job idempotency key per slot', fallback_routes: ['manual.handoff'], adapter_implemented: true,
    note: 'deterministic vector mark concepts composed from the approved genome; logo and icon roles only' }),
  route({ route_id: 'manual.handoff', provider: 'operator', tasks: ['MANUAL_HANDOFF'], formats_in: ['image/png', 'image/svg+xml'],
    formats_out: ['application/json'], quota_scope: 'none', price_per_job_minor: 0, pricing_source: 'no provider call is made by this server',
    data_policy: 'ELIGIBLE', max_payload_bytes: 12_000_000, reconciliation: 'import idempotency key', adapter_implemented: true,
    note: 'prompt package export and result import; imported provenance stays USER_REPORTED (unverified)' }),
  route({ route_id: 'local.measure', provider: 'local', model: 'vnexus.directions.review', model_pin: 'amc-vnexus-review-rubric/1.0.0',
    tasks: ['LOCAL_MEASURE'], formats_in: ['image/png', 'image/svg+xml'], price_per_job_minor: 0, pricing_source: 'local compute',
    data_policy: 'ELIGIBLE', adapter_implemented: true,
    note: 'deterministic measurements on stored bytes (palette, contrast, small-size, geometry); never creative scores' }),
  route({ route_id: 'local.trace', provider: 'local', model: 'avic.optimize', model_pin: 'avic-h1-region-split', tasks: ['VECTOR_RECONSTRUCT'],
    formats_in: ['image/png'], formats_out: ['image/svg+xml'], price_per_job_minor: 0, pricing_source: 'local compute', data_policy: 'ELIGIBLE',
    adapter_implemented: true, note: 'controlled region-split trace snapped to the approved palette; fidelity is measured in local Chromium' }),
  route({ route_id: 'cloudflare.workers_ai.text_to_image', provider: 'cloudflare', tasks: ['TEXT_TO_IMAGE'], formats_out: ['image/png'],
    credential_ref: 'CLOUDFLARE_API_TOKEN', fallback_routes: ['manual.handoff'], adapter_implemented: false,
    note: 'proposed concept route; DISABLED until a verified adapter and entitlement exist' }),
  route({ route_id: 'gemini.image_critique', provider: 'google', tasks: ['IMAGE_CRITIQUE'], formats_in: ['image/png'], credential_ref: 'GEMINI_API_KEY',
    adapter_implemented: false, note: 'the model router has no image-input path; rendered-image critique needs a verified adapter' }),
  route({ route_id: 'exa.research', provider: 'exa', tasks: ['RESEARCH'], credential_ref: 'EXA_API_KEY', adapter_implemented: false,
    note: 'one of Exa or Tavily, not both, once workload justifies it' }),
  route({ route_id: 'tavily.research', provider: 'tavily', tasks: ['RESEARCH'], credential_ref: 'TAVILY_API_KEY', adapter_implemented: false,
    note: 'one of Exa or Tavily, not both, once workload justifies it' }),
  route({ route_id: 'groq.text', provider: 'groq', tasks: ['TEXT'], credential_ref: 'GROQ_API_KEY', adapter_implemented: false,
    note: 'optional text/transcription route; only if measured workload justifies it' }),
  route({ route_id: 'mock.simulated', provider: 'test', tasks: ['SIMULATED'], formats_out: ['image/svg+xml'], price_per_job_minor: 0,
    pricing_source: 'test stand-in', data_policy: 'ELIGIBLE', adapter_implemented: true,
    note: 'AMC_VNEXUS_MOCK_PROVIDERS=1 outside production only; output is SIMULATED and never selectable' }),
];

/** The ambient facts Python reads: env vars, the mock switch and the Chromium probe. */
export interface RouteEnv {
  /** Raw `AMC_VNEXUS_SPEND_MODE` (undefined when unset). */
  readonly spend_mode?: string;
  /** Names of credential env vars that are set to a non-empty value. */
  readonly credentials_present?: readonly string[];
  readonly mock_enabled?: boolean;
  readonly browser?: { readonly available: boolean; readonly blockers?: readonly string[] };
}

export class UnknownRoute extends Error {
  override name = 'LookupError';
  constructor(routeId: string) {
    super(`unknown route ${routeId}`);
  }
}

export function spendMode(env: RouteEnv): 'zero' | 'approval_required' {
  const mode = pyStrip((env.spend_mode ?? '') || 'zero').toLowerCase();
  return mode === 'zero' || mode === 'approval_required' ? mode : 'zero';
}

export function getRoute(routeId: string): RouteSpec {
  const found = ROUTES.find((r) => r.route_id === routeId);
  if (found === undefined) throw new UnknownRoute(routeId);
  return found;
}

function hasCredential(r: RouteSpec, env: RouteEnv): boolean {
  return r.credential_ref !== null && (env.credentials_present ?? []).includes(r.credential_ref);
}

export function health(r: RouteSpec, env: RouteEnv = {}): [Health, string[]] {
  if (!r.adapter_implemented) {
    const blockers = [...UNVERIFIED_HOSTED];
    if (r.credential_ref && !hasCredential(r, env)) blockers.push(`CREDENTIAL_NOT_CONFIGURED: ${r.credential_ref}`);
    return ['DISABLED', blockers];
  }
  if (r.route_id === 'mock.simulated') return env.mock_enabled ? ['AVAILABLE', []] : ['DISABLED', ['MOCK_PROVIDERS_DISABLED']];
  if (r.route_id === 'local.trace' && !(env.browser?.available ?? false)) {
    // Tracing still runs; fidelity cannot be measured, so reconstructions stay NOT_VERIFIED.
    return ['AVAILABLE', ['FIDELITY_NOT_MEASURABLE: ' + (env.browser?.blockers ?? []).join(', ')]];
  }
  return ['AVAILABLE', []];
}

export interface RouteDecision {
  readonly route_id: string;
  readonly allowed: boolean;
  readonly health: Health;
  readonly blockers: readonly string[];
  readonly estimate_minor: number | null;
  readonly spend_mode: string;
  readonly offer: string | null;
  readonly note: string;
}

function priceReason(r: RouteSpec, mode: string, budgetMinor: number): string | null {
  const price = r.price_per_job_minor;
  if (price === null) return 'PRICE_UNKNOWN: a route without a verified price is never run' + (mode === 'zero' ? ' in zero-spend mode' : '');
  if (price > 0 && mode === 'zero') return `ZERO_SPEND: ${r.route_id} costs ${price} minor units per job`;
  if (price > budgetMinor && price > 0) return `BUDGET_EXCEEDED: ${price} > ${budgetMinor}`;
  return null;
}

/** May this pinned route run this task now? Never picks a different route; offers manual handoff instead. */
export function decide(routeId: string, task: Task, budgetMinor: number, env: RouteEnv = {}): RouteDecision {
  return decideRoute(getRoute(routeId), task, budgetMinor, env);
}

/** `decide` for an explicit route spec (the registry's own routes never carry a positive price). */
export function decideRoute(r: RouteSpec, task: Task, budgetMinor: number, env: RouteEnv = {}): RouteDecision {
  const routeId = r.route_id;
  const mode = spendMode(env);
  const [state, blockers] = health(r, env);
  const reasons = blockers.filter((b) => !b.startsWith('FIDELITY_NOT_MEASURABLE'));
  if (!r.tasks.includes(task)) reasons.push(`TASK_UNSUPPORTED: ${routeId} does not perform ${task}`);
  const price = priceReason(r, mode, budgetMinor);
  if (price !== null) reasons.push(price);
  const allowed = state === 'AVAILABLE' && reasons.length === 0;
  const offer = !allowed && r.fallback_routes.includes('manual.handoff') ? 'manual.handoff' : null;
  return { route_id: routeId, allowed, health: state, blockers: reasons, estimate_minor: r.price_per_job_minor, spend_mode: mode, offer,
    note: allowed ? '' : 'nothing was called; no other model was substituted' };
}

export const REGISTRY_NOTES: readonly string[] = ['Connection managers (e.g. Nango) manage connections, not generation rights.',
  'A chat subscription does not include arbitrary API usage.', 'Free-credit directories are discovery catalogs, not pooled balances.',
  'No browser automation or quota circumvention is implemented.'];

export function describeRoutes(env: RouteEnv = {}): { registry_version: string; spend_mode: string; routes: unknown[]; notes: readonly string[] } {
  const routes = ROUTES.map((r) => {
    const [state, blockers] = health(r, env);
    return { ...r, health: state, blockers, credential_present: hasCredential(r, env) };
  });
  return { registry_version: REGISTRY_VERSION, spend_mode: spendMode(env), routes, notes: REGISTRY_NOTES };
}
