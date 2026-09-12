import { randomUUID } from 'node:crypto';
import type { Database } from '../pool.js';
import { AislError } from '../../lib/errors.js';
import { assertSplitInvariants, negateSplit, type CommissionSplit } from '../../lib/money.js';

export const LEDGER_ACCOUNTS = {
  /** Money owed to AISL by the payment rail for a captured sale. */
  merchantReceivable: 'merchant_receivable',
  /** The merchant's share after commission. */
  merchantRevenue: 'merchant_revenue',
  /** Commission owed onward to the referring agent. */
  agentPayable: 'agent_payable',
  /** AISL's take-rate. */
  platformRevenue: 'platform_revenue',
} as const;

export type LedgerAccount = (typeof LEDGER_ACCOUNTS)[keyof typeof LEDGER_ACCOUNTS];
export type LedgerDirection = 'DEBIT' | 'CREDIT';

export interface LedgerLeg {
  account: LedgerAccount;
  direction: LedgerDirection;
  amountCents: number;
}

export type ConversionStatus = 'PENDING_SETTLEMENT' | 'SETTLED' | 'REFUNDED' | 'REVERSAL';

export interface Conversion {
  id: string;
  clickId: string;
  merchantId: string;
  agentId: string | null;
  externalOrderId: string;
  currency: string;
  entryType: 'SALE' | 'REVERSAL';
  parentConversionId: string | null;
  stripePaymentIntentId: string | null;
  stripeChargeId: string | null;
  status: ConversionStatus;
  split: CommissionSplit;
  createdAt: Date;
}

interface ConversionRow {
  id: string;
  click_id: string;
  merchant_id: string;
  agent_id: string | null;
  external_order_id: string;
  currency: string;
  entry_type: 'SALE' | 'REVERSAL';
  parent_conversion_id: string | null;
  stripe_payment_intent_id: string | null;
  stripe_charge_id: string | null;
  status: ConversionStatus;
  gross_amount_cents: string;
  commission_total_cents: string;
  aisl_fee_cents: string;
  agent_payout_cents: string;
  merchant_net_cents: string;
  created_at: Date;
}

const CONVERSION_COLUMNS = `
  id, click_id, merchant_id, agent_id, external_order_id, currency, entry_type,
  parent_conversion_id, stripe_payment_intent_id, stripe_charge_id, status,
  gross_amount_cents, commission_total_cents, aisl_fee_cents, agent_payout_cents,
  merchant_net_cents, created_at
`;

export interface RecordSaleInput {
  clickId: string;
  merchantId: string;
  agentId: string;
  externalOrderId: string;
  currency: string;
  stripePaymentIntentId: string | null;
  stripeChargeId: string | null;
  split: CommissionSplit;
}

export class ConversionRepository {
  constructor(private readonly db: Database) {}

  /**
   * Write a sale and its balanced ledger legs atomically.
   *
   * The unique constraint on `external_order_id` is the deduplication point:
   * two concurrent checkouts that reach the same merchant order can only
   * produce one conversion row.
   */
  async recordSale(input: RecordSaleInput): Promise<Conversion> {
    assertSplitInvariants(input.split);

    return this.db.transaction(async (tx) => {
      const { rows } = await tx.query<ConversionRow>(
        `INSERT INTO conversions (
            click_id, merchant_id, agent_id, external_order_id, currency, entry_type,
            stripe_payment_intent_id, stripe_charge_id, status,
            gross_amount_cents, commission_total_cents, aisl_fee_cents, agent_payout_cents, merchant_net_cents
         ) VALUES ($1, $2, $3, $4, $5, 'SALE', $6, $7, 'PENDING_SETTLEMENT', $8, $9, $10, $11, $12)
         RETURNING ${CONVERSION_COLUMNS}`,
        [
          input.clickId,
          input.merchantId,
          input.agentId,
          input.externalOrderId,
          input.currency.toUpperCase(),
          input.stripePaymentIntentId,
          input.stripeChargeId,
          input.split.grossAmountCents,
          input.split.commissionTotalCents,
          input.split.aislFeeCents,
          input.split.agentPayoutCents,
          input.split.merchantNetCents,
        ],
      );
      const row = rows[0];
      if (!row) {
        throw AislError.internal('conversion_insert_failed', 'conversion insert returned no row');
      }

      await insertLedgerGroup(tx, {
        conversionId: row.id,
        merchantId: input.merchantId,
        currency: input.currency.toUpperCase(),
        memo: `sale ${input.externalOrderId}`,
        legs: saleLegs(input.split),
      });

      return toConversion(row);
    });
  }

