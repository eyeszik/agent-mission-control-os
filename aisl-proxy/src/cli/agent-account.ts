import { loadEnv } from '../config/env.js';
import { createDatabase } from '../db/pool.js';
import { PayoutRepository } from '../db/repositories/payouts.js';
import { numberArg, parseArgs } from './args.js';

/**
 * Register or update the payout destination for an agent.
 *
 * Until an agent has a row here with `stripe_account_id` set and payouts
 * enabled, its commission accrues in the ledger and every sweep skips it — by
 * design, so money is never sent to a destination nobody configured.
 *
 *   npx tsx src/cli/agent-account.ts --agent-id agent_acme \
 *     --stripe-account acct_123 --currency USD --minimum-cents 5000
 *   npx tsx src/cli/agent-account.ts --agent-id agent_acme --disable
 */
async function main(): Promise<void> {
  const args = parseArgs(process.argv.slice(2));
  const agentId = args.get('agent-id');
  if (!agentId) {
    throw new Error('--agent-id is required');
  }

  const env = loadEnv();
  const db = createDatabase(env);
  try {
    const repository = new PayoutRepository(db);
    const existing = await repository.findAgentAccount(agentId);

    const enabled = args.has('disable') ? false : args.has('enable') ? true : (existing?.payoutsEnabled ?? true);
    const account = await repository.upsertAgentAccount({
      agentId,
      displayName: args.get('display-name') ?? existing?.displayName ?? null,
      stripeAccountId: args.get('stripe-account') ?? existing?.stripeAccountId ?? null,
      payoutCurrency: args.get('currency') ?? existing?.payoutCurrency ?? 'USD',
      minimumPayoutCents: numberArg(args, 'minimum-cents') ?? existing?.minimumPayoutCents ?? 0,
      payoutsEnabled: enabled,
    });

    process.stdout.write(
      `${JSON.stringify(
        {
          agent_id: account.agentId,
          display_name: account.displayName,
          // Printed so an operator can confirm the destination; it is an
          // account identifier, not a credential.
          stripe_account_id: account.stripeAccountId,
          payout_currency: account.payoutCurrency,
          minimum_payout_cents: account.minimumPayoutCents,
          payouts_enabled: account.payoutsEnabled,
        },
        null,
        2,
      )}\n`,
    );
  } finally {
    await db.close();
  }
}

main().catch((error: unknown) => {
  process.stderr.write(`agent account update failed: ${error instanceof Error ? error.message : String(error)}\n`);
  process.exit(1);
});
