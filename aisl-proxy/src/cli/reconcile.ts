import { loadEnv } from '../config/env.js';
import { createDatabase } from '../db/pool.js';
import { ConversionRepository } from '../db/repositories/conversions.js';
import { PayoutRepository } from '../db/repositories/payouts.js';
import { ReconciliationService } from '../services/reconciliationService.js';
import { numberArg, parseArgs } from './args.js';

/**
 * Report the states that need a human.
 *
 * Exits 0 when clean, 1 when anything is outstanding, so it can run from cron
 * and page on a non-zero exit:
 *
 *   npm run reconcile
 *   npm run reconcile -- --stale-payout-minutes 30
 */
async function main(): Promise<void> {
  const args = parseArgs(process.argv.slice(2));
  const env = loadEnv();
  const db = createDatabase(env);

  try {
    const pendingSettlementMinutes = numberArg(args, 'pending-settlement-minutes');
    const stalePayoutMinutes = numberArg(args, 'stale-payout-minutes');

    const report = await new ReconciliationService({
      db,
      conversions: new ConversionRepository(db),
      payouts: new PayoutRepository(db),
      thresholds: {
        ...(pendingSettlementMinutes !== undefined ? { pendingSettlementMinutes } : {}),
        ...(stalePayoutMinutes !== undefined ? { stalePayoutMinutes } : {}),
      },
    }).run();

    process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
    if (!report.healthy) {
      process.exitCode = 1;
    }
  } finally {
    await db.close();
  }
}

main().catch((error: unknown) => {
  process.stderr.write(`reconciliation failed: ${error instanceof Error ? error.message : String(error)}\n`);
  process.exit(1);
});