  async findById(id: string): Promise<Conversion | null> {
    const { rows } = await this.db.query<ConversionRow>(
      `SELECT ${CONVERSION_COLUMNS} FROM conversions WHERE id = $1`,
      [id],
    );
    return rows[0] ? toConversion(rows[0]) : null;
  }

  async findByExternalOrderId(externalOrderId: string): Promise<Conversion | null> {
    const { rows } = await this.db.query<ConversionRow>(
      `SELECT ${CONVERSION_COLUMNS} FROM conversions WHERE external_order_id = $1`,
      [externalOrderId],
    );
    return rows[0] ? toConversion(rows[0]) : null;
  }

  /**
   * Locate the sale a Stripe object refers to. `charge.refunded` carries a
   * charge id and (for modern API versions) the payment intent id; either is a
   * valid handle, so both are tried before giving up.
   */
  async findSaleByStripeReference(reference: {
    chargeId?: string | null;
    paymentIntentId?: string | null;
  }): Promise<Conversion | null> {
    const { rows } = await this.db.query<ConversionRow>(
      `SELECT ${CONVERSION_COLUMNS}
         FROM conversions
        WHERE entry_type = 'SALE'
          AND (
            ($1::text IS NOT NULL AND stripe_charge_id = $1)
            OR ($2::text IS NOT NULL AND stripe_payment_intent_id = $2)
          )
        ORDER BY created_at ASC
        LIMIT 1`,
      [reference.chargeId ?? null, reference.paymentIntentId ?? null],
    );
    return rows[0] ? toConversion(rows[0]) : null;
  }

  async markSettled(conversionId: string, chargeId: string | null): Promise<Conversion | null> {
    const { rows } = await this.db.query<ConversionRow>(
      `UPDATE conversions
          SET status = 'SETTLED',
              stripe_charge_id = COALESCE($2, stripe_charge_id),
              updated_at = NOW()
        WHERE id = $1
          AND entry_type = 'SALE'
          AND status = 'PENDING_SETTLEMENT'
        RETURNING ${CONVERSION_COLUMNS}`,
      [conversionId, chargeId],
    );
    return rows[0] ? toConversion(rows[0]) : null;
  }

