/**
 * Twin of `agency/project_os/publishing.py`: the publication provider
 * contract and the fail-closed provider registry.
 *
 * Provider contract: prepare -> validate -> preview -> publish -> verify, plus
 * update and remove. Attempt states run SPEC -> VALIDATED -> AUTHORIZED ->
 * APPROVED -> EXECUTING -> READBACK -> RECONCILED -> VERIFIED, with BLOCKED /
 * FAILED / UNCERTAIN as exits. UNCERTAIN means the provider call may or may
 * not have happened; it is resolved by reading back with the same idempotency
 * key, never by blindly retrying.
 *
 * The only provider that exists is `DryRunProvider`, which never leaves the
 * process. The live registry is private and ships empty, and nothing here can
 * register into it: `live` mode resolves to no provider, so no publish, send
 * or spend path exists. Nothing can make an unavailable provider look active.
 */
import { pyRepr } from '@amc/kernel';
import { PublicationBlocked, PyRuntimeError, PyValueError } from './errors';
import { canonicalJsonBytes, canonicalSha256, type PyJson } from './json';
import { lowerView, pyStrip, truthy } from './pytext';
import { PUBLICATION_STATES, PUBLICATION_TRANSITIONS, canTransition, parseEnum } from './vocabulary';

export type ProviderMode = 'DISABLED' | 'DRY_RUN' | 'LIVE';
export type PreparedRecord = Readonly<Record<string, PyJson>>;

export class PyKeyError extends PyRuntimeError {
  override name = 'KeyError';
}

export interface PublicationRequest {
  readonly tenant_id: string;
  readonly project_id: string;
  readonly content_item_id: string;
  readonly version: number;
  readonly channel: string;
  readonly body: Readonly<Record<string, PyJson>>;
  readonly idempotency_key: string;
}

/** SHA-256 over what is being published (item, version, channel, body); the idempotency key is not part of it. */
export function requestHash(request: PublicationRequest): string {
  return canonicalSha256({
    content_item_id: request.content_item_id,
    version: request.version,
    channel: request.channel,
    body: request.body,
  });
}

export interface ProviderResult {
  readonly external_ref: string;
  readonly observed: Readonly<Record<string, PyJson>>;
}

export interface PublicationProvider {
  readonly name: string;
  readonly mode: ProviderMode;
  prepare(request: PublicationRequest): PreparedRecord;
  validate(prepared: PreparedRecord): string[];
  preview(prepared: PreparedRecord): Record<string, PyJson>;
  publish(prepared: PreparedRecord, idempotencyKey: string): ProviderResult;
  verify(idempotencyKey: string): ProviderResult | null;
  update(externalRef: string, prepared: PreparedRecord): ProviderResult;
  remove(externalRef: string): boolean;
}

function field(prepared: PreparedRecord, key: string): PyJson {
  const value = prepared[key];
  if (value === undefined) throw new PyKeyError(pyRepr(key));
  return value;
}

/**
 * Exercises the full contract without leaving the process. It "publishes"
 * into an in-memory ledger keyed by idempotency key, so a repeated publish is
 * deduplicated as a real idempotent provider must do, and `verify` reads back
 * what was recorded.
 */
export class DryRunProvider implements PublicationProvider {
  readonly name = 'dry-run';
  readonly mode: ProviderMode = 'DRY_RUN';
  private readonly ledger = new Map<string, ProviderResult>();

  constructor(readonly maxBodyChars: number = 20_000) {}

  prepare(request: PublicationRequest): PreparedRecord {
    return {
      channel: request.channel,
      content_item_id: request.content_item_id,
      version: request.version,
      body: { ...request.body },
      request_hash: requestHash(request),
    };
  }

  validate(prepared: PreparedRecord): string[] {
    const problems: string[] = [];
    if (!truthy(prepared.channel)) problems.push('CHANNEL_REQUIRED');
    const body = truthy(prepared.body) ? (prepared.body as PyJson) : {};
    if (canonicalJsonBytes(body).length > this.maxBodyChars) problems.push('BODY_TOO_LARGE');
    return problems;
  }

  preview(prepared: PreparedRecord): Record<string, PyJson> {
    return { channel: field(prepared, 'channel'), mode: this.mode, would_publish: { ...(field(prepared, 'body') as object) } as PyJson };
  }

  publish(prepared: PreparedRecord, idempotencyKey: string): ProviderResult {
    const existing = this.ledger.get(idempotencyKey);
    if (existing) return existing;
    const hash = field(prepared, 'request_hash') as string;
    const result: ProviderResult = {
      external_ref: `dryrun:${hash.slice(0, 24)}`,
      observed: { channel: field(prepared, 'channel'), request_hash: hash },
    };
    this.ledger.set(idempotencyKey, result);
    return result;
  }

  verify(idempotencyKey: string): ProviderResult | null {
    return this.ledger.get(idempotencyKey) ?? null;
  }

  update(externalRef: string, prepared: PreparedRecord): ProviderResult {
    return { external_ref: externalRef, observed: { request_hash: field(prepared, 'request_hash') } };
  }

  remove(externalRef: string): boolean {
    return [...this.ledger.values()].some((result) => result.external_ref === externalRef);
  }
}

// Live providers must be installed by reviewed code. The registry ships empty and is not exported.
const LIVE_PROVIDERS = new Map<string, PublicationProvider>();
const DRY_RUN = new DryRunProvider();

/** `AMC_PUBLICATION_MODE`: anything unrecognised is DISABLED. */
export function publicationMode(raw: string | undefined): ProviderMode {
  const value = lowerView(pyStrip(raw || 'disabled'));
  if (value === 'dry_run') return 'DRY_RUN';
  return value === 'live' ? 'LIVE' : 'DISABLED';
}

export function resolveProvider(channel: string, rawMode: string | undefined): PublicationProvider {
  const mode = publicationMode(rawMode);
  if (mode === 'DISABLED') throw new PublicationBlocked('publication_disabled');
  if (mode === 'DRY_RUN') return DRY_RUN;
  const provider = LIVE_PROVIDERS.get(channel);
  if (provider === undefined || provider.mode !== 'LIVE') {
    throw new PublicationBlocked(`no reviewed live provider installed for channel ${pyRepr(channel)}`);
  }
  return provider;
}

export function providerCapabilities(rawMode: string | undefined): Record<string, PyJson> {
  const mode = publicationMode(rawMode);
  const channels = [...LIVE_PROVIDERS.keys()].sort();
  return {
    mode,
    dry_run_provider: DRY_RUN.name,
    live_channels: channels,
    live_available: mode === 'LIVE' && channels.length > 0,
    status: channels.length === 0 ? 'DRY_RUN_ONLY' : 'EXTERNAL_ACTIVATION_REQUIRED',
  };
}

export function nextState(current: string, target: string): string {
  const from = parseEnum('PublicationState', PUBLICATION_STATES, current);
  const to = parseEnum('PublicationState', PUBLICATION_STATES, target);
  if (!canTransition(PUBLICATION_TRANSITIONS, from, to)) {
    throw new PyValueError(`illegal publication transition ${from} -> ${to}`);
  }
  return to;
}
