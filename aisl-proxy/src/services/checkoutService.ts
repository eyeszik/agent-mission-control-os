import { createHash, randomUUID } from 'node:crypto';
import { AislError } from '../lib/errors.js';
import { attributionSignature, safeEqual } from '../lib/crypto.js';
import { computeCommissionSplit } from '../lib/money.js';
import type { Env } from '../config/env.js';
import type { ConnectorRegistry, PaymentAuthorizationResult, PaymentProcessor } from '../connectors/types.js';
import type { ConversionRepository } from '../db/repositories/conversions.js';
import type { CheckoutIdempotencyRepository } from '../db/repositories/checkoutIdempotency.js';
import type { IntentBinding, IntentRepository } from '../db/repositories/intents.js';
import type { Merchant, MerchantRepository } from '../db/repositories/merchants.js';
import type { CheckoutRequest, CheckoutResponse } from '../types/acp.js';

export interface CheckoutLogger {
  warn: (obj: object, msg: string) => void;
  error: (obj: object, msg: string) => void;
  info: (obj: object, msg: string) => void;
}

export interface CheckoutServiceDeps {
  env: Env;
  merchants: MerchantRepository;
  intents: IntentRepository;
  conversions: ConversionRepository;
  idempotency: CheckoutIdempotencyRepository;
  connectors: ConnectorRegistry;
  payments: PaymentProcessor;
  logger: CheckoutLogger;
}

/**
 * Delegated checkout.
 *
 * Ordering follows the blueprint: redeem the delegated payment credential
 * first, then place the merchant order. That ordering makes order creation the
 * step that can strand money, so a failure there triggers an immediate
 * compensating refund before the request fails.
 */
export class CheckoutService {
  constructor(private readonly deps: CheckoutServiceDeps) {}

  async execute(request: CheckoutRequest): Promise<{ response: CheckoutResponse; replayed: boolean }> {
    const binding = await this.deps.intents.findByClickId(request.acp_token);
    if (!binding) {
      throw AislError.notFound('acp_token_not_found', 'acp_token is unknown to this gateway', 'acp_token');
    }
    if (binding.expiresAt.getTime() <= Date.now()) {
      throw AislError.notFound(
        'acp_token_expired',
        `acp_token expired at ${binding.expiresAt.toISOString()}`,
        'acp_token',
      );
    }
    if (binding.merchantId !== request.merchant_id) {
      throw AislError.badRequest(
        'acp_token_merchant_mismatch',
        'acp_token was not minted for the supplied merchant_id',
        'merchant_id',
      );
    }
    if (binding.variantId !== request.variant_id) {
      throw AislError.badRequest(
        'acp_token_variant_mismatch',
        'acp_token was not minted for the supplied variant_id',
        'variant_id',
      );
    }

    if (request.attribution_signature !== undefined) {
      const expected = attributionSignature({
        salt: this.deps.env.AISL_ATTRIBUTION_SALT,
        clickId: binding.clickId,
        agentId: binding.agentId,
        merchantId: binding.merchantId,
      });
      if (!safeEqual(expected, request.attribution_signature)) {
        throw AislError.badRequest(
          'attribution_signature_invalid',
          'attribution_signature does not match the stored attribution binding',
          'attribution_signature',
        );
      }
    }

    const merchant = await this.deps.merchants.findById(request.merchant_id);
    if (!merchant) {
      throw AislError.notFound('merchant_not_found', `merchant ${request.merchant_id} does not exist`, 'merchant_id');
    }

    const idempotencyKey = request.idempotency_key ?? `acp:${binding.clickId}`;
    const requestDigest = digestRequest(request);
    const claim = await this.deps.idempotency.claim(idempotencyKey, requestDigest);

    switch (claim.kind) {
      case 'replay':
        return { response: claim.body as CheckoutResponse, replayed: true };
      case 'in_flight':
        throw AislError.conflict(
          'checkout_in_flight',
          'a checkout with this idempotency key is still executing; poll the order status endpoint',
        );
      case 'mismatch':
        throw AislError.conflict(
          'idempotency_key_reused',
          'this idempotency key was already used with a different request body',
        );
      case 'acquired':
        break;
    }

    try {
      const response = await this.runCheckout({ request, binding, merchant, idempotencyKey });
      await this.deps.idempotency.complete(idempotencyKey, response.order_id, response);
      return { response, replayed: false };
    } catch (error) {
      // Release only the unfinished claim; a completed one stays as the replay record.
      await this.deps.idempotency.release(idempotencyKey);
      throw error;
    }
  }