  /**
   * Insert the negative offset entry for a refund or dispute and flip the
   * parent sale to REFUNDED, in one transaction.
   *
   * The reversal is its own conversion row because `external_order_id` is
   * UNIQUE on the blueprint schema; it is derived from the parent's id plus
   * the triggering event so replaying the same event cannot double-reverse.
   */
  async recordReversal(input: {
    parent: Conversion;
    reversalReference: string;
    memo: string;
  }): Promise<Conversion> {
    const reversedSplit = negateSplit(input.parent.split);
    const externalOrderId = `${input.parent.externalOrderId}:reversal:${input.reversalReference}`;

    return this.db.transaction(async (tx) => {
      const { rows } = await tx.query<ConversionRow>(
        `INSERT INTO conversions (
            click_id, merchant_id, agent_id, external_order_id, currency, entry_type,
            parent_conversion_id, stripe_payment_intent_id, stripe_charge_id, status,
            gross_amount_cents, commission_total_cents, aisl_fee_cents, agent_payout_cents, merchant_net_cents
         ) VALUES ($1, $2, $3, $4, $5, 'REVERSAL', $6, $7, $8, 'REVERSAL', $9, $10, $11, $12, $13)
         ON CONFLICT (external_order_id) DO NOTHING
         RETURNING ${CONVERSION_COLUMNS}`,
        [
          input.parent.clickId,
          input.parent.merchantId,
          input.parent.agentId,
          externalOrderId,
          input.parent.currency,
          input.parent.id,
          input.parent.stripePaymentIntentId,
          input.parent.stripeChargeId,
          reversedSplit.grossAmountCents,
          reversedSplit.commissionTotalCents,
          reversedSplit.aislFeeCents,
          reversedSplit.agentPayoutCents,
          reversedSplit.merchantNetCents,
        ],
      );

      const row = rows[0];
      if (!row) {
        // Another delivery of the same event already wrote this reversal.
        const existing = await tx.query<ConversionRow>(
          `SELECT ${CONVERSION_COLUMNS} FROM conversions WHERE external_order_id = $1`,
          [externalOrderId],
        );
        const found = existing.rows[0];
        if (!found) {
          throw AislError.internal('reversal_insert_failed', 'reversal insert conflicted but no row was found');
        }
        return toConversion(found);
      }

      await insertLedgerGroup(tx, {
        conversionId: row.id,
        merchantId: input.parent.merchantId,
        currency: input.parent.currency,
        memo: input.memo,
        legs: reversalLegs(input.parent.split),
      });

      await tx.query(
        `UPDATE conversions SET status = 'REFUNDED', updated_at = NOW() WHERE id = $1 AND entry_type = 'SALE'`,
        [input.parent.id],
      );

      return toConversion(row);
    });
  }

  /** Sale plus every reversal that offsets it, for order-status reporting. */
  async findOrderFamily(saleId: string): Promise<{ sale: Conversion; reversals: Conversion[] } | null> {
    const sale = await this.findById(saleId);
    if (!sale || sale.entryType !== 'SALE') return null;

    const { rows } = await this.db.query<ConversionRow>(
      `SELECT ${CONVERSION_COLUMNS} FROM conversions WHERE parent_conversion_id = $1 ORDER BY created_at ASC`,
      [saleId],
    );
    return { sale, reversals: rows.map(toConversion) };
  }

  /** Balance of one ledger account, as (debits - credits). */
  async accountBalance(merchantId: string, account: LedgerAccount, currency: string): Promise<number> {
    const { rows } = await this.db.query<{ balance: string }>(
      `SELECT COALESCE(SUM(CASE WHEN direction = 'DEBIT' THEN amount_cents ELSE -amount_cents END), 0) AS balance
         FROM ledger_entries
        WHERE merchant_id = $1 AND account = $2 AND currency = $3`,
      [merchantId, account, currency.toUpperCase()],
    );
    return Number(rows[0]?.balance ?? 0);
  }

  /** Every entry group must balance; a non-empty result is a ledger corruption alarm. */
  async findUnbalancedEntryGroups(): Promise<Array<{ entryGroupId: string; delta: number }>> {
    const { rows } = await this.db.query<{ entry_group_id: string; delta: string }>(
      `SELECT entry_group_id,
              SUM(CASE WHEN direction = 'DEBIT' THEN amount_cents ELSE -amount_cents END) AS delta
         FROM ledger_entries
        GROUP BY entry_group_id
       HAVING SUM(CASE WHEN direction = 'DEBIT' THEN amount_cents ELSE -amount_cents END) <> 0`,
    );
    return rows.map((row) => ({ entryGroupId: row.entry_group_id, delta: Number(row.delta) }));
  }

