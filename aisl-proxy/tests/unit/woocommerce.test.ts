import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { WooCommerceConnector } from '../../src/connectors/woocommerce/rest.js';
import { AislError } from '../../src/lib/errors.js';
import type { Merchant } from '../../src/db/repositories/merchants.js';
import type { PaymentAuthorizationResult } from '../../src/connectors/types.js';
import { startMockWooCommerce, type MockWooCommerce, type MockWooProduct } from '../helpers/mockWooCommerce.js';

const PRODUCTS: MockWooProduct[] = [
  {
    id: 4101,
    name: 'Cedar Desk Lamp',
    short_description: '<p>A warm <strong>cedar</strong> lamp.</p>',
    description: 'Long form description',
    price: '129.95',
    permalink: 'https://shop.example/product/cedar-desk-lamp',
    stock_status: 'instock',
    stock_quantity: 12,
    images: [{ src: 'https://cdn.example/lamp.jpg' }, { src: 'https://cdn.example/lamp-2.jpg' }],
  },
  {
    id: 4102,
    name: 'Cedar Shelf',
    short_description: '',
    description: 'Solid cedar shelving',
    price: '89.00',
    stock_status: 'outofstock',
    stock_quantity: 0,
  },
  {
    id: 4103,
    name: 'Cedar Stool',
    short_description: 'Backordered stool',
    price: '54.50',
    stock_status: 'onbackorder',
    stock_quantity: null,
  },
];

let woo: MockWooCommerce;

function merchantFor(baseUrl: string): Merchant {
  return {
    id: '018f4a1e-8e3b-7000-8432-1b1f9b3b1111',
    name: 'Cedar Works',
    platform: 'woocommerce',
    commissionRateBps: 500,
    aislCutBps: 80,
    createdAt: new Date(),
    enabled: true,
    credentialsRotatedAt: null,
    credentials: {
      platform: 'woocommerce',
      base_url: baseUrl,
      consumer_key: 'ck_test_key',
      consumer_secret: 'cs_test_secret',
    },
  };
}

function connector(): WooCommerceConnector {
  return new WooCommerceConnector({ fetchImpl: globalThis.fetch, timeoutMs: 5_000 });
}

beforeEach(async () => {
  woo = await startMockWooCommerce(PRODUCTS);
});

afterEach(async () => {
  await woo.close();
});

describe('WooCommerceConnector.search', () => {
  it('normalises REST v3 products into the ACP product shape', async () => {
    const results = await connector().search(merchantFor(woo.url), { query: 'Cedar', limit: 10 });

    expect(results).toHaveLength(3);
    const lamp = results.find((product) => product.productId === '4101');
    expect(lamp).toMatchObject({
      productId: '4101',
      // A WooCommerce simple product is its own purchasable unit.
      variantId: '4101',
      title: 'Cedar Desk Lamp',
      priceCents: 12_995,
      currency: 'USD',
      availability: 'in_stock',
      inventoryQuantity: 12,
      url: 'https://shop.example/product/cedar-desk-lamp',
      imageUrl: 'https://cdn.example/lamp.jpg',
    });
    // HTML is stripped so an agent never renders markup from a merchant feed.
    expect(lamp?.description).toBe('A warm cedar lamp.');
  });

  it('maps each WooCommerce stock status onto ACP availability', async () => {
    const results = await connector().search(merchantFor(woo.url), { query: 'Cedar', limit: 10 });
    const byId = new Map(results.map((product) => [product.productId, product.availability]));

    expect(byId.get('4101')).toBe('in_stock');
    expect(byId.get('4102')).toBe('out_of_stock');
    // `onbackorder` is neither purchasable-now nor definitively unavailable.
    expect(byId.get('4103')).toBe('unknown');
  });

  it('forwards the query, limit and published filter to the REST API', async () => {
    await connector().search(merchantFor(woo.url), { query: 'Shelf', limit: 3 });

    expect(woo.state.searches[0]).toEqual({ search: 'Shelf', perPage: '3', status: 'publish' });
  });

  it('authenticates with HTTP Basic over the consumer key pair', async () => {
    await connector().search(merchantFor(woo.url), { query: 'Cedar', limit: 5 });

    const decoded = Buffer.from(woo.state.authHeaders[0]?.replace('Basic ', '') ?? '', 'base64').toString('utf8');
    expect(decoded).toBe('ck_test_key:cs_test_secret');
  });

  it('reads the store currency once and caches it per merchant', async () => {
    const shared = connector();
    const merchant = merchantFor(woo.url);
    await shared.search(merchant, { query: 'Cedar', limit: 5 });
    await shared.search(merchant, { query: 'Shelf', limit: 5 });
    await shared.getVariant(merchant, '4101');

    expect(woo.state.currencyRequests).toBe(1);
  });

  it('honours a non-USD store currency when converting to minor units', async () => {
    const jpyStore = await startMockWooCommerce([{ ...PRODUCTS[0]!, price: '1250' }], 'JPY');
    try {
      const results = await connector().search(merchantFor(jpyStore.url), { query: 'Cedar', limit: 5 });
      // JPY is a zero-decimal currency: 1250 yen is 1250 minor units, not 125000.
      expect(results[0]).toMatchObject({ currency: 'JPY', priceCents: 1_250 });
    } finally {
      await jpyStore.close();
    }
  });

  it('surfaces an authentication failure as an upstream error', async () => {
    woo.state.rejectAuth = true;

    await expect(connector().search(merchantFor(woo.url), { query: 'Cedar', limit: 5 })).rejects.toBeInstanceOf(
      AislError,
    );
  });

  it('refuses a merchant belonging to another platform', async () => {
    const shopifyMerchant = {
      ...merchantFor(woo.url),
      credentials: {
        platform: 'shopify' as const,
        store_domain: 'acme.myshopify.com',
        storefront_token: 'shpstf',
        storefront_api_version: '2026-01',
        admin_api_version: '2026-01',
      },
    };

    await expect(connector().search(shopifyMerchant, { query: 'x', limit: 1 })).rejects.toThrow(
      /received a shopify merchant/,
    );
  });

  it('tolerates a base_url with a trailing slash', async () => {
    const results = await connector().search(merchantFor(`${woo.url}/`), { query: 'Cedar', limit: 5 });
    expect(results).toHaveLength(3);
  });
});

