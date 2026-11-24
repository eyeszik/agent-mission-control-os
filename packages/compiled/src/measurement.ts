/**
 * Twin of `agency/compiled/measurement.py` (T22): measurement and process
 * mining over actual run telemetry. Every metric without evidence is
 * `NOT_MEASURED`: never estimated, never a marketing multiplier.
 *
 * Timestamps go through `isotime.ts` (a strict subset of Python's
 * `datetime.fromisoformat`); an unsupported spelling reads as unparseable,
 * i.e. NOT_MEASURED, which is the conservative direction.
 */
import { PyFloat, pyStr } from '@amc/kernel';
import { CompiledTypeError, CompiledValueError } from './errors';
import { parseIsoDateTime, type ParsedDateTime } from './isotime';
import { compareScalars, pyRound, pyTruthy } from './python';

export const NOT_MEASURED = 'NOT_MEASURED';

/** Live LangGraph stage → the N1 artifact the compiled plan calls it. */
export const STAGE_ARTIFACT: ReadonlyMap<string, string> = new Map([
  ['brand_strategy', 'positioning_statement'],
  ['creative_concepting', 'creative_concept'],
  ['copywriting', 'copy_variant'],
  ['design_brief', 'design_brief'],
  ['campaign_assembly', 'campaign_package'],
  ['brand_safety_qa', 'qa_report'],
  ['delivery', 'release_record'],
]);

/** A telemetry row (`persistence/events.py`): any field may be absent or null. */
export interface EventRow {
  readonly sequence?: number | null;
  readonly event_type?: string | null;
  readonly node_id?: unknown;
  readonly started_at?: unknown;
  readonly completed_at?: unknown;
  readonly observed_at?: unknown;
  readonly safe_payload?: Readonly<Record<string, unknown>> | null;
}

function parseTs(value: unknown): ParsedDateTime | null {
  if (!pyTruthy(value)) return null;
  try {
    return parseIsoDateTime(pyStr(value).replaceAll('Z', '+00:00'));
  } catch (error) {
    if (error instanceof CompiledValueError) return null;
    throw error;
  }
}

function microsDiff(a: ParsedDateTime, b: ParsedDateTime): bigint {
  if ((a.offset === null) !== (b.offset === null)) {
    throw new CompiledTypeError("can't subtract offset-naive and offset-aware datetimes");
  }
  return b.local - (b.offset ?? 0n) - (a.local - (a.offset ?? 0n));
}

const SAFE = BigInt(Number.MAX_SAFE_INTEGER);

/** `(end - start).total_seconds()`, or null when either side is unparseable. */
export function secondsBetween(start: unknown, end: unknown): PyFloat | null {
  const a = parseTs(start);
  const b = parseTs(end);
  if (a === null || b === null) return null;
  const micros = microsDiff(a, b);
  if (micros > SAFE || micros < -SAFE) throw new CompiledValueError('time span too large for the twin');
  return new PyFloat(Number(micros) / 1e6);
}

export interface Conformance {
  readonly fitness: PyFloat | typeof NOT_MEASURED;
  readonly unplanned: readonly string[];
  readonly skipped: readonly string[];
  readonly out_of_order: readonly string[];
}

/** Plan-vs-actual routing: fitness = observed steps that were planned and in planned order. */
export function conformance(plannedOrder: Iterable<string>, observedOrder: Iterable<string>): Conformance {
  const plan = [...plannedOrder];
  const observed = [...observedOrder];
  if (!observed.length) return { fitness: NOT_MEASURED, unplanned: [], skipped: [], out_of_order: [] };
  const position = new Map(plan.map((p, i) => [p, i]));
  const inPlan = observed.filter((o) => position.has(o));
  const outOfOrder: string[] = [];
  for (let i = 1; i < inPlan.length; i += 1) {
    if ((position.get(inPlan[i] as string) ?? 0) < (position.get(inPlan[i - 1] as string) ?? 0)) outOfOrder.push(inPlan[i] as string);
  }
  const fitting = inPlan.length - outOfOrder.length;
  return {
    fitness: new PyFloat(pyRound(fitting / observed.length, 6)),
    unplanned: observed.filter((o) => !position.has(o)),
    skipped: plan.filter((p) => !observed.includes(p)),
    out_of_order: outOfOrder,
  };
}

