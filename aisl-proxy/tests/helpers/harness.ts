import Stripe from 'stripe';
import type { FastifyInstance } from 'fastify';
import { buildServer } from '../../src/app.js';
import { buildRepositories, StripeWebhookVerifier, type AppDependencies } from '../../src/container.js';
import { createDatabase, type Database } from '../../src/db/pool.js';
import { runMigrations } from '../../src/db/migrate.js';
import type { Merchant } from '../../src/db/repositories/merchants.js';
import { RedisStore, type KeyValueStore } from '../../src/redis/store.js';
import { ConnectorRegistry } from '../../src/connectors/types.js';
import { ShopifyStorefrontConnector } from '../../src/connectors/shopify/storefront.js';
import { ShopifyAdminOrderDispatcher } from '../../src/connectors/shopify/admin.js';
import { StripeDelegatedPaymentProcessor } from '../../src/connectors/stripe/delegatedPayments.js';
import { startMockShopify, redirectingFetch, type MockProduct, type MockShopify } from './mockShopify.js';
import { startMockStripe, type MockStripe } from './mockStripe.js';
import { testEnv, TEST_WEBHOOK_SECRET } from './testEnv.js';

export interface Harness {
  app: FastifyInstance;
  deps: AppDependencies;
  db: Database;
  cache: KeyValueStore;
  shopify: MockShopify;
  stripe: MockStripe;
  merchant: Merchant;
  stripeClient: Stripe;
  /** Build a signed Stripe webhook request exactly as Stripe would send it. */
  signedWebhook: (event: unknown) => { payload: string; signature: string };
  reset: () => Promise<void>;
  close: () => Promise<void>;
}

export const DEFAULT_PRODUCTS: MockProduct[] = [
  {
    id: 'gid://shopify/Product/9001',
    variantId: 'gid://shopify/ProductVariant/12345678',
    title: 'Aurora Wireless Noise Cancelling Headphones',
    description: 'Over-ear wireless headphones with adaptive noise cancelling.',
    price: '249.00',
    currencyCode: 'USD',
    available: true,
    quantity: 42,
  },
  {
    id: 'gid://shopify/Product/9002',
    variantId: 'gid://shopify/ProductVariant/12345679',
    title: 'Nimbus Wireless Earbuds',
    description: 'Compact wireless earbuds with noise cancelling and 8h battery.',
    price: '129.50',
    currencyCode: 'USD',
    available: true,
    quantity: 8,
  },
  {
    id: 'gid://shopify/Product/9003',
    variantId: 'gid://shopify/ProductVariant/12345680',
    title: 'Sold Out Studio Headphones',
    description: 'Reference studio headphones, currently unavailable.',
    price: '399.00',
    currencyCode: 'USD',
    available: false,
    quantity: 0,
  },
];

/**
 * Boots the whole gateway against a real Postgres, a real Redis, and
 * in-process HTTP stand-ins for Shopify and Stripe. Only the merchant and
 * payment-rail *servers* are simulated; every line of gateway code, including
 * the connectors and the Stripe SDK's own request encoding, is the production
 * path.
 */
export async function startHarness(
  options: { products?: MockProduct[]; envOverrides?: NodeJS.ProcessEnv } = {},
): Promise<Harness> {
  const shopify = await startMockShopify(options.products ?? DEFAULT_PRODUCTS);
  const stripeMock = await startMockStripe();

  const env = testEnv(options.envOverrides);
  const db = createDatabase(env);
  await runMigrations(db);
  await truncateAll(db);

  const cache = new RedisStore(env.REDIS_URL, env.REDIS_KEY_PREFIX);

  const stripeClient = new Stripe('sk_test_aisl', {
    apiVersion: env.STRIPE_API_VERSION as Stripe.StripeConfig['apiVersion'],
    host: stripeMock.host,
    port: stripeMock.port,
    protocol: 'http',
    maxNetworkRetries: 0,
    telemetry: false,
  });

  const http = { fetchImpl: redirectingFetch(shopify.domain, shopify.url), timeoutMs: env.CONNECTOR_TIMEOUT_MS };
  const connectors = new ConnectorRegistry()
    .registerCatalog(new ShopifyStorefrontConnector(http))
    .registerDispatcher(new ShopifyAdminOrderDispatcher(http));

  const repositories = buildRepositories(db, env);
  const deps: AppDependencies = {
    env,
    db,
    cache,
    connectors,
    payments: new StripeDelegatedPaymentProcessor(stripeClient),
    webhookVerifier: new StripeWebhookVerifier(stripeClient, TEST_WEBHOOK_SECRET),
    repositories,
    shutdown: async () => {
      await Promise.allSettled([db.close(), cache.close()]);
    },
  };

  const merchant = await repositories.merchants.create({
    name: 'Aurora Audio',
    commissionRateBps: 500,
    aislCutBps: 80,
    credentials: {
      platform: 'shopify',
      store_domain: shopify.domain,
      storefront_token: 'shpstf_test_token',
      storefront_api_version: '2026-01',
      admin_token: 'shpat_test_token',
      admin_api_version: '2026-01',
      stripe_account_id: 'acct_test_merchant',
    },
  });

  const app = await buildServer(deps);
  await app.ready();

  return {
    app,
    deps,
    db,
    cache,
    shopify,
    stripe: stripeMock,
    merchant,
    stripeClient,
    signedWebhook: (event: unknown) => {
      const payload = JSON.stringify(event);
      return {
        payload,
        signature: Stripe.webhooks.generateTestHeaderString({ payload, secret: TEST_WEBHOOK_SECRET }),
      };
    },
    reset: async () => {
      await truncateTransactional(db);
    },
    close: async () => {
      await app.close();
      await deps.shutdown();
      await Promise.all([shopify.close(), stripeMock.close()]);
    },
  };
}

export async function truncateAll(db: Database): Promise<void> {
  await db.query(`
    TRUNCATE TABLE ledger_entries, checkout_idempotency, webhook_events, conversions,
                   agent_intent_bindings, agent_intents, idempotency_keys, merchants
    RESTART IDENTITY CASCADE
  `);
}

/** Clears run state but keeps the onboarded merchants a suite already seeded. */
export async function truncateTransactional(db: Database): Promise<void> {
  await db.query(`
    TRUNCATE TABLE ledger_entries, checkout_idempotency, webhook_events, conversions,
                   agent_intent_bindings, agent_intents, idempotency_keys
    RESTART IDENTITY CASCADE
  `);
}

/** A Stripe event envelope shaped like the real webhook payloads. */
export function stripeEvent(input: {
  id: string;
  type: string;
  object: Record<string, unknown>;
}): Record<string, unknown> {
  return {
    id: input.id,
    object: 'event',
    api_version: '2026-04-22.preview',
    created: Math.floor(Date.now() / 1000),
    livemode: false,
    pending_webhooks: 1,
    request: { id: null, idempotency_key: null },
    type: input.type,
    data: { object: input.object },
  };
}
