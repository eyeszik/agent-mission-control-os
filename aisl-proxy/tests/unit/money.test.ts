import { describe, expect, it } from 'vitest';
import {
  applyBps,
  assertSplitInvariants,
  computeCommissionSplit,
  negateSplit,
  toMinorUnits,
} from '../../src/lib/money.js';
import { AislError } from '../../src/lib/errors.js';

describe('computeCommissionSplit', () => {
  it('matches the blueprint worked example exactly', () => {
    // 249.00 USD at 500 bps commission with an 80 bps platform cut.
    const split = computeCommissionSplit({
      grossAmountCents: 24_900,
      commissionRateBps: 500,
      aislCutBps: 80,
    });

    expect(split).toEqual({
      grossAmountCents: 24_900,
      commissionTotalCents: 1_245,
      aislFeeCents: 199,
      agentPayoutCents: 1_046,
      merchantNetCents: 23_655,
    });
  });

  it('keeps every ledger invariant under rounding residue', () => {
    // 1 cent at 500/80 bps truncates both fees to zero; the residue must land
    // entirely in the merchant's net rather than vanishing.
    const split = computeCommissionSplit({ grossAmountCents: 1, commissionRateBps: 500, aislCutBps: 80 });
    expect(split.commissionTotalCents).toBe(0);
    expect(split.aislFeeCents).toBe(0);
    expect(split.agentPayoutCents).toBe(0);
    expect(split.merchantNetCents).toBe(1);
    expect(() => assertSplitInvariants(split)).not.toThrow();
  });

  it('never loses a cent across a wide sweep of amounts and rates', () => {
    for (let gross = 1; gross <= 5_000; gross += 7) {
      for (const [commissionBps, aislBps] of [
        [500, 80],
        [1_250, 333],
        [10_000, 10_000],
        [1, 1],
        [777, 0],
      ] as const) {
        const split = computeCommissionSplit({
          grossAmountCents: gross,
          commissionRateBps: commissionBps,
          aislCutBps: aislBps,
        });
        expect(split.merchantNetCents + split.aislFeeCents + split.agentPayoutCents).toBe(gross);
        expect(split.agentPayoutCents).toBeGreaterThanOrEqual(0);
        expect(split.merchantNetCents).toBeGreaterThanOrEqual(0);
      }
    }
  });

  it('rejects a platform cut larger than the commission it is carved from', () => {
    expect(() => computeCommissionSplit({ grossAmountCents: 10_000, commissionRateBps: 100, aislCutBps: 200 })).toThrow(
      AislError,
    );
  });

  it('rejects out-of-range basis points', () => {
    expect(() => computeCommissionSplit({ grossAmountCents: 100, commissionRateBps: 10_001, aislCutBps: 0 })).toThrow(
      /commission_rate_bps/,
    );
    expect(() => computeCommissionSplit({ grossAmountCents: 100, commissionRateBps: 100, aislCutBps: -1 })).toThrow(
      /aisl_cut_bps/,
    );
  });
});

describe('negateSplit', () => {
  it('produces an exact arithmetic mirror that still balances', () => {
    const split = computeCommissionSplit({ grossAmountCents: 12_999, commissionRateBps: 500, aislCutBps: 80 });
    const reversed = negateSplit(split);

    expect(reversed.grossAmountCents).toBe(-split.grossAmountCents);
    expect(reversed.commissionTotalCents).toBe(-split.commissionTotalCents);
    expect(reversed.aislFeeCents).toBe(-split.aislFeeCents);
    expect(reversed.agentPayoutCents).toBe(-split.agentPayoutCents);
    expect(reversed.merchantNetCents).toBe(-split.merchantNetCents);

    // Sale + reversal nets to zero on every column.
    expect(split.grossAmountCents + reversed.grossAmountCents).toBe(0);
    expect(split.agentPayoutCents + reversed.agentPayoutCents).toBe(0);
  });
});

describe('applyBps', () => {
  it('truncates toward zero so a reversal is the exact negation', () => {
    expect(applyBps(999, 333)).toBe(33);
    expect(applyBps(-999, 333)).toBe(-33);
  });
});

describe('toMinorUnits', () => {
  it('parses decimal money strings without float drift', () => {
    expect(toMinorUnits('249.00', 'USD')).toBe(24_900);
    expect(toMinorUnits('129.50', 'USD')).toBe(12_950);
    expect(toMinorUnits('0.07', 'USD')).toBe(7);
    expect(toMinorUnits('1.005', 'USD')).toBe(100);
  });

  it('honours zero-decimal and three-decimal currencies', () => {
    expect(toMinorUnits('1200', 'JPY')).toBe(1_200);
    expect(toMinorUnits('1.234', 'KWD')).toBe(1_234);
  });

  it('pads short fractions rather than misreading them', () => {
    expect(toMinorUnits('12.5', 'USD')).toBe(1_250);
    expect(toMinorUnits('12', 'USD')).toBe(1_200);
  });

  it('rejects unparseable amounts', () => {
    expect(() => toMinorUnits('not-a-price', 'USD')).toThrow(AislError);
  });
});
