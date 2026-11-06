import { createHash } from 'node:crypto';
import { AislError } from '../lib/errors.js';
import { attributionSignature } from '../lib/crypto.js';
import { newClickId } from '../lib/ids.js';
import type { Env } from '../config/env.js';
import type { ConnectorRegistry, NormalizedProduct } from '../connectors/types.js';
import type { Merchant, MerchantRepository } from '../db/repositories/merchants.js';
import type { IntentBinding, IntentRepository } from '../db/repositories/intents.js';
import type { KeyValueStore } from '../redis/store.js';
import { SUPPORTED_CURRENCIES, type IntentProductResult, type IntentRequest, type IntentResponse } from '../types/acp.js';

interface CachedProduct extends NormalizedProduct {
  merchantId: string;
}

export interface IntentServiceDeps {
  env: Env;
  merchants: MerchantRepository;
  intents: IntentRepository;
  connectors: ConnectorRegistry;
  cache: KeyValueStore;
  logger: { warn: (obj: object, msg: string) => void };
}

/**
 * Catalog discovery for agents.
 *
 * Search results are cached per (merchant, query, limit); attribution tokens
 * are *not*. Every response mints fresh UUIDv7 click ids so two agents issuing
 * the same query never share an attribution trail.
 */
export class IntentService {
  constructor(private readonly deps: IntentServiceDeps) {}

  async search(request: IntentRequest): Promise<IntentResponse> {
    if (request.currency && !SUPPORTED_CURRENCIES.has(request.currency.toUpperCase())) {
      throw AislError.badRequest(
        'unsupported_currency',
        `currency ${request.currency} is not in the gateway's supported set`,
        'currency',
      );
    }

    const merchants = await this.resolveMerchants(request.merchant_id);
    if (merchants.length === 0) {
      throw AislError.notFound('no_merchants_available', 'no merchant catalogues are configured for search');
    }

    const perMerchantLimit = Math.max(1, Math.ceil(request.max_results / merchants.length));
    const settled = await Promise.allSettled(
      merchants.map(async (merchant) => this.searchMerchant(merchant, request.query, perMerchantLimit)),
    );

    const products: CachedProduct[] = [];
    let cacheState: IntentResponse['cache'] = 'bypass';
    let anySucceeded = false;
    const failures: string[] = [];

    for (const [index, outcome] of settled.entries()) {
      const merchant = merchants[index];
      if (!merchant) continue;

      if (outcome.status === 'rejected') {
        // One unreachable merchant must not blank the whole result set.
        const reason = outcome.reason instanceof Error ? outcome.reason.message : String(outcome.reason);
        failures.push(`${merchant.id}: ${reason}`);
        this.deps.logger.warn({ merchant_id: merchant.id, reason }, 'catalog search failed for merchant');
        continue;
      }
      anySucceeded = true;
      cacheState = mergeCacheState(cacheState, outcome.value.cache);
      products.push(...outcome.value.products);
    }

    if (!anySucceeded) {
      throw AislError.upstream(
        'catalog_search_unavailable',
        `no merchant catalogue answered the query (${failures.join('; ')})`,
      );
    }

    const selected = products
      .filter((product) => !request.currency || product.currency === request.currency.toUpperCase())
      .filter((product) => product.availability !== 'out_of_stock')
      .slice(0, request.max_results);

    const now = new Date();
    const expiresAt = new Date(now.getTime() + this.deps.env.ACP_TOKEN_TTL_SECONDS * 1000);
    const subId1 = request.sub_ids.sub1 ?? null;
    const subId2 = request.sub_ids.sub2 ?? null;

    const bindings: IntentBinding[] = [];
    const results: IntentProductResult[] = [];

    for (const product of selected) {
      const merchant = merchants.find((candidate) => candidate.id === product.merchantId);
      if (!merchant) continue;

      const clickId = newClickId();
      bindings.push({
        clickId,
        agentId: request.agent_id,
        subId1,
        subId2,
        merchantId: merchant.id,
        productId: product.productId,
        variantId: product.variantId,
        quotedPriceCents: product.priceCents,
        currency: product.currency,
        query: request.query,
        expiresAt,
        createdAt: now,
      });

      results.push({
        acp_token: clickId,
        merchant_id: merchant.id,
        merchant_name: merchant.name,
        platform: merchant.platform,
        product_id: product.productId,
        variant_id: product.variantId,
        title: product.title,
        description: product.description,
        price: { amount_cents: product.priceCents, currency: product.currency },
        availability: product.availability,
        inventory_quantity: product.inventoryQuantity,
        url: product.url,
        image_url: product.imageUrl,
        attribution: {
          click_id: clickId,
          signature: attributionSignature({
            salt: this.deps.env.AISL_ATTRIBUTION_SALT,
            clickId,
            agentId: request.agent_id,
            merchantId: merchant.id,
          }),
          expires_at: expiresAt.toISOString(),
          sub_id_1: subId1,
          sub_id_2: subId2,
        },
        checkout: {
          endpoint: '/v1/agent/checkout',
          method: 'POST',
          required_fields: ['acp_token', 'merchant_id', 'variant_id', 'payment_credential', 'shipping_address'],
        },
      });
    }

    // Tokens are persisted before the response leaves the gateway: an agent
    // must never hold a token the ledger has never heard of.
    await this.deps.intents.recordBatch(bindings);

    return {
      query: request.query,
      agent_id: request.agent_id,
      result_count: results.length,
      cache: cacheState,
      results,
    };
  }

