/**
 * Pure arithmetic and reporting of `vnexus/marketing.py`: sample sizes, UTM
 * attribution, the SIMULATED forecast and the MEASURED-only report.
 *
 * Three kinds of number stay apart and labelled: MEASURED (a recorded value with a
 * named source), COMPUTED (arithmetic over measured values or requester inputs) and
 * SIMULATED (a forecast from stated assumptions, never reported as performance).
 * `compile_campaign` needs the genome projection (foundry grammars) and stays in Python.
 */
import { CanonicalFloat } from '@amc/canonical';
import { PyKeyError, PyOverflowError, PyTypeError, PyValueError, PyZeroDivisionError, VnexusDivergenceError } from './errors';
import { normalInvCdf } from './mathx';
import { isPlainRecord, isRealNumber, num, pyFloat, pyRepr, pyStrip, pyTruthy, roundTo, sortedUnique, type PyData } from './python';

export const MARKETING_VERSION = 'amc-vnexus-marketing/v1';
export const CHANNELS = ['social_feed', 'social_story', 'email', 'web_landing', 'search', 'video'] as const;
export type Channel = (typeof CHANNELS)[number];

/** `sample_size_per_arm`: two-proportion z-test, two-sided; null when undefined. */
export function sampleSizePerArm(p1: number, lift: number, alpha: number, power: number): number | null {
  const p2 = p1 * (1 + lift);
  if (!(p2 > 0 && p2 < 1)) return null;
  const zA = normalInvCdf(1 - alpha / 2);
  const zB = normalInvCdf(power);
  const pbar = (p1 + p2) / 2;
  const lead = zA * Math.sqrt(2 * pbar * (1 - pbar)) + zB * Math.sqrt(p1 * (1 - p1) + p2 * (1 - p2));
  const gap = p2 - p1;
  if (gap * gap === 0) throw new PyZeroDivisionError('float division by zero');
  const n = Math.ceil((lead * lead) / (gap * gap));
  if (Number.isNaN(n)) throw new PyValueError('cannot convert float NaN to integer');
  if (!Number.isFinite(n)) throw new PyOverflowError('cannot convert float infinity to integer');
  if (!Number.isSafeInteger(n)) throw new VnexusDivergenceError('sample size beyond 2^53 is refused (Python returns an exact big int)');
  return n;
}

