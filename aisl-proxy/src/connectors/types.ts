import type { Merchant } from '../db/repositories/merchants.js';
import type { ShippingAddress } from '../types/acp.js';

export interface NormalizedProduct {
  productId: string;
  variantId: string;
  title: string;
  description: string;
  priceCents: number;
  currency: string;
  availability: 'in_stock' | 'out_of_stock' | 'unknown';
  inventoryQuantity: number | null;
  url: string | null;
  imageUrl: string | null;
}

export interface CatalogSearchRequest {
  query: string;
  limit: number;
}

/** Reads a merchant catalogue and normalises it to the ACP product shape. */
export interface CatalogConnector {
  readonly platform: string;
  search(merchant: Merchant, request: CatalogSearchRequest): Promise<NormalizedProduct[]>;
  getVariant(merchant: Merchant, variantId: string): Promise<NormalizedProduct | null>;
}

export interface PaymentAuthorizationRequest {
  merchant: Merchant;
  amountCents: number;
  currency: string;
  /** Shared payment token (spt_...) delegated by the agent. */
  token: string;
  tokenType: 'stripe_payment_token' | 'merchant_shared_payment_token';
  idempotencyKey: string;
  description: string;
  metadata: Record<string, string>;
}

export interface PaymentAuthorizationResult {
  processor: string;
  paymentIntentId: string;
  chargeId: string | null;
  status: string;
  amountCents: number;
  currency: string;
}

/** Redeems a delegated payment credential against the merchant's payment rail. */
export interface PaymentProcessor {
  readonly name: string;
  authorize(request: PaymentAuthorizationRequest): Promise<PaymentAuthorizationResult>;
  /** Compensating action when the order cannot be placed after a successful charge. */
  refund(request: { paymentIntentId: string; reason: string }): Promise<{ refundId: string }>;
}

export interface OrderDispatchRequest {
  merchant: Merchant;
  variantId: string;
  quantity: number;
  shippingAddress: ShippingAddress;
  currency: string;
  payment: PaymentAuthorizationResult;
  clickId: string;
  agentId: string;
  idempotencyKey: string;
}

export interface OrderDispatchResult {
  externalOrderId: string;
  totalAmountCents: number;
  currency: string;
  raw?: unknown;
}

/** Places the paid order on the merchant's own commerce backend. */
export interface OrderDispatcher {
  readonly platform: string;
  createOrder(request: OrderDispatchRequest): Promise<OrderDispatchResult>;
}

export class ConnectorRegistry {
  private readonly catalogs = new Map<string, CatalogConnector>();
  private readonly dispatchers = new Map<string, OrderDispatcher>();

  registerCatalog(connector: CatalogConnector): this {
    this.catalogs.set(connector.platform, connector);
    return this;
  }

  registerDispatcher(dispatcher: OrderDispatcher): this {
    this.dispatchers.set(dispatcher.platform, dispatcher);
    return this;
  }

  catalogFor(platform: string): CatalogConnector | null {
    return this.catalogs.get(platform) ?? null;
  }

  dispatcherFor(platform: string): OrderDispatcher | null {
    return this.dispatchers.get(platform) ?? null;
  }

  platforms(): string[] {
    return [...this.catalogs.keys()];
  }
}
