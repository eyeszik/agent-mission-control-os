"use client";

import { useCallback, useEffect, useState } from 'react';
import { fetchFoundryContent } from '../../../lib/api/foundry';
import {
  getMediaJob,
  jobAction,
  listMediaJobs,
  listProviders,
  produceArtDirection,
  produceExperience,
  produceIdentity,
  produceVideo,
  type ArtDirectionReport,
  type ExperienceReport,
  type IdentityReport,
  type MediaJob,
  type MediaProvider,
  type VideoReport,
} from '../../../lib/api/vnexus';
import { useProjectStore } from '../../../lib/stores/projectStore';
import { useVnexusStore } from '../../../lib/stores/vnexusStore';
import { Badge, Empty, Field, KeyValue, Panel, StatusLine, buttonClass, inputClass, short, useAction } from './ui';

function useProduction() {
  const brandId = useVnexusStore((s) => s.brandId) as string;
  const scope = useVnexusStore((s) => s.scope);
  const scopeRef = useVnexusStore((s) => s.scopeRef);
  const projectId = useProjectStore((s) => s.activeProjectId);
  return { brandId, projectId, target: projectId ? { scope, scope_ref: scopeRef, project_id: projectId } : null };
}

/** Fetches stored bytes for preview. A missing preview is reported, never substituted. */
function useArtifactUrl(projectId: string | null, artifactId: string | null | undefined) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!projectId || !artifactId) return;
    let made: string | null = null;
    let cancelled = false;
    fetchFoundryContent(projectId, artifactId)
      .then(({ blob }) => { made = URL.createObjectURL(blob); if (!cancelled) setUrl(made); })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; if (made) URL.revokeObjectURL(made); };
  }, [projectId, artifactId]);
  return { url, failed };
}

function Preview({ projectId, artifactId, name, kind }: { projectId: string | null; artifactId: string | null; name: string; kind: 'image' | 'video' | 'html' | 'link' }) {
  const { url, failed } = useArtifactUrl(projectId, artifactId);
  if (failed) return <p className="text-[11px] text-red-300">Preview unavailable for {name}</p>;
  if (!url) return <p className="text-[11px] text-zinc-500">Loading {name}…</p>;
  if (kind === 'image') return <img src={url} alt={`${name} (synthetic render, not a photograph)`} className="max-h-48 w-auto rounded border border-zinc-800 bg-zinc-100" />;
  if (kind === 'video') return <video src={url} controls muted playsInline className="max-h-60 rounded border border-zinc-800" aria-label={`${name} (procedural animation)`} />;
  if (kind === 'html') return <iframe src={url} title={`${name} working page`} sandbox="allow-scripts allow-forms" className="w-full h-96 rounded border border-zinc-800 bg-zinc-50" />;
  return <a href={url} download={name} className="text-xs text-emerald-300 underline">Download {name}</a>;
}

const needsProject = <Empty>Select a project in the Projects view first; outputs are stored in that project.</Empty>;

