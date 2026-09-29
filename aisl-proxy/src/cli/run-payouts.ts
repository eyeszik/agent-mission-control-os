import Stripe from 'stripe';
import { loadEnv } from '../config/env.js';
import { createDatabase } from '../db/pool.js';
import { PayoutRepository } from '../db/repositories/payouts.js';
import { StripeTransferProcessor } from '../connectors/stripe/transfers.js';
import { PayoutService } from '../services/payoutService.js';
import { boolArg, cliLogger, parseArgs } from './args.js';

/**
 * Sweep accrued agent commission and transfer it.
 *
 * Intended to run on a schedule (cron, a Kubernetes CronJob, or a container
 * sidecar). Safe to run concurrently with itself: claiming is atomic and the
 * UNIQUE index on `payout_items.conversion_id` makes a double claim a
 * constraint violation rather than a double transfer.
 *
 *   npm run payouts -- --dry-run
 *   npm run payouts -- --agent-id agent_acme
 *
 * Exits non-zero if any payout failed, so a scheduler surfaces it.
 */
async function main(): Promise<void> {
  const args = parseArgs(process.argv.slice(2));
  const env = loadEnv();
  const db = createDatabase(env);

  try {
    const stripe = new Stripe(env.STRIPE_SECRET_KEY || 'sk_test_unconfigured', {
      apiVersion: env.STRIPE_API_VERSION as Stripe.StripeConfig['apiVersion'],
      timeout: env.CONNECTOR_TIMEOUT_MS,
      maxNetworkRetries: 2,
      telemetry: false,
    });

    const service = new PayoutService({
      payouts: new PayoutRepository(db),
      transfers: new StripeTransferProcessor(stripe),
      logger: cliLogger,
    });

    const agentId = args.get('agent-id');
    const result = await service.run({
      dryRun: boolArg(args, 'dry-run'),
      ...(agentId ? { agentId } : {}),
    });

    process.stdout.write(`${JSON.stringify(summarise(result), null, 2)}\n`);
    if (result.failedCount > 0) {
      process.exitCode = 1;
    }
  } finally {
    await db.close();
  }
}

function summarise(result: Awaited<ReturnType<PayoutService['run']>>) {
  return {
    paid_count: result.paidCount,
    paid_cents: result.paidCents,
    failed_count: result.failedCount,
    skipped_count: result.skippedCount,
    outcomes: result.outcomes.map((outcome) => ({
      agent_id: outcome.agentId,
      currency: outcome.currency,
      status: outcome.status,
      ...(outcome.status === 'skipped'
        ? { reason: outcome.reason, pending_cents: outcome.amountCents }
        : {
            payout_id: outcome.payout.id,
            amount_cents: outcome.payout.amountCents,
            ...(outcome.status === 'paid'
              ? { transfer_id: outcome.payout.stripeTransferId }
              : { reason: outcome.reason }),
          }),
    })),
  };
}

main().catch((error: unknown) => {
  process.stderr.write(`payout run failed: ${error instanceof Error ? error.message : String(error)}\n`);
  process.exit(1);
});
