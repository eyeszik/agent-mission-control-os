import { z } from 'zod';

/**
 * Agentic Commerce Protocol surface exposed by the gateway.
 *
 * The discovery document shape is fixed by the AISL blueprint's completion
 * invariant (section 1.3 / Task 1) and is asserted verbatim by the test suite.
 * See docs/acp-compatibility.md for how this relates to the upstream
 * agenticcommerce.dev specification.
 */
export const AcpCapabilitiesSchema = z.object({
  catalog_search: z.boolean(),
  delegated_checkout: z.boolean(),
  session_persistence: z.boolean(),
});

export const AcpEndpointsSchema = z.object({
  catalog_query: z.string(),
  checkout_execution: z.string(),
  order_status: z.string(),
});

export const AcpConfigSchema = z.object({
  version: z.string(),
  capabilities: AcpCapabilitiesSchema,
  endpoints: AcpEndpointsSchema,
  payment_methods: z.array(z.string()).min(1),
  supported_currencies: z.array(z.string()).min(1),
});

export type AcpConfig = z.infer<typeof AcpConfigSchema>;

export const ACP_CONFIG: AcpConfig = Object.freeze({
  version: '2026.1',
  capabilities: {
    catalog_search: true,
    delegated_checkout: true,
    session_persistence: false,
  },
  endpoints: {
    catalog_query: '/v1/agent/intent',
    checkout_execution: '/v1/agent/checkout',
    order_status: '/v1/agent/order/{order_id}',
  },
  payment_methods: ['stripe_delegated_token', 'merchant_shared_payment_token'],
  supported_currencies: ['USD', 'EUR', 'GBP'],
});

export const SUPPORTED_CURRENCIES: ReadonlySet<string> = new Set(ACP_CONFIG.supported_currencies);

/* -------------------------------------------------------------------------- */
/* POST /v1/agent/intent                                                       */
/* -------------------------------------------------------------------------- */

const subIdValue = z.string().min(1).max(64);

export const IntentRequestSchema = z.object({
  agent_id: z.string().min(1).max(128),
  query: z.string().min(1).max(512),
  max_results: z.number().int().min(1).max(50).default(5),
  merchant_id: z.uuid().optional(),
  currency: z.string().length(3).optional(),
  sub_ids: z
    .object({
      sub1: subIdValue.optional(),
      sub2: subIdValue.optional(),
    })
    .default({}),
});

export type IntentRequest = z.infer<typeof IntentRequestSchema>;

export interface IntentProductResult {
  acp_token: string;
  merchant_id: string;
  merchant_name: string;
  platform: string;
  product_id: string;
  variant_id: string;
  title: string;
  description: string;
  price: { amount_cents: number; currency: string };
  availability: 'in_stock' | 'out_of_stock' | 'unknown';
  inventory_quantity: number | null;
  url: string | null;
  image_url: string | null;
  attribution: {
    click_id: string;
    signature: string;
    expires_at: string;
    sub_id_1: string | null;
    sub_id_2: string | null;
  };
  checkout: {
    endpoint: string;
    method: 'POST';
    required_fields: string[];
  };
}

export interface IntentResponse {
  query: string;
  agent_id: string;
  result_count: number;
  cache: 'hit' | 'miss' | 'bypass';
  results: IntentProductResult[];
}

/* -------------------------------------------------------------------------- */
/* POST /v1/agent/checkout                                                     */
/* -------------------------------------------------------------------------- */

export const ShippingAddressSchema = z.object({
  name: z.string().min(1).max(255),
  address1: z.string().min(1).max(255),
  address2: z.string().max(255).optional(),
  city: z.string().min(1).max(128),
  state: z.string().max(128).optional(),
  postal_code: z.string().min(1).max(32),
  country: z.string().length(2),
  phone: z.string().max(32).optional(),
  email: z.email().optional(),
});

export type ShippingAddress = z.infer<typeof ShippingAddressSchema>;

export const PaymentCredentialSchema = z.object({
  /**
   * `stripe_payment_token` carries a Stripe shared payment token (spt_...),
   * redeemed via payment_method_data[shared_payment_granted_token].
   * Source: https://docs.stripe.com/agentic-commerce/concepts/shared-payment-tokens
   */
  type: z.enum(['stripe_payment_token', 'merchant_shared_payment_token']),
  token: z.string().min(8).max(255),
});

export type PaymentCredential = z.infer<typeof PaymentCredentialSchema>;

export const CheckoutRequestSchema = z.object({
  acp_token: z.uuid(),
  merchant_id: z.uuid(),
  variant_id: z.string().min(1).max(255),
  quantity: z.number().int().min(1).max(100).default(1),
  payment_credential: PaymentCredentialSchema,
  shipping_address: ShippingAddressSchema,
  attribution_signature: z.string().length(64).optional(),
  idempotency_key: z.string().min(8).max(255).optional(),
});

export type CheckoutRequest = z.infer<typeof CheckoutRequestSchema>;

export interface CheckoutResponse {
  order_id: string;
  external_order_id: string;
  merchant_id: string;
  click_id: string;
  status: 'PENDING_SETTLEMENT' | 'SETTLED' | 'REFUNDED';
  payment: {
    processor: string;
    payment_intent_id: string;
    charge_id: string | null;
    status: string;
  };
  amounts: {
    currency: string;
    gross_amount_cents: number;
    commission_total_cents: number;
    aisl_fee_cents: number;
    agent_payout_cents: number;
    merchant_net_cents: number;
  };
  order_status_url: string;
  created_at: string;
}

/* -------------------------------------------------------------------------- */
/* GET /v1/agent/order/{order_id}                                              */
/* -------------------------------------------------------------------------- */

export interface OrderStatusResponse {
  order_id: string;
  external_order_id: string;
  merchant_id: string;
  click_id: string;
  status: string;
  amounts: {
    currency: string;
    gross_amount_cents: number;
    commission_total_cents: number;
    aisl_fee_cents: number;
    agent_payout_cents: number;
  };
  net_amounts: {
    currency: string;
    gross_amount_cents: number;
    commission_total_cents: number;
    aisl_fee_cents: number;
    agent_payout_cents: number;
  };
  reversals: Array<{
    conversion_id: string;
    external_order_id: string;
    gross_amount_cents: number;
    created_at: string;
  }>;
  created_at: string;
}