export function ExperienceArea() {
  const { brandId, projectId, target } = useProduction();
  const [form, setForm] = useState({ target: 'LANDING_PAGE', objective: '', audience: '', primary_action: '', items: '' });
  const [report, setReport] = useState<ExperienceReport | null>(null);
  const { state, run, busy } = useAction();
  if (!target) return needsProject;
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const content = form.items.split('\n').map((l) => l.trim()).filter(Boolean).slice(0, 12).map((l) => {
      const [title, ...rest] = l.split(':'); return { title: title.trim().slice(0, 120), body: rest.join(':').trim().slice(0, 400) };
    });
    const r = await run('Compiling experience', () => produceExperience(brandId, target, { target: form.target, objective: form.objective,
      audience: form.audience, primary_action: form.primary_action, content }), (x) => `Experience ${x.status}`);
    if (r) setReport(r);
  };
  return (
    <Panel title="Experience compiler" description="Genome → intent → architecture → tokens → components → responsive rules → interactions → accessibility → working page, verified in local Chromium.">
      <form onSubmit={submit} className="grid grid-cols-1 md:grid-cols-2 gap-2">
        <Field label="Target"><select className={inputClass} value={form.target} onChange={(e) => setForm({ ...form, target: e.target.value })}>
          {['LANDING_PAGE', 'MARKETING_SITE', 'BRAND_MICROSITE', 'CAMPAIGN_EXPERIENCE', 'SAAS_DASHBOARD', 'WEB_APPLICATION'].map((t) => <option key={t}>{t}</option>)}</select></Field>
        <Field label="Objective"><input className={inputClass} required value={form.objective} onChange={(e) => setForm({ ...form, objective: e.target.value })} /></Field>
        <Field label="Audience"><input className={inputClass} value={form.audience} onChange={(e) => setForm({ ...form, audience: e.target.value })} /></Field>
        <Field label="Primary action"><input className={inputClass} value={form.primary_action} onChange={(e) => setForm({ ...form, primary_action: e.target.value })} /></Field>
        <Field label="Content items" hint="Title: body — one per line; empty means visible placeholders"><textarea className={inputClass} rows={3} value={form.items} onChange={(e) => setForm({ ...form, items: e.target.value })} /></Field>
        <button type="submit" className={`${buttonClass} self-end justify-self-start`} disabled={busy || !form.objective.trim()}>Compile and verify</button>
      </form>
      <StatusLine state={state} />
      {report && (
        <div className="flex flex-col gap-2 text-xs">
          <p><Badge value={report.status} /> verification <Badge value={report.verification.status} /> {report.verification.reason ?? ''}</p>
          <ol className="list-decimal pl-5 text-zinc-300">{report.package.stages.map((s) => <li key={s.stage}>{s.stage} <span className="font-mono text-zinc-500">{short(s.stage_hash, 10)}</span></li>)}</ol>
          {report.verification.scenarios && <p className="text-zinc-400">Scenarios passed {report.verification.scenarios.filter((s) => s.passed).length}/{report.verification.scenarios.length}</p>}
          {report.package.assumptions.length > 0 && <details><summary className="text-zinc-400 cursor-pointer">Assumptions ({report.package.assumptions.length})</summary><ul className="list-disc pl-5">{report.package.assumptions.map((a) => <li key={a}>{a}</li>)}</ul></details>}
          {report.stored.html && <Preview projectId={projectId} artifactId={report.stored.html} name="experience.html" kind="html" />}
        </div>
      )}
    </Panel>
  );
}

export function ArtDirectionArea() {
  const { brandId, target } = useProduction();
  const [form, setForm] = useState({ objective: '', medium: 'POSTER', platform: 'print.poster_a_ratio', exploration: false });
  const [report, setReport] = useState<ArtDirectionReport | null>(null);
  const { state, run, busy } = useAction();
  if (!target) return needsProject;
  const groups = ['VERIFIED_REQUIREMENT', 'INFERRED_DECISION', 'EXPERIMENTAL_SUGGESTION', 'UNSUPPORTED_ASSUMPTION'] as const;
  return (
    <Panel title="Art direction studio" description="Every statement is labelled: required, inferred, experimental, or an unsupported assumption.">
      <form className="grid grid-cols-1 md:grid-cols-4 gap-2 items-end" onSubmit={async (e) => {
        e.preventDefault();
        const r = await run('Compiling brief', () => produceArtDirection(brandId, target, form), () => 'Brief compiled');
        if (r) setReport(r);
      }}>
        <Field label="Objective"><input className={inputClass} required value={form.objective} onChange={(e) => setForm({ ...form, objective: e.target.value })} /></Field>
        <Field label="Medium"><select className={inputClass} value={form.medium} onChange={(e) => setForm({ ...form, medium: e.target.value })}>{['POSTER', 'SOCIAL', 'WEB', 'VIDEO', 'PACKAGING', 'PRESENTATION', 'IDENTITY'].map((m) => <option key={m}>{m}</option>)}</select></Field>
        <Field label="Platform preset"><select className={inputClass} value={form.platform} onChange={(e) => setForm({ ...form, platform: e.target.value })}>{['print.poster_a_ratio', 'social.square', 'social.portrait_4x5', 'social.story_9x16', 'web.open_graph', 'video.landscape_16x9', 'presentation.16x9'].map((p) => <option key={p}>{p}</option>)}</select></Field>
        <label className="text-xs text-zinc-300 flex items-center gap-2"><input type="checkbox" checked={form.exploration} onChange={(e) => setForm({ ...form, exploration: e.target.checked })} /> Include exploratory suggestions</label>
        <button type="submit" className={`${buttonClass} justify-self-start`} disabled={busy || !form.objective.trim()}>Compile brief</button>
      </form>
      <StatusLine state={state} />
      {report && groups.map((g) => {
        const claims = report.brief.claims.filter((c) => c.claim_class === g);
        return claims.length ? (
          <div key={g} className="text-xs"><p className="text-zinc-400 mb-1">{g.replace(/_/g, ' ').toLowerCase()} ({claims.length})</p>
            <ul className="list-disc pl-5">{claims.map((c, i) => <li key={`${g}${i}`}><span className="text-zinc-500">{c.section}:</span> {c.statement}{c.rationale ? <span className="text-zinc-500"> — {c.rationale}</span> : null}</li>)}</ul></div>
        ) : null;
      })}
      {report && <p className="text-[11px] text-zinc-500">Rubric: {report.brief.rubric.map((r) => `${r.criterion} (${r.method === 'HUMAN_REQUIRED' ? 'human' : 'measured'})`).join(', ')}</p>}
    </Panel>
  );
}