  private async runCheckout(input: {
    request: CheckoutRequest;
    binding: IntentBinding;
    merchant: Merchant;
    idempotencyKey: string;
  }): Promise<CheckoutResponse> {
    const { request, binding, merchant, idempotencyKey } = input;

    const dispatcher = this.deps.connectors.dispatcherFor(merchant.platform);
    if (!dispatcher) {
      throw AislError.internal(
        'dispatcher_not_registered',
        `no order dispatcher registered for platform ${merchant.platform}`,
      );
    }

    const chargeAmountCents = binding.quotedPriceCents * request.quantity;
    if (chargeAmountCents <= 0) {
      throw AislError.badRequest('invalid_charge_amount', 'quoted price multiplied by quantity is not positive');
    }

    const payment = await this.deps.payments.authorize({
      merchant,
      amountCents: chargeAmountCents,
      currency: binding.currency,
      token: request.payment_credential.token,
      tokenType: request.payment_credential.type,
      // Stripe idempotency is scoped per key, so reuse ours: a retried
      // checkout can never produce a second charge.
      idempotencyKey: `pay:${idempotencyKey}`,
      description: `AISL delegated checkout ${binding.clickId}`,
      metadata: {
        aisl_click_id: binding.clickId,
        aisl_agent_id: binding.agentId,
        aisl_merchant_id: merchant.id,
      },
    });

    let order: Awaited<ReturnType<typeof dispatcher.createOrder>>;
    try {
      order = await dispatcher.createOrder({
        merchant,
        variantId: request.variant_id,
        quantity: request.quantity,
        shippingAddress: request.shipping_address,
        currency: payment.currency,
        payment,
        clickId: binding.clickId,
        agentId: binding.agentId,
        idempotencyKey,
      });
    } catch (error) {
      await this.compensate(payment, error);
      throw error;
    }

    try {
      return await this.settle({ request, binding, merchant, payment, order, chargeAmountCents });
    } catch (error) {
      // The order exists on the merchant backend; refunding here would leave an
      // unpaid order behind. Surface it loudly instead and leave reconciliation
      // to the webhook path, which can still match on the payment intent.
      this.deps.logger.error(
        {
          click_id: binding.clickId,
          merchant_id: merchant.id,
          payment_intent_id: payment.paymentIntentId,
          external_order_id: order.externalOrderId,
          reason: error instanceof Error ? error.message : String(error),
        },
        'order placed and paid but ledger write failed; manual reconciliation required',
      );
      throw error;
    }
  }

  private async settle(input: {
    request: CheckoutRequest;
    binding: IntentBinding;
    merchant: Merchant;
    payment: PaymentAuthorizationResult;
    order: { externalOrderId: string; totalAmountCents: number; currency: string };
    chargeAmountCents: number;
  }): Promise<CheckoutResponse> {
    const { binding, merchant, payment, order } = input;

    if (order.totalAmountCents !== payment.amountCents) {
      this.deps.logger.warn(
        {
          click_id: binding.clickId,
          external_order_id: order.externalOrderId,
          order_total_cents: order.totalAmountCents,
          captured_cents: payment.amountCents,
        },
        'merchant order total differs from the captured amount; settling on the lower of the two',
      );
    }
    // Commission is never paid on money that was not captured, and never on
    // more than the merchant actually billed.
    const grossAmountCents = Math.min(order.totalAmountCents, payment.amountCents);

    const split = computeCommissionSplit({
      grossAmountCents,
      commissionRateBps: merchant.commissionRateBps,
      aislCutBps: merchant.aislCutBps,
    });

    const conversion = await this.deps.conversions.recordSale({
      clickId: binding.clickId,
      merchantId: merchant.id,
      agentId: binding.agentId,
      externalOrderId: order.externalOrderId,
      currency: order.currency,
      stripePaymentIntentId: payment.paymentIntentId,
      stripeChargeId: payment.chargeId,
      split,
    });

    this.deps.logger.info(
      {
        conversion_id: conversion.id,
        click_id: binding.clickId,
        merchant_id: merchant.id,
        external_order_id: order.externalOrderId,
        gross_amount_cents: split.grossAmountCents,
      },
      'delegated checkout settled',
    );

    return {
      order_id: conversion.id,
      external_order_id: conversion.externalOrderId,
      merchant_id: merchant.id,
      click_id: binding.clickId,
      status: 'PENDING_SETTLEMENT',
      payment: {
        processor: payment.processor,
        payment_intent_id: payment.paymentIntentId,
        charge_id: payment.chargeId,
        status: payment.status,
      },
      amounts: {
        currency: conversion.currency,
        gross_amount_cents: split.grossAmountCents,
        commission_total_cents: split.commissionTotalCents,
        aisl_fee_cents: split.aislFeeCents,
        agent_payout_cents: split.agentPayoutCents,
        merchant_net_cents: split.merchantNetCents,
      },
      order_status_url: `${this.deps.env.PUBLIC_BASE_URL}/v1/agent/order/${conversion.id}`,
      created_at: conversion.createdAt.toISOString(),
    };
  }

  /** Refund a captured payment whose order could not be placed. */
  private async compensate(payment: PaymentAuthorizationResult, cause: unknown): Promise<void> {
    try {
      const refund = await this.deps.payments.refund({
        paymentIntentId: payment.paymentIntentId,
        reason: 'aisl_order_dispatch_failed',
      });
      this.deps.logger.warn(
        {
          payment_intent_id: payment.paymentIntentId,
          refund_id: refund.refundId,
          reason: cause instanceof Error ? cause.message : String(cause),
        },
        'order dispatch failed after capture; payment refunded',
      );
    } catch (refundError) {
      // Both legs failed: the buyer has been charged with no order. This is the
      // one state that always needs a human.
      this.deps.logger.error(
        {
          payment_intent_id: payment.paymentIntentId,
          dispatch_error: cause instanceof Error ? cause.message : String(cause),
          refund_error: refundError instanceof Error ? refundError.message : String(refundError),
        },
        'ORPHANED CAPTURE: order dispatch and compensating refund both failed',
      );
    }
  }
}

/** Stable digest of the semantically meaningful request fields. */
export function digestRequest(request: CheckoutRequest): string {
  const canonical = JSON.stringify({
    acp_token: request.acp_token,
    merchant_id: request.merchant_id,
    variant_id: request.variant_id,
    quantity: request.quantity,
    token: request.payment_credential.token,
    shipping: request.shipping_address,
  });
  return createHash('sha256').update(canonical).digest('hex');
}

export function newIdempotencyKey(): string {
  return randomUUID();
}