describe('WooCommerceConnector.getVariant', () => {
  it('returns the single product by id', async () => {
    const product = await connector().getVariant(merchantFor(woo.url), '4102');

    expect(product).toMatchObject({ variantId: '4102', title: 'Cedar Shelf', priceCents: 8_900 });
  });

  it('raises rather than inventing a product for an unknown id', async () => {
    await expect(connector().getVariant(merchantFor(woo.url), '999999')).rejects.toBeInstanceOf(AislError);
  });
});

describe('WooCommerceConnector.createOrder', () => {
  const payment: PaymentAuthorizationResult = {
    processor: 'stripe_delegated_token',
    paymentIntentId: 'pi_test_woo_1',
    chargeId: 'ch_test_woo_1',
    status: 'succeeded',
    amountCents: 25_990,
    currency: 'USD',
  };

  it('places a paid order carrying the attribution trail', async () => {
    const result = await connector().createOrder({
      merchant: merchantFor(woo.url),
      variantId: '4101',
      quantity: 2,
      currency: 'USD',
      payment,
      clickId: '018f4a1e-8e3b-7000-8432-1b1f9b3b2222',
      agentId: 'agent_test',
      idempotencyKey: 'idem_woo_1',
      shippingAddress: {
        name: 'Ada Lovelace',
        address1: '12 Analytical Way',
        city: 'London',
        postal_code: 'EC1A 1AA',
        country: 'gb',
      },
    });

    expect(result).toMatchObject({ externalOrderId: '9001', totalAmountCents: 25_990, currency: 'USD' });

    const order = woo.state.orders[0] as Record<string, unknown>;
    expect(order.set_paid).toBe(true);
    expect(order.transaction_id).toBe('pi_test_woo_1');
    expect(order.line_items).toEqual([{ product_id: 4101, quantity: 2 }]);
    expect(order.meta_data).toEqual([
      { key: 'aisl_click_id', value: '018f4a1e-8e3b-7000-8432-1b1f9b3b2222' },
      { key: 'aisl_agent_id', value: 'agent_test' },
      { key: 'aisl_idempotency_key', value: 'idem_woo_1' },
    ]);
  });

  it('splits the recipient name and upper-cases the country code', async () => {
    await connector().createOrder({
      merchant: merchantFor(woo.url),
      variantId: '4102',
      quantity: 1,
      currency: 'USD',
      payment,
      clickId: '018f4a1e-8e3b-7000-8432-1b1f9b3b3333',
      agentId: 'agent_test',
      idempotencyKey: 'idem_woo_2',
      shippingAddress: {
        name: 'Grace Brewster Hopper',
        address1: '1 Navy Yard',
        address2: 'Suite 7',
        city: 'Arlington',
        state: 'VA',
        postal_code: '22202',
        country: 'us',
      },
    });

    const shipping = (woo.state.orders[0] as { shipping: Record<string, string> }).shipping;
    expect(shipping).toMatchObject({
      first_name: 'Grace',
      last_name: 'Brewster Hopper',
      address_1: '1 Navy Yard',
      address_2: 'Suite 7',
      state: 'VA',
      country: 'US',
    });
  });

  it('trusts the store total over the quoted price', async () => {
    // The store prices the line at 129.95 x 1 regardless of what was quoted.
    const result = await connector().createOrder({
      merchant: merchantFor(woo.url),
      variantId: '4101',
      quantity: 1,
      currency: 'USD',
      payment: { ...payment, amountCents: 1 },
      clickId: '018f4a1e-8e3b-7000-8432-1b1f9b3b4444',
      agentId: 'agent_test',
      idempotencyKey: 'idem_woo_3',
      shippingAddress: {
        name: 'Ada Lovelace',
        address1: '12 Analytical Way',
        city: 'London',
        postal_code: 'EC1A 1AA',
        country: 'GB',
      },
    });

    expect(result.totalAmountCents).toBe(12_995);
  });

  it('fails loudly when the store rejects the order', async () => {
    woo.state.rejectAuth = true;

    await expect(
      connector().createOrder({
        merchant: merchantFor(woo.url),
        variantId: '4101',
        quantity: 1,
        currency: 'USD',
        payment,
        clickId: '018f4a1e-8e3b-7000-8432-1b1f9b3b5555',
        agentId: 'agent_test',
        idempotencyKey: 'idem_woo_4',
        shippingAddress: {
          name: 'Ada Lovelace',
          address1: '12 Analytical Way',
          city: 'London',
          postal_code: 'EC1A 1AA',
          country: 'GB',
        },
      }),
    ).rejects.toBeInstanceOf(AislError);
  });
});