const IDENTITY = ['logo_mark', 'logo_lockup', 'monogram', 'icon_family', 'color_system', 'typography_specimen', 'poster', 'social_graphics', 'presentation', 'editorial_layout', 'brand_guidelines'];

export function GraphicArea() {
  const { brandId, projectId, target } = useProduction();
  const [picked, setPicked] = useState<string[]>(['logo_mark', 'icon_family', 'color_system']);
  const [headline, setHeadline] = useState('');
  const [report, setReport] = useState<IdentityReport | null>(null);
  const { state, run, busy } = useAction();
  if (!target) return needsProject;
  return (
    <Panel title="Graphic design and identity" description="Vector-first deliverables rendered locally (SVG, PNG, WebP, PDF) with deterministic checks. Taste stays a human review.">
      <fieldset className="flex flex-wrap gap-3 text-xs text-zinc-300">
        <legend className="sr-only">Deliverables</legend>
        {IDENTITY.map((d) => <label key={d} className="flex items-center gap-1"><input type="checkbox" checked={picked.includes(d)} onChange={() => setPicked((p) => (p.includes(d) ? p.filter((x) => x !== d) : [...p, d]))} />{d.replace(/_/g, ' ')}</label>)}
      </fieldset>
      <div className="flex flex-wrap items-end gap-2">
        <Field label="Headline copy (posters and social)"><input className={inputClass} value={headline} onChange={(e) => setHeadline(e.target.value)} /></Field>
        <button type="button" className={buttonClass} disabled={busy || picked.length === 0} onClick={async () => {
          const r = await run('Rendering identity', () => produceIdentity(brandId, target, picked, headline ? { headline } : {}), (x) => `Identity ${x.status}`);
          if (r) setReport(r);
        }}>Render</button>
      </div>
      <StatusLine state={state} />
      {report && (
        <div className="flex flex-col gap-3 text-xs">
          <p><Badge value={report.status} /> human review still required: {report.human_review_required.join(', ')}</p>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {report.outputs.map((o) => (
              <figure key={o.job_id} className="flex flex-col gap-1">
                {o.artifact_id && /SVG|PNG|WEBP/.test(o.capability) ? <Preview projectId={projectId} artifactId={o.artifact_id} name={o.name} kind="image" />
                  : o.artifact_id ? <Preview projectId={projectId} artifactId={o.artifact_id} name={o.name} kind="link" /> : null}
                <figcaption className="flex flex-wrap items-center gap-1"><span>{o.name}</span><Badge value={o.state} /></figcaption>
                {o.error && <span className="text-red-300">{o.error}</span>}
              </figure>
            ))}
          </div>
          <table className="w-full"><caption className="sr-only">Checks</caption><thead><tr className="text-left text-zinc-500"><th className="p-1">Output</th><th className="p-1">Check</th><th className="p-1">Result</th><th className="p-1">Detail</th></tr></thead>
            <tbody>{report.validations.map((v, i) => <tr key={`${v.output}${v.check}${i}`} className="border-t border-zinc-800"><td className="p-1">{v.output}</td><td className="p-1">{v.check}</td><td className="p-1"><Badge value={v.status} /></td><td className="p-1 text-zinc-400">{v.detail}</td></tr>)}</tbody></table>
        </div>
      )}
    </Panel>
  );
}

