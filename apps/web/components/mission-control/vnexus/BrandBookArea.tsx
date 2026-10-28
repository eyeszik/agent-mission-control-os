"use client";

import { useEffect, useState } from 'react';
import type { BrandBookBuild, BrandBookCompile, BrandBookCurrent, BrandBookGaps, BrandBookMode } from '@amc/shared';
import {
  bookHtml, bookPdf, bookPreview, buildBook, compileBook, currentBook, getBookGaps, getIntake, proposeFromIntake, releaseBook,
  requestBookApproval, saveIntake,
} from '../../../lib/api/vnexusBrandbook';
import type { ScopeTarget } from '../../../lib/api/vnexus';
import { useProjectStore } from '../../../lib/stores/projectStore';
import { useVnexusStore } from '../../../lib/stores/vnexusStore';
import { Badge, Empty, Field, KeyValue, Panel, StatusLine, buttonClass, inputClass, short, useAction } from './ui';

// Brand book: a projection of the approved genome. Intake evidence and proposals become genome drafts that go through the
// existing review; the book never edits authority. Prompt-ready, rendered, validated and released are separate states.

const MODES: BrandBookMode[] = ['PREVIEW', 'PRODUCTION', 'PROMPTS_ONLY'];

function useTarget() {
  const brandId = useVnexusStore((s) => s.brandId) as string;
  const scope = useVnexusStore((s) => s.scope);
  const scopeRef = useVnexusStore((s) => s.scopeRef);
  const projectId = useProjectStore((s) => s.activeProjectId);
  return { brandId, target: projectId ? { scope, scope_ref: scopeRef, project_id: projectId } : null };
}

function PagePreview({ brandId, target, mode, pageId }: { brandId: string; target: NonNullable<ReturnType<typeof useTarget>['target']>; mode: BrandBookMode; pageId: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let made: string | null = null;
    let cancelled = false;
    setUrl(null); setFailed(false);
    bookPreview(brandId, target, mode, pageId)
      .then(({ blob }) => { made = URL.createObjectURL(blob); if (!cancelled) setUrl(made); })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; if (made) URL.revokeObjectURL(made); };
  }, [brandId, target, mode, pageId]);
  if (failed) return <p className="text-[11px] text-zinc-500">No raster preview stored for {pageId} (previews are captured in PREVIEW builds).</p>;
  if (!url) return <p className="text-[11px] text-zinc-500">Loading preview…</p>;
  return <img src={url} alt={`Raster preview of brand book page ${pageId}; the editable source is the HTML book`} className="max-h-[32rem] w-auto rounded-sm border border-zinc-800" />;
}

function Decisions({ gaps }: { gaps: BrandBookGaps }) {
  if (gaps.decisions.length === 0) return <p className="text-xs text-emerald-300">No open decisions for {gaps.mode.toLowerCase()} mode.</p>;
  return (
    <ul className="flex flex-col gap-1 text-xs">
      {gaps.decisions.map((d) => (
        <li key={d.path} className="flex flex-wrap items-baseline gap-2 border-t border-zinc-800 pt-1">
          <span className="shrink-0"><Badge value={d.severity === 'BLOCKING' ? 'BLOCKING' : 'WARNING'} label={d.severity} /></span>
          <code className="text-zinc-200 break-all">{d.path}</code>
          <span className="text-zinc-400">{d.status.toLowerCase()} · pages {d.pages.join(', ')}</span>
          <span className="text-zinc-300 basis-full">{d.next_action}</span>
        </li>
      ))}
    </ul>
  );
}

