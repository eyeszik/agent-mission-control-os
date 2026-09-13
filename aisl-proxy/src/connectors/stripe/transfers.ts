import Stripe from 'stripe';
import { AislError } from '../../lib/errors.js';

export interface TransferRequest {
  amountCents: number;
  currency: string;
  /** Stripe Connect account id (`acct_...`) receiving the funds. */
  destination: string;
  /** Reused as the Stripe request idempotency key; never regenerate it on retry. */
  idempotencyKey: string;
  description: string;
  metadata: Record<string, string>;
}

export interface TransferResult {
  transferId: string;
  amountCents: number;
  currency: string;
}

/** Moves accrued commission from the platform balance to an agent's account. */
export interface PayoutProcessor {
  readonly name: string;
  transfer(request: TransferRequest): Promise<TransferResult>;
}

/**
 * Stripe Connect transfers.
 *
 * Unlike shared payment token redemption, this is the stable, generally
 * available Transfers API — no preview version and no cast. The idempotency key
 * is the payout row's own key, so retrying an ambiguous failure (timeout,
 * connection reset) returns the original transfer instead of sending the money
 * a second time.
 */
export class StripeTransferProcessor implements PayoutProcessor {
  readonly name = 'stripe_transfer';

  constructor(private readonly stripe: Stripe) {}

  async transfer(request: TransferRequest): Promise<TransferResult> {
    if (request.amountCents <= 0) {
      throw AislError.badRequest('invalid_transfer_amount', 'transfer amount must be greater than zero');
    }
    if (!request.destination) {
      throw AislError.badRequest('missing_transfer_destination', 'a Stripe Connect destination is required');
    }

    let transfer: Stripe.Transfer;
    try {
      transfer = await this.stripe.transfers.create(
        {
          amount: request.amountCents,
          currency: request.currency.toLowerCase(),
          destination: request.destination,
          description: request.description,
          metadata: request.metadata,
        },
        { idempotencyKey: request.idempotencyKey },
      );
    } catch (error) {
      if (error instanceof Stripe.errors.StripeError) {
        throw new AislError({
          // An invalid destination or insufficient platform balance is a
          // configuration problem, not a transient upstream fault.
          statusCode: error.type === 'StripeInvalidRequestError' ? 400 : 502,
          type: 'processing_error',
          code: error.code ?? 'stripe_transfer_failed',
          message: error.message,
          cause: error,
        });
      }
      throw AislError.upstream(
        'stripe_transfer_failed',
        error instanceof Error ? error.message : String(error),
        error,
      );
    }

    return {
      transferId: transfer.id,
      amountCents: transfer.amount,
      currency: transfer.currency.toUpperCase(),
    };
  }
}