  private async resolveMerchants(merchantId?: string): Promise<Merchant[]> {
    if (merchantId) {
      const merchant = await this.deps.merchants.findById(merchantId);
      if (!merchant) {
        throw AislError.notFound('merchant_not_found', `merchant ${merchantId} does not exist`, 'merchant_id');
      }
      return [merchant];
    }
    return this.deps.merchants.listSearchable();
  }

  private async searchMerchant(
    merchant: Merchant,
    query: string,
    limit: number,
  ): Promise<{ products: CachedProduct[]; cache: IntentResponse['cache'] }> {
    const connector = this.deps.connectors.catalogFor(merchant.platform);
    if (!connector) {
      throw AislError.internal(
        'connector_not_registered',
        `no catalog connector registered for platform ${merchant.platform}`,
      );
    }

    const ttl = this.deps.env.CATALOG_CACHE_TTL_SECONDS;
    const cacheKey = catalogCacheKey(merchant.id, query, limit);

    if (ttl > 0) {
      const cached = await this.deps.cache.get(cacheKey);
      if (cached) {
        try {
          const parsed = JSON.parse(cached) as NormalizedProduct[];
          return { products: parsed.map((product) => ({ ...product, merchantId: merchant.id })), cache: 'hit' };
        } catch {
          // A poisoned cache entry is never worth a failed search.
          await this.deps.cache.del(cacheKey);
        }
      }
    }

    const products = await connector.search(merchant, { query, limit });
    if (ttl > 0) {
      await this.deps.cache.set(cacheKey, JSON.stringify(products), ttl);
    }
    return {
      products: products.map((product) => ({ ...product, merchantId: merchant.id })),
      cache: ttl > 0 ? 'miss' : 'bypass',
    };
  }
}

export function catalogCacheKey(merchantId: string, query: string, limit: number): string {
  const digest = createHash('sha256').update(`${query}|${limit}`).digest('hex').slice(0, 32);
  return `catalog:${merchantId}:${digest}`;
}

function mergeCacheState(current: IntentResponse['cache'], next: IntentResponse['cache']): IntentResponse['cache'] {
  if (current === 'bypass') return next;
  if (current === next) return current;
  // Any miss in a fan-out makes the overall response a miss.
  return next === 'miss' ? 'miss' : current;
}
