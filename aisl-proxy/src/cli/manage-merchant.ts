import { loadEnv } from '../config/env.js';
import { createDatabase } from '../db/pool.js';
import { MerchantCredentialsSchema, MerchantRepository, type Merchant } from '../db/repositories/merchants.js';
import { parseArgs, readStdin } from './args.js';

/**
 * Merchant lifecycle after onboarding.
 *
 * Rotation re-seals new credentials under AES-256-GCM and overwrites the old
 * ciphertext, so a leaked token stops existing in the database. Disabling drops
 * a merchant out of catalogue fan-out while leaving its conversions and ledger
 * entries intact — the books must stay readable for a merchant that has stopped
 * trading.
 *
 *   npx tsx src/cli/manage-merchant.ts list
 *   echo '{"platform":"shopify", ...}' \
 *     | npx tsx src/cli/manage-merchant.ts rotate --merchant-id <uuid>
 *   npx tsx src/cli/manage-merchant.ts disable --merchant-id <uuid>
 *   npx tsx src/cli/manage-merchant.ts enable  --merchant-id <uuid>
 */
async function main(): Promise<void> {
  const [command, ...rest] = process.argv.slice(2);
  const args = parseArgs(rest);

  const env = loadEnv();
  const db = createDatabase(env);
  try {
    const repository = new MerchantRepository(db, env.AISL_CREDENTIAL_ENCRYPTION_KEY);

    switch (command) {
      case 'list': {
        const merchants = await repository.listAll();
        return print(merchants.map(describe));
      }
      case 'rotate': {
        const merchantId = required(args, 'merchant-id');
        const raw = await readStdin();
        if (raw.trim().length === 0) {
          throw new Error('replacement credentials JSON must be supplied on stdin');
        }
        const credentials = MerchantCredentialsSchema.parse(JSON.parse(raw));
        const merchant = await repository.rotateCredentials(merchantId, credentials);
        return print({ ...describe(merchant), rotated: true });
      }
      case 'disable':
        return print(describe(await repository.setEnabled(required(args, 'merchant-id'), false)));
      case 'enable':
        return print(describe(await repository.setEnabled(required(args, 'merchant-id'), true)));
      default:
        throw new Error(`unknown command "${command ?? ''}"; expected one of: list, rotate, disable, enable`);
    }
  } finally {
    await db.close();
  }
}

/** Never includes credentials: this output is meant to be safe to paste. */
function describe(merchant: Merchant) {
  return {
    merchant_id: merchant.id,
    name: merchant.name,
    platform: merchant.platform,
    enabled: merchant.enabled,
    commission_rate_bps: merchant.commissionRateBps,
    aisl_cut_bps: merchant.aislCutBps,
    credentials_rotated_at: merchant.credentialsRotatedAt?.toISOString() ?? null,
  };
}

function required(args: Map<string, string>, key: string): string {
  const value = args.get(key);
  if (!value || value === 'true') {
    throw new Error(`--${key} is required`);
  }
  return value;
}

function print(payload: unknown): void {
  process.stdout.write(`${JSON.stringify(payload, null, 2)}\n`);
}

main().catch((error: unknown) => {
  process.stderr.write(`merchant management failed: ${error instanceof Error ? error.message : String(error)}\n`);
  process.exit(1);
});
