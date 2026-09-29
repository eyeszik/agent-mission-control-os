import type { Database } from '../db/pool.js';
import type { ConversionRepository } from '../db/repositories/conversions.js';
import type { PayoutRepository } from '../db/repositories/payouts.js';

export type ReconciliationSeverity = 'critical' | 'warning';

export interface ReconciliationFinding {
  /** Stable machine-readable key, safe to alert on. */
  check: string;
  severity: ReconciliationSeverity;
  count: number;
  /** What a human should do about it. */
  detail: string;
  samples: string[];
}

export interface ReconciliationReport {
  checkedAt: string;
  healthy: boolean;
  findings: ReconciliationFinding[];
}

export interface ReconciliationThresholds {
  /** A capture with no settlement webhook after this long is suspicious. */
  pendingSettlementMinutes: number;
  /** A payout claimed but never confirmed after this long is money in limbo. */
  stalePayoutMinutes: number;
}

export const DEFAULT_THRESHOLDS: ReconciliationThresholds = {
  pendingSettlementMinutes: 24 * 60,
  stalePayoutMinutes: 60,
};

export interface ReconciliationDeps {
  db: Database;
  conversions: ConversionRepository;
  payouts: PayoutRepository;
  thresholds?: Partial<ReconciliationThresholds>;
}

const SAMPLE_LIMIT = 10;

/**
 * The states that need a human.
 *
 * Everything the gateway can fix itself, it fixes inline — compensating
 * refunds, released payout claims, webhook retries. This service reports only
 * what is left over: conditions where the safe automated action has already
 * been taken and money is still somewhere it should not be. A `critical`
 * finding means the books disagree with reality; a `warning` means something
 * is overdue and may resolve on its own.
 */
export class ReconciliationService {
  private readonly thresholds: ReconciliationThresholds;

  constructor(private readonly deps: ReconciliationDeps) {
    this.thresholds = { ...DEFAULT_THRESHOLDS, ...deps.thresholds };
  }

  async run(): Promise<ReconciliationReport> {
    const findings = (
      await Promise.all([
        this.unbalancedLedgerGroups(),
        this.splitInvariantViolations(),
        this.orphanedCaptures(),
        this.stuckSettlements(),
        this.stalePayouts(),
        this.unpayableBalances(),
      ])
    ).filter((finding): finding is ReconciliationFinding => finding !== null);

    return {
      checkedAt: new Date().toISOString(),
      healthy: findings.length === 0,
      findings,
    };
  }

  /** Debits must equal credits inside every entry group. Nothing else is acceptable. */
  private async unbalancedLedgerGroups(): Promise<ReconciliationFinding | null> {
    const groups = await this.deps.conversions.findUnbalancedEntryGroups();
    if (groups.length === 0) return null;

    return {
      check: 'ledger_unbalanced',
      severity: 'critical',
      count: groups.length,
      detail:
        'One or more ledger entry groups do not balance. The books are corrupt; stop payouts and investigate before any further transfer.',
      samples: groups.slice(0, SAMPLE_LIMIT).map((group) => `${group.entryGroupId} (delta ${group.delta})`),
    };
  }

  /**
   * A second opinion on the commission arithmetic. The Postgres CHECK
   * constraint should make this impossible; if it ever fires, the constraint
   * was dropped or bypassed.
   */
  private async splitInvariantViolations(): Promise<ReconciliationFinding | null> {
    const { rows } = await this.deps.db.query<{ id: string }>(
      `SELECT id FROM conversions
        WHERE commission_total_cents <> aisl_fee_cents + agent_payout_cents
           OR gross_amount_cents <> merchant_net_cents + commission_total_cents
        LIMIT $1`,
      [SAMPLE_LIMIT],
    );
    if (rows.length === 0) return null;

    return {
      check: 'conversion_split_violation',
      severity: 'critical',
      count: rows.length,
      detail:
        'A conversion row violates the commission invariants. conversions_split_balance_check must have been dropped; restore it and correct the rows.',
      samples: rows.map((row) => row.id),
    };
  }

