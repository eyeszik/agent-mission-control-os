'use client';

import { useEffect, useRef, useState } from 'react';
import type { InnovationDetail, InnovationGenerationStage, InnovationLocalExperiment } from '@amc/shared';
import { getGenerationStage, getLocalExperiment, prepareGenerationStage, runLocalExperiment, tickGenerationStage } from '../../lib/api/innovation';
import { resolveApproval } from '../../lib/api/approvals';
import { ServiceError } from '../../lib/api/client';

const button = 'rounded-md border border-zinc-700 px-3 py-2 text-sm disabled:opacity-40 focus-visible:ring-2 focus-visible:ring-emerald-400';
type Action = 'prepare' | 'tick' | 'local' | 'approve' | 'reject';

function Computation({ result }: { result: InnovationLocalExperiment }) {
  if (result.status === 'BLOCKED') return <div role="status">Local computation blocked. {result.limitations.join(' ')}</div>;
  const m = result.measurements;
  return <div className="space-y-2 break-words" aria-label="Actual local computation receipt">
    <p className="text-emerald-300">ACTUAL LOCAL COMPUTATION · {result.replayed ? 'Persisted receipt reloaded' : 'Measured and persisted'}</p>
    <p>Inputs: {result.input_provenance}; {m.case_count} disclosed cases. This tests lexical normalization, not concept quality or market demand.</p>
    <p>Redundant retained items: baseline {m.baseline_redundant_items}; candidate {m.candidate_redundant_items}. Unit: {m.unit}.</p>
    <p>Preregistered decision: {result.learning.decision}. Rule: {result.learning.rule}</p>
    <p>{result.learning.interpretation} {result.learning.next_action}</p>
    <p>Source: {result.source_ref}</p><p>Plan: {result.plan_ref}</p><p>Result: {result.result_ref}</p>
    <p className="text-xs font-mono">Input hash: {result.input_hash}</p><p>Executor: {result.executor_version}</p>
    <p>Canonical permits: {result.proof.summary.dispatch_count}; execution receipts: {result.proof.summary.execution_count}; matched observations: {result.proof.summary.matched_observation_count}.</p>
    <ul>{result.learning.limitations.map((entry) => <li key={entry}>{entry}</li>)}</ul><p>Release remains unauthorized.</p>
  </div>;
}

