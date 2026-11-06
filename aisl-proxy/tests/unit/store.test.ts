import { describe, expect, it } from 'vitest';
import { InMemoryStore } from '../../src/redis/store.js';
import { stripeReference } from '../../src/services/webhookService.js';
import { AislError } from '../../src/lib/errors.js';
import type Stripe from 'stripe';

describe('KeyValueStore dedupe semantics', () => {
  it('grants the key to exactly one caller', async () => {
    const store = new InMemoryStore();
    const results = await Promise.all(
      Array.from({ length: 10 }, () => store.setIfAbsent('event:evt_1', '1', 60)),
    );
    expect(results.filter(Boolean)).toHaveLength(1);
  });

  it('releases the key once deleted so a genuine retry can proceed', async () => {
    const store = new InMemoryStore();
    expect(await store.setIfAbsent('k', '1', 60)).toBe(true);
    expect(await store.setIfAbsent('k', '1', 60)).toBe(false);
    await store.del('k');
    expect(await store.setIfAbsent('k', '1', 60)).toBe(true);
  });

  it('expires keys', async () => {
    const store = new InMemoryStore();
    await store.set('k', 'v', 0.01);
    await new Promise((resolve) => setTimeout(resolve, 25));
    expect(await store.get('k')).toBeNull();
  });
});

describe('token bucket', () => {
  it('allows exactly `capacity` requests before throttling', async () => {
    const store = new InMemoryStore();
    const decisions = [];
    for (let index = 0; index < 6; index += 1) {
      decisions.push(await store.consumeToken('bucket', 5, 0.001));
    }
    expect(decisions.filter((decision) => decision.allowed)).toHaveLength(5);
    expect(decisions[5]?.allowed).toBe(false);
    expect(decisions[5]?.retryAfterMs).toBeGreaterThan(0);
  });
});

describe('stripeReference', () => {
  const event = (object: Record<string, unknown>): Stripe.Event =>
    ({ id: 'evt_1', type: 'charge.refunded', data: { object } }) as unknown as Stripe.Event;

  it('reads a charge object', () => {
    expect(stripeReference(event({ object: 'charge', id: 'ch_1', payment_intent: 'pi_1' }))).toEqual({
      chargeId: 'ch_1',
      paymentIntentId: 'pi_1',
    });
  });

  it('reads a payment_intent object', () => {
    expect(stripeReference(event({ object: 'payment_intent', id: 'pi_1', latest_charge: 'ch_1' }))).toEqual({
      chargeId: 'ch_1',
      paymentIntentId: 'pi_1',
    });
  });

  it('reads a dispute object', () => {
    expect(stripeReference(event({ object: 'dispute', id: 'dp_1', charge: 'ch_1' }))).toEqual({
      chargeId: 'ch_1',
      paymentIntentId: null,
    });
  });

  it('rejects an object type it cannot attribute', () => {
    expect(() => stripeReference(event({ object: 'customer', id: 'cus_1' }))).toThrow(AislError);
  });
});
