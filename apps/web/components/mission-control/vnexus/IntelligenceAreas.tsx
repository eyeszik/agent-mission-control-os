"use client";

import { useCallback, useEffect, useState } from 'react';
import {
  auditTrail,
  campaignReport,
  compilePrompt,
  createPrompt,
  immuneRemediate,
  immuneScan,
  importPrompt,
  jobAction,
  listBranches,
  listMediaJobs,
  listPrompts,
  listVersions,
  planCampaign,
  recordMeasurement,
  settleBranch,
  settleVersion,
  type AuditResponse,
  type CampaignPlan,
  type CampaignReport,
  type GenomeVersion,
  type ImmuneScan,
  type MediaJob,
  type PromptCompileResult,
  type PromptRow,
  type VnexusBranch,
} from '../../../lib/api/vnexus';
import type { PromptInventory } from '@amc/shared';
import { useProjectStore } from '../../../lib/stores/projectStore';
import { useVnexusStore } from '../../../lib/stores/vnexusStore';
import { Badge, Empty, Field, KeyValue, Panel, StatusLine, buttonClass, inputClass, short, useAction } from './ui';

function useTarget() {
  const brandId = useVnexusStore((s) => s.brandId) as string;
  const scope = useVnexusStore((s) => s.scope);
  const scopeRef = useVnexusStore((s) => s.scopeRef);
  const projectId = useProjectStore((s) => s.activeProjectId);
  return { brandId, projectId, scopeTarget: { scope, scope_ref: scopeRef } };
}

const CHANNELS = ['social_feed', 'social_story', 'email', 'web_landing', 'search', 'video'];

