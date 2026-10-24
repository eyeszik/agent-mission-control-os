'use client';

import { useEffect, useRef, useState } from 'react';
import dynamic from 'next/dynamic';
import type { RenderCapability, RenderEngineId, RenderJob } from '@amc/shared';
import { listProjects } from '../../lib/api/projects';
import { renderCapabilities, submitRender, getRenderJob, cancelRenderJob, resumeRenderJob } from '../../lib/api/rendering';
import { useAgencyStore } from '../../lib/stores/agencyStore';
import { SSEClient } from '../../lib/api/events';
import { EventEmitter } from '../../lib/events/bus';
import { RunEventSchema } from '@amc/shared';
import { readSession } from '../../lib/auth/session';
import { usesSupabaseAuth } from '../../lib/config';
import { useRouter } from 'next/navigation';

const RenderPreview = dynamic(() => import('./RenderPreview'), { ssr: false, loading: () => <p>Loading preview…</p> });

export function CreativeRendering() {
  const router = useRouter();
  const project = useAgencyStore(s => s.projectId);
  const setProject = useAgencyStore(s => s.setProject);
  const [projects, setProjects] = useState<{ project_id: string; display_name: string }[]>([]);
  const [capabilities, setCapabilities] = useState<RenderCapability[]>([]);
  const [engine, setEngine] = useState<RenderEngineId>('rough_js');
  const [brief, setBrief] = useState('Create a seeded geometric study using the supplied bounded rectangle scene.');
  const [job, setJob] = useState<RenderJob | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [events, setEvents] = useState<string[]>([]);
  const key = useRef<string | null>(null);
  const generation = useRef(0);
  const actionController = useRef<AbortController | null>(null);
  useEffect(() => {
    if (usesSupabaseAuth() && !readSession()) { router.replace('/login'); return; }
    const controller = new AbortController(); let active = true;
    void Promise.all([listProjects(), renderCapabilities(controller.signal)]).then(([p, c]) => {
      if (!active) return;
      setProjects(p.projects); setCapabilities(c.engines);
    }).catch(() => { if (active) setError('Unable to load authorized projects or render capabilities.'); });
    return () => { active = false; controller.abort(); actionController.current?.abort(); };
  }, [router]);
  useEffect(() => { generation.current++; actionController.current?.abort(); key.current = null; setJob(null); setEvents([]); setBusy(false); }, [project]);
  useEffect(() => {
    if (!job || !project || job.workflow_status === 'completed' || job.workflow_status === 'cancelled') return;
    const expected = generation.current; const controller = new AbortController();
    const bus = new EventEmitter();
    const onEvent = (raw: unknown) => {
      const parsed = RunEventSchema.safeParse(raw);
      if (!parsed.success || expected !== generation.current) return;
      setEvents(old => [...old, parsed.data.event_type].slice(-50));
      void getRenderJob(project, job.job_id, controller.signal).then(next => {
        if (expected === generation.current) setJob(next);
      }).catch(() => { if (!controller.signal.aborted) setError('Progress disconnected; use Refresh to read the current job.'); });
    };
    bus.on('run_event_received', onEvent);
    const stream = new SSEClient(job.run_id, bus); stream.connect();
    return () => { controller.abort(); stream.disconnect(); bus.off('run_event_received', onEvent); };
  }, [job?.job_id, job?.run_id, project, job?.workflow_status === 'completed', job?.workflow_status === 'cancelled']);
  const selected = capabilities.find(c => c.engine === engine);
  async function run() {
    if (!project || busy) return;
    const expected = generation.current; const controller = new AbortController(); actionController.current = controller;
    key.current ??= crypto.randomUUID(); setBusy(true); setError('');
    try {
      const next = await submitRender(project, brief, engine, key.current, controller.signal);
      if (expected === generation.current) setJob(next);
    } catch { if (!controller.signal.aborted) setError('Dispatch failed. Retry preserves the same request key.'); }
    finally { if (expected === generation.current) setBusy(false); }
  }
  return <main className="mx-auto grid max-w-6xl gap-6 p-6 text-fg">
    <a href="/agency" className="text-accent underline">Back to Agency OS</a>
    <h1 className="text-2xl font-semibold text-fg-strong">Governed creative rendering</h1>
    <p>Render a bounded geometric study, inspect persisted output, then use the existing approval inbox for human review.</p>
    <label className="grid gap-2">Project<select className="rounded border border-line bg-surface p-2" value={project ?? ''} onChange={e => setProject(e.target.value || null)}>
      <option value="">Select an authorized project</option>{projects.map(p => <option key={p.project_id} value={p.project_id}>{p.display_name}</option>)}
    </select></label>
    <label className="grid gap-2">Rendering engine<select className="rounded border border-line bg-surface p-2" value={engine} onChange={e => { setEngine(e.target.value as RenderEngineId); key.current = null; }}>
      {capabilities.map(c => <option key={c.engine} value={c.engine}>{c.engine}{c.available ? '' : ' — unavailable'}</option>)}
    </select></label>
    {selected && !selected.available && <p role="status">Unavailable: {selected.blockers.join(', ')}</p>}
    <label className="grid gap-2">Brief<textarea className="min-h-28 rounded border border-line bg-surface p-2" value={brief} maxLength={4000} onChange={e => { setBrief(e.target.value); key.current = null; }} /></label>
    <button type="button" className="rounded border border-line p-3 disabled:opacity-50" disabled={busy || !project || !selected?.available} onClick={() => void run()}>{busy ? 'Submitting…' : 'Queue render'}</button>
    {error && <p role="alert">{error}</p>}
    {job && <section aria-label="Render evidence" className="grid gap-3 rounded border border-line p-4">
      <dl className="grid grid-cols-2 gap-2"><dt>Workflow</dt><dd>{job.workflow_status}</dd><dt>Compute</dt><dd>{job.job_status}</dd><dt>Artifact</dt><dd>{job.artifact_status}</dd><dt>Approval</dt><dd>{job.approval_status}</dd></dl>
      <p className="break-all text-xs">Specification: {job.spec_hash}</p>
      {job.blockers.length > 0 && <p role="status">{job.blockers.join(', ')}</p>}
      <button type="button" className="text-accent underline" onClick={() => { if (project) void getRenderJob(project, job.job_id).then(setJob).catch(() => setError('Refresh failed.')); }}>Refresh job</button>
      {!job.artifact_id && job.workflow_status !== 'cancelled' && <button type="button" className="text-accent underline" onClick={() => { if (project) void cancelRenderJob(project, job.job_id).then(setJob).catch(() => setError('Cancellation failed.')); }}>Cancel queued or active render</button>}
      {job.artifact_id && project && <RenderPreview project={project} artifact={job.artifact_id} />}
      {job.approval_id && <a href="/agency" className="text-accent underline" onClick={() => useAgencyStore.getState().setSection('approvals')}>Review in Approval inbox</a>}
      {(job.approval_status === 'approved' || job.approval_status === 'rejected') && job.workflow_status === 'awaiting_approval' && <button type="button" className="text-accent underline" onClick={() => { if (project) void resumeRenderJob(project, job.job_id).then(setJob).catch(() => setError('Review could not be applied; refresh the current evidence.')); }}>Apply authoritative review decision</button>}
      <p>{job.release.allowed ? 'Release eligibility confirmed by the server. No publication was performed.' : 'Release is not authorized.'}</p>
      <ol aria-label="Observed progress events" className="max-h-48 overflow-auto text-xs">{events.map((event, index) => <li key={index}>{event}</li>)}</ol>
    </section>}
    <p className="text-xs">Queued jobs require the separately running control-plane render driver. Arbitrary sketches, remote storage and unimplemented engines remain unavailable.</p>
  </main>;
}
