import { z } from 'zod';

/**
 * Runtime configuration contract.
 *
 * Every value the gateway depends on is declared here and validated once at
 * boot. A missing or malformed variable is a startup failure, never a runtime
 * surprise in the middle of a payment.
 */
const booleanish = z
  .union([z.boolean(), z.string()])
  .transform((value) =>
    typeof value === 'boolean' ? value : ['1', 'true', 'yes', 'on'].includes(value.toLowerCase()),
  );

const csv = z
  .string()
  .optional()
  .transform((value) =>
    (value ?? '')
      .split(',')
      .map((item) => item.trim())
      .filter((item) => item.length > 0),
  );

export const EnvSchema = z.object({
  NODE_ENV: z.enum(['development', 'test', 'production']).default('development'),
  LOG_LEVEL: z.enum(['fatal', 'error', 'warn', 'info', 'debug', 'trace', 'silent']).default('info'),

  HOST: z.string().default('0.0.0.0'),
  PORT: z.coerce.number().int().min(1).max(65535).default(8080),
  PUBLIC_BASE_URL: z.string().url().default('http://localhost:8080'),

  DATABASE_URL: z.string().min(1, 'DATABASE_URL is required'),
  DATABASE_POOL_MAX: z.coerce.number().int().min(1).max(200).default(10),
  DATABASE_STATEMENT_TIMEOUT_MS: z.coerce.number().int().min(100).default(10_000),

  REDIS_URL: z.string().min(1, 'REDIS_URL is required'),
  REDIS_KEY_PREFIX: z.string().default('aisl'),

  STRIPE_SECRET_KEY: z.string().default(''),
  STRIPE_WEBHOOK_SECRET: z.string().default(''),
  /**
   * Shared payment tokens are served by a preview Stripe API version.
   * Verified against https://docs.stripe.com/agentic-commerce/concepts/shared-payment-tokens
   */
  STRIPE_API_VERSION: z.string().default('2026-04-22.preview'),

  /** HMAC salt binding click_id -> (agent, merchant). Rotating it invalidates outstanding tokens. */
  AISL_ATTRIBUTION_SALT: z.string().min(32, 'AISL_ATTRIBUTION_SALT must be at least 32 characters'),
  /** base64-encoded 32-byte key for AES-256-GCM encryption of merchant API credentials. */
  AISL_CREDENTIAL_ENCRYPTION_KEY: z
    .string()
    .refine((value) => Buffer.from(value, 'base64').length === 32, {
      message: 'AISL_CREDENTIAL_ENCRYPTION_KEY must be a base64-encoded 32-byte key',
    }),
  AISL_AGENT_API_KEYS: csv,
  AISL_REQUIRE_AGENT_AUTH: booleanish.default(true),

  ACP_TOKEN_TTL_SECONDS: z.coerce.number().int().min(60).default(86_400),
  CATALOG_CACHE_TTL_SECONDS: z.coerce.number().int().min(0).default(60),
  WEBHOOK_DEDUPE_TTL_SECONDS: z.coerce.number().int().min(60).default(604_800),

  RATE_LIMIT_ENABLED: booleanish.default(true),
  RATE_LIMIT_CAPACITY: z.coerce.number().int().min(1).default(120),
  RATE_LIMIT_REFILL_PER_SECOND: z.coerce.number().min(0.01).default(2),

  /** Outbound HTTP timeout for merchant/platform connectors. */
  CONNECTOR_TIMEOUT_MS: z.coerce.number().int().min(100).default(8_000),
});

export type Env = z.infer<typeof EnvSchema>;

export function loadEnv(source: NodeJS.ProcessEnv = process.env): Env {
  const parsed = EnvSchema.safeParse(source);
  if (!parsed.success) {
    const issues = parsed.error.issues
      .map((issue) => `  - ${issue.path.join('.') || '(root)'}: ${issue.message}`)
      .join('\n');
    throw new Error(`Invalid environment configuration:\n${issues}`);
  }

  const env = parsed.data;
  if (env.NODE_ENV === 'production') {
    if (env.AISL_REQUIRE_AGENT_AUTH && env.AISL_AGENT_API_KEYS.length === 0) {
      throw new Error('AISL_AGENT_API_KEYS must be set in production while AISL_REQUIRE_AGENT_AUTH is enabled');
    }
    if (env.STRIPE_SECRET_KEY.length === 0) {
      throw new Error('STRIPE_SECRET_KEY is required in production');
    }
    if (env.STRIPE_WEBHOOK_SECRET.length === 0) {
      throw new Error('STRIPE_WEBHOOK_SECRET is required in production');
    }
  }
  return env;
}