export function MarketingArea() {
  const { brandId, projectId, scopeTarget } = useTarget();
  const today = new Date().toISOString().slice(0, 10);
  const [form, setForm] = useState({ ref: 'launch', objective: '', channels: ['social_feed'], start: today, weeks: 4, landing: '' });
  const [plan, setPlan] = useState<CampaignPlan | null>(null);
  const [report, setReport] = useState<CampaignReport | null>(null);
  const [m, setM] = useState({ metric: 'signup', value: '', unit: 'count', source: '', source_ref: '' });
  const { state, run, busy } = useAction();
  if (!projectId) return <Empty>Select a project first; campaign plans are stored in it.</Empty>;
  const target = { ...scopeTarget, project_id: projectId };
  return (
    <Panel title="Marketing campaign studio" description="Plans only: publishing, sending and ad spend are disabled. Reports show measured values with sources; forecasts are labelled simulations.">
      <form className="grid grid-cols-1 md:grid-cols-3 gap-2 items-end" onSubmit={async (e) => {
        e.preventDefault();
        const r = await run('Planning campaign', () => planCampaign(brandId, target, { campaign_ref: form.ref, objective: form.objective, channels: form.channels,
          start: form.start, weeks: form.weeks, landing_url: form.landing || null,
          metrics: [{ name: 'signup_rate', numerator_event: 'signup', denominator_event: 'landing_view', source_system: 'first-party analytics' }] }), () => 'Plan compiled');
        if (r) setPlan(r);
      }}>
        <Field label="Campaign ref" hint="lower-case, digits, - and _"><input className={inputClass} value={form.ref} onChange={(e) => setForm({ ...form, ref: e.target.value })} /></Field>
        <Field label="Objective"><input className={inputClass} required value={form.objective} onChange={(e) => setForm({ ...form, objective: e.target.value })} /></Field>
        <Field label="Start"><input type="date" className={inputClass} value={form.start} onChange={(e) => setForm({ ...form, start: e.target.value })} /></Field>
        <Field label="Weeks"><input type="number" min={1} max={26} className={inputClass} value={form.weeks} onChange={(e) => setForm({ ...form, weeks: Number(e.target.value) })} /></Field>
        <Field label="Landing URL (for UTM links)"><input className={inputClass} value={form.landing} onChange={(e) => setForm({ ...form, landing: e.target.value })} /></Field>
        <fieldset className="flex flex-wrap gap-2 text-xs text-zinc-300"><legend className="text-zinc-400">Channels</legend>
          {CHANNELS.map((c) => <label key={c} className="flex items-center gap-1"><input type="checkbox" checked={form.channels.includes(c)} onChange={() => setForm((f) => ({ ...f, channels: f.channels.includes(c) ? f.channels.filter((x) => x !== c) : [...f.channels, c] }))} />{c}</label>)}
        </fieldset>
        <button type="submit" className={`${buttonClass} justify-self-start`} disabled={busy || !form.objective.trim() || form.channels.length === 0}>Compile plan</button>
      </form>
      <StatusLine state={state} />
      {plan && (
        <div className="text-xs flex flex-col gap-2">
          {plan.plan.assumptions.map((a) => <p key={a} className="text-amber-300">Assumption: {a}</p>)}
          {plan.plan.gaps.length > 0 && <p className="text-amber-300">Gaps: {plan.plan.gaps.join(', ')}</p>}
          <table className="w-full"><caption className="text-left text-zinc-400">Messaging matrix</caption><thead><tr className="text-left text-zinc-500"><th className="p-1">Segment</th><th className="p-1">Stage</th><th className="p-1">Message</th><th className="p-1">Proof</th></tr></thead>
            <tbody>{plan.plan.messaging_matrix.map((c) => <tr key={`${c.segment_id}${c.stage}`} className="border-t border-zinc-800"><td className="p-1">{c.segment_id}</td><td className="p-1">{c.stage}</td><td className="p-1">{c.message}</td><td className="p-1">{typeof c.proof === 'string' ? c.proof : 'cited'}</td></tr>)}</tbody></table>
          <p className="text-zinc-400">Calendar: {plan.plan.content_calendar.length} planned slots (publishing disabled), first {plan.plan.content_calendar[0]?.date ?? '—'}</p>
        </div>
      )}
      <form className="grid grid-cols-1 md:grid-cols-5 gap-2 items-end" onSubmit={async (e) => {
        e.preventDefault();
        await run('Recording measurement', () => recordMeasurement(projectId, { campaign_ref: form.ref, metric: m.metric, value: Number(m.value), unit: m.unit,
          source: m.source, source_ref: m.source_ref, observed_at: new Date().toISOString() }), () => 'Measurement recorded');
        setReport(await campaignReport(projectId, form.ref));
      }}>
        <Field label="Measured event"><input className={inputClass} value={m.metric} onChange={(e) => setM({ ...m, metric: e.target.value })} /></Field>
        <Field label="Value"><input className={inputClass} inputMode="decimal" required value={m.value} onChange={(e) => setM({ ...m, value: e.target.value })} /></Field>
        <Field label="Source system"><input className={inputClass} required value={m.source} onChange={(e) => setM({ ...m, source: e.target.value })} /></Field>
        <Field label="Source reference"><input className={inputClass} required value={m.source_ref} onChange={(e) => setM({ ...m, source_ref: e.target.value })} /></Field>
        <button type="submit" className={buttonClass} disabled={busy || !m.source.trim() || !m.source_ref.trim() || m.value === ''}>Record</button>
      </form>
      <button type="button" className={`${buttonClass} self-start`} disabled={busy} onClick={() => void run('Loading report', async () => setReport(await campaignReport(projectId, form.ref)))}>Load report</button>
      {report && <div className="text-xs">{report.metrics.map((r) => <p key={r.metric}>{r.metric}: {r.rate ?? r.numerator.value ?? '—'} <span className="text-zinc-500">({r.rate_kind ?? r.value_kind})</span></p>)}<p className="text-zinc-500">{report.note}</p></div>}
    </Panel>
  );
}

