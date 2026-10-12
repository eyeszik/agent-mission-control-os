import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { GenomeDocumentSchema } from '@amc/shared';
import { changeSetFromLines, documentFromRows, parseValue, rowsFromDocument, scopeRefHint } from '../lib/design/vnexus-editor';

// A real approved genome document recorded from the backend (packages/shared/tests/fixtures/vnexus.json).
const fixture = JSON.parse(readFileSync(join(__dirname, '..', '..', '..', 'packages', 'shared', 'tests', 'fixtures', 'vnexus.json'), 'utf8'));

describe('VNEXUS genome editor helpers', () => {
  it('round-trips a real backend document through editable rows', () => {
    const doc = GenomeDocumentSchema.parse(fixture.version.document);
    const rows = rowsFromDocument(doc);
    const back = documentFromRows(rows.values, rows.constraints);
    expect(back.ok).toBe(true);
    if (back.ok) {
      expect(back.document.chromosomes).toEqual(doc.chromosomes);
      expect(back.document.constraints.map((c) => [c.constraint_id, c.key, c.kind, c.params])).toEqual(
        doc.constraints.map((c) => [c.constraint_id, c.key, c.kind, c.params]));
    }
  });

  it('never coerces what the operator typed', () => {
    expect(parseValue('text', '42')).toEqual({ ok: true, value: '42' });
    expect(parseValue('number', '4.5')).toEqual({ ok: true, value: 4.5 });
    expect(parseValue('number', 'abc').ok).toBe(false);
    expect(parseValue('number', '').ok).toBe(false);
    expect(parseValue('boolean', 'yes').ok).toBe(false);
    expect(parseValue('list', 'plain\n\n warm ')).toEqual({ ok: true, value: ['plain', 'warm'] });
  });

  it('reports row errors instead of building a document', () => {
    const out = documentFromRows([{ id: 'a', chromosome: 'visual', key: '', kind: 'text', raw: 'x' },
      { id: 'b', chromosome: 'visual', key: 'size', kind: 'number', raw: 'big' }],
    [{ id: 'c', constraint_id: 'r', key: 'visual.size', kind: 'RANGE', params: '[1,2]', severity: 'BLOCKING' }]);
    expect(out.ok).toBe(false);
    if (!out.ok) expect(out.errors).toHaveLength(3);
  });

  it('parses branch change lines', () => {
    const r = changeSetFromLines('visual.color.accent=#1d4ed8\nvisual.grid.columns=12\n-verbal.voice.tone\nvisual.flag=true');
    expect(r.ok && r.changes).toEqual({ set: { 'visual.color.accent': '#1d4ed8', 'visual.grid.columns': 12, 'visual.flag': true },
      unset: ['verbal.voice.tone'], add_constraints: [], remove_constraints: [] });
    expect(changeSetFromLines('no equals').ok).toBe(false);
  });

  it('hints scope references with one segment per level', () => {
    expect(scopeRefHint('component', 'b', 'p1')).toBe('p1/home/hero');
    expect(scopeRefHint('brand', 'b', 'p1')).toBe('b');
  });
});
