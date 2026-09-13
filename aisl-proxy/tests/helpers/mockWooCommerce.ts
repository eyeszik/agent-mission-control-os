import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http';
import { once } from 'node:events';
import type { AddressInfo } from 'node:net';

export interface MockWooProduct {
  id: number;
  name: string;
  description?: string;
  short_description?: string;
  price: string;
  permalink?: string;
  stock_status: 'instock' | 'outofstock' | 'onbackorder';
  stock_quantity?: number | null;
  images?: Array<{ src: string }>;
}

export interface MockWooState {
  /** Every Authorization header the connector sent, to assert Basic auth. */
  authHeaders: string[];
  /** Orders the connector created, in creation order. */
  orders: Array<Record<string, unknown>>;
  /** How many times the currency endpoint was hit, to prove the cache works. */
  currencyRequests: number;
  /** Search strings the connector forwarded. */
  searches: Array<{ search: string; perPage: string | null; status: string | null }>;
  currency: string;
  /** Reject every request with 401, to exercise the auth-failure path. */
  rejectAuth: boolean;
}

export interface MockWooCommerce {
  url: string;
  state: MockWooState;
  close: () => Promise<void>;
}

/**
 * Stand-in for a WooCommerce store's REST v3 surface, covering the four
 * endpoints the connector calls: product search, single product, store
 * currency, and order creation.
 */
export async function startMockWooCommerce(products: MockWooProduct[], currency = 'USD'): Promise<MockWooCommerce> {
  const state: MockWooState = {
    authHeaders: [],
    orders: [],
    currencyRequests: 0,
    searches: [],
    currency,
    rejectAuth: false,
  };
  let orderSequence = 0;

  const server: Server = createServer((request: IncomingMessage, response: ServerResponse) => {
    const chunks: Buffer[] = [];
    request.on('data', (chunk: Buffer) => chunks.push(chunk));
    request.on('end', () => {
      const url = new URL(request.url ?? '/', 'http://mock.invalid');
      const auth = request.headers.authorization;
      if (typeof auth === 'string') state.authHeaders.push(auth);

      if (state.rejectAuth) {
        return json(response, 401, {
          code: 'woocommerce_rest_cannot_view',
          message: 'Sorry, you cannot list resources.',
        });
      }

      if (url.pathname === '/wp-json/wc/v3/data/currencies/current') {
        state.currencyRequests += 1;
        return json(response, 200, { code: state.currency, name: state.currency, symbol: '$' });
      }

      if (url.pathname === '/wp-json/wc/v3/products' && request.method === 'GET') {
        const search = url.searchParams.get('search') ?? '';
        state.searches.push({
          search,
          perPage: url.searchParams.get('per_page'),
          status: url.searchParams.get('status'),
        });
        const needle = search.toLowerCase();
        const matches = products.filter((product) => product.name.toLowerCase().includes(needle));
        return json(response, 200, matches);
      }

      const single = /^\/wp-json\/wc\/v3\/products\/(\d+)$/.exec(url.pathname);
      if (single && request.method === 'GET') {
        const product = products.find((candidate) => String(candidate.id) === single[1]);
        if (!product) {
          return json(response, 404, { code: 'woocommerce_rest_product_invalid_id', message: 'Invalid ID.' });
        }
        return json(response, 200, product);
      }

      if (url.pathname === '/wp-json/wc/v3/orders' && request.method === 'POST') {
        const body = JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}') as Record<string, unknown>;
        state.orders.push(body);
        orderSequence += 1;

        const lineItems = (body.line_items as Array<{ product_id: number; quantity: number }>) ?? [];
        const total = lineItems.reduce((sum, item) => {
          const product = products.find((candidate) => candidate.id === item.product_id);
          return sum + Number(product?.price ?? 0) * item.quantity;
        }, 0);

        return json(response, 201, {
          id: 9_000 + orderSequence,
          total: total.toFixed(2),
          currency: (body.currency as string | undefined) ?? state.currency,
          status: 'processing',
        });
      }

      json(response, 404, { code: 'rest_no_route', message: `no mock route for ${url.pathname}` });
    });
  });

  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const { port } = server.address() as AddressInfo;

  return {
    url: `http://127.0.0.1:${port}`,
    state,
    close: async () => {
      server.close();
      await once(server, 'close');
    },
  };
}

function json(response: ServerResponse, status: number, body: unknown): void {
  const payload = JSON.stringify(body);
  response.writeHead(status, {
    'content-type': 'application/json',
    'content-length': Buffer.byteLength(payload),
  });
  response.end(payload);
}
