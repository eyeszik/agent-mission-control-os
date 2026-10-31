'use client';

import { useEffect, useRef, useState } from 'react';
import type { InnovationConcept, InnovationDetail, InnovationList, InnovationRun } from '@amc/shared';
import { controlInnovationRun, createInnovationRun, getInnovationRun, listInnovationRuns, tickInnovationRun } from '../../lib/api/innovation';
import { useProjectStore } from '../../lib/stores/projectStore';

const VIEWS = ['Brief', 'Runs', 'Ideas', 'Lineage', 'Experiments', 'Evidence', 'Reviews', 'Results', 'Configuration'] as const;
type View = typeof VIEWS[number];
const input = 'rounded-md border border-zinc-700 bg-zinc-950 p-2 text-zinc-100 focus-visible:ring-2 focus-visible:ring-emerald-400';
const button = 'rounded-md border border-zinc-700 px-3 py-2 text-sm text-zinc-100 disabled:opacity-40 focus-visible:ring-2 focus-visible:ring-emerald-400';

function remember(project: string, run: string | null) {
  const url = new URL(window.location.href);
  url.searchParams.set('mode', 'innovation');
  url.searchParams.set('innovation_project', project);
  if (run) url.searchParams.set('innovation_run', run);
  else url.searchParams.delete('innovation_run');
  window.history.replaceState(null, '', url);
}

function ConceptCard({ concept, run }: { concept: InnovationConcept; run: InnovationRun }) {
  const wildcard = run.wildcards.find((entry) => entry.concept_id === concept.concept_id);
  const score = run.evaluations.find((entry) => entry.concept_id === concept.concept_id);
  return <article className="rounded-lg border border-zinc-800 p-3 space-y-2 break-words">
    <h3 className="font-medium text-zinc-100">{concept.title}</h3>
    <p className="text-xs text-zinc-400">{concept.concept_id} · {concept.generation} · {concept.lens_tags.join(', ')}</p>
    <p>{concept.mechanism}</p><p className="text-xs">Assumptions: {concept.assumptions.join('; ')}</p>
    {concept.parent_ids.length > 0 && <p className="text-xs">Parents: {concept.parent_ids.join(', ')}</p>}
    {concept.commercial_fields && <p className="text-xs">Commercial hypothesis: {concept.commercial_fields.buyer} · {concept.commercial_fields.purchased_outcome} · {concept.commercial_fields.payment_model}</p>}
    {wildcard && <p className="text-xs">Wildcard: breaks {wildcard.broken_assumption}. {wildcard.insight}</p>}
    {score && <p className="text-xs">Simulated decision aid: {score.composite}/5 · {score.rubric_version}. {score.reviewer_notes}</p>}
    <p className="text-xs text-amber-300">Speculative · SIMULATED_OFFLINE_FIXTURE</p>
  </article>;
}