export function PromptsArea() {
  const { brandId, scopeTarget } = useTarget();
  const [rows, setRows] = useState<PromptRow[]>([]);
  const [inventory, setInventory] = useState<PromptInventory | null>(null);
  const [form, setForm] = useState({ id: '', intent: '', family: 'IMAGE', asset: 'hero image', constraints: '' });
  const [imp, setImp] = useState({ id: '', text: '', source: '' });
  const [result, setResult] = useState<PromptCompileResult | null>(null);
  const { state, run, busy } = useAction();
  const refresh = useCallback(async () => { const r = await listPrompts(brandId); setRows(r.prompts); setInventory(r.inventory); }, [brandId]);
  useEffect(() => { void run('Loading prompts', refresh, () => 'Prompts loaded'); }, [refresh, run]);
  const load = () => refresh().catch(() => undefined);
  return (
    <Panel title="Prompt genome library" description="Prompts compile through the existing five-pass compiler and stop at PROMPT_PACKAGE_READY. No provider is called.">
      <StatusLine state={state} />
      {inventory && <p className="text-xs"><Badge value={inventory.status === 'COMPLETE' ? 'PASSED' : 'WARNING'} label={inventory.status} /> {inventory.imported_originals} of {inventory.expected_originals} original source prompts imported. {inventory.note}</p>}
      <form className="grid grid-cols-1 md:grid-cols-5 gap-2 items-end" onSubmit={async (e) => {
        e.preventDefault();
        await run('Saving prompt', () => createPrompt(brandId, form.id, { intent: form.intent, family: form.family, asset_type: form.asset,
          constraints: form.constraints.split('\n').map((c) => c.trim()).filter(Boolean) }), (r) => `Saved v${r.prompt.version}`);
        void load();
      }}>
        <Field label="Prompt id"><input className={inputClass} required value={form.id} onChange={(e) => setForm({ ...form, id: e.target.value })} /></Field>
        <Field label="Intent"><input className={inputClass} required value={form.intent} onChange={(e) => setForm({ ...form, intent: e.target.value })} /></Field>
        <Field label="Family"><select className={inputClass} value={form.family} onChange={(e) => setForm({ ...form, family: e.target.value })}>{['IMAGE', 'COPY', 'VIDEO', 'MOTION', 'PRINT', 'PRESENTATION', 'STORYBOARD', 'UI_UX'].map((f) => <option key={f}>{f}</option>)}</select></Field>
        <Field label="Negative constraints (one per line)"><textarea className={inputClass} rows={1} value={form.constraints} onChange={(e) => setForm({ ...form, constraints: e.target.value })} /></Field>
        <button type="submit" className={`${buttonClass} justify-self-start`} disabled={busy || !form.id || !form.intent}>Save version</button>
      </form>
      <form className="grid grid-cols-1 md:grid-cols-4 gap-2 items-end" onSubmit={async (e) => {
        e.preventDefault();
        await run('Importing original', () => importPrompt(brandId, { prompt_id: imp.id, text: imp.text, source_ref: imp.source }), (r) => `Imported, SHA-256 ${short(r.prompt.source_hash, 12)}`);
        void load();
      }}>
        <Field label="Original id"><input className={inputClass} required value={imp.id} onChange={(e) => setImp({ ...imp, id: e.target.value })} /></Field>
        <Field label="Exact original text" hint="stored byte for byte"><textarea className={inputClass} rows={2} required value={imp.text} onChange={(e) => setImp({ ...imp, text: e.target.value })} /></Field>
        <Field label="Where it came from"><input className={inputClass} required value={imp.source} onChange={(e) => setImp({ ...imp, source: e.target.value })} /></Field>
        <button type="submit" className={`${buttonClass} justify-self-start`} disabled={busy || !imp.id || !imp.text || !imp.source}>Import original</button>
      </form>
      {rows.length === 0 ? <Empty>No prompts yet.</Empty> : (
        <ul className="text-xs flex flex-col gap-1" aria-label="Prompt versions">
          {rows.map((r) => (
            <li key={r.prompt_version_id} className="flex flex-wrap items-center gap-2">
              <span>{r.prompt_id} v{r.version}</span><Badge value={r.status} /><span className="text-zinc-500">{r.source_kind}</span>
              <button type="button" className={buttonClass} disabled={busy} onClick={() => void run('Compiling', async () => setResult(await compilePrompt(r.prompt_version_id, scopeTarget, 'generic_text_to_image')))}>Compile</button>
            </li>
          ))}
        </ul>
      )}
      {result && (
        <div className="text-xs flex flex-col gap-1">
          <p><Badge value={result.final_state} /> {result.package_hash ? `package ${short(result.package_hash, 12)}` : ''}</p>
          {result.missing_genome_keys.length > 0 && <p className="text-amber-300">The approved genome lacks: {result.missing_genome_keys.join(', ')}. Nothing was filled in.</p>}
          {result.checks && <p className="text-zinc-400">{Object.entries(result.checks).map(([k, v]) => `${k}: ${v ? 'yes' : 'no'}`).join(' · ')}</p>}
          {result.adapted && <pre className="whitespace-pre-wrap break-words bg-zinc-950/60 border border-zinc-800 rounded p-2 max-h-48 overflow-auto">{JSON.stringify(result.adapted.body, null, 2)}</pre>}
        </div>
      )}
    </Panel>
  );
}

