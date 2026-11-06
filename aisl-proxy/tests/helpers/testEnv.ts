import { randomBytes } from 'node:crypto';
import { loadEnv, type Env } from '../../src/config/env.js';

export const TEST_DATABASE_URL =
  process.env.TEST_DATABASE_URL ?? 'postgresql://aisl:aisl@127.0.0.1:5432/aisl_test';
export const TEST_REDIS_URL = process.env.TEST_REDIS_URL ?? 'redis://127.0.0.1:6379';
export const TEST_WEBHOOK_SECRET = 'whsec_test_aisl_integration_secret';
export const TEST_ENCRYPTION_KEY = Buffer.alloc(32, 7).toString('base64');
export const TEST_ATTRIBUTION_SALT = 'aisl-test-attribution-salt-0123456789abcdef';

/**
 * A fully validated Env for tests, built through the real `loadEnv` so the
 * suite exercises the same validation the production boot path does.
 * Each call gets a unique Redis prefix so parallel suites cannot collide.
 */
export function testEnv(overrides: NodeJS.ProcessEnv = {}): Env {
  return loadEnv({
    NODE_ENV: 'test',
    LOG_LEVEL: 'silent',
    HOST: '127.0.0.1',
    PORT: '8080',
    PUBLIC_BASE_URL: 'http://127.0.0.1:8080',
    DATABASE_URL: TEST_DATABASE_URL,
    REDIS_URL: TEST_REDIS_URL,
    REDIS_KEY_PREFIX: `aisl-test-${randomBytes(6).toString('hex')}`,
    STRIPE_SECRET_KEY: 'sk_test_aisl',
    STRIPE_WEBHOOK_SECRET: TEST_WEBHOOK_SECRET,
    AISL_ATTRIBUTION_SALT: TEST_ATTRIBUTION_SALT,
    AISL_CREDENTIAL_ENCRYPTION_KEY: TEST_ENCRYPTION_KEY,
    AISL_REQUIRE_AGENT_AUTH: 'false',
    RATE_LIMIT_ENABLED: 'false',
    CATALOG_CACHE_TTL_SECONDS: '0',
    ...overrides,
  });
}
