import { describe, expect, it } from 'vitest';
import { canClaimGenerated, compareBranches, impactedNodes, resolveGenome } from '../lib/design/brand-genome';

describe('VNEXUS brand genome foundation', () => {
  it('inherits approved values in brand → project order', () => {
    const result = resolveGenome([
      { scope: 'brand', scopeId: 'b', authority: 'APPROVED', values: { color: 'blue', voice: 'calm' } },
      { scope: 'project', scopeId: 'p', authority: 'APPROVED', values: { color: 'red' } },
    ]);
    expect(result.values.color).toBe('red');
    expect(result.values.voice).toBe('calm');
    expect(result.conflicts).toEqual([]);
  });
  it('blocks immutable and unapproved overrides', () => {
    const result = resolveGenome([
      { scope: 'brand', scopeId: 'b', authority: 'APPROVED', values: { logo: 'approved' }, immutableKeys: ['logo'] },
      { scope: 'project', scopeId: 'p', authority: 'APPROVED', values: { logo: 'different' } },
      { scope: 'page', scopeId: 'pg', authority: 'EXPERIMENTAL', values: { logo: 'other' } },
    ]);
    expect(result.values.logo).toBe('approved');
    expect(result.conflicts.map((c) => c.reason)).toEqual(['IMMUTABLE_OVERRIDE', 'UNAPPROVED_OVERRIDE']);
  });
  it('blocks reversed scope order', () => {
    const result = resolveGenome([
      { scope: 'project', scopeId: 'p', authority: 'APPROVED', values: { a: 1 } },
      { scope: 'brand', scopeId: 'b', authority: 'APPROVED', values: { a: 2 } },
    ]);
    expect(result.values.a).toBe(1);
    expect(result.conflicts[0].reason).toBe('SCOPE_ORDER');
  });
  it('compares branches without modifying either', () => {
    const a = { id: 'a', parentId: null, genomeHash: 'h', reviewState: 'DRAFT' as const, changes: { x: 1, gone: true } };
    const b = { ...a, id: 'b', changes: { x: 2, new: true } };
    expect(compareBranches(a, b)).toEqual({ changedKeys: ['x'], addedKeys: ['new'], removedKeys: ['gone'] });
  });
  it('calculates transitive change impact even for unordered nodes', () => {
    const nodes = [
      { id: 'asset', dependsOn: ['page'] },
      { id: 'page', dependsOn: ['brand'] },
      { id: 'unrelated', dependsOn: [] },
    ];
    expect(impactedNodes(nodes, ['brand'])).toEqual(['asset', 'page']);
  });
  it('never treats simulated or unvalidated output as generated', () => {
    const hash = 'a'.repeat(64);
    expect(canClaimGenerated('SIMULATED', hash)).toBe(false);
    expect(canClaimGenerated('ARTIFACT_RECEIVED', hash)).toBe(false);
    expect(canClaimGenerated('VALIDATED', 'not-a-hash')).toBe(false);
    expect(canClaimGenerated('VALIDATED', hash)).toBe(true);
  });
});
