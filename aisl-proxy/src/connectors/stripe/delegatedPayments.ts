import Stripe from 'stripe';
import { AislError } from '../../lib/errors.js';
import type { Merchant } from '../../db/repositories/merchants.js';
import type { PaymentAuthorizationRequest, PaymentAuthorizationResult, PaymentProcessor } from '../types.js';

/**
 * Redeems a Stripe shared payment token (SPT).
 *
 * Verified against Stripe's agentic-commerce documentation: the seller charges
 * a granted SPT by creating a PaymentIntent with
 * `payment_method_data[shared_payment_granted_token]` and `confirm=true`.
 * Source: https://docs.stripe.com/agentic-commerce/concepts/shared-payment-tokens
 *
 * `shared_payment_granted_token` ships on a preview API version
 * (2026-04-22.preview by default, see STRIPE_API_VERSION) and is therefore not
 * present in the stable SDK's parameter types. The cast below is the single
 * place that gap is crossed; everything around it is fully typed.
 */
export interface SharedPaymentTokenParams {
  shared_payment_granted_token: string;
}

export class StripeDelegatedPaymentProcessor implements PaymentProcessor {
  readonly name = 'stripe_delegated_token';

  constructor(private readonly stripe: Stripe) {}

  static fromSecretKey(secretKey: string, apiVersion: string, timeoutMs: number): StripeDelegatedPaymentProcessor {
    const stripe = new Stripe(secretKey, {
      // Preview API versions are outside the SDK's literal union.
      apiVersion: apiVersion as Stripe.StripeConfig['apiVersion'],
      timeout: timeoutMs,
      maxNetworkRetries: 2,
      telemetry: false,
    });
    return new StripeDelegatedPaymentProcessor(stripe);
  }

  async authorize(request: PaymentAuthorizationRequest): Promise<PaymentAuthorizationResult> {
    if (request.amountCents <= 0) {
      throw AislError.badRequest('invalid_charge_amount', 'payment amount must be greater than zero');
    }

    const params = {
      amount: request.amountCents,
      currency: request.currency.toLowerCase(),
      confirm: true,
      payment_method_data: { shared_payment_granted_token: request.token } satisfies SharedPaymentTokenParams,
      description: request.description,
      metadata: request.metadata,
    } as unknown as Stripe.PaymentIntentCreateParams;

    const options: Stripe.RequestOptions = { idempotencyKey: request.idempotencyKey };
    const account = stripeAccountOf(request.merchant);
    if (account) {
      // Direct charge on the seller's connected account: the SPT is scoped to
      // the seller's Stripe profile, so the charge must originate there.
      options.stripeAccount = account;
    }

    let intent: Stripe.PaymentIntent;
    try {
      intent = await this.stripe.paymentIntents.create(params, options);
    } catch (error) {
      throw toAislError(error, 'stripe_payment_intent_failed');
    }

    if (intent.status !== 'succeeded' && intent.status !== 'requires_capture') {
      throw new AislError({
        statusCode: 402,
        type: 'processing_error',
        code: 'delegated_payment_not_completed',
        message: `Stripe PaymentIntent ${intent.id} settled to status "${intent.status}"; the delegated token was not charged`,
      });
    }

    return {
      processor: this.name,
      paymentIntentId: intent.id,
      chargeId: latestChargeId(intent),
      status: intent.status,
      amountCents: intent.amount_received > 0 ? intent.amount_received : intent.amount,
      currency: intent.currency.toUpperCase(),
    };
  }

  async refund(request: { paymentIntentId: string; reason: string; stripeAccount?: string }): Promise<{
    refundId: string;
  }> {
    const options: Stripe.RequestOptions = {};
    if (request.stripeAccount) {
      options.stripeAccount = request.stripeAccount;
    }
    try {
      const refund = await this.stripe.refunds.create(
        { payment_intent: request.paymentIntentId, metadata: { aisl_reason: request.reason } },
        options,
      );
      return { refundId: refund.id };
    } catch (error) {
      throw toAislError(error, 'stripe_refund_failed');
    }
  }
}

export function stripeAccountOf(merchant: Merchant): string | null {
  const credentials = merchant.credentials;
  if ('stripe_account_id' in credentials && credentials.stripe_account_id) {
    return credentials.stripe_account_id;
  }
  return null;
}

/** `latest_charge` is an id or an expanded Charge depending on request options. */
function latestChargeId(intent: Stripe.PaymentIntent): string | null {
  const latest = intent.latest_charge;
  if (!latest) return null;
  return typeof latest === 'string' ? latest : latest.id;
}

function toAislError(error: unknown, code: string): AislError {
  if (error instanceof Stripe.errors.StripeError) {
    // Card declines and invalid tokens are the agent's problem to resolve;
    // everything else is an upstream processing failure.
    const clientFault = error.type === 'StripeCardError' || error.type === 'StripeInvalidRequestError';
    return new AislError({
      statusCode: clientFault ? 402 : 502,
      type: 'processing_error',
      code: error.code ?? code,
      message: error.message,
      cause: error,
    });
  }
  return AislError.upstream(code, error instanceof Error ? error.message : String(error), error);
}
