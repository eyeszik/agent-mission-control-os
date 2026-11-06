import { createServer, type Server } from 'node:http';
import { once } from 'node:events';
import type { AddressInfo } from 'node:net';

export interface MockProduct {
  id: string;
  variantId: string;
  title: string;
  description: string;
  price: string;
  currencyCode: string;
  available: boolean;
  quantity: number;
}

export interface MockShopifyState {
  products: MockProduct[];
  orders: Array<{ id: number; total: string; currency: string; body: unknown }>;
  /** Set to fail the next order creation, to exercise the compensating refund. */
  failNextOrder: boolean;
  requestLog: Array<{ method: string; path: string }>;
  nextOrderId: number;
  /** Total charged for an order, overriding the line-item sum (tax, shipping). */
  orderTotalOverride: string | null;
}

export interface MockShopify {
  url: string;
  domain: string;
  state: MockShopifyState;
  close: () => Promise<void>;
}

/**
 * Minimal Shopify stand-in covering the two calls the gateway makes: the
 * Storefront `products` GraphQL query and the Admin `orders.json` mutation.
 * The real connectors run against it unmodified.
 */
export async function startMockShopify(products: MockProduct[]): Promise<MockShopify> {
  const state: MockShopifyState = {
    products: [...products],
    orders: [],
    failNextOrder: false,
    requestLog: [],
    nextOrderId: 5_000_001,
    orderTotalOverride: null,
  };

  const server: Server = createServer((request, response) => {
    const chunks: Buffer[] = [];
    request.on('data', (chunk: Buffer) => chunks.push(chunk));
    request.on('end', () => {
      const path = request.url ?? '';
      state.requestLog.push({ method: request.method ?? 'GET', path });
      const raw = Buffer.concat(chunks).toString('utf8');

      try {
        if (path.includes('/graphql.json')) {
          if (request.headers['x-shopify-storefront-access-token'] !== 'shpstf_test_token') {
            return json(response, 401, { errors: [{ message: 'Invalid API key or access token' }] });
          }
          return json(response, 200, graphqlResponse(state, raw));
        }

        if (path.includes('/orders.json') && request.method === 'POST') {
          if (request.headers['x-shopify-access-token'] !== 'shpat_test_token') {
            return json(response, 401, { errors: 'Invalid API key or access token' });
          }
          if (state.failNextOrder) {
            state.failNextOrder = false;
            return json(response, 422, { errors: { base: ['inventory is not available'] } });
          }

          const body = JSON.parse(raw) as {
            order: { line_items: Array<{ variant_id: number; quantity: number }>; currency: string };
          };
          const lineItem = body.order.line_items[0];
          const product = state.products.find((candidate) => numericId(candidate.variantId) === lineItem?.variant_id);
          const unitPrice = Number(product?.price ?? '0');
          const total = state.orderTotalOverride ?? (unitPrice * (lineItem?.quantity ?? 1)).toFixed(2);
          const id = state.nextOrderId;
          state.nextOrderId += 1;
          state.orders.push({ id, total, currency: body.order.currency, body });

          return json(response, 201, {
            order: {
              id,
              name: `#${id}`,
              total_price: total,
              currency: body.order.currency,
              financial_status: 'paid',
            },
          });
        }

        json(response, 404, { errors: 'Not Found' });
      } catch (error) {
        json(response, 500, { errors: error instanceof Error ? error.message : String(error) });
      }
    });
  });

  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const { port } = server.address() as AddressInfo;

  return {
    url: `http://127.0.0.1:${port}`,
    domain: `127.0.0.1:${port}`,
    state,
    close: async () => {
      server.close();
      await once(server, 'close');
    },
  };
}

function graphqlResponse(state: MockShopifyState, raw: string): unknown {
  const payload = JSON.parse(raw) as { query: string; variables: Record<string, unknown> };

  if (payload.query.includes('SearchProducts')) {
    const term = String(payload.variables.query ?? '').toLowerCase();
    const first = Number(payload.variables.first ?? 5);
    const matched = state.products
      .filter((product) => matches(product, term))
      .slice(0, first)
      .map((product) => ({ node: productNode(product) }));
    return { data: { products: { edges: matched } } };
  }

  if (payload.query.includes('VariantById')) {
    const id = String(payload.variables.id ?? '');
    const product = state.products.find((candidate) => candidate.variantId === id);
    if (!product) return { data: { node: null } };
    return {
      data: {
        node: {
          id: product.variantId,
          title: product.title,
          availableForSale: product.available,
          quantityAvailable: product.quantity,
          price: { amount: product.price, currencyCode: product.currencyCode },
          image: null,
          product: {
            id: product.id,
            title: product.title,
            description: product.description,
            onlineStoreUrl: null,
          },
        },
      },
    };
  }

  return { errors: [{ message: 'unrecognised query' }] };
}

function productNode(product: MockProduct): unknown {
  return {
    id: product.id,
    title: product.title,
    description: product.description,
    handle: product.title.toLowerCase().replace(/\s+/g, '-'),
    onlineStoreUrl: null,
    availableForSale: product.available,
    totalInventory: product.quantity,
    featuredImage: null,
    variants: {
      edges: [
        {
          node: {
            id: product.variantId,
            availableForSale: product.available,
            quantityAvailable: product.quantity,
            price: { amount: product.price, currencyCode: product.currencyCode },
          },
        },
      ],
    },
  };
}

function matches(product: MockProduct, term: string): boolean {
  if (term.length === 0) return true;
  const haystack = `${product.title} ${product.description}`.toLowerCase();
  return term.split(/\s+/).some((word) => word.length > 2 && haystack.includes(word));
}

function numericId(gid: string): number {
  return Number(/(\d+)\s*$/.exec(gid)?.[1] ?? 0);
}

function json(response: import('node:http').ServerResponse, status: number, body: unknown): void {
  const payload = JSON.stringify(body);
  response.writeHead(status, { 'content-type': 'application/json', 'content-length': Buffer.byteLength(payload) });
  response.end(payload);
}

/**
 * Rewrites `https://<mock domain>/...` to the mock server's plain-HTTP origin
 * so the production connectors run byte-for-byte unchanged in tests.
 */
export function redirectingFetch(domain: string, origin: string): typeof globalThis.fetch {
  return ((input: Parameters<typeof fetch>[0], init?: Parameters<typeof fetch>[1]) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
    const rewritten = url.replace(`https://${domain}`, origin);
    return globalThis.fetch(rewritten, init);
  }) as typeof globalThis.fetch;
}
