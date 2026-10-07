import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { PayoutRepository } from '../../src/db/repositories/payouts.js';
import { StripeTransferProcessor } from '../../src/connectors/stripe/transfers.js';
import { PayoutService } from '../../src/services/payoutService.js';
import { computeCommissionSplit } from '../../src/lib/money.js';
import type { Merchant } from '../../src/db/repositories/merchants.js';
import { startHarness, truncateTransactional, type Harness } from '../helpers/harness.js';

const SILENT = { info: () => {}, warn: () => {}, error: () => {} };

const SHIPPING_ADDRESS = {
  name: 'Ada Lovelace',
  address1: '12 Analytical Way',
  city: 'London',
  postal_code: 'EC1A 1AA',
  country: 'GB',
};

let harness: Harness;

beforeAll(async () => {
  harness = await startHarness();
});

afterAll(async () => {
  await harness.close();
});

beforeEach(async () => {
  await truncateTransactional(harness.db);
  harness.stripe.state.paymentIntents.length = 0;
  harness.stripe.state.refunds.length = 0;
  harness.stripe.state.transfers.length = 0;
  harness.stripe.state.failRefunds = false;
  harness.stripe.state.failTransfers = false;
});

async function checkout(agentId: string, merchant: Merchant = harness.merchant) {
  const intent = await harness.app.inject({
    method: 'POST',
    url: '/v1/agent/intent',
    payload: { agent_id: agentId, query: 'noise cancelling headphones', max_results: 25 },
  });
  const result = intent.json().results.find((item: { merchant_id: string }) => item.merchant_id === merchant.id);
  if (!result) throw new Error(`no catalogue result for merchant ${merchant.id}`);

  return harness.app.inject({
    method: 'POST',
    url: '/v1/agent/checkout',
    payload: {
      acp_token: result.acp_token,
      merchant_id: merchant.id,
      variant_id: result.variant_id,
      quantity: 1,
      payment_credential: { type: 'stripe_payment_token', token: `spt_${agentId}` },
      shipping_address: SHIPPING_ADDRESS,
    },
  });
}

