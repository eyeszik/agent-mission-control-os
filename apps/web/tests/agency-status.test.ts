import { describe, expect, it } from 'vitest';
import { ActionStateSchema, ImplStatusSchema } from '@amc/shared';
import { RISK_LABELS, formatMinor, labelOf, riskTone, shortHash, toneOf } from '../lib/agency/status';

describe('Agency OS status language', () => {
  it('uses the agreed user-readable labels', () => {
    expect(labelOf('PROVIDER_GAP')).toBe('Tool not connected');
    expect(labelOf('BLOCKED_DEPENDENCY')).toBe('Waiting on prerequisite');
    expect(labelOf('AWAITING_APPROVAL')).toBe('Approval required');
    expect(labelOf('RECONCILING')).toBe('Checking outcome');
    expect(labelOf('LIVE_GATED')).toBe('External action disabled');
    expect(labelOf('VERIFIED')).toBe('Independently checked');
  });

  it('gives every action and catalogue state a label in words (colour is never the only cue)', () => {
    for (const state of [...ActionStateSchema.options, ...ImplStatusSchema.options]) {
      const label = labelOf(state);
      expect(label.length).toBeGreaterThan(2);
      expect(label).not.toMatch(/_/);
    }
  });

  it('maps tones conservatively', () => {
    expect(toneOf('COMPLETED')).toBe('success');
    expect(toneOf('UNKNOWN')).toBe('warning');
    expect(toneOf('BLOCKED')).toBe('danger');
    expect(toneOf('LIVE_GATED')).toBe('info');
    expect(toneOf('SOMETHING_NEW')).toBe('neutral');
    expect(riskTone('R5')).toBe('danger');
    expect(riskTone('R3')).toBe('warning');
    expect(Object.keys(RISK_LABELS)).toEqual(['R0', 'R1', 'R2', 'R3', 'R4', 'R5', 'R6']);
  });

  it('formats money from integer minor units without inventing a currency', () => {
    expect(formatMinor(0, null)).toBe('No cost');
    expect(formatMinor(12500, 'USD')).toMatch(/125/);
    expect(formatMinor(null, 'USD')).toBe('—');
    expect(shortHash(null)).toBe('—');
  });
});
