import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { PayoutRepository } from '../../src/db/repositories/payouts.js';
import { StripeTransferProcessor } from '../../src/connectors/stripe/transfers.js';
import { PayoutService } from '../../src/services/payoutService.js';
import { LEDGER_ACCOUNTS } from '../../src/db/repositories/conversions.js';
import { computeCommissionSplit } from '../../src/lib/money.js';
import { newClickId } from '../../src/lib/ids.js';
import { startHarness, truncateTransactional, type Harness } from '../helpers/harness.js';

const SILENT = { info: () => {}, warn: () => {}, error: () => {} };

let harness: Harness;
let payouts: PayoutRepository;
let service: PayoutService;

beforeAll(async () => {
  harness = await startHarness();
  payouts = new PayoutRepository(harness.db);
  service = new PayoutService({
    payouts,
    transfers: new StripeTransferProcessor(harness.stripeClient),
    logger: SILENT,
  });
});

afterAll(async () => {
  await harness.close();
});

beforeEach(async () => {
  await truncateTransactional(harness.db);
  harness.stripe.state.transfers.length = 0;
  harness.stripe.state.failTransfers = false;
});

/**
 * Seed one attributed, captured sale. Mirrors what checkout + the settlement
 * webhook leave behind, without driving the whole HTTP path again.
 */
async function seedSettledSale(options: {
  agentId: string;
  grossCents: number;
  orderId: string;
  settle?: boolean;
}) {
  const clickId = newClickId();
  await harness.db.query(
    `INSERT INTO agent_intents (click_id, agent_id, merchant_id) VALUES ($1, $2, $3)`,
    [clickId, options.agentId, harness.merchant.id],
  );

  const split = computeCommissionSplit({
    grossAmountCents: options.grossCents,
    commissionRateBps: harness.merchant.commissionRateBps,
    aislCutBps: harness.merchant.aislCutBps,
  });

  const conversion = await harness.deps.repositories.conversions.recordSale({
    clickId,
    merchantId: harness.merchant.id,
    agentId: options.agentId,
    externalOrderId: options.orderId,
    currency: 'USD',
    stripePaymentIntentId: `pi_seed_${options.orderId}`,
    stripeChargeId: `ch_seed_${options.orderId}`,
    split,
  });

  if (options.settle !== false) {
    await harness.deps.repositories.conversions.markSettled(conversion.id, conversion.stripeChargeId);
  }
  return { conversion, split };
}

async function registerAgent(agentId: string, overrides: Partial<{ minimumPayoutCents: number }> = {}) {
  return payouts.upsertAgentAccount({
    agentId,
    stripeAccountId: `acct_${agentId}`,
    payoutCurrency: 'USD',
    minimumPayoutCents: overrides.minimumPayoutCents ?? 0,
    payoutsEnabled: true,
  });
}

describe('payout eligibility', () => {
  it('counts a settled sale and ignores one still awaiting settlement', async () => {
    await seedSettledSale({ agentId: 'agent_a', grossCents: 100_000, orderId: 'order-settled' });
    await seedSettledSale({
      agentId: 'agent_a',
      grossCents: 250_000,
      orderId: 'order-pending',
      settle: false,
    });

    const balances = await payouts.pendingBalances();
    expect(balances).toHaveLength(1);
    // 100000 * 500bps = 5000 commission; 100000 * 80bps = 800 platform fee.
    expect(balances[0]).toMatchObject({ agentId: 'agent_a', currency: 'USD', amountCents: 4_200, itemCount: 1 });
  });

  it('does not claw back commission that was never paid out', async () => {
    const { conversion } = await seedSettledSale({
      agentId: 'agent_b',
      grossCents: 100_000,
      orderId: 'order-refunded-early',
    });
    await harness.deps.repositories.conversions.recordReversal({
      parent: conversion,
      reversalReference: 'evt_early_refund',
      memo: 'refund before payout',
    });

    // The sale left the eligible set (REFUNDED) and its reversal never entered
    // it, because nothing was ever transferred to reclaim.
    const balances = await payouts.pendingBalances();
    expect(balances).toHaveLength(0);
  });
});