export function VideoArea() {
  const { brandId, projectId, target } = useProduction();
  const [form, setForm] = useState({ objective: '', headline: '', points: '', cta: '', liveAction: false });
  const [report, setReport] = useState<VideoReport | null>(null);
  const { state, run, busy } = useAction();
  if (!target) return needsProject;
  return (
    <Panel title="Video and motion" description="Procedural shots render locally (Chromium frames → FFmpeg). Shots needing footage route to hosted providers, which are disabled, and are reported blocked.">
      <form className="grid grid-cols-1 md:grid-cols-2 gap-2" onSubmit={async (e) => {
        e.preventDefault();
        const r = await run('Producing video', () => produceVideo(brandId, target, { objective: form.objective, headline: form.headline, cta: form.cta,
          points: form.points.split('\n').map((p) => p.trim()).filter(Boolean).slice(0, 4), width: 640, height: 360, fps: 12, max_duration_s: 10,
          include_shots: form.liveAction ? ['LIVE_ACTION'] : [] }), (x) => `Video ${x.status}`);
        if (r) setReport(r);
      }}>
        <Field label="Objective"><input className={inputClass} required value={form.objective} onChange={(e) => setForm({ ...form, objective: e.target.value })} /></Field>
        <Field label="Headline"><input className={inputClass} value={form.headline} onChange={(e) => setForm({ ...form, headline: e.target.value })} /></Field>
        <Field label="Points (one per line, max 4)"><textarea className={inputClass} rows={2} value={form.points} onChange={(e) => setForm({ ...form, points: e.target.value })} /></Field>
        <Field label="Call to action"><input className={inputClass} value={form.cta} onChange={(e) => setForm({ ...form, cta: e.target.value })} /></Field>
        <label className="text-xs text-zinc-300 flex items-center gap-2"><input type="checkbox" checked={form.liveAction} onChange={(e) => setForm({ ...form, liveAction: e.target.checked })} /> Include a live-action shot (will be blocked: no provider)</label>
        <button type="submit" className={`${buttonClass} justify-self-start`} disabled={busy || !form.objective.trim()}>Produce</button>
      </form>
      <StatusLine state={state} />
      {report && (
        <div className="flex flex-col gap-2 text-xs">
          <p><Badge value={report.status} /> {report.label}</p>
          <p className="text-zinc-400">Audio: {report.stages.audio.status}{report.stages.audio.reason ? ` — ${report.stages.audio.reason}` : ''}</p>
          {report.stages.render_jobs.blocked_shots.map((b) => <p key={b.shot_id} className="text-amber-300">Shot {b.shot_id} blocked: {b.error}</p>)}
          {report.stages.script.placeholders.length > 0 && <p className="text-amber-300">Placeholders in script: {report.stages.script.placeholders.join(', ')}</p>}
          {report.stages.master.deliverables.master_silent && <Preview projectId={projectId} artifactId={report.stages.master.deliverables.master_silent} name="master.mp4" kind="video" />}
          {report.stages.master.deliverables.captions && <Preview projectId={projectId} artifactId={report.stages.master.deliverables.captions} name="captions.vtt" kind="link" />}
        </div>
      )}
    </Panel>
  );
}

