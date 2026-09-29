import { AislError } from '../../lib/errors.js';
import { toMinorUnits } from '../../lib/money.js';
import type { Merchant } from '../../db/repositories/merchants.js';
import { requestJson, type HttpOptions } from '../http.js';
import type {
  CatalogConnector,
  CatalogSearchRequest,
  NormalizedProduct,
  OrderDispatchRequest,
  OrderDispatchResult,
  OrderDispatcher,
} from '../types.js';

interface WooProduct {
  id: number;
  name: string;
  description: string | null;
  short_description: string | null;
  price: string;
  permalink: string | null;
  stock_status: 'instock' | 'outofstock' | 'onbackorder' | string;
  stock_quantity: number | null;
  images?: Array<{ src: string }>;
}

interface WooOrder {
  id: number;
  total: string;
  currency: string;
  status: string;
}

/**
 * WooCommerce REST v3 connector.
 *
 * WooCommerce exposes no per-request currency on the product payload, so the
 * merchant's configured store currency is read once from `/data/currencies/current`
 * and cached for the lifetime of the connector instance.
 */
export class WooCommerceConnector implements CatalogConnector, OrderDispatcher {
  readonly platform = 'woocommerce';
  private readonly currencyCache = new Map<string, string>();

  constructor(private readonly http: HttpOptions) {}

  async search(merchant: Merchant, request: CatalogSearchRequest): Promise<NormalizedProduct[]> {
    const credentials = this.credentials(merchant);
    const currency = await this.storeCurrency(merchant);

    const url = new URL(`${trimSlash(credentials.base_url)}/wp-json/wc/v3/products`);
    url.searchParams.set('search', request.query);
    url.searchParams.set('per_page', String(request.limit));
    url.searchParams.set('status', 'publish');

    const products = await requestJson<WooProduct[]>(
      { url: url.toString(), source: 'woocommerce', headers: this.authHeaders(merchant) },
      this.http,
    );

    return products.filter((product) => product.price !== '').map((product) => this.normalize(product, currency));
  }

  async getVariant(merchant: Merchant, variantId: string): Promise<NormalizedProduct | null> {
    const credentials = this.credentials(merchant);
    const currency = await this.storeCurrency(merchant);

    const product = await requestJson<WooProduct | null>(
      {
        url: `${trimSlash(credentials.base_url)}/wp-json/wc/v3/products/${encodeURIComponent(variantId)}`,
        source: 'woocommerce',
        headers: this.authHeaders(merchant),
      },
      this.http,
    );
    return product ? this.normalize(product, currency) : null;
  }

  async createOrder(request: OrderDispatchRequest): Promise<OrderDispatchResult> {
    const credentials = this.credentials(request.merchant);
    const address = request.shippingAddress;
    const [firstName, ...restName] = address.name.split(' ');

    const order = await requestJson<WooOrder>(
      {
        url: `${trimSlash(credentials.base_url)}/wp-json/wc/v3/orders`,
        method: 'POST',
        source: 'woocommerce',
        headers: this.authHeaders(request.merchant),
        body: {
          payment_method: request.payment.processor,
          payment_method_title: 'AISL delegated payment',
          set_paid: true,
          transaction_id: request.payment.paymentIntentId,
          currency: request.currency.toUpperCase(),
          line_items: [{ product_id: Number(request.variantId), quantity: request.quantity }],
          shipping: {
            first_name: firstName ?? address.name,
            last_name: restName.join(' '),
            address_1: address.address1,
            address_2: address.address2 ?? '',
            city: address.city,
            state: address.state ?? '',
            postcode: address.postal_code,
            country: address.country.toUpperCase(),
          },
          meta_data: [
            { key: 'aisl_click_id', value: request.clickId },
            { key: 'aisl_agent_id', value: request.agentId },
            { key: 'aisl_idempotency_key', value: request.idempotencyKey },
          ],
        },
      },
      this.http,
    );

    if (!order?.id) {
      throw AislError.upstream('woocommerce_missing_order', 'WooCommerce did not return an order');
    }
    const currency = (order.currency ?? request.currency).toUpperCase();
    return {
      externalOrderId: String(order.id),
      totalAmountCents: toMinorUnits(order.total, currency),
      currency,
      raw: order,
    };
  }

  private normalize(product: WooProduct, currency: string): NormalizedProduct {
    return {
      productId: String(product.id),
      // WooCommerce simple products are their own purchasable unit.
      variantId: String(product.id),
      title: product.name,
      description: stripHtml(product.short_description ?? product.description ?? ''),
      priceCents: toMinorUnits(product.price, currency),
      currency,
      availability:
        product.stock_status === 'instock'
          ? 'in_stock'
          : product.stock_status === 'outofstock'
            ? 'out_of_stock'
            : 'unknown',
      inventoryQuantity: product.stock_quantity,
      url: product.permalink,
      imageUrl: product.images?.[0]?.src ?? null,
    };
  }

  private async storeCurrency(merchant: Merchant): Promise<string> {
    const cached = this.currencyCache.get(merchant.id);
    if (cached) return cached;

    const credentials = this.credentials(merchant);
    const payload = await requestJson<{ code?: string }>(
      {
        url: `${trimSlash(credentials.base_url)}/wp-json/wc/v3/data/currencies/current`,
        source: 'woocommerce',
        headers: this.authHeaders(merchant),
      },
      this.http,
    );

    const currency = (payload?.code ?? 'USD').toUpperCase();
    this.currencyCache.set(merchant.id, currency);
    return currency;
  }

  private authHeaders(merchant: Merchant): Record<string, string> {
    const credentials = this.credentials(merchant);
    const basic = Buffer.from(`${credentials.consumer_key}:${credentials.consumer_secret}`).toString('base64');
    return { authorization: `Basic ${basic}` };
  }

  private credentials(merchant: Merchant) {
    if (merchant.credentials.platform !== 'woocommerce') {
      throw AislError.internal(
        'connector_platform_mismatch',
        `woocommerce connector received a ${merchant.credentials.platform} merchant`,
      );
    }
    return merchant.credentials;
  }
}

function trimSlash(value: string): string {
  return value.replace(/\/+$/, '');
}

function stripHtml(value: string): string {
  return value
    .replace(/<[^>]*>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}