export function ImmuneArea() {
  const brandId = useVnexusStore((st) => st.brandId) as string;
  const scope = useVnexusStore((st) => st.scope);
  const scopeRef = useVnexusStore((st) => st.scopeRef);
  const [scan, setScan] = useState<ImmuneScan | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [outcome, setOutcome] = useState<string | null>(null);
  const { state, run, busy } = useAction();
  const load = useCallback(() => run('Scanning', async () => { setScan(await immuneScan(brandId, { scope, scope_ref: scopeRef })); setPicked([]); },
    () => 'Scan complete'), [brandId, scope, scopeRef, run]);
  useEffect(() => { void load(); }, [load]);
  return (
    <Panel title="Design immune system" description="Evidence-backed findings. Only deterministic, reversible repairs are offered, and only when you choose them."
      actions={<>
        <button type="button" className={buttonClass} onClick={() => void load()} disabled={busy}>Rescan</button>
        <button type="button" className={buttonClass} disabled={busy || picked.length === 0} onClick={async () => {
          const r = await run('Applying repairs', () => immuneRemediate(brandId, { scope, scope_ref: scopeRef }, picked));
          if (r) setOutcome(`Applied ${r.applied.length}; refused ${r.refused.length}${r.refused.length ? ` (${r.refused.map((x) => x.reason).join('; ')})` : ''}`);
          void load();
        }}>Repair selected</button>
      </>}>
      <StatusLine state={state} />
      {outcome && <p role="status" className="text-xs text-zinc-300">{outcome}</p>}
      {scan && (scan.findings.length === 0 ? <Empty>No findings across {scan.outputs_scanned} outputs.</Empty> : (
        <table className="text-xs w-full"><caption className="sr-only">Findings</caption>
          <thead><tr className="text-left text-zinc-500"><th className="p-1">Repair</th><th className="p-1">Severity</th><th className="p-1">Finding</th><th className="p-1">Subject</th><th className="p-1">Detail</th></tr></thead>
          <tbody>{scan.findings.map((f) => (
            <tr key={f.finding_id} className="border-t border-zinc-800">
              <td className="p-1">{f.remediation ? <input type="checkbox" aria-label={`Repair ${f.code} on ${f.subject}`} checked={picked.includes(f.finding_id)}
                onChange={() => setPicked((p) => (p.includes(f.finding_id) ? p.filter((x) => x !== f.finding_id) : [...p, f.finding_id]))} /> : <span className="text-zinc-600">—</span>}</td>
              <td className="p-1"><Badge value={f.severity} /></td><td className="p-1">{f.code}</td><td className="p-1">{f.subject}</td><td className="p-1 text-zinc-400">{f.detail}</td>
            </tr>))}</tbody></table>
      ))}
    </Panel>
  );
}