function Results({ view, detail }: { view: View; detail: InnovationDetail }) {
  const run = detail.run;
  const concepts = [...run.ideas, ...run.hybrids, ...run.meta_hybrids];
  if (view === 'Ideas') return <div className="grid gap-3 md:grid-cols-2">{concepts.length ? concepts.map((c) => <ConceptCard key={c.concept_id} concept={c} run={run} />) : <p>No concepts generated. Advance the received run first.</p>}</div>;
  if (view === 'Lineage') return <ul aria-label="Concept lineage" className="space-y-2 break-words">{run.lineage.length ? run.lineage.map((e) => <li key={`${e.parent_id}:${e.child_id}`}>{e.parent_id} → {e.child_id} · {e.transformation} · v{e.source_version}<p className="text-xs">{e.rationale}</p></li>) : <li>No lineage recorded.</li>}</ul>;
  if (view === 'Experiments') return <div className="space-y-3">{run.experiments.length ? run.experiments.map((e) => <article key={e.experiment_id} className="border border-zinc-800 rounded-lg p-3 space-y-2">
    <h3 className="text-zinc-100">{e.experiment_id} · {e.concept_id}</h3><p>{e.hypothesis}</p><p>Method: {e.method}</p>
    <p>Measurements: {e.measurements.join('; ')}</p><p>Disconfirmation: {e.falsification_criteria}</p><p>Success: {e.success_rule}</p><p>Stop: {e.stop_conditions.join('; ')}</p>
    <p className="text-amber-300">{e.execution_state} · approval {e.approval_state}. Experiment execution is unavailable.</p>
  </article>) : <p>No experiment drafts recorded.</p>}</div>;
  if (view === 'Evidence') return <p>No live evidence has been retrieved. Claims remain unverified. Simulation does not establish originality, market demand, or experiment outcomes.</p>;
  if (view === 'Reviews') return <div className="space-y-3"><p>No release or experiment approvals have been requested. This slice creates drafts only.</p><button className={button} disabled title="Experiment execution and approval linkage are not implemented">Approve experiment (unavailable)</button></div>;
  if (view === 'Configuration') return <dl className="space-y-2"><dt>Prompt version</dt><dd>{run.prompt_version}</dd><dt>Mode</dt><dd>{run.mode}</dd><dt>Provider</dt><dd>{run.simulation ? 'Deterministic offline simulation' : 'Unavailable live provider'}</dd><dt>Usage and cost</dt><dd>Not measured</dd><dt>External execution</dt><dd>Disabled</dd></dl>;
  return <div className="space-y-3 break-words"><p>{run.ideas.length} raw ideas · {run.wildcards.length} wildcards · {run.hybrids.length} hybrids · {run.meta_hybrids.length} meta-hybrids</p><p>{run.shortlist.length} shortlisted · {run.experiments.length} experiment drafts · {run.lineage.length} lineage edges</p><h3 className="text-zinc-100">Shortlist</h3><ol className="list-decimal pl-5">{run.shortlist.map((id) => <li key={id}>{concepts.find((c) => c.concept_id === id)?.title ?? id}</li>)}</ol><p>Artifact {detail.artifact_id} · version {detail.version}</p><p className="font-mono text-xs">Content hash: {detail.content_hash}</p><ul>{run.limitations.map((entry) => <li key={entry}>{entry}</li>)}</ul></div>;
}

