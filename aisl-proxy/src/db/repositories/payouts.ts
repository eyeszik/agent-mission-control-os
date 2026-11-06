import { randomUUID } from 'node:crypto';
import type { Database } from '../pool.js';
import { AislError } from '../../lib/errors.js';
import { insertLedgerGroup, payoutLegs } from './conversions.js';

export type PayoutStatus = 'IN_FLIGHT' | 'PAID' | 'FAILED';

export interface AgentAccount {
  agentId: string;
  displayName: string | null;
  stripeAccountId: string | null;
  payoutCurrency: string;
  minimumPayoutCents: number;
  payoutsEnabled: boolean;
}

export interface Payout {
  id: string;
  agentId: string;
  currency: string;
  amountCents: number;
  status: PayoutStatus;
  idempotencyKey: string;
  stripeTransferId: string | null;
  destinationAccount: string | null;
  failureCode: string | null;
  failureMessage: string | null;
  createdAt: Date;
  paidAt: Date | null;
}

/** One conversion's signed contribution to a payout. */
export interface PayoutItem {
  conversionId: string;
  merchantId: string;
  amountCents: number;
}

export interface PendingBalance {
  agentId: string;
  currency: string;
  amountCents: number;
  itemCount: number;
}

interface AgentAccountRow {
  agent_id: string;
  display_name: string | null;
  stripe_account_id: string | null;
  payout_currency: string;
  minimum_payout_cents: string;
  payouts_enabled: boolean;
}

interface PayoutRow {
  id: string;
  agent_id: string;
  currency: string;
  amount_cents: string;
  status: PayoutStatus;
  idempotency_key: string;
  stripe_transfer_id: string | null;
  destination_account: string | null;
  failure_code: string | null;
  failure_message: string | null;
  created_at: Date;
  paid_at: Date | null;
}

const PAYOUT_COLUMNS = `
  id, agent_id, currency, amount_cents, status, idempotency_key, stripe_transfer_id,
  destination_account, failure_code, failure_message, created_at, paid_at
`;

/**
 * What a payout is allowed to draw on.
 *
 * A SALE contributes only once it is SETTLED — the webhook confirming the money
 * actually cleared. A REVERSAL contributes its negative amount only if its
 * parent sale was itself claimed by a payout: clawing back commission that was
 * never paid would invent a debt. When a sale is refunded before it was ever
 * paid out, the sale leaves the eligible set (status becomes REFUNDED) and its
 * reversal never enters it, so the pair nets to zero exactly as it should.
 */
const ELIGIBLE_PREDICATE = `
  pi.conversion_id IS NULL
  AND c.agent_payout_cents <> 0
  AND c.agent_id IS NOT NULL
  AND (
    (c.entry_type = 'SALE' AND c.status = 'SETTLED')
    OR (
      c.entry_type = 'REVERSAL'
      AND EXISTS (SELECT 1 FROM payout_items done WHERE done.conversion_id = c.parent_conversion_id)
    )
  )
`;

export class PayoutRepository {
  constructor(private readonly db: Database) {}

  async upsertAgentAccount(input: {
    agentId: string;
    displayName?: string | null;
    stripeAccountId?: string | null;
    payoutCurrency?: string;
    minimumPayoutCents?: number;
    payoutsEnabled?: boolean;
  }): Promise<AgentAccount> {
    const { rows } = await this.db.query<AgentAccountRow>(
      `INSERT INTO agent_accounts
         (agent_id, display_name, stripe_account_id, payout_currency, minimum_payout_cents, payouts_enabled)
       VALUES ($1, $2, $3, $4, $5, $6)
       ON CONFLICT (agent_id) DO UPDATE SET
         display_name = COALESCE(EXCLUDED.display_name, agent_accounts.display_name),
         stripe_account_id = COALESCE(EXCLUDED.stripe_account_id, agent_accounts.stripe_account_id),
         payout_currency = EXCLUDED.payout_currency,
         minimum_payout_cents = EXCLUDED.minimum_payout_cents,
         payouts_enabled = EXCLUDED.payouts_enabled,
         updated_at = NOW()
       RETURNING agent_id, display_name, stripe_account_id, payout_currency,
                 minimum_payout_cents, payouts_enabled`,
      [
        input.agentId,
        input.displayName ?? null,
        input.stripeAccountId ?? null,
        (input.payoutCurrency ?? 'USD').toUpperCase(),
        input.minimumPayoutCents ?? 0,
        input.payoutsEnabled ?? true,
      ],
    );
    const row = rows[0];
    if (!row) {
      throw AislError.internal('agent_account_upsert_failed', 'agent account upsert returned no row');
    }
    return toAgentAccount(row);
  }

