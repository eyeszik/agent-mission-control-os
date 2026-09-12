import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { performance } from 'node:perf_hooks';
import { ACP_CONFIG, AcpConfigSchema } from '../../src/types/acp.js';
import { isUuidV7 } from '../../src/lib/ids.js';
import { LEDGER_ACCOUNTS } from '../../src/db/repositories/conversions.js';
import { startHarness, stripeEvent, type Harness } from '../helpers/harness.js';

const SHIPPING_ADDRESS = {
  name: 'Jane Doe',
  address1: '123 Market St',
  city: 'San Francisco',
  state: 'CA',
  postal_code: '94105',
  country: 'US',
};

describe('AISL proxy gateway end-to-end', () => {
  let harness: Harness;

  beforeAll(async () => {
    harness = await startHarness();
  });

  afterAll(async () => {
    await harness.close();
  });

  beforeEach(async () => {
    await harness.reset();
    harness.stripe.state.paymentIntents.length = 0;
    harness.stripe.state.refunds.length = 0;
    harness.stripe.state.declineNext = false;
    harness.stripe.state.failRefunds = false;
    harness.shopify.state.orders.length = 0;
    harness.shopify.state.failNextOrder = false;
    harness.shopify.state.orderTotalOverride = null;
  });

  /* ---------------------------------------------------------------------- */
  /* TASK 1 gate: protocol manifest                                          */
  /* ---------------------------------------------------------------------- */

  describe('GET /.well-known/acp/config.json', () => {
    it('returns the blueprint-locked ACP configuration', async () => {
      const response = await harness.app.inject({ method: 'GET', url: '/.well-known/acp/config.json' });

      expect(response.statusCode).toBe(200);
      expect(response.headers['content-type']).toMatch(/^application\/json/);
      expect(response.json()).toEqual({
        version: '2026.1',
        capabilities: { catalog_search: true, delegated_checkout: true, session_persistence: false },
        endpoints: {
          catalog_query: '/v1/agent/intent',
          checkout_execution: '/v1/agent/checkout',
          order_status: '/v1/agent/order/{order_id}',
        },
        payment_methods: ['stripe_delegated_token', 'merchant_shared_payment_token'],
        supported_currencies: ['USD', 'EUR', 'GBP'],
      });
      expect(AcpConfigSchema.safeParse(response.json()).success).toBe(true);
    });

    it('answers well inside the 10ms budget because it performs no I/O', async () => {
      // Warm the route so the measurement is not dominated by first-hit setup.
      await harness.app.inject({ method: 'GET', url: '/.well-known/acp/config.json' });

      const timings: number[] = [];
      for (let index = 0; index < 25; index += 1) {
        const start = performance.now();
        const response = await harness.app.inject({ method: 'GET', url: '/.well-known/acp/config.json' });
        timings.push(performance.now() - start);
        expect(response.statusCode).toBe(200);
      }
      timings.sort((a, b) => a - b);
      const median = timings[Math.floor(timings.length / 2)] ?? Number.POSITIVE_INFINITY;
      expect(median).toBeLessThan(10);
    });

    it('advertises the endpoints the gateway actually serves', async () => {
      const intent = await harness.app.inject({
        method: 'POST',
        url: ACP_CONFIG.endpoints.catalog_query,
        payload: { agent_id: 'route_probe', query: 'headphones' },
      });
      expect(intent.statusCode).toBe(200);

      const checkout = await harness.app.inject({
        method: 'POST',
        url: ACP_CONFIG.endpoints.checkout_execution,
        payload: {},
      });
      // Reached the route and failed validation, rather than 404-ing.
      expect(checkout.statusCode).toBe(400);
    });
  });

  /* ---------------------------------------------------------------------- */
  /* TASK 3 gate: intent / discovery                                         */
  /* ---------------------------------------------------------------------- */

  describe('POST /v1/agent/intent', () => {
    it('returns live catalogue results bound to UUIDv7 attribution tokens', async () => {
      const response = await harness.app.inject({
        method: 'POST',
        url: '/v1/agent/intent',
        payload: {
          agent_id: 'openai_chatgpt_operator_1',
          query: 'wireless noise cancelling headphones under 300',
          max_results: 5,
          sub_ids: { sub1: 'campaign_alpha', sub2: 'prompt_v4' },
        },
      });

      expect(response.statusCode).toBe(200);
      const body = response.json();
      expect(body.result_count).toBeGreaterThan(0);

      for (const result of body.results) {
        expect(isUuidV7(result.acp_token)).toBe(true);
        expect(result.attribution.click_id).toBe(result.acp_token);
        expect(result.attribution.signature).toMatch(/^[0-9a-f]{64}$/);
        expect(result.attribution.sub_id_1).toBe('campaign_alpha');
        expect(result.attribution.sub_id_2).toBe('prompt_v4');
        expect(result.merchant_id).toBe(harness.merchant.id);
        expect(result.checkout.endpoint).toBe('/v1/agent/checkout');

        // Prices match the merchant catalogue, not a cached guess.
        const source = harness.shopify.state.products.find(
          (product) => product.variantId === result.variant_id,
        );
        expect(source).toBeDefined();
        expect(result.price.amount_cents).toBe(Math.round(Number(source?.price ?? 0) * 100));
      }
    });

    it('omits out-of-stock products an agent could not actually buy', async () => {
      const response = await harness.app.inject({
        method: 'POST',
        url: '/v1/agent/intent',
        payload: { agent_id: 'agent_stock', query: 'headphones', max_results: 10 },
      });

      const variants = response.json().results.map((result: { variant_id: string }) => result.variant_id);
      expect(variants).not.toContain('gid://shopify/ProductVariant/12345680');
    });

    it('persists every minted token before the response is returned', async () => {
      const response = await harness.app.inject({
        method: 'POST',
        url: '/v1/agent/intent',
        payload: { agent_id: 'agent_persist', query: 'headphones', max_results: 2 },
      });

      const tokens: string[] = response.json().results.map((result: { acp_token: string }) => result.acp_token);
      const { rows } = await harness.db.query<{ count: string }>(
        `SELECT COUNT(*) AS count FROM agent_intents WHERE click_id = ANY($1::uuid[])`,
        [tokens],
      );
      expect(Number(rows[0]?.count)).toBe(tokens.length);
    });

    it('mints a distinct token per search so attribution trails never merge', async () => {
      const first = await harness.app.inject({
        method: 'POST',
        url: '/v1/agent/intent',
        payload: { agent_id: 'agent_a', query: 'headphones', max_results: 1 },
      });
      const second = await harness.app.inject({
        method: 'POST',
        url: '/v1/agent/intent',
        payload: { agent_id: 'agent_b', query: 'headphones', max_results: 1 },
      });

      expect(first.json().results[0].acp_token).not.toBe(second.json().results[0].acp_token);
    });

    it('rejects a malformed request with a typed ACP error body', async () => {
      const response = await harness.app.inject({
        method: 'POST',
        url: '/v1/agent/intent',
        payload: { query: 'headphones' },
      });

      expect(response.statusCode).toBe(400);
      expect(response.json()).toMatchObject({ type: 'invalid_request', code: 'schema_validation_failed' });
    });
  });

  /* ---------------------------------------------------------------------- */
  /* TASK 4 gate: delegated checkout                                         */
  /* ---------------------------------------------------------------------- */

  describe('POST /v1/agent/checkout', () => {
    it('redeems the shared payment token, places the order, and books a balanced ledger', async () => {
      const { token, variantId } = await mintToken('agent_checkout');

      const response = await harness.app.inject({
        method: 'POST',
        url: '/v1/agent/checkout',
        payload: {
          acp_token: token,
          merchant_id: harness.merchant.id,
          variant_id: variantId,
          quantity: 1,
          payment_credential: { type: 'stripe_payment_token', token: 'spt_test_9876543210abcdef' },
          shipping_address: SHIPPING_ADDRESS,
        },
      });

      expect(response.statusCode).toBe(201);
      const body = response.json();

      // 249.00 USD at 500 bps commission, 80 bps platform cut.
      expect(body.amounts).toEqual({
        currency: 'USD',
        gross_amount_cents: 24_900,
        commission_total_cents: 1_245,
        aisl_fee_cents: 199,
        agent_payout_cents: 1_046,
        merchant_net_cents: 23_655,
      });
      expect(body.status).toBe('PENDING_SETTLEMENT');
      expect(body.payment.payment_intent_id).toMatch(/^pi_test_/);

      // The delegated credential reached Stripe in the documented parameter,
      // on the merchant's connected account, under our idempotency key.
      const intent = harness.stripe.state.paymentIntents[0];
      expect(intent).toMatchObject({
        token: 'spt_test_9876543210abcdef',
        amount: 24_900,
        currency: 'usd',
        stripeAccount: 'acct_test_merchant',
      });
      expect(intent?.idempotencyKey).toBeTruthy();

      // Double-entry legs balance and carry the split.
      const legs = await harness.deps.repositories.conversions.listLedgerEntries(body.order_id);
      expect(legs).toHaveLength(4);
      const debits = legs.filter((leg) => leg.direction === 'DEBIT').reduce((sum, leg) => sum + leg.amountCents, 0);
      const credits = legs.filter((leg) => leg.direction === 'CREDIT').reduce((sum, leg) => sum + leg.amountCents, 0);
      expect(debits).toBe(24_900);
      expect(credits).toBe(24_900);
      expect(legs.find((leg) => leg.account === LEDGER_ACCOUNTS.agentPayable)?.amountCents).toBe(1_046);
      expect(legs.find((leg) => leg.account === LEDGER_ACCOUNTS.platformRevenue)?.amountCents).toBe(199);

      expect(await harness.deps.repositories.conversions.findUnbalancedEntryGroups()).toEqual([]);
    });

    it('charges quantity x unit price', async () => {
      const { token, variantId } = await mintToken('agent_qty');

      const response = await harness.app.inject({
        method: 'POST',
        url: '/v1/agent/checkout',
        payload: {
          acp_token: token,
          merchant_id: harness.merchant.id,
          variant_id: variantId,
          quantity: 3,
          payment_credential: { type: 'stripe_payment_token', token: 'spt_test_qty' },
          shipping_address: SHIPPING_ADDRESS,
        },
      });

      expect(response.statusCode).toBe(201);
      expect(harness.stripe.state.paymentIntents[0]?.amount).toBe(74_700);
      expect(response.json().amounts.gross_amount_cents).toBe(74_700);
    });

    it('replays an identical request instead of charging the token twice', async () => {
      const { token, variantId } = await mintToken('agent_idem');
      const payload = {
        acp_token: token,
        merchant_id: harness.merchant.id,
        variant_id: variantId,
        quantity: 1,
        payment_credential: { type: 'stripe_payment_token', token: 'spt_test_idem' },
        shipping_address: SHIPPING_ADDRESS,
        idempotency_key: 'agent-supplied-key-0001',
      };

      const first = await harness.app.inject({ method: 'POST', url: '/v1/agent/checkout', payload });
      const second = await harness.app.inject({ method: 'POST', url: '/v1/agent/checkout', payload });

      expect(first.statusCode).toBe(201);
      expect(second.statusCode).toBe(200);
      expect(second.headers['idempotent-replay']).toBe('true');
      expect(second.json().order_id).toBe(first.json().order_id);

      expect(harness.stripe.state.paymentIntents).toHaveLength(1);
      expect(harness.shopify.state.orders).toHaveLength(1);
    });

    it('refuses a reused idempotency key carrying a different request', async () => {
      const first = await mintToken('agent_mismatch');
      const second = await mintToken('agent_mismatch');

      const base = {
        merchant_id: harness.merchant.id,
        quantity: 1,
        payment_credential: { type: 'stripe_payment_token', token: 'spt_test_mismatch' },
        shipping_address: SHIPPING_ADDRESS,
        idempotency_key: 'shared-key-0002',
      };

      const ok = await harness.app.inject({
        method: 'POST',
        url: '/v1/agent/checkout',
        payload: { ...base, acp_token: first.token, variant_id: first.variantId },
      });
      expect(ok.statusCode).toBe(201);

      const conflict = await harness.app.inject({
        method: 'POST',
        url: '/v1/agent/checkout',
        payload: { ...base, acp_token: second.token, variant_id: second.variantId },
      });
      expect(conflict.statusCode).toBe(409);
      expect(conflict.json().code).toBe('idempotency_key_reused');
    });

    it('rejects an unknown token', async () => {
      const response = await harness.app.inject({
        method: 'POST',
        url: '/v1/agent/checkout',
        payload: {
          acp_token: '018f4a1e-8e3b-7000-8432-1b1f9b3bffff',
          merchant_id: harness.merchant.id,
          variant_id: 'gid://shopify/ProductVariant/12345678',
          quantity: 1,
          payment_credential: { type: 'stripe_payment_token', token: 'spt_test' },
          shipping_address: SHIPPING_ADDRESS,
        },
      });

      expect(response.statusCode).toBe(404);
      expect(response.json().code).toBe('acp_token_not_found');
    });

    it('rejects a token older than the 24h attribution window', async () => {
      const { token, variantId } = await mintToken('agent_expired');
      await harness.db.query(
        `UPDATE agent_intent_bindings SET expires_at = NOW() - INTERVAL '1 minute' WHERE click_id = $1`,
        [token],
      );

      const response = await harness.app.inject({
        method: 'POST',
        url: '/v1/agent/checkout',
        payload: {
          acp_token: token,
          merchant_id: harness.merchant.id,
          variant_id: variantId,
          quantity: 1,
          payment_credential: { type: 'stripe_payment_token', token: 'spt_test' },
          shipping_address: SHIPPING_ADDRESS,
        },
      });

      expect(response.statusCode).toBe(404);
      expect(response.json().code).toBe('acp_token_expired');
      expect(harness.stripe.state.paymentIntents).toHaveLength(0);
    });

    it('rejects a token replayed against a different variant', async () => {
      const { token } = await mintToken('agent_swap');

      const response = await harness.app.inject({
        method: 'POST',
        url: '/v1/agent/checkout',
        payload: {
          acp_token: token,
          merchant_id: harness.merchant.id,
          variant_id: 'gid://shopify/ProductVariant/12345679',
          quantity: 1,
          payment_credential: { type: 'stripe_payment_token', token: 'spt_test' },
          shipping_address: SHIPPING_ADDRESS,
        },
      });

      expect(response.statusCode).toBe(400);
      expect(response.json().code).toBe('acp_token_variant_mismatch');
    });

    it('rejects a forged attribution signature', async () => {
      const { token, variantId } = await mintToken('agent_forge');

      const response = await harness.app.inject({
        method: 'POST',
        url: '/v1/agent/checkout',
        payload: {
          acp_token: token,
          merchant_id: harness.merchant.id,
          variant_id: variantId,
          quantity: 1,
          payment_credential: { type: 'stripe_payment_token', token: 'spt_test' },
          shipping_address: SHIPPING_ADDRESS,
          attribution_signature: 'f'.repeat(64),
        },
      });

      expect(response.statusCode).toBe(400);
      expect(response.json().code).toBe('attribution_signature_invalid');
      expect(harness.stripe.state.paymentIntents).toHaveLength(0);
    });

    it('accepts the signature the intent endpoint issued', async () => {
      const minted = await mintToken('agent_signed');

      const response = await harness.app.inject({
        method: 'POST',
        url: '/v1/agent/checkout',
        payload: {
          acp_token: minted.token,
          merchant_id: harness.merchant.id,
          variant_id: minted.variantId,
          quantity: 1,
          payment_credential: { type: 'stripe_payment_token', token: 'spt_test_signed' },
          shipping_address: SHIPPING_ADDRESS,
          attribution_signature: minted.signature,
        },
      });

      expect(response.statusCode).toBe(201);
    });

    it('refunds the capture when the merchant order cannot be placed', async () => {
      const { token, variantId } = await mintToken('agent_compensate');
      harness.shopify.state.failNextOrder = true;

      const response = await harness.app.inject({
        method: 'POST',
        url: '/v1/agent/checkout',
        payload: {
          acp_token: token,
          merchant_id: harness.merchant.id,
          variant_id: variantId,
          quantity: 1,
          payment_credential: { type: 'stripe_payment_token', token: 'spt_test_compensate' },
          shipping_address: SHIPPING_ADDRESS,
        },
      });

      expect(response.statusCode).toBeGreaterThanOrEqual(500);
      expect(harness.stripe.state.paymentIntents).toHaveLength(1);
      // The compensating refund ran, so no money is stranded.
      expect(harness.stripe.state.refunds).toHaveLength(1);
      expect(harness.stripe.state.refunds[0]?.paymentIntentId).toBe(harness.stripe.state.paymentIntents[0]?.id);

      // No conversion was booked for a checkout that did not complete.
      const { rows } = await harness.db.query<{ count: string }>(`SELECT COUNT(*) AS count FROM conversions`);
      expect(Number(rows[0]?.count)).toBe(0);
    });

    it('surfaces a declined delegated token without placing an order', async () => {
      const { token, variantId } = await mintToken('agent_declined');
      harness.stripe.state.declineNext = true;

      const response = await harness.app.inject({
        method: 'POST',
        url: '/v1/agent/checkout',
        payload: {
          acp_token: token,
          merchant_id: harness.merchant.id,
          variant_id: variantId,
          quantity: 1,
          payment_credential: { type: 'stripe_payment_token', token: 'spt_test_declined' },
          shipping_address: SHIPPING_ADDRESS,
        },
      });

      expect(response.statusCode).toBe(402);
      expect(response.json().code).toBe('card_declined');
      expect(harness.shopify.state.orders).toHaveLength(0);
    });

    it('never pays commission on more than was captured', async () => {
      const { token, variantId } = await mintToken('agent_tax');
      // Merchant bills more than the agent's quote (tax added at the store).
      harness.shopify.state.orderTotalOverride = '299.00';

      const response = await harness.app.inject({
        method: 'POST',
        url: '/v1/agent/checkout',
        payload: {
          acp_token: token,
          merchant_id: harness.merchant.id,
          variant_id: variantId,
          quantity: 1,
          payment_credential: { type: 'stripe_payment_token', token: 'spt_test_tax' },
          shipping_address: SHIPPING_ADDRESS,
        },
      });

      expect(response.statusCode).toBe(201);
      expect(response.json().amounts.gross_amount_cents).toBe(24_900);
    });
  });

  /* ---------------------------------------------------------------------- */
  /* TASK 5 gate: webhooks, deduplication, clawback                          */
  /* ---------------------------------------------------------------------- */

  describe('POST /v1/webhooks/stripe-acp', () => {
    it('rejects an unsigned payload', async () => {
      const response = await harness.app.inject({
        method: 'POST',
        url: '/v1/webhooks/stripe-acp',
        headers: { 'content-type': 'application/json' },
        payload: JSON.stringify(stripeEvent({ id: 'evt_unsigned', type: 'charge.refunded', object: {} })),
      });

      expect(response.statusCode).toBe(401);
      expect(response.json().code).toBe('missing_signature');
    });

    it('rejects a forged signature', async () => {
      const { payload } = harness.signedWebhook(
        stripeEvent({ id: 'evt_forged', type: 'payment_intent.succeeded', object: {} }),
      );

      const response = await harness.app.inject({
        method: 'POST',
        url: '/v1/webhooks/stripe-acp',
        headers: { 'content-type': 'application/json', 'stripe-signature': 't=1,v1=deadbeef' },
        payload,
      });

      expect(response.statusCode).toBe(401);
      expect(response.json().code).toBe('invalid_signature');
    });

    it('settles a pending conversion on payment_intent.succeeded', async () => {
      const checkout = await completeCheckout('agent_settle', 'spt_test_settle');
      const intentId = checkout.payment.payment_intent_id;

      const result = await sendWebhook(
        stripeEvent({
          id: 'evt_settle_1',
          type: 'payment_intent.succeeded',
          object: { object: 'payment_intent', id: intentId, latest_charge: 'ch_test_settle' },
        }),
      );

      expect(result.statusCode).toBe(200);
      expect(result.json()).toMatchObject({ status: 'PROCESSED', outcome: 'SETTLED' });

      const status = await harness.app.inject({ method: 'GET', url: `/v1/agent/order/${checkout.order_id}` });
      expect(status.json().status).toBe('SETTLED');
    });

    it('ignores a duplicate event without touching the ledger', async () => {
      const checkout = await completeCheckout('agent_dup', 'spt_test_dup');
      const event = stripeEvent({
        id: 'evt_duplicate_1',
        type: 'charge.refunded',
        object: { object: 'charge', id: checkout.payment.charge_id, payment_intent: checkout.payment.payment_intent_id },
      });

      const first = await sendWebhook(event);
      const second = await sendWebhook(event);

      expect(first.statusCode).toBe(200);
      expect(second.statusCode).toBe(200);
      expect(first.json().status).toBe('PROCESSED');
      expect(second.json()).toMatchObject({ status: 'DUPLICATE_EVENT_IGNORED', outcome: 'DUPLICATE' });

      const { rows } = await harness.db.query<{ count: string }>(
        `SELECT COUNT(*) AS count FROM conversions WHERE entry_type = 'REVERSAL'`,
      );
      expect(Number(rows[0]?.count)).toBe(1);
    });

    it('admits exactly one of two concurrent identical deliveries', async () => {
      const checkout = await completeCheckout('agent_race', 'spt_test_race');
      const event = stripeEvent({
        id: 'evt_concurrent_1',
        type: 'charge.refunded',
        object: { object: 'charge', id: checkout.payment.charge_id, payment_intent: checkout.payment.payment_intent_id },
      });

      const [a, b] = await Promise.all([sendWebhook(event), sendWebhook(event)]);

      expect(a.statusCode).toBe(200);
      expect(b.statusCode).toBe(200);
      const outcomes = [a.json().status, b.json().status].sort();
      expect(outcomes).toEqual(['DUPLICATE_EVENT_IGNORED', 'PROCESSED']);

      const { rows } = await harness.db.query<{ count: string }>(
        `SELECT COUNT(*) AS count FROM conversions WHERE entry_type = 'REVERSAL'`,
      );
      expect(Number(rows[0]?.count)).toBe(1);
    });

    it('writes a balancing negative ledger entry on charge.refunded', async () => {
      const checkout = await completeCheckout('agent_refund', 'spt_test_refund');

      await sendWebhook(
        stripeEvent({
          id: 'evt_refund_1',
          type: 'charge.refunded',
          object: {
            object: 'charge',
            id: checkout.payment.charge_id,
            payment_intent: checkout.payment.payment_intent_id,
            amount_refunded: 24_900,
          },
        }),
      );

      const { rows } = await harness.db.query<{
        gross_amount_cents: string;
        commission_total_cents: string;
        aisl_fee_cents: string;
        agent_payout_cents: string;
        status: string;
      }>(`SELECT gross_amount_cents, commission_total_cents, aisl_fee_cents, agent_payout_cents, status
            FROM conversions WHERE entry_type = 'REVERSAL'`);

      expect(rows).toHaveLength(1);
      expect(Number(rows[0]?.gross_amount_cents)).toBe(-24_900);
      expect(Number(rows[0]?.commission_total_cents)).toBe(-1_245);
      expect(Number(rows[0]?.aisl_fee_cents)).toBe(-199);
      expect(Number(rows[0]?.agent_payout_cents)).toBe(-1_046);

      const parent = await harness.deps.repositories.conversions.findById(checkout.order_id);
      expect(parent?.status).toBe('REFUNDED');

      // Every account nets to zero once the reversal lands.
      for (const account of Object.values(LEDGER_ACCOUNTS)) {
        expect(
          await harness.deps.repositories.conversions.accountBalance(harness.merchant.id, account, 'USD'),
        ).toBe(0);
      }
      expect(await harness.deps.repositories.conversions.findUnbalancedEntryGroups()).toEqual([]);
    });

    it('claws back a disputed charge the same way', async () => {
      const checkout = await completeCheckout('agent_dispute', 'spt_test_dispute');

      const result = await sendWebhook(
        stripeEvent({
          id: 'evt_dispute_1',
          type: 'charge.dispute.created',
          object: { object: 'dispute', id: 'dp_test_1', charge: checkout.payment.charge_id },
        }),
      );

      expect(result.json().outcome).toBe('REVERSED');
      expect(
        await harness.deps.repositories.conversions.accountBalance(
          harness.merchant.id,
          LEDGER_ACCOUNTS.agentPayable,
          'USD',
        ),
      ).toBe(0);
    });

    it('does not resurrect a refunded conversion on a late settlement event', async () => {
      const checkout = await completeCheckout('agent_late', 'spt_test_late');

      await sendWebhook(
        stripeEvent({
          id: 'evt_late_refund',
          type: 'charge.refunded',
          object: { object: 'charge', id: checkout.payment.charge_id, payment_intent: checkout.payment.payment_intent_id },
        }),
      );
      const late = await sendWebhook(
        stripeEvent({
          id: 'evt_late_success',
          type: 'payment_intent.succeeded',
          object: { object: 'payment_intent', id: checkout.payment.payment_intent_id },
        }),
      );

      expect(late.json().outcome).toBe('IGNORED_ALREADY_REFUNDED');
      const parent = await harness.deps.repositories.conversions.findById(checkout.order_id);
      expect(parent?.status).toBe('REFUNDED');
    });

    it('acknowledges an event that matches no conversion instead of retrying forever', async () => {
      const result = await sendWebhook(
        stripeEvent({
          id: 'evt_orphan_1',
          type: 'charge.refunded',
          object: { object: 'charge', id: 'ch_unknown', payment_intent: 'pi_unknown' },
        }),
      );

      expect(result.statusCode).toBe(200);
      expect(result.json().outcome).toBe('IGNORED_NO_MATCHING_CONVERSION');
    });

    it('acknowledges an event type the ledger does not act on', async () => {
      const result = await sendWebhook(
        stripeEvent({
          id: 'evt_unhandled_1',
          type: 'customer.created',
          object: { object: 'customer', id: 'cus_1' },
        }),
      );

      expect(result.statusCode).toBe(200);
      expect(result.json().outcome).toBe('IGNORED_UNHANDLED_TYPE');
    });
  });

  /* ---------------------------------------------------------------------- */
  /* TASK 6 gate: the full synthetic cycle                                   */
  /* ---------------------------------------------------------------------- */

  describe('full synthetic cycle: discovery -> search -> checkout -> refund reconciliation', () => {
    it('completes and reconciles to a zero net ledger', async () => {
      // 1. Discovery
      const discovery = await harness.app.inject({ method: 'GET', url: '/.well-known/acp/config.json' });
      expect(discovery.statusCode).toBe(200);
      const config = AcpConfigSchema.parse(discovery.json());

      // 2. Search
      const search = await harness.app.inject({
        method: 'POST',
        url: config.endpoints.catalog_query,
        payload: {
          agent_id: 'openai_chatgpt_operator_1',
          query: 'wireless noise cancelling headphones under 300',
          max_results: 1,
          sub_ids: { sub1: 'campaign_alpha', sub2: 'prompt_v4' },
        },
      });
      expect(search.statusCode).toBe(200);
      const offer = search.json().results[0];
      expect(isUuidV7(offer.acp_token)).toBe(true);

      // 3. Delegated checkout
      const checkout = await harness.app.inject({
        method: 'POST',
        url: config.endpoints.checkout_execution,
        payload: {
          acp_token: offer.acp_token,
          merchant_id: offer.merchant_id,
          variant_id: offer.variant_id,
          quantity: 1,
          payment_credential: { type: 'stripe_payment_token', token: 'spt_test_cycle' },
          shipping_address: SHIPPING_ADDRESS,
          attribution_signature: offer.attribution.signature,
        },
      });
      expect(checkout.statusCode).toBe(201);
      const order = checkout.json();
      expect(order.external_order_id).toBeTruthy();

      // 4. Settlement
      const settled = await sendWebhook(
        stripeEvent({
          id: 'evt_cycle_settle',
          type: 'payment_intent.succeeded',
          object: { object: 'payment_intent', id: order.payment.payment_intent_id, latest_charge: order.payment.charge_id },
        }),
      );
      expect(settled.json().outcome).toBe('SETTLED');

      // 5. Refund reconciliation
      const refunded = await sendWebhook(
        stripeEvent({
          id: 'evt_cycle_refund',
          type: 'charge.refunded',
          object: { object: 'charge', id: order.payment.charge_id, payment_intent: order.payment.payment_intent_id },
        }),
      );
      expect(refunded.json().outcome).toBe('REVERSED');

      // 6. Order status reports the sale and its offsetting reversal.
      const status = await harness.app.inject({ method: 'GET', url: order.order_status_url.replace(/^https?:\/\/[^/]+/, '') });
      expect(status.statusCode).toBe(200);
      const statusBody = status.json();
      expect(statusBody.status).toBe('REFUNDED');
      expect(statusBody.reversals).toHaveLength(1);
      expect(statusBody.net_amounts).toMatchObject({
        gross_amount_cents: 0,
        commission_total_cents: 0,
        aisl_fee_cents: 0,
        agent_payout_cents: 0,
      });

      expect(await harness.deps.repositories.conversions.findUnbalancedEntryGroups()).toEqual([]);
    });
  });

  /* ---------------------------------------------------------------------- */
  /* Helpers                                                                 */
  /* ---------------------------------------------------------------------- */

  async function mintToken(agentId: string): Promise<{ token: string; variantId: string; signature: string }> {
    const response = await harness.app.inject({
      method: 'POST',
      url: '/v1/agent/intent',
      payload: { agent_id: agentId, query: 'noise cancelling headphones', max_results: 1 },
    });
    const result = response.json().results[0];
    if (!result) throw new Error('intent search returned no products');
    return { token: result.acp_token, variantId: result.variant_id, signature: result.attribution.signature };
  }

  async function completeCheckout(
    agentId: string,
    paymentToken: string,
  ): Promise<{ order_id: string; payment: { payment_intent_id: string; charge_id: string } }> {
    const { token, variantId } = await mintToken(agentId);
    const response = await harness.app.inject({
      method: 'POST',
      url: '/v1/agent/checkout',
      payload: {
        acp_token: token,
        merchant_id: harness.merchant.id,
        variant_id: variantId,
        quantity: 1,
        payment_credential: { type: 'stripe_payment_token', token: paymentToken },
        shipping_address: SHIPPING_ADDRESS,
      },
    });
    if (response.statusCode !== 201) {
      throw new Error(`checkout failed: ${response.statusCode} ${response.body}`);
    }
    return response.json();
  }

  async function sendWebhook(event: unknown) {
    const { payload, signature } = harness.signedWebhook(event);
    return harness.app.inject({
      method: 'POST',
      url: '/v1/webhooks/stripe-acp',
      headers: { 'content-type': 'application/json', 'stripe-signature': signature },
      payload,
    });
  }
});