export function JobsArea() {
  const projectId = useProjectStore((s) => s.activeProjectId);
  const [providers, setProviders] = useState<MediaProvider[]>([]);
  const [jobs, setJobs] = useState<MediaJob[]>([]);
  const [detail, setDetail] = useState<MediaJob | null>(null);
  const { state, run, busy } = useAction();
  const refresh = useCallback(async () => {
    setProviders(await listProviders());
    if (projectId) setJobs(await listMediaJobs(projectId));
  }, [projectId]);
  useEffect(() => { void run('Loading jobs', refresh, () => 'Jobs loaded'); }, [refresh, run]);
  const act = async (id: string, a: 'authorize' | 'run' | 'retry' | 'cancel') => {
    await run(a, () => jobAction(id, a), (j) => `Job ${j.state}`);
    setDetail(await getMediaJob(id)); void refresh().catch(() => undefined);
  };
  return (
    <Panel title="Provider jobs and artifacts" description="A job is complete only when its bytes were stored, read back and passed QC. Simulated output is never claimable.">
      <StatusLine state={state} />
      <table className="text-xs w-full"><caption className="text-left text-zinc-400 mb-1">Providers (live discovery)</caption>
        <thead><tr className="text-left text-zinc-500"><th className="p-1">Provider</th><th className="p-1">Kind</th><th className="p-1">Status</th><th className="p-1">Capabilities</th><th className="p-1">Blockers</th></tr></thead>
        <tbody>{providers.map((p) => <tr key={p.provider_id} className="border-t border-zinc-800"><td className="p-1">{p.provider_id}</td><td className="p-1">{p.kind}</td><td className="p-1"><Badge value={p.status === 'AVAILABLE' ? 'PASSED' : p.status === 'DISABLED' ? 'CANCELED' : 'WARNING'} label={p.status} /></td><td className="p-1">{p.capabilities.join(', ')}</td><td className="p-1 text-zinc-400">{p.blockers.join(', ') || '—'}</td></tr>)}</tbody></table>
      {!projectId ? needsProject : jobs.length === 0 ? <Empty>No jobs in this project yet.</Empty> : (
        <ul className="text-xs flex flex-col gap-1" aria-label="Jobs">
          {jobs.map((j) => (
            <li key={j.job_id} className="flex flex-wrap items-center gap-2">
              <button type="button" className={buttonClass} onClick={() => void run('Loading job', async () => setDetail(await getMediaJob(j.job_id)))}>{j.label || short(j.job_id)}</button>
              <Badge value={j.state} />{j.simulated && <Badge value="SIMULATED_ONLY" label="simulated" />}{j.claimable_as_generated && <Badge value="PASSED" label="verified output" />}
              <span className="text-zinc-500">{j.provider_id} · attempts {j.attempts}/{j.max_attempts}</span>
            </li>
          ))}
        </ul>
      )}
      {detail && (
        <div className="text-xs flex flex-col gap-2 border-t border-zinc-800 pt-2">
          <KeyValue rows={[['Job', detail.job_id], ['State', <Badge key="s" value={detail.state} />], ['Error', detail.error ?? '—'], ['Authorized by', detail.authorized_by ?? '—'],
            ['Estimate', JSON.stringify(detail.estimate)], ['Artifact', String((detail.artifact as { artifact_id?: string }).artifact_id ?? '—')]]} />
          <ol className="list-decimal pl-5 text-zinc-400">{(detail.transitions ?? []).map((t) => <li key={t.transition_id}>{t.from_state} → {t.to_state}: {t.reason}</li>)}</ol>
          <div className="flex gap-2">
            <button type="button" className={buttonClass} disabled={busy || detail.state !== 'VALIDATED'} onClick={() => void act(detail.job_id, 'authorize')}>Check authorization</button>
            <button type="button" className={buttonClass} disabled={busy || !['AUTHORIZED', 'QUEUED'].includes(detail.state)} onClick={() => void act(detail.job_id, 'run')}>Run</button>
            <button type="button" className={buttonClass} disabled={busy || detail.state !== 'FAILED'} onClick={() => void act(detail.job_id, 'retry')}>Retry</button>
            <button type="button" className={buttonClass} disabled={busy || !['PLANNED', 'VALIDATED', 'AUTHORIZED', 'QUEUED'].includes(detail.state)} onClick={() => void act(detail.job_id, 'cancel')}>Cancel</button>
          </div>
        </div>
      )}
    </Panel>
  );
}