  async findAgentAccount(agentId: string): Promise<AgentAccount | null> {
    const { rows } = await this.db.query<AgentAccountRow>(
      `SELECT agent_id, display_name, stripe_account_id, payout_currency,
              minimum_payout_cents, payouts_enabled
         FROM agent_accounts WHERE agent_id = $1`,
      [agentId],
    );
    return rows[0] ? toAgentAccount(rows[0]) : null;
  }

  /** Unpaid balance per (agent, currency), including negative net positions. */
  async pendingBalances(): Promise<PendingBalance[]> {
    const { rows } = await this.db.query<{
      agent_id: string;
      currency: string;
      amount_cents: string;
      item_count: string;
    }>(
      `SELECT c.agent_id, c.currency,
              SUM(c.agent_payout_cents) AS amount_cents,
              COUNT(*) AS item_count
         FROM conversions c
         LEFT JOIN payout_items pi ON pi.conversion_id = c.id
        WHERE ${ELIGIBLE_PREDICATE}
        GROUP BY c.agent_id, c.currency
        ORDER BY c.agent_id, c.currency`,
    );
    return rows.map((row) => ({
      agentId: row.agent_id,
      currency: row.currency,
      amountCents: Number(row.amount_cents),
      itemCount: Number(row.item_count),
    }));
  }

  /**
   * Atomically claim every eligible conversion for one (agent, currency) into a
   * new IN_FLIGHT payout.
   *
   * The claim is the whole point: after this returns, no other run — and no
   * concurrent replica — can attach those conversions to a second transfer.
   * If a racing run got there first, the UNIQUE index on
   * `payout_items.conversion_id` aborts this transaction rather than paying
   * twice; the caller simply retries on the next sweep.
   */
  async claim(agentId: string, currency: string): Promise<{ payout: Payout; items: PayoutItem[] } | null> {
    return this.db.transaction(async (tx) => {
      const { rows: eligible } = await tx.query<{
        id: string;
        merchant_id: string;
        agent_payout_cents: string;
      }>(
        `SELECT c.id, c.merchant_id, c.agent_payout_cents
           FROM conversions c
           LEFT JOIN payout_items pi ON pi.conversion_id = c.id
          WHERE ${ELIGIBLE_PREDICATE}
            AND c.agent_id = $1
            AND c.currency = $2
          ORDER BY c.created_at ASC
            FOR UPDATE OF c`,
        [agentId, currency.toUpperCase()],
      );

      const items: PayoutItem[] = eligible.map((row) => ({
        conversionId: row.id,
        merchantId: row.merchant_id,
        amountCents: Number(row.agent_payout_cents),
      }));
      const total = items.reduce((sum, item) => sum + item.amountCents, 0);

      // A non-positive net is a carried debt, not a payout: leave every item
      // unclaimed so the next sale nets against it.
      if (items.length === 0 || total <= 0) {
        return null;
      }

      const idempotencyKey = `aisl_payout_${randomUUID()}`;
      const { rows: created } = await tx.query<PayoutRow>(
        `INSERT INTO payouts (agent_id, currency, amount_cents, idempotency_key)
         VALUES ($1, $2, $3, $4)
         RETURNING ${PAYOUT_COLUMNS}`,
        [agentId, currency.toUpperCase(), total, idempotencyKey],
      );
      const payoutRow = created[0];
      if (!payoutRow) {
        throw AislError.internal('payout_insert_failed', 'payout insert returned no row');
      }

      for (const item of items) {
        const { rowCount } = await tx.query(
          `INSERT INTO payout_items (payout_id, conversion_id, amount_cents)
           VALUES ($1, $2, $3)
           ON CONFLICT (conversion_id) DO NOTHING`,
          [payoutRow.id, item.conversionId, item.amountCents],
        );
        if (rowCount === 0) {
          // A concurrent run claimed this conversion between our SELECT and
          // now. Abort the whole claim rather than transfer a partial amount.
          throw AislError.internal(
            'payout_claim_conflict',
            `conversion ${item.conversionId} was claimed by a concurrent payout run`,
          );
        }
      }

      return { payout: toPayout(payoutRow), items };
    });
  }