  /**
   * Money captured on the rail with no conversion behind it.
   *
   * The checkout path issues a compensating refund when order dispatch fails,
   * and logs ORPHANED CAPTURE when even that refund fails. This check finds the
   * database-visible half of that state: a settlement webhook that could not be
   * matched to any sale.
   */
  private async orphanedCaptures(): Promise<ReconciliationFinding | null> {
    // Scoped to settlement events on purpose. An unmatched *refund* is routine
    // — the account may refund charges this gateway never brokered — but an
    // unmatched *capture* means money moved that nothing here can account for.
    const { rows } = await this.deps.db.query<{ event_id: string }>(
      `SELECT event_id FROM webhook_events
        WHERE outcome = 'IGNORED_NO_MATCHING_CONVERSION'
          AND event_type IN ('payment_intent.succeeded', 'charge.succeeded')
        ORDER BY received_at DESC
        LIMIT $1`,
      [SAMPLE_LIMIT],
    );
    if (rows.length === 0) return null;

    return {
      check: 'orphaned_capture',
      severity: 'critical',
      count: rows.length,
      detail:
        'Stripe reported a payment the gateway cannot attribute to any conversion. Money may have moved without a matching order; reconcile each event against the Stripe dashboard.',
      samples: rows.map((row) => row.event_id),
    };
  }

  /** A capture whose settlement webhook never arrived blocks the agent's payout. */
  private async stuckSettlements(): Promise<ReconciliationFinding | null> {
    const { rows } = await this.deps.db.query<{ id: string }>(
      `SELECT id FROM conversions
        WHERE entry_type = 'SALE'
          AND status = 'PENDING_SETTLEMENT'
          AND created_at < NOW() - ($1 || ' minutes')::interval
        ORDER BY created_at ASC
        LIMIT $2`,
      [String(this.thresholds.pendingSettlementMinutes), SAMPLE_LIMIT],
    );
    if (rows.length === 0) return null;

    return {
      check: 'settlement_overdue',
      severity: 'warning',
      count: rows.length,
      detail: `Sales have sat in PENDING_SETTLEMENT for over ${this.thresholds.pendingSettlementMinutes} minutes. Check that the Stripe webhook endpoint is reachable and its events are being delivered.`,
      samples: rows.map((row) => row.id),
    };
  }

  /**
   * A payout that claimed conversions and never resolved.
   *
   * The claim is deliberately taken before the transfer, so a crash in between
   * leaves exactly this row rather than risking a double payment. Releasing it
   * automatically would risk paying twice, so it is escalated instead.
   */
  private async stalePayouts(): Promise<ReconciliationFinding | null> {
    const stale = await this.deps.payouts.findStalePayouts(this.thresholds.stalePayoutMinutes);
    if (stale.length === 0) return null;

    return {
      check: 'payout_in_flight_stale',
      severity: 'critical',
      count: stale.length,
      detail: `Payouts have been IN_FLIGHT for over ${this.thresholds.stalePayoutMinutes} minutes. Confirm against Stripe whether each transfer landed before releasing or retrying it; the idempotency key on the payout row makes a safe retry possible.`,
      samples: stale.map((payout) => `${payout.id} (${payout.amountCents} ${payout.currency})`),
    };
  }

  /** Commission accruing with nowhere to go: not an error, but someone is not getting paid. */
  private async unpayableBalances(): Promise<ReconciliationFinding | null> {
    const balances = await this.deps.payouts.pendingBalances();
    const unpayable: string[] = [];

    for (const balance of balances) {
      if (balance.amountCents <= 0) continue;
      const account = await this.deps.payouts.findAgentAccount(balance.agentId);
      if (!account || !account.stripeAccountId || !account.payoutsEnabled) {
        unpayable.push(`${balance.agentId} (${balance.amountCents} ${balance.currency})`);
      }
    }
    if (unpayable.length === 0) return null;

    return {
      check: 'balance_unpayable',
      severity: 'warning',
      count: unpayable.length,
      detail:
        'Agents have earned commission but have no enabled payout destination. Register them with the agent-account CLI, or the balance will accrue indefinitely.',
      samples: unpayable.slice(0, SAMPLE_LIMIT),
    };
  }
}