function Generation({ stage }: { stage: InnovationGenerationStage }) {
  return <div className="space-y-2 break-words" aria-label="Provider generation intent">
    <p>Generation stage: {stage.status}. Plan version {stage.version}.</p>
    <p>Target: {stage.spec.provider_profile.primary.provider} / {stage.spec.provider_profile.primary.model}</p>
    <p>Limits: {stage.spec.max_calls} call; {stage.spec.max_output_tokens} output tokens; {stage.spec.timeout_seconds}s timeout; ${stage.spec.max_cost_usd} paid API ceiling. Remote pricing enforcement is unavailable.</p>
    <p>Approval: {stage.approval?.status ?? 'NOT_REQUESTED'}{stage.approval?.decision ? ` / ${stage.approval.decision}` : ''}. Separate approval authority is enforced by the server.</p>
    {stage.reasons.length > 0 && <ul aria-label="Generation blockers">{stage.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>}
    {stage.output && <><p>{stage.output.state}: {stage.output.ideas.length} model-generated hypotheses, {stage.output.coverage.length}/12 lenses. This is not a researched or completed innovation run.</p>
      <p>Invocation receipt: {stage.output.receipt?.outcome ?? 'NONE'}. Reported usage: {stage.output.receipt?.usage ? JSON.stringify(stage.output.receipt.usage) : 'UNKNOWN'}. Monetary cost: UNKNOWN.</p>
      {stage.output.ideas.map((idea) => <div key={idea.concept_id} className="border-t border-zinc-800 pt-2"><h4>{idea.title}</h4><p>{idea.mechanism}</p><p>{idea.evidence_class} · {idea.lens_ids.join(', ')}</p></div>)}</>}
    <p className="text-xs font-mono">Plan hash: {stage.content_hash}</p>
  </div>;
}

export function InnovationCapabilitiesPanel({ project, detail }: { project: string; detail: InnovationDetail }) {
  const [generation, setGeneration] = useState<InnovationGenerationStage | null>(null);
  const [local, setLocal] = useState<InnovationLocalExperiment | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const active = useRef(true);
  const controller = useRef<AbortController | null>(null);
  const pending = useRef(false);
  const readController = useRef<AbortController | null>(null);
  const run = detail.run;
  const eligibleLocal = run.simulation && run.status === 'COMPLETED';

  useEffect(() => {
    active.current = true;
    const reads = new AbortController(); readController.current = reads;
    const load = run.simulation ? (eligibleLocal ? getLocalExperiment(project, run.run_id, detail.version, reads.signal).then((result) => { if (active.current && !reads.signal.aborted) setLocal(result); }) : Promise.resolve()) : getGenerationStage(project, run.run_id, reads.signal).then((result) => { if (active.current && !reads.signal.aborted) setGeneration(result); });
    load.catch((err: unknown) => {
      if (!reads.signal.aborted && !(err instanceof ServiceError && err.status === 404)) setError(err instanceof Error ? err.message : 'Could not load capability records');
    });
    return () => { active.current = false; reads.abort(); controller.current?.abort(); };
  }, [project, run.run_id, run.simulation, detail.version, eligibleLocal, refresh]);

  async function perform(action: Action) {
    if (pending.current) return;
    pending.current = true; readController.current?.abort(); setBusy(true); setError(null);
    const abort = new AbortController(); controller.current?.abort(); controller.current = abort;
    try {
      if (action === 'local') {
        const result = await runLocalExperiment(project, run.run_id, detail.version, abort.signal);
        if (active.current && !abort.signal.aborted) setLocal(result);
      } else if (action === 'approve' || action === 'reject') {
        if (generation?.approval) await resolveApproval(generation.approval.approval_id, action, crypto.randomUUID());
        if (active.current && !abort.signal.aborted) setRefresh((n) => n + 1);
      } else {
        const result = action === 'prepare' ? await prepareGenerationStage(project, run.run_id, detail.version, abort.signal) : generation ? await tickGenerationStage(project, run.run_id, generation.version, abort.signal) : null;
        if (active.current && !abort.signal.aborted) setGeneration(result);
      }
    } catch (err: unknown) {
      if (active.current && !abort.signal.aborted) setError(err instanceof Error ? err.message : 'Capability operation failed');
    } finally {
      pending.current = false;
      if (active.current && !abort.signal.aborted) setBusy(false);
    }
  }

  const measured = local?.status === 'COMPLETED';
  const providerValidated = generation?.output?.state === 'GENERATED' && generation.output.receipt?.outcome === 'OUTPUT_VALIDATED';
  const approved = generation?.approval?.status === 'resolved' && generation.approval.decision === 'approve';
  return <aside className="rounded-lg border border-zinc-700 p-3 space-y-3 min-w-0 break-words" aria-label="Innovation capability records">
    <h3 className="text-zinc-100">Independent capability records</h3>
    <p>C0 fixture workflow: {run.simulation && run.status === 'COMPLETED' ? 'VERIFIED for this run' : 'NOT_VERIFIED for this run'}. C1 live generation: {providerValidated ? 'structural output and invocation receipt recorded; relevance NOT_VERIFIED' : 'NOT_VERIFIED'}.</p>
    <p>C2 research: BLOCKED. C3 independent evaluation: NOT_VERIFIED. C4 experiment drafts: {run.experiments.length > 0 ? 'present; no execution approval implied' : 'absent'}.</p>
    <p>C5 local observation: {measured ? 'VERIFIED lexical computation only' : 'NOT_VERIFIED'}. C6 learning: {measured ? 'preregistered lexical rule recorded' : 'NOT_VERIFIED'}. C7 hosted mobile HTTPS: NOT_VERIFIED. C8 release approval: NOT_REQUESTED.</p>
    <button type="button" className={button} disabled={busy} onClick={() => { setError(null); setRefresh((n) => n + 1); }}>Refresh capability records</button>
    {busy && <p role="status">Processing bounded capability request…</p>}{error && <p role="alert" className="text-rose-300">{error}</p>}
    {run.simulation ? <><button type="button" className={button} disabled={busy || !eligibleLocal} onClick={() => void perform('local')}>Run local lexical experiment</button><p>This policy-gated, non-networked computation uses disclosed synthetic inputs. It does not execute generated code or the five proposed concept experiments.</p>{local && <Computation result={local} />}</> : <div className="space-y-3">
      {!generation && <button type="button" className={button} disabled={busy} onClick={() => void perform('prepare')}>Prepare live generation intent</button>}
      {generation && <><Generation stage={generation} />
        <div className="flex flex-wrap gap-2"><button type="button" className={button} disabled={busy || !approved || generation.reasons.length > 0 || Boolean(generation.output)} onClick={() => void perform('tick')}>Advance approved generation</button>
          <button type="button" className={button} disabled={busy || generation.approval?.status !== 'pending'} onClick={() => void perform('approve')}>Human approve generation intent</button>
          <button type="button" className={button} disabled={busy || generation.approval?.status !== 'pending'} onClick={() => void perform('reject')}>Human reject generation intent</button></div>
        <p>Approve only the displayed exact provider, source version, plan hash and resource bounds. Authorization never transfers to external experiments or release.</p></>}
    </div>}
  </aside>;
}
