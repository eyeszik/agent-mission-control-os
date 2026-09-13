import Stripe from 'stripe';
import type { Env } from './config/env.js';
import { createDatabase, type Database } from './db/pool.js';
import { CheckoutIdempotencyRepository } from './db/repositories/checkoutIdempotency.js';
import { ConversionRepository } from './db/repositories/conversions.js';
import { IntentRepository } from './db/repositories/intents.js';
import { MerchantRepository } from './db/repositories/merchants.js';
import { PayoutRepository } from './db/repositories/payouts.js';
import { WebhookEventRepository } from './db/repositories/webhookEvents.js';
import { InMemoryStore, RedisStore, type KeyValueStore } from './redis/store.js';
import { ConnectorRegistry, type PaymentProcessor } from './connectors/types.js';
import { ShopifyStorefrontConnector } from './connectors/shopify/storefront.js';
import { ShopifyAdminOrderDispatcher } from './connectors/shopify/admin.js';
import { WooCommerceConnector } from './connectors/woocommerce/rest.js';
import { StripeDelegatedPaymentProcessor } from './connectors/stripe/delegatedPayments.js';
import { StripeTransferProcessor, type PayoutProcessor } from './connectors/stripe/transfers.js';
import { AislError } from './lib/errors.js';

/** Verifies and parses a raw S2S webhook body. */
export interface WebhookVerifier {
  construct(rawBody: Buffer | string, signature: string | undefined): Stripe.Event;
}

export class StripeWebhookVerifier implements WebhookVerifier {
  constructor(
    private readonly stripe: Stripe,
    private readonly endpointSecret: string,
  ) {}

  construct(rawBody: Buffer | string, signature: string | undefined): Stripe.Event {
    if (!signature) {
      throw AislError.unauthorized('missing_signature', 'Stripe-Signature header is required');
    }
    if (!this.endpointSecret) {
      throw AislError.internal('webhook_secret_missing', 'STRIPE_WEBHOOK_SECRET is not configured');
    }
    try {
      // HMAC-SHA256 over the raw body, with replay-window enforcement.
      return this.stripe.webhooks.constructEvent(rawBody, signature, this.endpointSecret);
    } catch (error) {
      throw AislError.unauthorized(
        'invalid_signature',
        `webhook signature verification failed: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
  }
}

export interface AppDependencies {
  env: Env;
  db: Database;
  cache: KeyValueStore;
  connectors: ConnectorRegistry;
  payments: PaymentProcessor;
  transfers: PayoutProcessor;
  webhookVerifier: WebhookVerifier;
  repositories: {
    merchants: MerchantRepository;
    intents: IntentRepository;
    conversions: ConversionRepository;
    idempotency: CheckoutIdempotencyRepository;
    webhookEvents: WebhookEventRepository;
    payouts: PayoutRepository;
  };
  /** Releases every owned resource. Only closes what this container created. */
  shutdown: () => Promise<void>;
}

export function buildRepositories(db: Database, env: Env): AppDependencies['repositories'] {
  return {
    merchants: new MerchantRepository(db, env.AISL_CREDENTIAL_ENCRYPTION_KEY),
    intents: new IntentRepository(db),
    conversions: new ConversionRepository(db),
    idempotency: new CheckoutIdempotencyRepository(db),
    webhookEvents: new WebhookEventRepository(db),
    payouts: new PayoutRepository(db),
  };
}

export function buildConnectorRegistry(env: Env, fetchImpl: typeof globalThis.fetch = globalThis.fetch): ConnectorRegistry {
  const http = { fetchImpl, timeoutMs: env.CONNECTOR_TIMEOUT_MS };
  const woocommerce = new WooCommerceConnector(http);

  return new ConnectorRegistry()
    .registerCatalog(new ShopifyStorefrontConnector(http))
    .registerDispatcher(new ShopifyAdminOrderDispatcher(http))
    .registerCatalog(woocommerce)
    .registerDispatcher(woocommerce);
}

export function createContainer(env: Env): AppDependencies {
  const db = createDatabase(env);
  const cache: KeyValueStore = env.REDIS_URL === 'memory://' ? new InMemoryStore() : new RedisStore(env.REDIS_URL, env.REDIS_KEY_PREFIX);

  const stripe = new Stripe(env.STRIPE_SECRET_KEY || 'sk_test_unconfigured', {
    apiVersion: env.STRIPE_API_VERSION as Stripe.StripeConfig['apiVersion'],
    timeout: env.CONNECTOR_TIMEOUT_MS,
    maxNetworkRetries: 2,
    telemetry: false,
  });

  return {
    env,
    db,
    cache,
    connectors: buildConnectorRegistry(env),
    payments: new StripeDelegatedPaymentProcessor(stripe),
    transfers: new StripeTransferProcessor(stripe),
    webhookVerifier: new StripeWebhookVerifier(stripe, env.STRIPE_WEBHOOK_SECRET),
    repositories: buildRepositories(db, env),
    shutdown: async () => {
      await Promise.allSettled([db.close(), cache.close()]);
    },
  };
}