type Latency = PyFloat | typeof NOT_MEASURED;

export interface RunMetrics {
  readonly events: number;
  readonly node_durations_seconds: ReadonlyMap<string, PyFloat> | typeof NOT_MEASURED;
  readonly node_errors: number | typeof NOT_MEASURED;
  readonly retry_rate: PyFloat | typeof NOT_MEASURED;
  readonly client_decision_latency_seconds: Latency;
  readonly production_latency_seconds: Latency;
  readonly artifacts_generated: number | typeof NOT_MEASURED;
  readonly accept_reject: readonly unknown[] | typeof NOT_MEASURED;
  readonly plan_conformance: Conformance | typeof NOT_MEASURED;
  readonly cost_schedule_variance: typeof NOT_MEASURED;
  readonly release_result: typeof NOT_MEASURED;
}

const sequenceOf = (e: EventRow): number => (e.sequence ? e.sequence : 0);

function durations(completes: readonly EventRow[]): Map<string, PyFloat> {
  const out = new Map<string, PyFloat>();
  for (const e of completes) {
    const d = secondsBetween(e.started_at, e.completed_at);
    if (d !== null) out.set(pyStr(e.node_id), d);
  }
  return out;
}

function latencies(rows: readonly EventRow[], completes: readonly EventRow[], requested: readonly EventRow[], decided: readonly EventRow[]) {
  let approval: PyFloat | null = null;
  if (requested.length && decided.length) {
    approval = secondsBetween(requested[0]?.observed_at, decided[decided.length - 1]?.observed_at);
  }
  let production: PyFloat | null = null;
  if (completes.length) {
    const gate = requested.length ? requested[0]?.observed_at : completes[completes.length - 1]?.observed_at;
    production = secondsBetween(rows[0]?.observed_at, gate);
  }
  const measured = requested.length && decided.length ? (approval ?? NOT_MEASURED) : NOT_MEASURED;
  return { approval: measured as Latency, production: (completes.length ? (production ?? NOT_MEASURED) : NOT_MEASURED) as Latency };
}

/** `measure_run`. */
export function measureRun(events: Iterable<EventRow>, plannedArtifacts: Iterable<string> = []): RunMetrics {
  const rows = [...events].sort((a, b) => compareScalars(sequenceOf(a), sequenceOf(b)));
  const ofType = (t: string): EventRow[] => rows.filter((e) => e.event_type === t);
  const [completes, errors, requested, decided] = [
    ofType('node_complete'), ofType('node_error'), ofType('approval_requested'), ofType('approval_decided'),
  ];
  const dur = durations(completes);
  const observed = completes.map((e) => pyStr(e.node_id)).filter((n) => STAGE_ARTIFACT.has(n))
    .map((n) => STAGE_ARTIFACT.get(n) as string);
  const planned = [...plannedArtifacts];
  const decisions = decided.map((e) => (e.safe_payload ?? {})['decision'] ?? null);
  const lat = latencies(rows, completes, requested, decided);
  return {
    events: rows.length,
    node_durations_seconds: dur.size ? dur : NOT_MEASURED,
    node_errors: rows.length ? errors.length : NOT_MEASURED,
    retry_rate: completes.length ? new PyFloat(pyRound(errors.length / (completes.length + errors.length), 6)) : NOT_MEASURED,
    client_decision_latency_seconds: lat.approval,
    production_latency_seconds: lat.production,
    artifacts_generated: rows.length ? ofType('artifact_generated').length : NOT_MEASURED,
    accept_reject: decisions.length ? decisions : NOT_MEASURED,
    plan_conformance: planned.length ? conformance(planned, observed) : NOT_MEASURED,
    cost_schedule_variance: NOT_MEASURED,
    release_result: NOT_MEASURED,
  };
}
