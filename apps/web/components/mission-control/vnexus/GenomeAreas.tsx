"use client";

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { GenomeConstraint, VnexusChromosome } from '@amc/shared';
import {
  compareVersions,
  createVersion,
  editVersion,
  immuneScan,
  listVersions,
  resolveScope,
  revertVersion,
  settleVersion,
  submitVersion,
  twinSnapshot,
  versionReadiness,
  withdrawVersion,
  type CompareResponse,
  type GenomeVersion,
  type ImmuneScan,
  type Readiness,
  type ResolveResponse,
  type TwinSnapshot,
} from '../../../lib/api/vnexus';
import {
  CHROMOSOMES,
  documentFromRows,
  rowId,
  rowsFromDocument,
  type ConstraintRow,
  type ValueKind,
  type ValueRow,
} from '../../../lib/design/vnexus-editor';
import { useVnexusStore } from '../../../lib/stores/vnexusStore';
import { Badge, Empty, Field, KeyValue, Panel, StatusLine, Swatch, buttonClass, inputClass, short, useAction } from './ui';

function useTarget() {
  const brandId = useVnexusStore((s) => s.brandId) as string;
  const scope = useVnexusStore((s) => s.scope);
  const scopeRef = useVnexusStore((s) => s.scopeRef);
  return { brandId, scope, scopeRef };
}

export function OverviewArea() {
  const { brandId, scope, scopeRef } = useTarget();
  const [twin, setTwin] = useState<TwinSnapshot | null>(null);
  const [scan, setScan] = useState<ImmuneScan | null>(null);
  const [resolved, setResolved] = useState<ResolveResponse | null>(null);
  const { state, run, busy } = useAction();
  const load = useCallback(() => run('Loading overview', async () => {
    const [t, s, r] = await Promise.all([twinSnapshot(brandId), immuneScan(brandId, { scope, scope_ref: scopeRef }),
      resolveScope(brandId, { scope, scope_ref: scopeRef })]);
    setTwin(t); setScan(s); setResolved(r);
  }, () => 'Overview up to date'), [brandId, scope, scopeRef, run]);
  useEffect(() => { void load(); }, [load]);
  const colours = Object.entries(resolved?.resolution.values ?? {}).filter(([k, v]) => k.startsWith('visual.color.') && typeof v === 'string');
  return (
    <Panel title="Creative overview" description={twin?.label} actions={<button type="button" className={buttonClass} onClick={() => void load()} disabled={busy}>Refresh</button>}>
      <StatusLine state={state} />
      {twin && (
        <KeyValue rows={[
          ['Approved scopes', twin.approved_scopes.length],
          ['Produced outputs', twin.produced_outputs],
          ['Open branches', twin.open_branches],
          ['Awaiting human decision', twin.release_readiness.pending_human_decisions],
          ['Scopes with failed checks', twin.release_readiness.scopes_with_failed_findings],
        ]} />
      )}
      {resolved && (
        <div className="flex flex-col gap-2">
          <p className="text-xs text-zinc-400">Resolved genome for {scope}:{scopeRef} — {resolved.layers.length ? resolved.layers.map((l) => `${l.scope} v${l.version}`).join(' → ') : 'no approved layer'}</p>
          <div className="flex flex-wrap gap-3">{colours.map(([k, v]) => <Swatch key={k} color={String(v)} label={`${k.split('.').pop()} ${String(v)}`} />)}</div>
        </div>
      )}
      {scan && (
        <div className="flex flex-wrap gap-2 text-xs">
          {(['BLOCKING', 'ERROR', 'WARNING', 'INFO'] as const).map((s) => <Badge key={s} value={s} label={`${s} ${scan.counts[s]}`} />)}
          <span className="text-zinc-400">{scan.outputs_scanned} outputs scanned</span>
        </div>
      )}
    </Panel>
  );
}

const CONSTRAINT_KINDS: GenomeConstraint['kind'][] = ['IMMUTABLE', 'REQUIRED', 'ALLOWED_VALUES', 'RANGE', 'HEX_COLOR', 'MIN_CONTRAST'];

