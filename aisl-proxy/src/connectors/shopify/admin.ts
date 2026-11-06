import { AislError } from '../../lib/errors.js';
import { toMinorUnits } from '../../lib/money.js';
import type { Merchant } from '../../db/repositories/merchants.js';
import { requestJson, type HttpOptions } from '../http.js';
import type { OrderDispatchRequest, OrderDispatchResult, OrderDispatcher } from '../types.js';

interface ShopifyOrderResponse {
  order: {
    id: number;
    name: string;
    total_price: string;
    currency: string;
    financial_status: string;
  };
}

/**
 * Places the already-paid order on Shopify via the Admin REST API.
 *
 * The order is created with an external transaction so Shopify's own gateway
 * is never asked to charge the buyer a second time — the shared payment token
 * was already redeemed on the payment rail before this call.
 *
 * Shopify's order endpoint has no idempotency header, so replay protection
 * lives one layer up in `checkout_idempotency`.
 */
export class ShopifyAdminOrderDispatcher implements OrderDispatcher {
  readonly platform = 'shopify';

  constructor(private readonly http: HttpOptions) {}

  async createOrder(request: OrderDispatchRequest): Promise<OrderDispatchResult> {
    const credentials = this.credentials(request.merchant);
    if (!credentials.admin_token) {
      throw AislError.internal(
        'shopify_admin_token_missing',
        `merchant ${request.merchant.id} has no Shopify Admin token; delegated checkout cannot place the order`,
      );
    }

    const address = request.shippingAddress;
    const payload = {
      order: {
        line_items: [{ variant_id: numericVariantId(request.variantId), quantity: request.quantity }],
        currency: request.currency.toUpperCase(),
        financial_status: 'paid',
        send_receipt: false,
        send_fulfillment_receipt: false,
        inventory_behaviour: 'decrement_obeying_policy',
        email: address.email ?? undefined,
        shipping_address: {
          name: address.name,
          address1: address.address1,
          address2: address.address2 ?? undefined,
          city: address.city,
          province: address.state ?? undefined,
          zip: address.postal_code,
          country_code: address.country.toUpperCase(),
          phone: address.phone ?? undefined,
        },
        transactions: [
          {
            kind: 'sale',
            status: 'success',
            gateway: request.payment.processor,
            amount: (request.payment.amountCents / 100).toFixed(2),
            currency: request.payment.currency.toUpperCase(),
            authorization: request.payment.paymentIntentId,
          },
        ],
        note_attributes: [
          { name: 'aisl_click_id', value: request.clickId },
          { name: 'aisl_agent_id', value: request.agentId },
          { name: 'aisl_idempotency_key', value: request.idempotencyKey },
        ],
        tags: 'aisl,agentic-commerce',
      },
    };

    const response = await requestJson<ShopifyOrderResponse>(
      {
        url: `https://${credentials.store_domain}/admin/api/${credentials.admin_api_version}/orders.json`,
        method: 'POST',
        source: 'shopify_admin',
        headers: { 'X-Shopify-Access-Token': credentials.admin_token },
        body: payload,
      },
      this.http,
    );

    const order = response.order;
    if (!order?.id) {
      throw AislError.upstream('shopify_admin_missing_order', 'Shopify Admin API did not return an order');
    }

    const currency = (order.currency ?? request.currency).toUpperCase();
    return {
      externalOrderId: String(order.id),
      totalAmountCents: toMinorUnits(order.total_price, currency),
      currency,
      raw: order,
    };
  }

  private credentials(merchant: Merchant) {
    if (merchant.credentials.platform !== 'shopify') {
      throw AislError.internal(
        'connector_platform_mismatch',
        `shopify admin dispatcher received a ${merchant.credentials.platform} merchant`,
      );
    }
    return merchant.credentials;
  }
}

/**
 * Admin REST takes the numeric variant id; agents are handed the Storefront
 * GID (`gid://shopify/ProductVariant/123`). Accept either.
 */
export function numericVariantId(variantId: string): number {
  const match = /(\d+)\s*$/.exec(variantId);
  if (!match?.[1]) {
    throw AislError.badRequest('invalid_variant_id', `unrecognised Shopify variant id: ${variantId}`, 'variant_id');
  }
  return Number(match[1]);
}