export function InnovationFoundryPanel() {
  const project = useProjectStore((state) => state.activeProjectId);
  const setProject = useProjectStore((state) => state.setActiveProject);
  const [view, setView] = useState<View>('Brief');
  const [objective, setObjective] = useState('');
  const [mode, setMode] = useState<'AUTO' | 'GENERAL' | 'VENTURE' | 'HYBRID'>('AUTO');
  const [constraints, setConstraints] = useState('');
  const [runs, setRuns] = useState<InnovationList | null>(null);
  const [detail, setDetail] = useState<InnovationDetail | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const scope = useRef(project);
  scope.current = project;
  const actionController = useRef<AbortController | null>(null);
  const detailController = useRef<AbortController | null>(null);
  const submissionKey = useRef<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const savedProject = params.get('innovation_project');
    if (savedProject) setProject(savedProject);
  }, [setProject]);

  useEffect(() => {
    actionController.current?.abort();
    setDetail(null); setError(null); setRuns(null); setBusy(false); submissionKey.current = null;
    const params = new URLSearchParams(window.location.search);
    const savedRun = params.get('innovation_project') === project ? params.get('innovation_run') : null;
    setSelected(savedRun);
    return () => actionController.current?.abort();
  }, [project]);

  useEffect(() => {
    if (!project) return;
    const controller = new AbortController();
    listInnovationRuns(project, controller.signal).then((value) => { if (!controller.signal.aborted) setRuns(value); }).catch((err: unknown) => {
      if (!controller.signal.aborted) setError(err instanceof Error ? err.message : 'Could not load runs');
    });
    return () => controller.abort();
  }, [project, refresh]);

  useEffect(() => {
    if (!project) return;
    remember(project, selected);
    if (!selected) return;
    const controller = new AbortController();
    detailController.current = controller;
    setDetail(null);
    getInnovationRun(project, selected, controller.signal).then((value) => {
      if (!controller.signal.aborted) setDetail(value);
    }).catch((err: unknown) => {
      if (!controller.signal.aborted) setError(err instanceof Error ? err.message : 'Could not load run');
    });
    return () => controller.abort();
  }, [project, selected]);

  async function perform(kind: 'start' | 'tick' | 'pause' | 'resume' | 'cancel') {
    if (!project || busy) return;
    const target = project;
    detailController.current?.abort();
    const controller = new AbortController();
    actionController.current?.abort(); actionController.current = controller;
    setBusy(true); setError(null);
    try {
      let result: InnovationDetail;
      if (kind === 'start') {
        submissionKey.current ??= crypto.randomUUID();
        result = await createInnovationRun(target, { objective, mode, provider: 'simulated', constraints: constraints.split('\n').map((v) => v.trim()).filter(Boolean) }, submissionKey.current, controller.signal);
        submissionKey.current = null;
      } else {
        if (!detail) return;
        result = kind === 'tick' ? await tickInnovationRun(target, detail.run.run_id, detail.version, controller.signal) : await controlInnovationRun(target, detail.run.run_id, detail.version, kind, controller.signal);
      }
      if (scope.current !== target || controller.signal.aborted) return;
      setSelected(result.run.run_id); setDetail(result); setRefresh((n) => n + 1); setView('Results');
      remember(target, result.run.run_id);
    } catch (err) {
      if (scope.current === target && !controller.signal.aborted) setError(err instanceof Error ? err.message : 'Operation failed');
    } finally {
      if (scope.current === target && !controller.signal.aborted) setBusy(false);
    }
  }

  const received = detail?.run.status === 'RECEIVED';
  const paused = detail?.run.status === 'PAUSED';
  return <section aria-labelledby="innovation-title" className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4 space-y-4 text-sm min-w-0">
    <h2 id="innovation-title" className="text-lg text-zinc-100">UNBOUND Innovation Foundry</h2>
    <p className="text-amber-300">SIMULATED development preview. Experiment execution, live research, and external actions are disabled.</p>
    {!project ? <p>Select a project in Project Workspace to begin.</p> : <>
      <nav aria-label="Innovation Foundry views" className="flex flex-wrap gap-2">{VIEWS.map((entry) => <button key={entry} className={button} aria-pressed={view === entry} onClick={() => setView(entry)}>{entry}</button>)}</nav>
      {busy && <p role="status">Saving bounded operation…</p>}{error && <p role="alert" className="text-rose-300">{error}</p>}
      {detail && <div className="space-y-2"><p role="status">{detail.run.status} · {detail.run.phase} · version {detail.version}</p><div className="flex flex-wrap gap-2">
        <button className={button} disabled={busy || !received} onClick={() => void perform('tick')}>Advance simulation</button>
        <button className={button} disabled={busy || !received} onClick={() => void perform('pause')}>Pause</button>
        <button className={button} disabled={busy || !paused} onClick={() => void perform('resume')}>Resume</button>
        <button className={button} disabled={busy || !(received || paused)} onClick={() => void perform('cancel')}>Cancel</button>
      </div></div>}
      {view === 'Brief' ? <form className="grid gap-3" onSubmit={(event) => { event.preventDefault(); void perform('start'); }}>
        <label className="grid gap-1">Innovation objective<textarea className={input} minLength={10} maxLength={4000} required value={objective} onChange={(event) => { setObjective(event.target.value); submissionKey.current = null; }} /></label>
        <label className="grid gap-1">Innovation mode<select className={input} value={mode} onChange={(event) => { setMode(event.target.value as typeof mode); submissionKey.current = null; }}>{['AUTO', 'GENERAL', 'VENTURE', 'HYBRID'].map((value) => <option key={value}>{value}</option>)}</select></label>
        <label className="grid gap-1">Constraints (one per line, up to 20)<textarea className={input} value={constraints} onChange={(event) => { setConstraints(event.target.value); submissionKey.current = null; }} /></label>
        <button className={button} disabled={busy || objective.trim().length < 10}>Start simulated run</button>
        <p>Start persists the brief. Advance simulation performs an explicit bounded tick; no background scheduler is claimed.</p>
      </form> : view === 'Runs' ? <div className="space-y-2"><h3>Persisted run history</h3><button className={button} disabled={busy} onClick={() => setRefresh((n) => n + 1)}>Refresh history</button>{runs ? <><p>{runs.total} persisted runs · showing first 20</p><ul className="space-y-2">{runs.runs.map((run) => <li key={run.run_id}><button className={`${button} text-left break-words w-full`} disabled={busy} onClick={() => { setSelected(run.run_id); setView('Results'); }}>{run.objective} · {run.status} · {run.simulation ? 'SIMULATED' : 'PROVIDER_GAP'}</button></li>)}</ul>{runs.total === 0 && <p>No runs yet.</p>}</> : <p role="status">Loading run history…</p>}</div> : detail ? <Results view={view} detail={detail} /> : <p>Select a persisted run from Runs, or start a new brief.</p>}
    </>}
  </section>;
}
