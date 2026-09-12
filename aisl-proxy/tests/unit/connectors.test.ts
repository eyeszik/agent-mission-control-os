import { describe, expect, it } from 'vitest';
import { ShopifyStorefrontConnector } from '../../src/connectors/shopify/storefront.js';
import { ShopifyAdminOrderDispatcher, numericVariantId } from '../../src/connectors/shopify/admin.js';
import { AislError } from '../../src/lib/errors.js';
import type { Merchant } from '../../src/db/repositories/merchants.js';
import { startMockShopify, redirectingFetch, type MockProduct } from '../helpers/mockShopify.js';

const PRODUCTS: MockProduct[] = [
  {
    id: 'gid://shopify/Product/1',
    variantId: 'gid://shopify/ProductVariant/1001',
    title: 'Test Headphones',
    description: 'Noise cancelling headphones',
    price: '199.99',
    currencyCode: 'usd',
    available: true,
    quantity: 3,
  },
];

function merchantFor(domain: string): Merchant {
  return {
    id: '018f4a1e-8e3b-7000-8432-1b1f9b3b0000',
    name: 'Test Shop',
    platform: 'shopify',
    commissionRateBps: 500,
    aislCutBps: 80,
    createdAt: new Date(),
    credentials: {
      platform: 'shopify',
      store_domain: domain,
      storefront_token: 'shpstf_test_token',
      storefront_api_version: '2026-01',
      admin_token: 'shpat_test_token',
      admin_api_version: '2026-01',
    },
  };
}

describe('ShopifyStorefrontConnector', () => {
  it('normalises a Storefront product graph into ACP product shape', async () => {
    const shopify = await startMockShopify(PRODUCTS);
    try {
      const connector = new ShopifyStorefrontConnector({
        fetchImpl: redirectingFetch(shopify.domain, shopify.url),
        timeoutMs: 5_000,
      });

      const results = await connector.search(merchantFor(shopify.domain), { query: 'headphones', limit: 5 });

      expect(results).toHaveLength(1);
      expect(results[0]).toMatchObject({
        productId: 'gid://shopify/Product/1',
        variantId: 'gid://shopify/ProductVariant/1001',
        title: 'Test Headphones',
        priceCents: 19_999,
        // Currency is upper-cased even when the API answers lower-case.
        currency: 'USD',
        availability: 'in_stock',
        inventoryQuantity: 3,
      });
    } finally {
      await shopify.close();
    }
  });

  it('surfaces an authentication failure as an upstream error, not an empty result', async () => {
    const shopify = await startMockShopify(PRODUCTS);
    try {
      const connector = new ShopifyStorefrontConnector({
        fetchImpl: redirectingFetch(shopify.domain, shopify.url),
        timeoutMs: 5_000,
      });
      const merchant = merchantFor(shopify.domain);
      merchant.credentials = { ...merchant.credentials, storefront_token: 'wrong' } as Merchant['credentials'];

      await expect(connector.search(merchant, { query: 'headphones', limit: 5 })).rejects.toThrow(AislError);
    } finally {
      await shopify.close();
    }
  });

  it('refuses to run against a merchant from another platform', async () => {
    const connector = new ShopifyStorefrontConnector({ fetchImpl: globalThis.fetch, timeoutMs: 5_000 });
    const merchant = merchantFor('example.myshopify.com');
    merchant.credentials = {
      platform: 'woocommerce',
      base_url: 'https://example.com',
      consumer_key: 'k',
      consumer_secret: 's',
    };

    await expect(connector.search(merchant, { query: 'x', limit: 1 })).rejects.toThrow(
      /received a woocommerce merchant/,
    );
  });
});

describe('ShopifyAdminOrderDispatcher', () => {
  it('places a paid order carrying the external payment reference', async () => {
    const shopify = await startMockShopify(PRODUCTS);
    try {
      const dispatcher = new ShopifyAdminOrderDispatcher({
        fetchImpl: redirectingFetch(shopify.domain, shopify.url),
        timeoutMs: 5_000,
      });

      const result = await dispatcher.createOrder({
        merchant: merchantFor(shopify.domain),
        variantId: 'gid://shopify/ProductVariant/1001',
        quantity: 2,
        currency: 'USD',
        clickId: '018f4a1e-8e3b-7000-8432-1b1f9b3b0001',
        agentId: 'agent_test',
        idempotencyKey: 'idem-1',
        shippingAddress: {
          name: 'Jane Doe',
          address1: '123 Market St',
          city: 'San Francisco',
          state: 'CA',
          postal_code: '94105',
          country: 'US',
        },
        payment: {
          processor: 'stripe_delegated_token',
          paymentIntentId: 'pi_test_1',
          chargeId: 'ch_test_1',
          status: 'succeeded',
          amountCents: 39_998,
          currency: 'USD',
        },
      });

      expect(result.externalOrderId).toMatch(/^\d+$/);
      expect(result.totalAmountCents).toBe(39_998);

      const order = shopify.state.orders[0]?.body as {
        order: { financial_status: string; transactions: Array<{ authorization: string; kind: string }> };
      };
      expect(order.order.financial_status).toBe('paid');
      expect(order.order.transactions[0]).toMatchObject({ kind: 'sale', authorization: 'pi_test_1' });
    } finally {
      await shopify.close();
    }
  });
});

describe('numericVariantId', () => {
  it('accepts both a Storefront GID and a bare numeric id', () => {
    expect(numericVariantId('gid://shopify/ProductVariant/12345678')).toBe(12_345_678);
    expect(numericVariantId('12345678')).toBe(12_345_678);
  });

  it('rejects an id with no numeric suffix', () => {
    expect(() => numericVariantId('gid://shopify/ProductVariant/')).toThrow(AislError);
  });
});
