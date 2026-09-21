import { createHash } from 'node:crypto';
import type Stripe from 'stripe';
import { AislError } from '../lib/errors.js';
import type { Env } from '../config/env.js';
import type { ConversionRepository } from '../db/repositories/conversions.js';
import type { WebhookEventRepository, WebhookOutcome } from '../db/repositories/webhookEvents.js';
import type { KeyValueStore } from '../redis/store.js';

export interface WebhookLogger {
  info: (obj: object, msg: string) => void;
  warn: (obj: object, msg: string) => void;
  error: (obj: object, msg: string) => void;
}

export interface WebhookServiceDeps {
  env: Env;
  conversions: ConversionRepository;
  events: WebhookEventRepository;
  cache: KeyValueStore;
  logger: WebhookLogger;
}

export interface WebhookResult {
  status: 'PROCESSED' | 'DUPLICATE_EVENT_IGNORED';
  outcome: WebhookOutcome | 'DUPLICATE';
  event_id: string;
  event_type: string;
  conversion_id: string | null;
}

const SETTLEMENT_EVENTS = new Set(['payment_intent.succeeded', 'charge.succeeded']);
const CLAWBACK_EVENTS = new Set(['charge.refunded', 'charge.dispute.created', 'charge.refund.updated']);

/**
 * S2S webhook ingestion.
 *
 * Two independent dedupe layers guard the ledger:
 *   1. Redis SETNX with a 7-day TTL — rejects concurrent redeliveries in
 *      microseconds, before any database work.
 *   2. `webhook_events` INSERT ... ON CONFLICT DO NOTHING — survives a Redis
 *      flush or failover, and is the durable record of what was applied.
 *
 * A handler that throws releases both claims so a genuine retry can run; a
 * handler that completes leaves them in place forever (within the TTL window).
 */
export class WebhookService {
  constructor(private readonly deps: WebhookServiceDeps) {}

  async handle(event: Stripe.Event, rawPayload: Buffer | string): Promise<WebhookResult> {
    const dedupKey = `event:${event.id}`;
    const payloadSha256 = createHash('sha256').update(rawPayload).digest('hex');

    const wonRedis = await this.deps.cache.setIfAbsent(
      dedupKey,
      '1',
      this.deps.env.WEBHOOK_DEDUPE_TTL_SECONDS,
    );
    if (!wonRedis) {
      this.deps.logger.info({ event_id: event.id, layer: 'redis' }, 'duplicate webhook ignored');
      return duplicate(event);
    }

    const wonDatabase = await this.deps.events.claim({
      eventId: event.id,
      eventType: event.type,
      payloadSha256,
    });
    if (!wonDatabase) {
      this.deps.logger.info({ event_id: event.id, layer: 'postgres' }, 'duplicate webhook ignored');
      return duplicate(event);
    }

    try {
      const { outcome, conversionId } = await this.dispatch(event);
      await this.deps.events.complete(event.id, outcome, conversionId);
      return {
        status: 'PROCESSED',
        outcome,
        event_id: event.id,
        event_type: event.type,
        conversion_id: conversionId,
      };
    } catch (error) {
      // Both claims are released so Stripe's retry can actually reprocess.
      await this.deps.events.release(event.id);
      await this.deps.cache.del(dedupKey);
      this.deps.logger.error(
        { event_id: event.id, event_type: event.type, reason: error instanceof Error ? error.message : String(error) },
        'webhook handler failed; dedupe claims released for retry',
      );
      throw error;
    }
  }

  private async dispatch(event: Stripe.Event): Promise<{ outcome: WebhookOutcome; conversionId: string | null }> {
    if (SETTLEMENT_EVENTS.has(event.type)) {
      return this.settle(event);
    }
    if (CLAWBACK_EVENTS.has(event.type)) {
      return this.clawback(event);
    }
    this.deps.logger.info({ event_id: event.id, event_type: event.type }, 'webhook type not handled by the ledger');
    return { outcome: 'IGNORED_UNHANDLED_TYPE', conversionId: null };
  }

  private async settle(event: Stripe.Event): Promise<{ outcome: WebhookOutcome; conversionId: string | null }> {
    const reference = stripeReference(event);
    const conversion = await this.deps.conversions.findSaleByStripeReference(reference);
    if (!conversion) {
      this.deps.logger.warn({ event_id: event.id, ...reference }, 'no conversion matches settlement event');
      return { outcome: 'IGNORED_NO_MATCHING_CONVERSION', conversionId: null };
    }

    const settled = await this.deps.conversions.markSettled(conversion.id, reference.chargeId ?? null);
    if (!settled) {
      // Already SETTLED or already REFUNDED; neither is an error, and a refund
      // must never be un-done by a late settlement event.
      this.deps.logger.info(
        { event_id: event.id, conversion_id: conversion.id, status: conversion.status },
        'settlement event did not change conversion status',
      );
      return { outcome: 'IGNORED_ALREADY_REFUNDED', conversionId: conversion.id };
    }

    this.deps.logger.info({ event_id: event.id, conversion_id: settled.id }, 'conversion settled');
    return { outcome: 'SETTLED', conversionId: settled.id };
  }

  private async clawback(event: Stripe.Event): Promise<{ outcome: WebhookOutcome; conversionId: string | null }> {
    const reference = stripeReference(event);
    const sale = await this.deps.conversions.findSaleByStripeReference(reference);
    if (!sale) {
      this.deps.logger.warn({ event_id: event.id, ...reference }, 'no conversion matches clawback event');
      return { outcome: 'IGNORED_NO_MATCHING_CONVERSION', conversionId: null };
    }

    const reversal = await this.deps.conversions.recordReversal({
      parent: sale,
      // Keyed on the event so a redelivery that somehow gets past both dedupe
      // layers still cannot write a second reversal.
      reversalReference: event.id,
      memo: `${event.type} ${event.id}`,
    });

    this.deps.logger.info(
      {
        event_id: event.id,
        conversion_id: sale.id,
        reversal_id: reversal.id,
        gross_amount_cents: reversal.split.grossAmountCents,
      },
      'clawback reversal written',
    );
    return { outcome: 'REVERSED', conversionId: reversal.id };
  }
}

/** Pull the charge / payment-intent handles out of whichever object the event carries. */
export function stripeReference(event: Stripe.Event): { chargeId: string | null; paymentIntentId: string | null } {
  const object = event.data.object as unknown as Record<string, unknown>;
  const objectType = typeof object.object === 'string' ? object.object : '';

  if (objectType === 'charge') {
    return {
      chargeId: typeof object.id === 'string' ? object.id : null,
      paymentIntentId: typeof object.payment_intent === 'string' ? object.payment_intent : null,
    };
  }
  if (objectType === 'payment_intent') {
    return {
      chargeId: typeof object.latest_charge === 'string' ? object.latest_charge : null,
      paymentIntentId: typeof object.id === 'string' ? object.id : null,
    };
  }
  if (objectType === 'dispute' || objectType === 'refund') {
    return {
      chargeId: typeof object.charge === 'string' ? object.charge : null,
      paymentIntentId: typeof object.payment_intent === 'string' ? object.payment_intent : null,
    };
  }

  throw AislError.badRequest(
    'unsupported_event_object',
    `webhook event ${event.id} carries an unsupported object type "${objectType || 'unknown'}"`,
  );
}

function duplicate(event: Stripe.Event): WebhookResult {
  return {
    status: 'DUPLICATE_EVENT_IGNORED',
    outcome: 'DUPLICATE',
    event_id: event.id,
    event_type: event.type,
    conversion_id: null,
  };
}