  /**
   * Record that the transfer landed: flip the payout to PAID and discharge the
   * liability with one balanced ledger group per claimed conversion.
   */
  async markPaid(input: {
    payoutId: string;
    stripeTransferId: string;
    destinationAccount: string;
    items: readonly PayoutItem[];
    currency: string;
  }): Promise<Payout> {
    return this.db.transaction(async (tx) => {
      const { rows } = await tx.query<PayoutRow>(
        `UPDATE payouts
            SET status = 'PAID',
                stripe_transfer_id = $2,
                destination_account = $3,
                paid_at = NOW(),
                updated_at = NOW()
          WHERE id = $1 AND status = 'IN_FLIGHT'
          RETURNING ${PAYOUT_COLUMNS}`,
        [input.payoutId, input.stripeTransferId, input.destinationAccount],
      );
      const row = rows[0];
      if (!row) {
        throw AislError.internal(
          'payout_not_in_flight',
          `payout ${input.payoutId} was not IN_FLIGHT when the transfer was confirmed`,
        );
      }

      for (const item of input.items) {
        await insertLedgerGroup(tx, {
          conversionId: item.conversionId,
          merchantId: item.merchantId,
          currency: input.currency.toUpperCase(),
          memo: `payout ${input.payoutId}`,
          legs: payoutLegs(item.amountCents),
        });
      }

      return toPayout(row);
    });
  }

  /**
   * Record a failed transfer and release the claim.
   *
   * The items are deleted so the money becomes claimable again on the next
   * sweep; the payouts row survives with its failure reason, so an operator can
   * still see that an attempt was made and why it did not land.
   */
  async markFailed(payoutId: string, failure: { code: string; message: string }): Promise<Payout> {
    return this.db.transaction(async (tx) => {
      await tx.query('DELETE FROM payout_items WHERE payout_id = $1', [payoutId]);
      const { rows } = await tx.query<PayoutRow>(
        `UPDATE payouts
            SET status = 'FAILED', failure_code = $2, failure_message = $3, updated_at = NOW()
          WHERE id = $1
          RETURNING ${PAYOUT_COLUMNS}`,
        [payoutId, failure.code.slice(0, 128), failure.message],
      );
      const row = rows[0];
      if (!row) {
        throw AislError.internal('payout_missing', `payout ${payoutId} disappeared while failing it`);
      }
      return toPayout(row);
    });
  }

  async findById(payoutId: string): Promise<Payout | null> {
    const { rows } = await this.db.query<PayoutRow>(
      `SELECT ${PAYOUT_COLUMNS} FROM payouts WHERE id = $1`,
      [payoutId],
    );
    return rows[0] ? toPayout(rows[0]) : null;
  }

  async listByAgent(agentId: string, limit = 50): Promise<Payout[]> {
    const { rows } = await this.db.query<PayoutRow>(
      `SELECT ${PAYOUT_COLUMNS} FROM payouts WHERE agent_id = $1 ORDER BY created_at DESC LIMIT $2`,
      [agentId, limit],
    );
    return rows.map(toPayout);
  }

  /**
   * Payouts that claimed money and never resolved. Each one is money the
   * gateway believes is in flight; a human needs to confirm with Stripe whether
   * the transfer landed before the claim is released.
   */
  async findStalePayouts(olderThanMinutes: number): Promise<Payout[]> {
    const { rows } = await this.db.query<PayoutRow>(
      `SELECT ${PAYOUT_COLUMNS}
         FROM payouts
        WHERE status = 'IN_FLIGHT'
          AND created_at < NOW() - ($1 || ' minutes')::interval
        ORDER BY created_at ASC`,
      [String(olderThanMinutes)],
    );
    return rows.map(toPayout);
  }
}

function toAgentAccount(row: AgentAccountRow): AgentAccount {
  return {
    agentId: row.agent_id,
    displayName: row.display_name,
    stripeAccountId: row.stripe_account_id,
    payoutCurrency: row.payout_currency,
    minimumPayoutCents: Number(row.minimum_payout_cents),
    payoutsEnabled: row.payouts_enabled,
  };
}

function toPayout(row: PayoutRow): Payout {
  return {
    id: row.id,
    agentId: row.agent_id,
    currency: row.currency,
    amountCents: Number(row.amount_cents),
    status: row.status,
    idempotencyKey: row.idempotency_key,
    stripeTransferId: row.stripe_transfer_id,
    destinationAccount: row.destination_account,
    failureCode: row.failure_code,
    failureMessage: row.failure_message,
    createdAt: row.created_at,
    paidAt: row.paid_at,
  };
}