function BuildView({ brandId, target, build }: { brandId: string; target: NonNullable<ReturnType<typeof useTarget>['target']>; build: BrandBookBuild | BrandBookCurrent }) {
  const [page, setPage] = useState('p06');
  const [approvalId, setApprovalId] = useState('');
  const { state, run, busy } = useAction();
  const mode = build.mode;
  const telemetry = 'telemetry' in build ? build.telemetry : null;
  const fresh = 'freshness' in build ? build.freshness : null;
  const download = async (kind: 'html' | 'pdf') => {
    const { blob } = kind === 'html' ? await bookHtml(brandId, target, mode) : await bookPdf(brandId, target);
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `brand-book-${build.brand_id}.${kind}`; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    return kind;
  };
  const approvalReason = mode !== 'PRODUCTION' ? 'Only a production build can be approved.'
    : build.status !== 'READY_FOR_APPROVAL' ? `Build is ${build.status.toLowerCase().replace(/_/g, ' ')}.`
    : fresh && !fresh.fresh ? `Stale: ${fresh.reasons.join(', ')}. Rebuild first.` : null;
  return (
    <div className="flex flex-col gap-3 text-xs">
      <KeyValue rows={[
        ['Status', <Badge key="s" value={build.status === 'READY_FOR_APPROVAL' ? 'PASSED' : build.status === 'BLOCKED' ? 'BLOCKING' : 'WARNING'} label={build.status} />],
        ['States', `prompt ${build.states.prompt} · rendered ${build.states.rendered} · validated ${build.states.validated} · ${build.states.released.toLowerCase().replace('_', ' ')}`],
        ['Genome', `${build.genome_ref}${build.proposal_ref ? ` + proposals (${short(build.proposal_ref, 24)})` : ''}`],
        ['Freshness', fresh ? (fresh.fresh ? 'current' : `stale: ${fresh.reasons.join(', ')}`) : 'just built'],
        ['Format', `${build.page_format.name} ${build.page_format.width}×${build.page_format.height}${build.page_format.provisional ? ' (default, provisional)' : ''}`],
        ['Master mark', `${build.mark.kind} · ${build.mark.source}`],
        ['Checks', `${build.checks.summary.PASSED} passed · ${build.checks.summary.FAILED} failed · ${build.checks.summary.NOT_RUN} not run${build.checks.measured ? '' : ' (not measured: Chromium unavailable)'}`],
        ...(telemetry ? [['This build', `${telemetry.pages_rendered} rendered · ${telemetry.pages_reused} reused · ${telemetry.browser_runs} browser run(s) · ${Math.round(telemetry.total_ms)} ms · ${telemetry.model_calls} model calls`] as [string, string]] : []),
      ]} />
      <div className="flex flex-wrap gap-2">
        <button type="button" className={buttonClass} disabled={busy} onClick={() => void run('Downloading book', () => download('html'))}>Download HTML (editable source)</button>
        <button type="button" className={buttonClass} disabled={busy || !build.pdf} onClick={() => void run('Downloading PDF', () => download('pdf'))}>Download PDF</button>
        {!build.pdf && <span className="text-zinc-500 self-center">PDF is printed only for production builds.</span>}
      </div>
      <table className="w-full">
        <caption className="sr-only">Pages</caption>
        <thead><tr className="text-left text-zinc-500"><th className="p-1">Page</th><th className="p-1">Status</th><th className="p-1">Checks</th><th className="p-1">Gaps</th><th className="p-1">Dependencies</th></tr></thead>
        <tbody>{build.pages.map((p) => (
          <tr key={p.page_id} className="border-t border-zinc-800">
            <td className="p-1"><button type="button" className="underline text-zinc-200 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-emerald-500/60" aria-pressed={page === p.page_id} onClick={() => setPage(p.page_id)}>{p.order.toString().padStart(2, '0')} {p.title}</button></td>
            <td className="p-1"><Badge value={p.status === 'READY' ? 'PASSED' : p.status === 'BLOCKED' ? 'BLOCKING' : 'WARNING'} label={p.status} /></td>
            <td className="p-1 text-zinc-300">{p.checks.PASSED} ok{p.checks.FAILED ? ` · ${p.checks.FAILED} failed` : ''}{p.checks.NOT_RUN ? ` · ${p.checks.NOT_RUN} not run` : ''}</td>
            <td className="p-1 text-zinc-300">{p.gaps.length || '—'}</td>
            <td className="p-1 text-zinc-500"><code>{short(p.dependency_hash, 10)}</code>{p.parts.length > 1 ? ` · ${p.parts.length} parts` : ''}</td>
          </tr>
        ))}</tbody>
      </table>
      {mode === 'PREVIEW' && <PagePreview brandId={brandId} target={target} mode={mode} pageId={page} />}
      <div className="flex flex-wrap items-end gap-2">
        <button type="button" className={buttonClass} disabled={busy || approvalReason !== null} onClick={() => void run('Requesting approval',
          () => requestBookApproval(brandId, target), (r) => (r.status === 'PENDING' ? `Approval ${short(r.approval_id, 10)} pending in the approval queue` : `Blocked: ${(r.reasons ?? []).join(', ')}`))}>Request approval</button>
        <Field label="Approval id (decided in the approval queue)"><input className={inputClass} value={approvalId} onChange={(e) => setApprovalId(e.target.value.trim())} /></Field>
        <button type="button" className={buttonClass} disabled={busy || mode !== 'PRODUCTION' || !approvalId} onClick={() => void run('Releasing',
          () => releaseBook(brandId, target, approvalId), (r) => (r.status === 'RELEASED_LOCAL' ? 'Released locally (no external effect)' : `Blocked: ${r.reasons.join(', ')}`))}>Release locally</button>
        {approvalReason && <span className="text-zinc-500 self-center">{approvalReason}</span>}
      </div>
      <StatusLine state={state} />
    </div>
  );
}