export function GenomeEditorArea() {
  const { brandId, scope, scopeRef } = useTarget();
  const [versions, setVersions] = useState<GenomeVersion[]>([]);
  const [working, setWorking] = useState<GenomeVersion | null>(null);
  const [values, setValues] = useState<ValueRow[]>([]);
  const [constraints, setConstraints] = useState<ConstraintRow[]>([]);
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [preview, setPreview] = useState<ResolveResponse | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const { state, run, busy } = useAction();

  const scoped = useMemo(() => versions.filter((v) => v.scope === scope && v.scope_ref === scopeRef), [versions, scope, scopeRef]);
  // isCurrent guards against overlapping loads (an effect re-run, or a target change):
  // a stale load must not overwrite rows the person has started editing.
  const refresh = useCallback(async (isCurrent: () => boolean = () => true) => {
    const all = await listVersions(brandId);
    if (!isCurrent()) return;
    setVersions(all);
    const mine = all.filter((v) => v.scope === scope && v.scope_ref === scopeRef);
    const draft = [...mine].reverse().find((v) => v.status === 'DRAFT' || v.status === 'EXPERIMENTAL');
    const base = draft ?? [...mine].reverse().find((v) => v.status === 'APPROVED') ?? null;
    setWorking(draft ?? null);
    const rows = base ? rowsFromDocument(base.document) : { values: [], constraints: [] };
    setValues(rows.values); setConstraints(rows.constraints); setReadiness(null); setPreview(null);
  }, [brandId, scope, scopeRef]);
  useEffect(() => {
    let active = true;
    void run('Loading versions', () => refresh(() => active), () => 'Loaded');
    return () => { active = false; };
  }, [refresh, run]);

  const save = async () => {
    const built = documentFromRows(values, constraints);
    if (!built.ok) { setErrors(built.errors); return; }
    setErrors([]);
    const saved = await run('Saving draft', () => working
      ? editVersion(working.version_id, working.revision, built.document)
      : createVersion(brandId, { scope, scope_ref: scopeRef, document: built.document }), (v) => `Saved draft v${v.version} (revision ${v.revision})`);
    if (saved) {
      setWorking(saved);
      setReadiness(await versionReadiness(saved.version_id));
      setPreview(await resolveScope(brandId, { scope, scope_ref: scopeRef }, saved.version_id));
    }
  };
  const submit = async () => {
    if (!working) return;
    const v = await run('Submitting for approval', () => submitVersion(working.version_id),
      (r) => `Submitted v${r.version}. A reviewer other than you decides it in the approval inbox.`);
    if (v) { setWorking(null); void refresh().catch(() => undefined); }
  };
  const setRow = (id: string, patch: Partial<ValueRow>) => setValues((rows) => rows.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  const setCRow = (id: string, patch: Partial<ConstraintRow>) => setConstraints((rows) => rows.map((r) => (r.id === id ? { ...r, ...patch } : r)));

  return (
    <Panel title="Brand genome editor" description={`${scope}:${scopeRef} — ${working ? `editing draft v${working.version}` : scoped.length ? 'starting a new draft from the approved version' : 'no versions yet'}`}
      actions={<>
        <button type="button" className={buttonClass} onClick={() => void save()} disabled={busy}>Save draft</button>
        <button type="button" className={buttonClass} onClick={() => void submit()} disabled={busy || !working || readiness?.ready === false}>Submit for approval</button>
      </>}>
      <StatusLine state={state} />
      {errors.length > 0 && <ul role="alert" className="text-xs text-red-300 list-disc pl-4">{errors.map((e) => <li key={e}>{e}</li>)}</ul>}
      <fieldset className="flex flex-col gap-2">
        <legend className="text-xs text-zinc-400 mb-1">Values</legend>
        {values.length === 0 && <Empty>No values. Add the chromosome values this scope defines.</Empty>}
        {values.map((r) => (
          <div key={r.id} className="grid grid-cols-1 sm:grid-cols-[8rem_1fr_6rem_1.5fr_auto] gap-2 items-start">
            <select aria-label="Chromosome" className={inputClass} value={r.chromosome} onChange={(e) => setRow(r.id, { chromosome: e.target.value as VnexusChromosome })}>
              {CHROMOSOMES.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
            <input aria-label="Key" className={inputClass} value={r.key} placeholder="color.ink" onChange={(e) => setRow(r.id, { key: e.target.value })} />
            <select aria-label="Value type" className={inputClass} value={r.kind} onChange={(e) => setRow(r.id, { kind: e.target.value as ValueKind })}>
              {(['text', 'number', 'boolean', 'list'] as const).map((k) => <option key={k} value={k}>{k}</option>)}
            </select>
            {r.kind === 'list'
              ? <textarea aria-label="Value (one item per line)" className={inputClass} rows={2} value={r.raw} onChange={(e) => setRow(r.id, { raw: e.target.value })} />
              : <input aria-label="Value" className={inputClass} value={r.raw} onChange={(e) => setRow(r.id, { raw: e.target.value })} />}
            <button type="button" className={buttonClass} aria-label={`Remove ${r.chromosome}.${r.key}`} onClick={() => setValues((rows) => rows.filter((x) => x.id !== r.id))}>Remove</button>
          </div>
        ))}
        <button type="button" className={`${buttonClass} self-start`} onClick={() => setValues((rows) => [...rows, { id: rowId(), chromosome: 'visual', key: '', kind: 'text', raw: '' }])}>Add value</button>
      </fieldset>
      <fieldset className="flex flex-col gap-2">
        <legend className="text-xs text-zinc-400 mb-1">Constraints (descendant scopes inherit them and cannot remove them)</legend>
        {constraints.map((r) => (
          <div key={r.id} className="grid grid-cols-1 sm:grid-cols-[1fr_1.2fr_9rem_1.5fr_auto] gap-2 items-start">
            <input aria-label="Constraint id" className={inputClass} value={r.constraint_id} placeholder="ink-lock" onChange={(e) => setCRow(r.id, { constraint_id: e.target.value })} />
            <input aria-label="Constraint key" className={inputClass} value={r.key} placeholder="visual.color.ink" onChange={(e) => setCRow(r.id, { key: e.target.value })} />
            <select aria-label="Constraint kind" className={inputClass} value={r.kind} onChange={(e) => setCRow(r.id, { kind: e.target.value as GenomeConstraint['kind'] })}>
              {CONSTRAINT_KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
            </select>
            <input aria-label="Constraint parameters (JSON)" className={inputClass} value={r.params} placeholder='{"against":"visual.color.paper","ratio":4.5}' onChange={(e) => setCRow(r.id, { params: e.target.value })} />
            <button type="button" className={buttonClass} aria-label={`Remove constraint ${r.constraint_id}`} onClick={() => setConstraints((rows) => rows.filter((x) => x.id !== r.id))}>Remove</button>
          </div>
        ))}
        <button type="button" className={`${buttonClass} self-start`} onClick={() => setConstraints((rows) => [...rows, { id: rowId(), constraint_id: '', key: '', kind: 'IMMUTABLE', params: '', severity: 'BLOCKING' }])}>Add constraint</button>
      </fieldset>
      {readiness && (
        <div className="text-xs flex flex-col gap-1">
          <p><Badge value={readiness.ready ? 'PASSED' : 'BLOCKING'} label={readiness.ready ? 'Ready to submit' : 'Blocked'} /></p>
          {[...readiness.conflicts.map((c) => `${c.reason}: ${c.key} (${c.detail})`), ...readiness.blocking_findings.map((f) => `${f.kind}: ${f.key} — ${f.detail}`),
            ...readiness.self_findings.map((f) => `${f.kind}: ${f.key} — ${f.detail}`)].map((m) => <p key={m} className="text-red-300">{m}</p>)}
        </div>
      )}
      {preview && <p className="text-[11px] text-zinc-500">Preview (not authoritative): {Object.keys(preview.resolution.values).length} resolved values, hash {short(preview.resolution_hash)}</p>}
    </Panel>
  );
}

export function HistoryArea() {
  const { brandId, scope, scopeRef } = useTarget();
  const [versions, setVersions] = useState<GenomeVersion[]>([]);
  const [picked, setPicked] = useState<string[]>([]);
  const [diff, setDiff] = useState<CompareResponse | null>(null);
  const { state, run, busy } = useAction();
  const refresh = useCallback(async () => setVersions(await listVersions(brandId)), [brandId]);
  useEffect(() => { void run('Loading history', refresh, () => 'History loaded'); }, [refresh, run]);
  const shown = versions.filter((v) => v.scope === scope && v.scope_ref === scopeRef);
  const act = async (label: string, fn: () => Promise<unknown>) => { await run(label, fn); void refresh().catch(() => undefined); };
  const toggle = (id: string) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p.slice(-1), id]));
  return (
    <Panel title="Genome version history" description="Approved versions are immutable. Reverting creates a new draft from an older version."
      actions={<button type="button" className={buttonClass} disabled={picked.length !== 2 || busy}
        onClick={() => void run('Comparing', async () => setDiff(await compareVersions(picked[0], picked[1])))}>Compare selected</button>}>
      <StatusLine state={state} />
      {shown.length === 0 ? <Empty>No versions at {scope}:{scopeRef}.</Empty> : (
        <table className="text-xs w-full">
          <caption className="sr-only">Versions</caption>
          <thead><tr className="text-left text-zinc-500"><th className="p-1">Pick</th><th className="p-1">Version</th><th className="p-1">Status</th><th className="p-1">Hash</th><th className="p-1">Origin</th><th className="p-1">Decided by</th><th className="p-1">Actions</th></tr></thead>
          <tbody>
            {shown.map((v) => (
              <tr key={v.version_id} className="border-t border-zinc-800">
                <td className="p-1"><input type="checkbox" aria-label={`Select v${v.version}`} checked={picked.includes(v.version_id)} onChange={() => toggle(v.version_id)} /></td>
                <td className="p-1">v{v.version}</td>
                <td className="p-1"><Badge value={v.status} /></td>
                <td className="p-1 font-mono">{short(v.content_hash, 10)}</td>
                <td className="p-1">{v.origin}{v.origin_ref ? ` (${short(v.origin_ref, 8)})` : ''}</td>
                <td className="p-1">{v.decided_by ?? '—'}</td>
                <td className="p-1 flex flex-wrap gap-1">
                  {v.status === 'IN_REVIEW' && <button type="button" className={buttonClass} onClick={() => void act('Checking decision', () => settleVersion(v.version_id))}>Check decision</button>}
                  {v.status === 'IN_REVIEW' && <button type="button" className={buttonClass} onClick={() => void act('Withdrawing', () => withdrawVersion(v.version_id))}>Withdraw</button>}
                  {(v.status === 'APPROVED' || v.status === 'SUPERSEDED') && <button type="button" className={buttonClass} onClick={() => void act('Reverting', () => revertVersion(v.version_id))}>Revert to this</button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {diff && (
        <div className="text-xs flex flex-col gap-1">
          <p className="text-zinc-400">v{diff.from.version} → v{diff.to.version}{diff.identical ? ' (identical)' : ''}</p>
          {diff.diff.added.map((c) => <p key={`a${c.key}`} className="text-emerald-300">+ {c.key} = {JSON.stringify(c.after)}</p>)}
          {diff.diff.removed.map((c) => <p key={`r${c.key}`} className="text-red-300">− {c.key} (was {JSON.stringify(c.before)})</p>)}
          {diff.diff.modified.map((c) => <p key={`m${c.key}`} className="text-amber-300">~ {c.key}: {JSON.stringify(c.before)} → {JSON.stringify(c.after)}</p>)}
          {[...diff.diff.constraints_added.map((c) => `+ constraint ${c}`), ...diff.diff.constraints_removed.map((c) => `− constraint ${c}`)].map((m) => <p key={m}>{m}</p>)}
        </div>
      )}
    </Panel>
  );
}
