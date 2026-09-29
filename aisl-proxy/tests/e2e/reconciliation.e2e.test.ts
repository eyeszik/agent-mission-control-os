import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { ConversionRepository } from '../../src/db/repositories/conversions.js';
import { PayoutRepository } from '../../src/db/repositories/payouts.js';
import { ReconciliationService } from '../../src/services/reconciliationService.js';
import { computeCommissionSplit } from '../../src/lib/money.js';
import { newClickId } from '../../src/lib/ids.js';
import { buildServer } from '../../src/app.js';
import { startHarness, truncateTransactional, type Harness } from '../helpers/harness.js';

let harness: Harness;
let service: ReconciliationService;

function serviceWith(thresholds?: { pendingSettlementMinutes?: number; stalePayoutMinutes?: number }) {
  return new ReconciliationService({
    db: harness.db,
    conversions: new ConversionRepository(harness.db),
    payouts: new PayoutRepository(harness.db),
    ...(thresholds ? { thresholds } : {}),
  });
}

beforeAll(async () => {
  harness = await startHarness();
  service = serviceWith();
});

afterAll(async () => {
  await harness.close();
});

beforeEach(async () => {
  await truncateTransactional(harness.db);
});

async function seedSale(options: { agentId: string; orderId: string; settle?: boolean }) {
  const clickId = newClickId();
  await harness.db.query(`INSERT INTO agent_intents (click_id, agent_id, merchant_id) VALUES ($1, $2, $3)`, [
    clickId,
    options.agentId,
    harness.merchant.id,
  ]);
  const conversion = await harness.deps.repositories.conversions.recordSale({
    clickId,
    merchantId: harness.merchant.id,
    agentId: options.agentId,
    externalOrderId: options.orderId,
    currency: 'USD',
    stripePaymentIntentId: `pi_${options.orderId}`,
    stripeChargeId: `ch_${options.orderId}`,
    split: computeCommissionSplit({ grossAmountCents: 100_000, commissionRateBps: 500, aislCutBps: 80 }),
  });
  if (options.settle) {
    await harness.deps.repositories.conversions.markSettled(conversion.id, conversion.stripeChargeId);
  }
  return conversion;
}

