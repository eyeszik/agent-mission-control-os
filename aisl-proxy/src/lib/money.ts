import { AislError } from './errors.js';

/**
 * Commission arithmetic.
 *
 * All amounts are integer minor units (cents). Basis points are integers:
 * 10000 bps = 100%. Rounding is floor-toward-zero on the *fee* side so the
 * merchant is never short-changed by a rounding artifact, and the residual
 * always lands in `merchant_net`.
 */
export interface CommissionInput {
  grossAmountCents: number;
  commissionRateBps: number;
  aislCutBps: number;
}

export interface CommissionSplit {
  grossAmountCents: number;
  commissionTotalCents: number;
  aislFeeCents: number;
  agentPayoutCents: number;
  merchantNetCents: number;
}

export function applyBps(amountCents: number, bps: number): number {
  // Math.trunc keeps the sign symmetric so a reversal of X is exactly -X.
  return Math.trunc((amountCents * bps) / 10_000);
}

export function computeCommissionSplit(input: CommissionInput): CommissionSplit {
  const { grossAmountCents, commissionRateBps, aislCutBps } = input;

  if (!Number.isSafeInteger(grossAmountCents)) {
    throw AislError.badRequest('invalid_amount', 'gross amount must be a safe integer of minor units');
  }
  if (!Number.isInteger(commissionRateBps) || commissionRateBps < 0 || commissionRateBps > 10_000) {
    throw AislError.badRequest('invalid_commission_rate', 'commission_rate_bps must be within [0, 10000]');
  }
  if (!Number.isInteger(aislCutBps) || aislCutBps < 0 || aislCutBps > 10_000) {
    throw AislError.badRequest('invalid_aisl_cut', 'aisl_cut_bps must be within [0, 10000]');
  }
  if (aislCutBps > commissionRateBps) {
    throw AislError.badRequest(
      'invalid_commission_split',
      'aisl_cut_bps must not exceed commission_rate_bps; the platform cut is carved out of the commission',
    );
  }

  const commissionTotalCents = applyBps(grossAmountCents, commissionRateBps);
  const aislFeeCents = applyBps(grossAmountCents, aislCutBps);
  const agentPayoutCents = commissionTotalCents - aislFeeCents;
  const merchantNetCents = grossAmountCents - commissionTotalCents;

  assertSplitInvariants({
    grossAmountCents,
    commissionTotalCents,
    aislFeeCents,
    agentPayoutCents,
    merchantNetCents,
  });

  return { grossAmountCents, commissionTotalCents, aislFeeCents, agentPayoutCents, merchantNetCents };
}

/** The invariants every ledger row must satisfy, in either direction (sale or reversal). */
export function assertSplitInvariants(split: CommissionSplit): void {
  const { grossAmountCents, commissionTotalCents, aislFeeCents, agentPayoutCents, merchantNetCents } = split;

  if (commissionTotalCents !== aislFeeCents + agentPayoutCents) {
    throw AislError.internal(
      'ledger_invariant_violation',
      `commission_total (${commissionTotalCents}) != aisl_fee (${aislFeeCents}) + agent_payout (${agentPayoutCents})`,
    );
  }
  if (grossAmountCents !== merchantNetCents + commissionTotalCents) {
    throw AislError.internal(
      'ledger_invariant_violation',
      `gross (${grossAmountCents}) != merchant_net (${merchantNetCents}) + commission_total (${commissionTotalCents})`,
    );
  }
}

export function negateSplit(split: CommissionSplit): CommissionSplit {
  const reversed: CommissionSplit = {
    grossAmountCents: -split.grossAmountCents,
    commissionTotalCents: -split.commissionTotalCents,
    aislFeeCents: -split.aislFeeCents,
    agentPayoutCents: -split.agentPayoutCents,
    merchantNetCents: -split.merchantNetCents,
  };
  assertSplitInvariants(reversed);
  return reversed;
}

/** Convert a decimal money string ("129.99") to integer minor units for the given currency. */
export function toMinorUnits(amount: string | number, currency: string): number {
  const exponent = MINOR_UNIT_EXPONENT[currency.toUpperCase()] ?? 2;
  const text = typeof amount === 'number' ? amount.toFixed(exponent) : amount.trim();

  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(text);
  if (!match) {
    throw AislError.badRequest('invalid_amount', `unparseable monetary amount: ${String(amount)}`);
  }
  const [, sign = '', whole = '0', fraction = ''] = match;
  const padded = (fraction + '0'.repeat(exponent)).slice(0, exponent);
  const scaled = Number(`${whole}${padded}`);
  if (!Number.isSafeInteger(scaled)) {
    throw AislError.badRequest('invalid_amount', `monetary amount out of safe range: ${String(amount)}`);
  }
  return sign === '-' ? -scaled : scaled;
}

/** Zero-decimal and three-decimal currencies per ISO 4217 / Stripe's published list. */
const MINOR_UNIT_EXPONENT: Record<string, number> = {
  BIF: 0, CLP: 0, DJF: 0, GNF: 0, JPY: 0, KMF: 0, KRW: 0, MGA: 0,
  PYG: 0, RWF: 0, UGX: 0, VND: 0, VUV: 0, XAF: 0, XOF: 0, XPF: 0,
  BHD: 3, IQD: 3, JOD: 3, KWD: 3, LYD: 3, OMR: 3, TND: 3,
};