/** `urllib.parse.quote(text, safe="")`: only letters, digits and `_.-~` stay unescaped. */
export function quoteAll(text: string): string {
  let encoded: string;
  try {
    encoded = encodeURIComponent(text);
  } catch (error) {
    if (error instanceof URIError) throw new PyValueError('surrogates not allowed');
    throw error;
  }
  return encoded.replace(/[!'()*]/g, (c) => `%${c.charCodeAt(0).toString(16).toUpperCase()}`);
}

export interface Utm {
  readonly params: Record<string, string>;
  readonly url: string | null;
}

function utmMedium(channel: Channel): string {
  if (channel === 'email' || channel === 'web_landing') return 'owned';
  return channel === 'social_feed' || channel === 'social_story' ? 'social' : channel;
}

/** `utm`: attribution parameters and, when a base URL is given, the tagged URL. */
export function utm(campaignRef: string, channel: Channel, content: string, base: string | null): Utm {
  const params = { utm_source: channel, utm_medium: utmMedium(channel), utm_campaign: campaignRef, utm_content: content };
  if (!base) return { params, url: null };
  const sep = base.includes('?') ? '&' : '?';
  const query = Object.entries(params).map(([k, v]) => `${k}=${quoteAll(v)}`).join('&');
  return { params, url: base + sep + query };
}

export interface Forecast {
  readonly kind: 'SIMULATED';
  readonly expected_conversions: number | CanonicalFloat;
  readonly interval_95: ReadonlyArray<number | CanonicalFloat>;
  readonly assumptions: { readonly audience_size: number; readonly assumed_rate: number; readonly source: string };
  readonly label: string;
}

/** `forecast`: a SIMULATED projection from stated assumptions; never a prediction and never stored as data. */
export function forecast(audienceSize: number, assumedRate: number, assumptionSource: string): Forecast {
  if (pyStrip(assumptionSource) === '') throw new PyValueError('a forecast states where its assumed rate comes from');
  if (!(assumedRate > 0 && assumedRate < 1) || audienceSize <= 0) throw new PyValueError('audience_size > 0 and 0 < assumed_rate < 1');
  const expected = audienceSize * assumedRate;
  const sd = Math.sqrt(audienceSize * assumedRate * (1 - assumedRate));
  const low = roundTo(expected - 1.96 * sd, 1);
  return {
    kind: 'SIMULATED', expected_conversions: pyFloat(roundTo(expected, 1)),
    interval_95: [pyFloat(Math.max(0.0, low)), pyFloat(roundTo(expected + 1.96 * sd, 1))],
    assumptions: { audience_size: audienceSize, assumed_rate: assumedRate, source: assumptionSource },
    label: 'SIMULATION from stated assumptions; not measured performance',
  };
}

type Row = Record<string, PyData>;

function field(record: { readonly [key: string]: PyData }, key: string): PyData {
  if (!Object.prototype.hasOwnProperty.call(record, key)) throw new PyKeyError(pyRepr(key));
  return record[key] as PyData;
}

function asRecord(value: PyData, what: string): { readonly [key: string]: PyData } {
  if (!isPlainRecord(value)) throw new PyTypeError(`${what} must be a mapping`);
  return value;
}

/** `float(x["value"])` for the values a measurement may hold; strings are refused (Python parses them). */
function measuredValue(m: { readonly [key: string]: PyData }): number {
  const value = field(m, 'value');
  if (typeof value === 'boolean') return value ? 1 : 0;
  if (isRealNumber(value)) return num(value);
  throw new VnexusDivergenceError('measurement values must be numbers; Python also parses numeric strings');
}

interface Side {
  readonly event: string;
  readonly total: number;
  readonly present: boolean;
  readonly sources: string[];
}

function side(event: string, measurements: readonly { readonly [key: string]: PyData }[]): Side {
  let total = 0;
  for (const m of measurements) total += measuredValue(m);
  const sources = sortedUnique(measurements.map((m) => String(field(m, 'source'))));
  return { event, total, present: measurements.length > 0, sources };
}

function dumpSide(s: Side): Row {
  return { event: s.event, value: s.present ? pyFloat(s.total) : null, sources: s.sources };
}

function reportRow(c: { readonly [key: string]: PyData }, by: Map<string, Array<{ readonly [key: string]: PyData }>>): Row {
  const numEvent = field(c, 'numerator_event') as string;
  const denEvent = c['denominator_event'];
  const numerator = side(numEvent, by.get(numEvent) ?? []);
  const row: Row = { metric: field(c, 'name'), numerator: dumpSide(numerator) };
  if (!pyTruthy(denEvent)) return { ...row, value_kind: numerator.present ? 'MEASURED' : 'NOT_MEASURED' };
  const denominator = side(denEvent as string, by.get(denEvent as string) ?? []);
  const rate = numerator.present && denominator.present && denominator.total > 0 ? roundTo(numerator.total / denominator.total, 6) : null;
  return {
    ...row, denominator: dumpSide(denominator), rate: rate === null ? null : pyFloat(rate),
    rate_kind: rate !== null ? 'COMPUTED from MEASURED values' : 'NOT_MEASURED',
  };
}

/** `report`: measured values per metric with sources; rates only where both events were measured. */
export function report(plan: { readonly [key: string]: PyData }, measurements: readonly PyData[]): Row {
  const by = new Map<string, Array<{ readonly [key: string]: PyData }>>();
  for (const raw of measurements) {
    const m = asRecord(raw, 'measurement');
    const metric = field(m, 'metric') as string;
    by.set(metric, [...(by.get(metric) ?? []), m]);
  }
  const contracts = field(plan, 'measurement_contracts') as readonly PyData[];
  const rows = contracts.map((c) => reportRow(asRecord(c, 'contract'), by));
  return {
    campaign_ref: field(plan, 'campaign_ref'), metrics: rows, measurement_count: measurements.length,
    note: 'only recorded measurements with a named source appear here; forecasts are excluded',
  };
}