  async listLedgerEntries(conversionId: string): Promise<
    Array<{ account: string; direction: LedgerDirection; amountCents: number; entryGroupId: string }>
  > {
    const { rows } = await this.db.query<{
      account: string;
      direction: LedgerDirection;
      amount_cents: string;
      entry_group_id: string;
    }>(
      `SELECT account, direction, amount_cents, entry_group_id
         FROM ledger_entries WHERE conversion_id = $1 ORDER BY id ASC`,
      [conversionId],
    );
    return rows.map((row) => ({
      account: row.account,
      direction: row.direction,
      amountCents: Number(row.amount_cents),
      entryGroupId: row.entry_group_id,
    }));
  }
}

/** A sale debits what the rail owes us and credits the three claimants on it. */
export function saleLegs(split: CommissionSplit): LedgerLeg[] {
  return [
    { account: LEDGER_ACCOUNTS.merchantReceivable, direction: 'DEBIT', amountCents: split.grossAmountCents },
    { account: LEDGER_ACCOUNTS.merchantRevenue, direction: 'CREDIT', amountCents: split.merchantNetCents },
    { account: LEDGER_ACCOUNTS.agentPayable, direction: 'CREDIT', amountCents: split.agentPayoutCents },
    { account: LEDGER_ACCOUNTS.platformRevenue, direction: 'CREDIT', amountCents: split.aislFeeCents },
  ];
}

/** A reversal is the same legs with the directions swapped. Amounts stay positive. */
export function reversalLegs(split: CommissionSplit): LedgerLeg[] {
  return saleLegs(split).map((leg) => ({
    ...leg,
    direction: leg.direction === 'DEBIT' ? ('CREDIT' as const) : ('DEBIT' as const),
  }));
}

async function insertLedgerGroup(
  tx: Database,
  input: {
    conversionId: string;
    merchantId: string;
    currency: string;
    memo: string;
    legs: readonly LedgerLeg[];
  },
): Promise<string> {
  const debits = input.legs
    .filter((leg) => leg.direction === 'DEBIT')
    .reduce((sum, leg) => sum + leg.amountCents, 0);
  const credits = input.legs
    .filter((leg) => leg.direction === 'CREDIT')
    .reduce((sum, leg) => sum + leg.amountCents, 0);

  if (debits !== credits) {
    throw AislError.internal(
      'ledger_unbalanced',
      `refusing to write an unbalanced entry group: debits=${debits} credits=${credits}`,
    );
  }
  if (input.legs.some((leg) => leg.amountCents < 0)) {
    throw AislError.internal('ledger_negative_leg', 'ledger legs must carry non-negative amounts');
  }

  const entryGroupId = randomUUID();
  for (const leg of input.legs) {
    await tx.query(
      `INSERT INTO ledger_entries
         (entry_group_id, conversion_id, merchant_id, account, direction, amount_cents, currency, memo)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`,
      [
        entryGroupId,
        input.conversionId,
        input.merchantId,
        leg.account,
        leg.direction,
        leg.amountCents,
        input.currency,
        input.memo,
      ],
    );
  }
  return entryGroupId;
}

function toConversion(row: ConversionRow): Conversion {
  const split: CommissionSplit = {
    grossAmountCents: Number(row.gross_amount_cents),
    commissionTotalCents: Number(row.commission_total_cents),
    aislFeeCents: Number(row.aisl_fee_cents),
    agentPayoutCents: Number(row.agent_payout_cents),
    merchantNetCents: Number(row.merchant_net_cents),
  };
  assertSplitInvariants(split);

  return {
    id: row.id,
    clickId: row.click_id,
    merchantId: row.merchant_id,
    agentId: row.agent_id,
    externalOrderId: row.external_order_id,
    currency: row.currency,
    entryType: row.entry_type,
    parentConversionId: row.parent_conversion_id,
    stripePaymentIntentId: row.stripe_payment_intent_id,
    stripeChargeId: row.stripe_charge_id,
    status: row.status,
    split,
    createdAt: row.created_at,
  };
}
