import { AislError } from '../lib/errors.js';
import type { PayoutProcessor } from '../connectors/stripe/transfers.js';
import type { AgentAccount, Payout, PayoutRepository } from '../db/repositories/payouts.js';

export interface PayoutLogger {
  warn: (obj: object, msg: string) => void;
  error: (obj: object, msg: string) => void;
  info: (obj: object, msg: string) => void;
}

export interface PayoutServiceDeps {
  payouts: PayoutRepository;
  transfers: PayoutProcessor;
  logger: PayoutLogger;
}

export type PayoutOutcome =
  | { agentId: string; currency: string; status: 'paid'; payout: Payout }
  | { agentId: string; currency: string; status: 'failed'; payout: Payout; reason: string }
  | {
      agentId: string;
      currency: string;
      status: 'skipped';
      reason: 'no_account' | 'payouts_disabled' | 'no_destination' | 'below_minimum' | 'nothing_claimable';
      amountCents: number;
    };

export interface PayoutRunResult {
  outcomes: PayoutOutcome[];
  paidCents: number;
  paidCount: number;
  failedCount: number;
  skippedCount: number;
}

/**
 * Sweeps accrued `agent_payable` and moves it.
 *
 * Every sweep is a three-step dance per agent: claim (atomic, in Postgres),
 * transfer (external, idempotent), then confirm or release. The claim happens
 * *before* the external call, so a crash between the two leaves a visible
 * IN_FLIGHT payout for reconciliation to surface rather than silently
 * double-paying on the next run.
 */
export class PayoutService {
  constructor(private readonly deps: PayoutServiceDeps) {}

  async run(options: { dryRun?: boolean; agentId?: string } = {}): Promise<PayoutRunResult> {
    const balances = await this.deps.payouts.pendingBalances();
    const targeted = options.agentId ? balances.filter((b) => b.agentId === options.agentId) : balances;

    const outcomes: PayoutOutcome[] = [];
    for (const balance of targeted) {
      outcomes.push(
        await this.settleOne(balance.agentId, balance.currency, balance.amountCents, options.dryRun ?? false),
      );
    }

    return {
      outcomes,
      paidCents: outcomes.reduce((sum, o) => (o.status === 'paid' ? sum + o.payout.amountCents : sum), 0),
      paidCount: outcomes.filter((o) => o.status === 'paid').length,
      failedCount: outcomes.filter((o) => o.status === 'failed').length,
      skippedCount: outcomes.filter((o) => o.status === 'skipped').length,
    };
  }

  private async settleOne(
    agentId: string,
    currency: string,
    pendingCents: number,
    dryRun: boolean,
  ): Promise<PayoutOutcome> {
    const account = await this.deps.payouts.findAgentAccount(agentId);
    const gate = gateFor(account, pendingCents);
    if (gate) {
      // Not an error: a below-minimum or unregistered agent simply keeps
      // accruing until the next run clears the bar.
      return { agentId, currency, status: 'skipped', reason: gate, amountCents: pendingCents };
    }
    // gateFor() has already rejected a null account and a null destination.
    const destination = account?.stripeAccountId as string;

    if (dryRun) {
      return { agentId, currency, status: 'skipped', reason: 'nothing_claimable', amountCents: pendingCents };
    }

    const claim = await this.deps.payouts.claim(agentId, currency);
    if (!claim) {
      return { agentId, currency, status: 'skipped', reason: 'nothing_claimable', amountCents: pendingCents };
    }

    try {
      const transfer = await this.deps.transfers.transfer({
        amountCents: claim.payout.amountCents,
        currency: claim.payout.currency,
        destination,
        idempotencyKey: claim.payout.idempotencyKey,
        description: `AISL agent commission ${agentId}`,
        metadata: {
          aisl_payout_id: claim.payout.id,
          aisl_agent_id: agentId,
          aisl_item_count: String(claim.items.length),
        },
      });

      const paid = await this.deps.payouts.markPaid({
        payoutId: claim.payout.id,
        stripeTransferId: transfer.transferId,
        destinationAccount: destination,
        items: claim.items,
        currency: claim.payout.currency,
      });

      this.deps.logger.info(
        {
          payoutId: paid.id,
          agentId,
          currency,
          amountCents: paid.amountCents,
          transferId: transfer.transferId,
          items: claim.items.length,
        },
        'agent payout transferred',
      );
      return { agentId, currency, status: 'paid', payout: paid };
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error);
      const code = error instanceof AislError ? error.code : 'transfer_failed';

      let released: Payout;
      try {
        released = await this.deps.payouts.markFailed(claim.payout.id, { code, message: reason });
      } catch (releaseError) {
        // The transfer failed AND we cannot release the claim. The money is
        // neither paid nor claimable: exactly the state a human must resolve.
        this.deps.logger.error(
          {
            payoutId: claim.payout.id,
            agentId,
            currency,
            amountCents: claim.payout.amountCents,
            transferError: reason,
            releaseError: releaseError instanceof Error ? releaseError.message : String(releaseError),
          },
          'STRANDED PAYOUT CLAIM: transfer failed and the claim could not be released',
        );
        throw releaseError;
      }

      this.deps.logger.warn(
        { payoutId: released.id, agentId, currency, amountCents: released.amountCents, code, reason },
        'agent payout failed; claim released for the next run',
      );
      return { agentId, currency, status: 'failed', payout: released, reason };
    }
  }
}

function gateFor(
  account: AgentAccount | null,
  pendingCents: number,
): 'no_account' | 'payouts_disabled' | 'no_destination' | 'below_minimum' | null {
  if (!account) return 'no_account';
  if (!account.payoutsEnabled) return 'payouts_disabled';
  if (!account.stripeAccountId) return 'no_destination';
  if (pendingCents <= 0 || pendingCents < account.minimumPayoutCents) return 'below_minimum';
  return null;
}
