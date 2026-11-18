/**
 * Twin of `agency/project_os/reliability.py`: reliability contracts for the
 * Project OS services.
 *
 * Same rule as `docs/production-slo-contract.md`: a numeric objective exists
 * only when an operator configures `AMC_SLO_<SERVICE>_<METRIC>` after
 * measuring a baseline; otherwise it reads `GAP_NO_BASELINE`. The mechanisms
 * (bounded retry, dead letter, reconciliation) are reported with the
 * constant the code actually enforces. The environment is passed in, so this
 * module reads nothing.
 */
import { pyFloat, pyStrip } from './pytext';

export const GAP = 'GAP_NO_BASELINE';

export interface ServiceSpec {
  readonly metrics: readonly string[];
  readonly telemetry: string;
}

export const SERVICES: Readonly<Record<string, ServiceSpec>> = {
  project_api: { metrics: ['availability', 'p95_latency_ms', 'p99_latency_ms', 'failure_rate'], telemetry: 'HTTP request logs' },
  scheduler: {
    metrics: ['scheduler_delay_seconds', 'queue_age_seconds', 'throughput_per_minute'],
    telemetry: 'scheduled_jobs.due_at vs updated_at',
  },
  publication_worker: {
    metrics: ['publication_delay_seconds', 'failure_rate', 'recovery_time_seconds'],
    telemetry: 'publication_attempts state timestamps',
  },
  knowledge_pipeline: { metrics: ['throughput_per_minute', 'failure_rate'], telemetry: 'knowledge_items stage/status' },
  memory: { metrics: ['p95_latency_ms'], telemetry: 'memory resolve request logs' },
  portfolio: { metrics: ['p95_latency_ms'], telemetry: 'portfolio request logs' },
};

export interface Mechanism {
  readonly status: string;
  readonly limit?: number;
  readonly source?: string;
}

export const MECHANISMS: Readonly<Record<string, Mechanism>> = {
  bounded_retry: { status: 'IMPLEMENTED', limit: 3, source: 'reliability.OutboxMessage.attempts <= 3' },
  dead_letter: { status: 'IMPLEMENTED', source: 'outbox status FAILED + scheduled_jobs status FAILED (kept, never deleted)' },
  duplicate_delivery_prevention: { status: 'IMPLEMENTED', source: 'compare-and-set job claim + provider idempotency key' },
  reconciliation: { status: 'IMPLEMENTED', source: 'publication UNCERTAIN → provider.verify(idempotency_key)' },
  object_reconciliation: { status: 'IMPLEMENTED', source: 'storage_objects PRESENT/MISSING reconcile' },
  circuit_breaker: { status: 'NOT_IMPLEMENTED', source: 'no live provider exists to break against' },
  backup_policy: { status: 'EXTERNAL_ACTIVATION_REQUIRED', source: 'PostgreSQL provider backups (Supabase)' },
  restore_validation: { status: GAP, source: 'requires a restore drill against the production provider' },
  rto: { status: GAP },
  rpo: { status: GAP },
  resource_limits: { status: 'IMPLEMENTED', source: 'per-tenant run limits, per-run token budget, request size caps' },
};

export type Environment = Readonly<Record<string, string | undefined>>;

function configured(env: Environment, service: string, metric: string): number | string {
  const raw = pyStrip(env[`AMC_SLO_${service.toUpperCase()}_${metric.toUpperCase()}`] || '');
  if (!raw) return GAP;
  return pyFloat(raw) ?? GAP;
}

export interface ReliabilityContracts {
  readonly services: Readonly<Record<string, { readonly objectives: Readonly<Record<string, number | string>>; readonly telemetry_source: string }>>;
  readonly mechanisms: Readonly<Record<string, Mechanism>>;
  readonly error_budget_policy: string;
}

export function reliabilityContracts(env: Environment): ReliabilityContracts {
  return {
    services: Object.fromEntries(
      Object.entries(SERVICES).map(([name, spec]) => [
        name,
        {
          objectives: Object.fromEntries(spec.metrics.map((metric) => [metric, configured(env, name, metric)])),
          telemetry_source: spec.telemetry,
        },
      ]),
    ),
    mechanisms: MECHANISMS,
    error_budget_policy: 'derived from configured availability objectives only; none without a baseline',
  };
}