describe('commission collection', () => {
  it('routes the whole commission to the platform as an application fee', async () => {
    const response = await checkout('agent_fee_basic');
    expect(response.statusCode).toBe(201);

    const intent = harness.stripe.state.paymentIntents[0];
    expect(intent).toBeDefined();

    const expected = computeCommissionSplit({
      grossAmountCents: intent!.amount,
      commissionRateBps: harness.merchant.commissionRateBps,
      aislCutBps: harness.merchant.aislCutBps,
    });

    // The fee is the WHOLE commission, not just the platform's slice: the
    // platform owes the agent the rest and pays it from this balance.
    expect(intent!.applicationFeeAmount).toBe(expected.commissionTotalCents);
    expect(intent!.applicationFeeAmount).toBeGreaterThan(expected.agentPayoutCents);
  });

  it('creates the charge on the merchant account so the fee is the only thing the platform keeps', async () => {
    await checkout('agent_fee_account');

    const intent = harness.stripe.state.paymentIntents[0];
    expect(intent!.stripeAccount).toBe('acct_test_merchant');
    // Merchant keeps gross minus the fee; the platform keeps exactly the fee.
    expect(intent!.amount - (intent!.applicationFeeAmount ?? 0)).toBe(
      computeCommissionSplit({
        grossAmountCents: intent!.amount,
        commissionRateBps: harness.merchant.commissionRateBps,
        aislCutBps: harness.merchant.aislCutBps,
      }).merchantNetCents,
    );
  });

  it('collects enough to fund the agent payout it books', async () => {
    const response = await checkout('agent_fee_funded');
    const body = response.json();

    const conversion = await harness.deps.repositories.conversions.findByExternalOrderId(body.external_order_id);
    const collected = harness.stripe.state.paymentIntents[0]?.applicationFeeAmount ?? 0;

    // The invariant that makes the business solvent: every cent owed to the
    // agent was already collected from the merchant on the same charge.
    expect(collected).toBeGreaterThanOrEqual(conversion!.split.agentPayoutCents);
    expect(collected - conversion!.split.agentPayoutCents).toBe(conversion!.split.aislFeeCents);
  });

  it('ends a settled-and-paid cycle with the platform up by exactly its own fee', async () => {
    const response = await checkout('agent_fee_cycle');
    const body = response.json();

    const conversion = await harness.deps.repositories.conversions.findByExternalOrderId(body.external_order_id);
    await harness.deps.repositories.conversions.markSettled(conversion!.id, conversion!.stripeChargeId);

    const payouts = new PayoutRepository(harness.db);
    await payouts.upsertAgentAccount({ agentId: 'agent_fee_cycle', stripeAccountId: 'acct_fee_cycle' });
    const run = await new PayoutService({
      payouts,
      transfers: new StripeTransferProcessor(harness.stripeClient),
      logger: SILENT,
    }).run();

    expect(run.paidCount).toBe(1);

    const collected = harness.stripe.state.paymentIntents[0]?.applicationFeeAmount ?? 0;
    const transferred = harness.stripe.state.transfers[0]?.amount ?? 0;

    // Cash in minus cash out equals the platform's booked revenue. Before the
    // application fee existed this figure was negative by the agent's payout.
    expect(collected - transferred).toBe(conversion!.split.aislFeeCents);
    expect(collected - transferred).toBeGreaterThan(0);
  });

  it('refuses a merchant with commission configured but no connected account', async () => {
    const stranded = await harness.deps.repositories.merchants.create({
      name: 'Stranded Co',
      commissionRateBps: 500,
      aislCutBps: 80,
      credentials: {
        platform: 'shopify',
        store_domain: harness.shopify.domain,
        storefront_token: 'shpstf_test_token',
        storefront_api_version: '2026-01',
        admin_token: 'shpat_test_token',
        admin_api_version: '2026-01',
        // No stripe_account_id: nothing could collect the commission.
      },
    });

    const response = await checkout('agent_stranded', stranded);

    // Failing loudly beats silently charging the buyer and losing the
    // commission on every sale.
    expect(response.statusCode).toBeGreaterThanOrEqual(500);
    expect(harness.stripe.state.paymentIntents).toHaveLength(0);

    await harness.deps.repositories.merchants.setEnabled(stranded.id, false);
  });

  it('sends no application fee when the merchant charges no commission', async () => {
    const freeMerchant = await harness.deps.repositories.merchants.create({
      name: 'Zero Commission Co',
      commissionRateBps: 0,
      aislCutBps: 0,
      credentials: {
        platform: 'shopify',
        store_domain: harness.shopify.domain,
        storefront_token: 'shpstf_test_token',
        storefront_api_version: '2026-01',
        admin_token: 'shpat_test_token',
        admin_api_version: '2026-01',
        stripe_account_id: 'acct_zero_commission',
      },
    });

    const response = await checkout('agent_zero', freeMerchant);
    expect(response.statusCode).toBe(201);

    const intent = harness.stripe.state.paymentIntents.find((i) => i.stripeAccount === 'acct_zero_commission');
    expect(intent?.applicationFeeAmount).toBeNull();

    await harness.deps.repositories.merchants.setEnabled(freeMerchant.id, false);
  });
});

describe('compensating refund on a direct charge', () => {
  it('targets the connected account and gives back the commission', async () => {
    // Force order dispatch to fail after the capture succeeds.
    harness.shopify.state.failNextOrder = true;
    try {
      const response = await checkout('agent_refund_path');
      expect(response.statusCode).toBeGreaterThanOrEqual(400);
    } finally {
      harness.shopify.state.failNextOrder = false;
    }

    const refund = harness.stripe.state.refunds[0];
    expect(refund).toBeDefined();
    // A refund that forgets Stripe-Account cannot see a direct charge at all.
    expect(refund!.stripeAccount).toBe('acct_test_merchant');
    // Unwinding the sale unwinds the fee; keeping it would be revenue on a
    // transaction that did not happen.
    expect(refund!.refundApplicationFee).toBe(true);

    // No conversion was booked, so nothing is owed to the agent either.
    expect(await new PayoutRepository(harness.db).pendingBalances()).toEqual([]);
  });
});