describe('payout runs', () => {
  it('transfers the accrued balance and discharges agent_payable', async () => {
    await registerAgent('agent_c');
    await seedSettledSale({ agentId: 'agent_c', grossCents: 100_000, orderId: 'order-c1' });
    await seedSettledSale({ agentId: 'agent_c', grossCents: 50_000, orderId: 'order-c2' });

    const before = await harness.deps.repositories.conversions.accountBalance(
      harness.merchant.id,
      LEDGER_ACCOUNTS.agentPayable,
      'USD',
    );
    // Credits are negative under (debits - credits), so the liability is -6300.
    expect(before).toBe(-6_300);

    const result = await service.run();
    expect(result.paidCount).toBe(1);
    expect(result.paidCents).toBe(6_300);

    const transfer = harness.stripe.state.transfers[0];
    expect(transfer).toMatchObject({ amount: 6_300, currency: 'usd', destination: 'acct_agent_c' });
    expect(transfer?.metadata.aisl_agent_id).toBe('agent_c');

    const after = await harness.deps.repositories.conversions.accountBalance(
      harness.merchant.id,
      LEDGER_ACCOUNTS.agentPayable,
      'USD',
    );
    expect(after).toBe(0);

    const cash = await harness.deps.repositories.conversions.accountBalance(
      harness.merchant.id,
      LEDGER_ACCOUNTS.agentCash,
      'USD',
    );
    expect(cash).toBe(-6_300);
    expect(await harness.deps.repositories.conversions.findUnbalancedEntryGroups()).toEqual([]);
  });

  it('is idempotent: a second run with nothing new transfers nothing', async () => {
    await registerAgent('agent_d');
    await seedSettledSale({ agentId: 'agent_d', grossCents: 100_000, orderId: 'order-d1' });

    await service.run();
    const second = await service.run();

    expect(second.paidCount).toBe(0);
    expect(harness.stripe.state.transfers).toHaveLength(1);
  });

  it('never pays the same conversion twice under concurrent runs', async () => {
    await registerAgent('agent_e');
    await seedSettledSale({ agentId: 'agent_e', grossCents: 400_000, orderId: 'order-e1' });

    const [first, second] = await Promise.allSettled([service.run(), service.run()]);
    const paid = [first, second].filter(
      (outcome) => outcome.status === 'fulfilled' && outcome.value.paidCount === 1,
    );

    expect(paid).toHaveLength(1);
    expect(harness.stripe.state.transfers).toHaveLength(1);
    expect(harness.stripe.state.transfers[0]?.amount).toBe(16_800);
  });

  it('releases the claim when the transfer fails, so the next run retries it', async () => {
    await registerAgent('agent_f');
    await seedSettledSale({ agentId: 'agent_f', grossCents: 100_000, orderId: 'order-f1' });

    harness.stripe.state.failTransfers = true;
    const failed = await service.run();
    expect(failed.failedCount).toBe(1);

    const history = await payouts.listByAgent('agent_f');
    expect(history[0]?.status).toBe('FAILED');
    expect(history[0]?.failureCode).toBe('balance_insufficient');

    // The money is claimable again, and no ledger leg was written for it.
    expect(await payouts.pendingBalances()).toMatchObject([{ agentId: 'agent_f', amountCents: 4_200 }]);

    harness.stripe.state.failTransfers = false;
    const retried = await service.run();
    expect(retried.paidCount).toBe(1);
    expect(await payouts.pendingBalances()).toEqual([]);
  });

  it('claws a refund back out of the next payout', async () => {
    await registerAgent('agent_g');
    const first = await seedSettledSale({ agentId: 'agent_g', grossCents: 100_000, orderId: 'order-g1' });

    await service.run();
    expect(harness.stripe.state.transfers[0]?.amount).toBe(4_200);

    // The paid sale is refunded, then a larger sale lands.
    await harness.deps.repositories.conversions.recordReversal({
      parent: first.conversion,
      reversalReference: 'evt_late_refund',
      memo: 'refund after payout',
    });
    await seedSettledSale({ agentId: 'agent_g', grossCents: 300_000, orderId: 'order-g2' });

    const second = await service.run();
    expect(second.paidCount).toBe(1);
    // 12600 earned minus the 4200 already paid on the refunded order.
    expect(second.paidCents).toBe(8_400);
    expect(harness.stripe.state.transfers[1]?.amount).toBe(8_400);
  });

  it('carries a negative net forward instead of transferring it', async () => {
    await registerAgent('agent_h');
    const sale = await seedSettledSale({ agentId: 'agent_h', grossCents: 200_000, orderId: 'order-h1' });
    await service.run();

    await harness.deps.repositories.conversions.recordReversal({
      parent: sale.conversion,
      reversalReference: 'evt_h_refund',
      memo: 'full refund',
    });

    const result = await service.run();
    expect(result.paidCount).toBe(0);
    // The debt is still outstanding and still visible.
    expect(await payouts.pendingBalances()).toMatchObject([{ agentId: 'agent_h', amountCents: -8_400 }]);

    // A later sale nets against it rather than paying gross.
    await seedSettledSale({ agentId: 'agent_h', grossCents: 300_000, orderId: 'order-h2' });
    const netted = await service.run();
    expect(netted.paidCents).toBe(12_600 - 8_400);
  });
});

describe('payout gating', () => {
  it('skips an agent with no registered account', async () => {
    await seedSettledSale({ agentId: 'agent_unknown', grossCents: 100_000, orderId: 'order-unknown' });
    const result = await service.run();

    expect(result.outcomes).toMatchObject([{ agentId: 'agent_unknown', status: 'skipped', reason: 'no_account' }]);
    expect(harness.stripe.state.transfers).toHaveLength(0);
  });

  it('skips an agent registered without a payout destination', async () => {
    await payouts.upsertAgentAccount({ agentId: 'agent_i', payoutCurrency: 'USD' });
    await seedSettledSale({ agentId: 'agent_i', grossCents: 100_000, orderId: 'order-i1' });

    const result = await service.run();
    expect(result.outcomes).toMatchObject([{ status: 'skipped', reason: 'no_destination' }]);
  });

  it('accrues below the configured minimum', async () => {
    await registerAgent('agent_j', { minimumPayoutCents: 10_000 });
    await seedSettledSale({ agentId: 'agent_j', grossCents: 100_000, orderId: 'order-j1' });

    const held = await service.run();
    expect(held.outcomes).toMatchObject([{ status: 'skipped', reason: 'below_minimum', amountCents: 4_200 }]);

    // Enough accrual clears the bar, and the whole balance goes at once.
    await seedSettledSale({ agentId: 'agent_j', grossCents: 200_000, orderId: 'order-j2' });
    const released = await service.run();
    expect(released.paidCents).toBe(12_600);
  });

  it('skips an agent whose payouts are disabled', async () => {
    await payouts.upsertAgentAccount({
      agentId: 'agent_k',
      stripeAccountId: 'acct_agent_k',
      payoutsEnabled: false,
    });
    await seedSettledSale({ agentId: 'agent_k', grossCents: 100_000, orderId: 'order-k1' });

    const result = await service.run();
    expect(result.outcomes).toMatchObject([{ status: 'skipped', reason: 'payouts_disabled' }]);
  });
});
