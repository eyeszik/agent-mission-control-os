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

    const account = stripeAccountOf(request.merchant);
    const applicationFeeCents = this.resolveApplicationFee(request, account);

    const params = {
      amount: request.amountCents,
      currency: request.currency.toLowerCase(),
      confirm: true,
      payment_method_data: { shared_payment_granted_token: request.token } satisfies SharedPaymentTokenParams,
      description: request.description,
      metadata: request.metadata,
      ...(applicationFeeCents > 0 ? { application_fee_amount: applicationFeeCents } : {}),
    } as unknown as Stripe.PaymentIntentCreateParams;

    const options: Stripe.RequestOptions = { idempotencyKey: request.idempotencyKey };
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
      applicationFeeCents,
      stripeAccount: account,
    };
  }

  /**
   * How much of this charge the platform collects.
   *
   * A direct charge settles into the merchant's balance, so without an
   * application fee the platform ends the transaction holding nothing while
   * still owing the agent a commission — it would be paying agents out of its
   * own pocket. The fee is therefore the whole commission, not just the
   * platform's slice of it.
   *
   * On a charge created against the platform's own account the gross is
   * already in the platform balance; an application fee there is meaningless
   * (Stripe rejects it) and the merchant's net has to be settled separately.
   */
  private resolveApplicationFee(request: PaymentAuthorizationRequest, account: string | null): number {
    const requested = request.applicationFeeCents;
    if (!Number.isInteger(requested) || requested < 0) {
      throw AislError.internal(
        'invalid_application_fee',
        `application fee must be a non-negative integer, received ${String(requested)}`,
      );
    }
    if (requested === 0) return 0;

    if (!account) {
      // Refusing beats silently dropping the commission: a misconfigured
      // merchant should fail loudly at the first checkout, not quietly cost
      // the platform money on every sale.
      throw AislError.internal(
        'application_fee_without_connected_account',
        `merchant ${request.merchant.id} has commission configured but no stripe_account_id; ` +
          'a charge on the platform account cannot carry an application fee',
      );
    }
    if (requested >= request.amountCents) {
      throw AislError.internal(
        'application_fee_exceeds_charge',
        `application fee ${requested} is not less than the charge amount ${request.amountCents}`,
      );
    }
    return requested;
  }

  async refund(request: {
    paymentIntentId: string;
    reason: string;
    stripeAccount?: string | null;
  }): Promise<{ refundId: string }> {
    const options: Stripe.RequestOptions = {};
    if (request.stripeAccount) {
      // A direct charge does not exist from the platform account's point of
      // view, so a refund that omits this looks up a missing PaymentIntent.
      options.stripeAccount = request.stripeAccount;
    }
    try {
      const refund = await this.stripe.refunds.create(
        {
          payment_intent: request.paymentIntentId,
          metadata: { aisl_reason: request.reason },
          // Unwinding the sale must unwind the commission too, or the platform
          // keeps a fee on a transaction that did not happen.
          ...(request.stripeAccount ? { refund_application_fee: true } : {}),
        } as Stripe.RefundCreateParams,
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
