import type { ChangeSet, GenomeConstraint, GenomeDocument, GenomeValue, VnexusChromosome, VnexusScope } from '@amc/shared';

// Pure helpers behind the VNEXUS genome editor. The server owns validation;
// these only convert between editable rows and the documents the API takes,
// and they never coerce a value the operator did not type.

export const CHROMOSOMES: readonly VnexusChromosome[] = ['strategy', 'visual', 'verbal', 'experience', 'production'];
export const SCOPES: readonly VnexusScope[] = ['brand', 'project', 'page', 'component', 'asset'];
export type ValueKind = 'text' | 'number' | 'boolean' | 'list';

export interface ValueRow { id: string; chromosome: VnexusChromosome; key: string; kind: ValueKind; raw: string }
export interface ConstraintRow { id: string; constraint_id: string; key: string; kind: GenomeConstraint['kind']; params: string; severity: GenomeConstraint['severity'] }

let counter = 0;
export const rowId = () => `r${++counter}`;

export function kindOf(value: GenomeValue): ValueKind {
  if (Array.isArray(value)) return 'list';
  if (typeof value === 'number') return 'number';
  if (typeof value === 'boolean') return 'boolean';
  return 'text';
}

export function rawOf(value: GenomeValue): string {
  if (Array.isArray(value)) return value.join('\n');
  if (value === null) return '';
  return String(value);
}

export function parseValue(kind: ValueKind, raw: string): { ok: true; value: GenomeValue } | { ok: false; error: string } {
  if (kind === 'text') return { ok: true, value: raw };
  if (kind === 'list') {
    // ⚡ Bolt: Replaced .map().filter() with a single-pass loop
    const parts = raw.split('\n');
    const res: string[] = [];
    for (let i = 0; i < parts.length; i++) {
      const t = parts[i].trim();
      if (t) res.push(t);
    }
    return { ok: true, value: res };
  }
  if (kind === 'boolean') {
    if (raw === 'true' || raw === 'false') return { ok: true, value: raw === 'true' };
    return { ok: false, error: 'enter true or false' };
  }
  const n = Number(raw);
  if (raw.trim() === '' || !Number.isFinite(n)) return { ok: false, error: 'enter a finite number' };
  return { ok: true, value: n };
}

export function rowsFromDocument(doc: GenomeDocument): { values: ValueRow[]; constraints: ConstraintRow[] } {
  const values: ValueRow[] = [];
  for (const chromosome of CHROMOSOMES) {
    const entries = doc.chromosomes[chromosome] ?? {};
    for (const key of Object.keys(entries).sort()) {
      const value = entries[key] as GenomeValue;
      values.push({ id: rowId(), chromosome, key, kind: kindOf(value), raw: rawOf(value) });
    }
  }
  const constraints = doc.constraints.map((c) => ({ id: rowId(), constraint_id: c.constraint_id, key: c.key, kind: c.kind,
    params: Object.keys(c.params).length ? JSON.stringify(c.params) : '', severity: c.severity }));
  return { values, constraints };
}

export function documentFromRows(values: ValueRow[], constraints: ConstraintRow[]): { ok: true; document: GenomeDocument } | { ok: false; errors: string[] } {
  const errors: string[] = [];
  const chromosomes: Record<string, Record<string, GenomeValue>> = {};
  for (const row of values) {
    if (!row.key.trim()) { errors.push(`a ${row.chromosome} row has no key`); continue; }
    const parsed = parseValue(row.kind, row.raw);
    if (!parsed.ok) { errors.push(`${row.chromosome}.${row.key}: ${parsed.error}`); continue; }
    const bucket = (chromosomes[row.chromosome] ??= {});
    if (row.key in bucket) errors.push(`${row.chromosome}.${row.key} appears twice`);
    bucket[row.key.trim()] = parsed.value;
  }
  const out: GenomeConstraint[] = [];
  for (const row of constraints) {
    let params: Record<string, unknown> = {};
    if (row.params.trim()) {
      try {
        const v: unknown = JSON.parse(row.params);
        if (typeof v !== 'object' || v === null || Array.isArray(v)) throw new Error('not an object');
        params = v as Record<string, unknown>;
      } catch { errors.push(`constraint ${row.constraint_id || '(unnamed)'}: params must be a JSON object`); continue; }
    }
    out.push({ constraint_id: row.constraint_id.trim(), key: row.key.trim(), kind: row.kind, params, severity: row.severity, rationale: '' });
  }
  if (errors.length) return { ok: false, errors };
  return { ok: true, document: { schema_version: 'amc-vnexus-genome/v1', chromosomes, constraints: out, provenance: [] } };
}

/** A change set from "key=value" lines (values typed as text unless they parse as JSON) and "-key" removals. */
export function changeSetFromLines(text: string): { ok: true; changes: ChangeSet } | { ok: false; error: string } {
  const set: Record<string, GenomeValue> = {};
  const unset: string[] = [];
  for (const raw of text.split('\n')) {
    const line = raw.trim();
    if (!line) continue;
    if (line.startsWith('-')) { unset.push(line.slice(1).trim()); continue; }
    const at = line.indexOf('=');
    if (at < 1) return { ok: false, error: `"${line}" is not key=value or -key` };
    const key = line.slice(0, at).trim();
    const value = line.slice(at + 1).trim();
    let parsed: GenomeValue = value;
    if (/^(-?\d+(\.\d+)?|true|false|\[.*\])$/.test(value)) {
      try { parsed = JSON.parse(value) as GenomeValue; } catch { parsed = value; }
    }
    set[key] = parsed;
  }
  return { ok: true, changes: { set, unset, add_constraints: [], remove_constraints: [] } };
}

/** Narrower scope refs are '/'-joined paths rooted at a project id (one segment per level). */
export function scopeRefHint(scope: VnexusScope, brandId: string, projectId: string | null): string {
  const p = projectId ?? '<project>';
  return { brand: brandId, project: p, page: `${p}/home`, component: `${p}/home/hero`, asset: `${p}/home/hero/logo` }[scope];
}
