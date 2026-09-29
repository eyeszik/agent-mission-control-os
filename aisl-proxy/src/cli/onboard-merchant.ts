import { loadEnv } from '../config/env.js';
import { createDatabase } from '../db/pool.js';
import { MerchantRepository, MerchantCredentialsSchema } from '../db/repositories/merchants.js';
import { numberArg, parseArgs, readStdin } from './args.js';

/**
 * Idempotent merchant onboarding.
 *
 * Credentials are supplied as JSON on stdin and sealed with AES-256-GCM before
 * they touch the database, so no plaintext API key is ever written to
 * `merchants.api_credentials_encrypted` or to shell history.
 *
 *   echo '{"platform":"shopify","store_domain":"acme.myshopify.com", ...}' \
 *     | npx tsx src/cli/onboard-merchant.ts --name "Acme" --commission-bps 500 --aisl-bps 80
 */
async function main(): Promise<void> {
  const args = parseArgs(process.argv.slice(2));
  const name = args.get('name');
  if (!name) {
    throw new Error('--name is required');
  }

  const raw = await readStdin();
  if (raw.trim().length === 0) {
    throw new Error('merchant credentials JSON must be supplied on stdin');
  }
  const credentials = MerchantCredentialsSchema.parse(JSON.parse(raw));

  const env = loadEnv();
  const db = createDatabase(env);
  try {
    const repository = new MerchantRepository(db, env.AISL_CREDENTIAL_ENCRYPTION_KEY);
    const merchant = await repository.create({
      name,
      credentials,
      commissionRateBps: numberArg(args, 'commission-bps'),
      aislCutBps: numberArg(args, 'aisl-bps'),
    });

    process.stdout.write(
      `${JSON.stringify(
        {
          merchant_id: merchant.id,
          name: merchant.name,
          platform: merchant.platform,
          commission_rate_bps: merchant.commissionRateBps,
          aisl_cut_bps: merchant.aislCutBps,
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
  process.stderr.write(`onboarding failed: ${error instanceof Error ? error.message : String(error)}\n`);
  process.exit(1);
});