function IntakePanel({ brandId, scope }: { brandId: string; scope: ScopeTarget }) {
  const [text, setText] = useState('');
  const [sha, setSha] = useState<string | null>(null);
  const { state, run, busy } = useAction();
  useEffect(() => {
    void getIntake(brandId).then((r) => { setText(JSON.stringify(r.intake, null, 2)); setSha(r.sha256); }).catch(() => undefined);
  }, [brandId]);
  let parsed: unknown = null;
  let parseError: string | null = null;
  try { parsed = text ? JSON.parse(text) : null; } catch (e) { parseError = (e as Error).message; }
  return (
    <Panel title="Intake evidence and proposals" description="Evidence is data, never instructions; user-reported statements are not independent inspection. Proposals become a genome draft for the usual review.">
      <Field label="Intake record (JSON)" hint="evidence: [{source_id, locator, evidence_class, observations…}], proposals: {genome key: value | '@none' | '@not_applicable: reason'}">
        <textarea className={`${inputClass} min-h-40 font-mono`} value={text} spellCheck={false} onChange={(e) => setText(e.target.value)} />
      </Field>
      <div className="flex flex-wrap gap-2 items-center">
        <button type="button" className={buttonClass} disabled={busy || parsed === null || parseError !== null} onClick={async () => {
          const saved = await run('Saving intake', () => saveIntake(brandId, parsed, sha), (r) => `Intake ${r.action} (v${r.version})`);
          if (saved) setSha(saved.sha256);
        }}>Save intake</button>
        <button type="button" className={buttonClass} disabled={busy} onClick={() => void run('Proposing draft',
          () => proposeFromIntake(brandId, scope), () => 'Draft created from proposals: review and submit it in Versions')}>Propose as genome draft</button>
        {parseError && <span className="text-red-300">Not valid JSON: {parseError}</span>}
      </div>
      <StatusLine state={state} />
    </Panel>
  );
}

export function BrandBookArea() {
  const { brandId, target } = useTarget();
  const [mode, setMode] = useState<BrandBookMode>('PREVIEW');
  const [gaps, setGaps] = useState<BrandBookGaps | null>(null);
  const [prompts, setPrompts] = useState<BrandBookCompile | null>(null);
  const [build, setBuild] = useState<BrandBookBuild | BrandBookCurrent | null>(null);
  const [promptPage, setPromptPage] = useState('p06');
  const { state, run, busy } = useAction();
  if (!target) return <Empty>Select a project in the Projects view first; the book is built and stored in that project.</Empty>;
  return (
    <div className="flex flex-col gap-4">
      <Panel title="Brand book" description="24 pages compiled from the approved genome, rendered locally, measured in Chromium and stored per page. Unchanged pages are reused; copy never comes from a template default.">
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Brand book mode">
            <select className={inputClass} value={mode} onChange={(e) => { setMode(e.target.value as BrandBookMode); setBuild(null); }}>
              {MODES.map((m) => <option key={m} value={m}>{m.replace('_', ' ').toLowerCase()}</option>)}
            </select>
          </Field>
          <button type="button" className={buttonClass} disabled={busy} onClick={async () => {
            const r = await run('Checking decisions', () => getBookGaps(brandId, target, mode === 'PROMPTS_ONLY' ? 'PRODUCTION' : mode), (x) => `${x.decisions.length} open decision(s)`);
            if (r) setGaps(r);
          }}>Open decisions</button>
          <button type="button" className={buttonClass} disabled={busy} onClick={async () => {
            const r = await run('Compiling prompts', () => compileBook(brandId, target, mode === 'PRODUCTION' ? 'PRODUCTION' : 'PROMPTS_ONLY'), (x) => `${Object.keys(x.prompts).length} page prompts compiled (nothing rendered or sent)`);
            if (r) setPrompts(r);
          }}>Compile prompts</button>
          <button type="button" className={buttonClass} disabled={busy || mode === 'PROMPTS_ONLY'} onClick={async () => {
            const r = await run('Building book', () => buildBook(brandId, target, mode), (x) => `Built: ${x.telemetry.pages_rendered} rendered, ${x.telemetry.pages_reused} reused`);
            if (r) setBuild(r);
          }}>Build</button>
          <button type="button" className={buttonClass} disabled={busy || mode === 'PROMPTS_ONLY'} onClick={async () => {
            const r = await run('Loading build', () => currentBook(brandId, target, mode), (x) => `Loaded build ${short(x.build_hash, 10)}`);
            if (r) setBuild(r);
          }}>Load current build</button>
        </div>
        <StatusLine state={state} />
        {gaps && <Decisions gaps={gaps} />}
        {build && <BuildView brandId={brandId} target={target} build={build} />}
        {prompts && (
          <div className="flex flex-col gap-2 text-xs">
            <Field label="Page prompt (self-contained; exact copy quoted)">
              <select className={inputClass} value={promptPage} onChange={(e) => setPromptPage(e.target.value)}>
                {prompts.package.pages.map((p) => <option key={p.page_id} value={p.page_id}>{p.order.toString().padStart(2, '0')} {p.title} · {p.status}</option>)}
              </select>
            </Field>
            <pre tabIndex={0} role="region" aria-label="Page prompt" className="max-h-80 overflow-auto whitespace-pre-wrap rounded-md border border-zinc-800 p-2 text-zinc-200 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-emerald-500/60">{prompts.prompts[promptPage] ?? 'Not compiled in this mode.'}</pre>
          </div>
        )}
      </Panel>
      <IntakePanel brandId={brandId} scope={{ scope: target.scope, scope_ref: target.scope_ref }} />
    </div>
  );
}