export function GovernanceArea() {
  const { brandId, projectId } = useTarget();
  const [versions, setVersions] = useState<GenomeVersion[]>([]);
  const [branches, setBranches] = useState<VnexusBranch[]>([]);
  const [jobs, setJobs] = useState<MediaJob[]>([]);
  const [audit, setAudit] = useState<AuditResponse | null>(null);
  const { state, run, busy } = useAction();
  const refresh = useCallback(async () => {
    const [v, b, a] = await Promise.all([listVersions(brandId), listBranches(brandId), auditTrail(brandId)]);
    setVersions(v.filter((x) => x.status === 'IN_REVIEW')); setBranches(b.filter((x) => x.state === 'IN_REVIEW')); setAudit(a);
    if (projectId) setJobs((await listMediaJobs(projectId)).filter((j) => j.state === 'VALIDATED' && j.estimate && 'approval_id' in j.estimate));
  }, [brandId, projectId]);
  const load = useCallback(() => run('Loading governance', refresh, () => 'Up to date'), [refresh, run]);
  useEffect(() => { void load(); }, [load]);
  const act = async (label: string, fn: () => Promise<unknown>) => { await run(label, fn); void refresh().catch(() => undefined); };
  return (
    <Panel title="Governance and approvals" description="Decisions are made by a different, authorized person in the approval inbox (header). Here you see what waits and apply decisions already made."
      actions={<button type="button" className={buttonClass} disabled={busy} onClick={() => void load()}>Refresh</button>}>
      <StatusLine state={state} />
      <div className="text-xs flex flex-col gap-1">
        <p className="text-zinc-400">Genome versions in review ({versions.length})</p>
        {versions.map((v) => <p key={v.version_id} className="flex flex-wrap items-center gap-2">{v.scope}:{v.scope_ref} v{v.version} <Badge value={v.status} /> submitted by {v.submitted_by ?? '—'}
          <button type="button" className={buttonClass} onClick={() => void act('Applying decision', () => settleVersion(v.version_id))}>Apply decision</button></p>)}
        <p className="text-zinc-400 mt-2">Branch promotions in review ({branches.length})</p>
        {branches.map((b) => <p key={b.branch_id} className="flex flex-wrap items-center gap-2">{b.name} <Badge value={b.state} />
          <button type="button" className={buttonClass} onClick={() => void act('Applying decision', () => settleBranch(b.branch_id))}>Apply decision</button></p>)}
        <p className="text-zinc-400 mt-2">Media jobs awaiting spend approval ({jobs.length})</p>
        {jobs.map((j) => <p key={j.job_id} className="flex flex-wrap items-center gap-2">{j.label || short(j.job_id)} estimate {String(j.estimate.amount_minor)} {j.currency}
          <button type="button" className={buttonClass} onClick={() => void act('Checking authorization', () => jobAction(j.job_id, 'authorize'))}>Check authorization</button></p>)}
      </div>
      {audit && (
        <div className="text-xs">
          <KeyValue rows={[['Audit chain', <Badge key="c" value={audit.verification.intact ? 'PASSED' : 'BLOCKING'} label={audit.verification.intact ? 'intact' : `broken at ${audit.verification.break_at}`} />],
            ['Entries', audit.verification.entries]]} />
          <ol className="list-decimal pl-5 text-zinc-400 max-h-48 overflow-auto mt-1">{audit.entries.slice(-25).reverse().map((e) => <li key={e.entry_id}>{e.created_at.slice(0, 19)} {e.actor} {e.action} {e.subject_type} {short(e.subject_id, 10)}{e.to_state ? ` → ${e.to_state}` : ''}</li>)}</ol>
        </div>
      )}
    </Panel>
  );
}