describe('reconciliation', () => {
  it('reports healthy on a clean ledger', async () => {
    const report = await service.run();

    expect(report.healthy).toBe(true);
    expect(report.findings).toEqual([]);
    expect(Date.parse(report.checkedAt)).not.toBeNaN();
  });

  it('stays healthy through a normal sale, settlement and refund cycle', async () => {
    const sale = await seedSale({ agentId: 'agent_clean', orderId: 'recon-clean', settle: true });
    await harness.deps.repositories.conversions.recordReversal({
      parent: sale,
      reversalReference: 'evt_clean_refund',
      memo: 'refund',
    });

    expect((await service.run()).healthy).toBe(true);
  });

  it('raises a critical finding when an entry group does not balance', async () => {
    const sale = await seedSale({ agentId: 'agent_corrupt', orderId: 'recon-corrupt', settle: true });
    // Simulate corruption the application layer refuses to write: a stray leg
    // with no offsetting counterpart.
    await harness.db.query(
      `INSERT INTO ledger_entries
         (entry_group_id, conversion_id, merchant_id, account, direction, amount_cents, currency, memo)
       VALUES (gen_random_uuid(), $1, $2, 'agent_payable', 'CREDIT', 500, 'USD', 'injected corruption')`,
      [sale.id, harness.merchant.id],
    );

    const report = await service.run();
    expect(report.healthy).toBe(false);
    expect(report.findings.map((finding) => finding.check)).toContain('ledger_unbalanced');
    expect(report.findings.find((finding) => finding.check === 'ledger_unbalanced')?.severity).toBe('critical');
  });

  it('flags a settlement webhook that matched no conversion', async () => {
    await harness.db.query(
      `INSERT INTO webhook_events (event_id, event_type, payload_sha256, outcome)
       VALUES ('evt_orphan_1', 'payment_intent.succeeded', repeat('a', 64), 'IGNORED_NO_MATCHING_CONVERSION')`,
    );

    const report = await service.run();
    const finding = report.findings.find((candidate) => candidate.check === 'orphaned_capture');
    expect(finding).toMatchObject({ severity: 'critical', count: 1 });
    expect(finding?.samples).toContain('evt_orphan_1');
  });

  it('does not flag an unmatched refund, which is routine', async () => {
    await harness.db.query(
      `INSERT INTO webhook_events (event_id, event_type, payload_sha256, outcome)
       VALUES ('evt_other_refund', 'charge.refunded', repeat('b', 64), 'IGNORED_NO_MATCHING_CONVERSION')`,
    );

    const report = await service.run();
    expect(report.findings.map((finding) => finding.check)).not.toContain('orphaned_capture');
  });

  it('warns about a capture whose settlement never arrived', async () => {
    const sale = await seedSale({ agentId: 'agent_stuck', orderId: 'recon-stuck' });
    await harness.db.query(`UPDATE conversions SET created_at = NOW() - INTERVAL '3 days' WHERE id = $1`, [sale.id]);

    const report = await service.run();
    const finding = report.findings.find((candidate) => candidate.check === 'settlement_overdue');
    expect(finding).toMatchObject({ severity: 'warning', count: 1 });
    expect(finding?.samples).toContain(sale.id);

    // A generous threshold makes the same row unremarkable.
    const relaxed = await serviceWith({ pendingSettlementMinutes: 10 * 24 * 60 }).run();
    expect(relaxed.findings.map((f) => f.check)).not.toContain('settlement_overdue');
  });

  it('escalates a payout claim that never resolved', async () => {
    const payouts = new PayoutRepository(harness.db);
    await payouts.upsertAgentAccount({ agentId: 'agent_limbo', stripeAccountId: 'acct_limbo' });
    await seedSale({ agentId: 'agent_limbo', orderId: 'recon-limbo', settle: true });

    const claim = await payouts.claim('agent_limbo', 'USD');
    expect(claim).not.toBeNull();
    await harness.db.query(`UPDATE payouts SET created_at = NOW() - INTERVAL '4 hours' WHERE id = $1`, [
      claim?.payout.id,
    ]);

    const report = await service.run();
    const finding = report.findings.find((candidate) => candidate.check === 'payout_in_flight_stale');
    expect(finding).toMatchObject({ severity: 'critical', count: 1 });
    expect(finding?.detail).toMatch(/idempotency key/);
  });

  it('warns when commission accrues for an agent that cannot be paid', async () => {
    await seedSale({ agentId: 'agent_nowhere', orderId: 'recon-nowhere', settle: true });

    const report = await service.run();
    const finding = report.findings.find((candidate) => candidate.check === 'balance_unpayable');
    expect(finding).toMatchObject({ severity: 'warning', count: 1 });
    expect(finding?.samples[0]).toContain('agent_nowhere');
  });

  it('serves the operator probe with a status a monitor can alert on', async () => {
    const healthy = await harness.app.inject({ method: 'GET', url: '/internal/reconciliation' });
    expect(healthy.statusCode).toBe(200);
    expect(healthy.json()).toMatchObject({ healthy: true, findings: [] });

    await harness.db.query(
      `INSERT INTO webhook_events (event_id, event_type, payload_sha256, outcome)
       VALUES ('evt_probe_orphan', 'charge.succeeded', repeat('c', 64), 'IGNORED_NO_MATCHING_CONVERSION')`,
    );

    const degraded = await harness.app.inject({ method: 'GET', url: '/internal/reconciliation' });
    expect(degraded.statusCode).toBe(503);
    expect(degraded.json().healthy).toBe(false);
  });

  it('does not require agent authentication on the operator probe', async () => {
    // The shared harness runs with auth off, so assert against a server built
    // with it on: the agent routes must reject an unauthenticated caller while
    // the probe stays reachable by a monitor that holds no payment-capable key.
    const guarded = await buildServer({
      ...harness.deps,
      env: { ...harness.deps.env, AISL_REQUIRE_AGENT_AUTH: true, AISL_AGENT_API_KEYS: ['monitor_test_key'] },
    });
    await guarded.ready();

    try {
      const agentRoute = await guarded.inject({
        method: 'POST',
        url: '/v1/agent/intent',
        headers: { 'content-type': 'application/json' },
        payload: { agent_id: 'x', query: 'y' },
      });
      expect(agentRoute.statusCode).toBe(401);

      const probe = await guarded.inject({ method: 'GET', url: '/internal/reconciliation' });
      expect(probe.statusCode).toBe(200);
    } finally {
      await guarded.close();
    }
  });
});
