"use client";

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { CouncilEngine, IdeaDetail, Mission } from '@amc/shared';
import { createIdea, dispatchMission, getEngines, getIdea, listIdeas, missionAction } from '../../lib/api/missions';
import { STATUS_LABEL, STATUS_TONE, deriveCouncil } from '../../lib/missions/council';
import { useMissionLive } from '../../lib/missions/useMissionLive';
import { useAgencyStore } from '../../lib/stores/agencyStore';
import {
  Badge, Button, Card, Empty, ErrorNote, Field, Hash, KeyValue, RunnerOutput, Skeleton, errorMessage, inputClass, useLoad, useRunner,
} from '../agency/ui';
import { ApprovalModal } from './ApprovalModal';
import { BlueprintPanel } from './BlueprintPanel';
import { CheckpointHistory } from './CheckpointHistory';
import { CouncilStatusCards } from './CouncilStatusCards';
import { EngineSelector } from './EngineSelector';
import { MissionTimeline } from './MissionTimeline';

function IdeaComposer({ projectId, onCreated }: { projectId: string; onCreated: (ideaId: string) => void }) {
  const runner = useRunner();
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const valid = title.trim().length >= 3 && description.trim().length >= 10;
  return (
    <form className="flex flex-col gap-3" onSubmit={(e) => {
      e.preventDefault();
      if (!valid) return;
      void runner.run('Create idea', async () => {
        const idea = await createIdea({ project_id: projectId, title: title.trim(), description: description.trim() });
        setTitle('');
        setDescription('');
        onCreated(idea.idea_id);
        return `Idea created: ${idea.title}`;
      });
    }}>
      <Field label="Idea title" htmlFor="idea-title">
        <input id="idea-title" className={inputClass} value={title} onChange={(e) => setTitle(e.target.value)} maxLength={160} required />
      </Field>
      <Field label="What should it do?" htmlFor="idea-desc" hint="Never paste credentials: an idea containing a secret is refused.">
        <textarea id="idea-desc" className={`${inputClass} min-h-24`} value={description} onChange={(e) => setDescription(e.target.value)} maxLength={4000} required />
      </Field>
      <div><Button type="submit" variant="primary" disabled={!valid || runner.busy}>Create idea</Button></div>
      <RunnerOutput message={runner.message} error={runner.error} />
    </form>
  );
}

function MissionDetail({ missionId, onChanged }: { missionId: string; onChanged: () => void }) {
  const { mission, events, error, loading, stream, reload } = useMissionLive(missionId);
  const [gateOpen, setGateOpen] = useState(false);
  const runner = useRunner();
  const view = useMemo(() => deriveCouncil(events), [events]);
  // The engine may finish on a worker thread after an action returns: keep the idea's mission list in step with the live status.
  const status = mission?.status;
  useEffect(() => { if (status) onChanged(); }, [status, onChanged]);
  let checkpointRevision = 0;
  for (const e of events) if (e.event_type === 'CHECKPOINT_SAVED' || e.event_type === 'TOOL_INVOKED') checkpointRevision++;

  const act = useCallback((label: string, action: 'cancel' | 'retry' | 'recover' | 'resume') =>
    runner.run(label, async () => {
      const next = await missionAction(missionId, action);
      await reload();
      onChanged();
      return `${label}: ${STATUS_LABEL[next.status]}`;
    }), [missionId, reload, onChanged, runner]);

  if (error && !mission) return <ErrorNote error={error} onRetry={() => void reload()} />;
  if (!mission) return <Skeleton lines={6} />;
  const awaiting = mission.status === 'needs_approval';
  const decided = mission.approval?.status === 'resolved';
  return (
    <div className="flex min-w-0 flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <KeyValue items={[
          ['Mission', <Hash key="m" value={mission.mission_id} />],
          ['Status', <span key="s" className="flex flex-wrap items-center gap-2">
            <Badge label={STATUS_LABEL[mission.status]} tone={STATUS_TONE[mission.status]} />
            <span className="text-xs text-fg">phase {mission.phase} · attempt {mission.attempts}</span></span>],
          ['Engine', `${mission.engine} · ${mission.model_mode === 'MOCK_DETERMINISTIC' ? 'deterministic mock model' : 'provider model'}`],
          ['Thread', <Hash key="t" value={mission.thread_id} />],
          ...(mission.last_error ? [['Last error', <span key="e" className="text-status-danger">{mission.last_error}</span>] as [string, React.ReactNode]] : []),
        ]} />
        <div className="flex flex-wrap gap-2">
          {awaiting && (
            <Button variant="primary" onClick={() => setGateOpen(true)}>{decided ? 'Resume from gate' : 'Review gate'}</Button>
          )}
          {(mission.status === 'queued' || mission.status === 'running' || mission.status === 'resuming' || awaiting) && (
            <Button variant="danger" disabled={runner.busy} onClick={() => void act('Cancel mission', 'cancel')}>Cancel</Button>
          )}
          {mission.status === 'failed' && (
            <Button disabled={runner.busy} onClick={() => void act('Retry from checkpoint', 'retry')}>Retry from checkpoint</Button>
          )}
          {(mission.status === 'running' || mission.status === 'resuming') && (
            <Button variant="ghost" disabled={runner.busy} onClick={() => void act('Recover stalled mission', 'recover')}>Recover if stalled</Button>
          )}
          <Button variant="ghost" disabled={loading} onClick={() => void reload()}>Refresh</Button>
        </div>
      </div>
      <RunnerOutput message={runner.message} error={runner.error} />
      {error && <ErrorNote error={error} onRetry={() => void reload()} />}

      <CouncilStatusCards view={view} mission={mission} />

      <div className="grid min-w-0 grid-cols-1 gap-6 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <MissionTimeline events={events} stream={stream} />
        <div className="flex min-w-0 flex-col gap-6">
          {mission.strategy && (
            <section aria-labelledby="strategy-title" className="flex flex-col gap-2">
              <h3 id="strategy-title" className="text-sm font-semibold text-fg-strong">George&apos;s strategy</h3>
              <p className="text-sm text-fg">{mission.strategy.summary}</p>
              <ol className="list-decimal pl-5 text-xs text-fg">
                {mission.strategy.tasks.map((t) => <li key={t.id}><span className="text-fg-strong">{t.title}</span> · {t.seat}{t.depends_on.length ? ` · after ${t.depends_on.join(', ')}` : ''}</li>)}
              </ol>
            </section>
          )}
          {mission.scaffold && (
            <section aria-labelledby="scaffold-title" className="flex flex-col gap-2">
              <h3 id="scaffold-title" className="text-sm font-semibold text-fg-strong">Arty&apos;s scaffold</h3>
              <p className="text-sm text-fg">{mission.scaffold.summary}</p>
              <ul className="text-xs text-fg">
                {mission.scaffold.files.map((f) => <li key={f.path}><code className="font-mono text-fg-strong">{f.path}</code> · {f.bytes} bytes</li>)}
              </ul>
            </section>
          )}
          <CheckpointHistory missionId={mission.mission_id} revision={checkpointRevision} />
        </div>
      </div>

      <ApprovalModal mission={mission} open={gateOpen} onClose={() => setGateOpen(false)}
        onSettled={() => { void reload(); onChanged(); }} />
    </div>
  );
}

/** Idea → council mission (LangGraph, CrewAI or AutoGen) → Sentinel gate → prototype → blueprint, all on the real API. */
export function MissionDashboard() {
  const projectId = useAgencyStore((s) => s.projectId);
  const engines = useLoad(getEngines, []);
  const ideas = useLoad(() => (projectId ? listIdeas(projectId) : Promise.resolve(null)), [projectId]);
  const [ideaId, setIdeaId] = useState<string | null>(null);
  const [idea, setIdea] = useState<IdeaDetail | null>(null);
  const [ideaError, setIdeaError] = useState<string | null>(null);
  const [ideaTick, setIdeaTick] = useState(0);
  const [missionId, setMissionId] = useState<string | null>(null);
  const [engine, setEngine] = useState<CouncilEngine>('langgraph');
  const [materialize, setMaterialize] = useState(true);
  const dispatcher = useRunner();

  useEffect(() => { setIdeaId(null); setMissionId(null); }, [projectId]);
  useEffect(() => {
    const items = ideas.data?.items ?? [];
    if (!ideaId && items.length > 0) setIdeaId(items[0].idea_id);
  }, [ideas.data, ideaId]);
  useEffect(() => {
    if (!ideaId) { setIdea(null); return; }
    let alive = true;
    getIdea(ideaId)
      .then((d) => { if (alive) { setIdea(d); setIdeaError(null); } })
      .catch((err) => { if (alive) setIdeaError(errorMessage(err)); });
    return () => { alive = false; };
  }, [ideaId, ideaTick]);
  useEffect(() => {
    if (!idea || missionId || idea.missions.length === 0) return;
    // Open the mission that needs a reviewer, else the newest one.
    const pick = idea.missions.find((m) => m.status === 'needs_approval') ?? idea.missions[idea.missions.length - 1];
    setMissionId(pick.mission_id);
  }, [idea, missionId]);

  const refreshIdea = useCallback(() => setIdeaTick((n) => n + 1), []);
  useEffect(() => {
    const available = engines.data?.engines.find((e) => e.engine === engine)?.available;
    const first = engines.data?.engines.find((e) => e.available)?.engine;
    if (available === false && first) setEngine(first);
  }, [engines.data, engine]);

  if (!projectId) {
    return <Empty title="Choose a project">Mission council work happens inside a project. Create one under Projects, then select it above.</Empty>;
  }
  const ideaItems = ideas.data?.items ?? [];
  return (
    <div className="flex min-w-0 flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h2 className="text-lg font-semibold text-fg-strong">Mission Council</h2>
        <p className="text-sm text-fg">
          George plans, Fable/Cipher audits, a person approves at the Sentinel gate, then Arty builds the scaffold. Every step is
          checkpointed; nothing writes, runs a shell or calls out without that approval.
        </p>
      </div>

      <div className="grid min-w-0 grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        <div className="flex min-w-0 flex-col gap-6">
          <Card title="New idea" id="new-idea">
            <IdeaComposer projectId={projectId} onCreated={(id) => { setIdeaId(id); setMissionId(null); ideas.reload(); }} />
          </Card>
          <Card title="Ideas" id="ideas">
            {ideas.loading && !ideas.data ? <Skeleton /> : ideas.error ? <ErrorNote error={ideas.error} onRetry={ideas.reload} /> : ideaItems.length === 0 ? (
              <Empty title="No ideas yet">Describe one above to convene the council.</Empty>
            ) : (
              <ul className="flex flex-col gap-1" aria-label="Ideas">
                {ideaItems.map((i) => (
                  <li key={i.idea_id}>
                    <button type="button" aria-pressed={ideaId === i.idea_id}
                      onClick={() => { setIdeaId(i.idea_id); setMissionId(null); }}
                      className={`flex w-full items-center justify-between gap-2 rounded-md px-3 py-2 text-left text-sm focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-focus ${ideaId === i.idea_id ? 'bg-surface-raised text-fg-strong' : 'text-fg hover:bg-surface-raised'}`}>
                      <span className="min-w-0 truncate">{i.title}</span>
                      <Badge label={i.status === 'PROMOTED' ? 'Promoted' : 'Open'} tone={i.status === 'PROMOTED' ? 'success' : 'neutral'} />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>

        <div className="flex min-w-0 flex-col gap-6">
          {ideaError && <ErrorNote error={ideaError} onRetry={refreshIdea} />}
          {idea ? (
            <>
              <Card title={idea.title} id="idea-detail" description={idea.description}>
                {engines.error ? <ErrorNote error={engines.error} onRetry={engines.reload} /> : !engines.data ? <Skeleton lines={2} /> : (
                  <form className="flex flex-col gap-3" onSubmit={(e) => {
                    e.preventDefault();
                    void dispatcher.run('Dispatch mission', async () => {
                      const m: Mission = await dispatchMission({ idea_id: idea.idea_id, engine, materialize_scaffold: materialize });
                      setMissionId(m.mission_id);
                      refreshIdea();
                      return `Mission dispatched on ${m.engine}: ${STATUS_LABEL[m.status]}`;
                    });
                  }}>
                    <EngineSelector engines={engines.data} value={engine} onChange={setEngine} disabled={dispatcher.busy || idea.status !== 'OPEN'} />
                    <label className="flex items-center gap-2 text-sm text-fg-strong">
                      <input type="checkbox" checked={materialize} onChange={(e) => setMaterialize(e.target.checked)} className="accent-accent" />
                      After approval, write the scaffold to the mission workspace (an approved WRITE)
                    </label>
                    <div className="flex flex-wrap items-center gap-2">
                      <Button type="submit" variant="primary" disabled={dispatcher.busy || idea.status !== 'OPEN'}>Dispatch to council</Button>
                      {idea.status !== 'OPEN' && <span className="text-xs text-fg">This idea was promoted; it no longer takes new missions.</span>}
                    </div>
                    <RunnerOutput message={dispatcher.message} error={dispatcher.error} />
                  </form>
                )}
                {idea.missions.length > 0 && (
                  <div className="flex flex-col gap-2">
                    <h3 className="text-sm font-semibold text-fg-strong">Missions for this idea</h3>
                    <ul className="flex flex-wrap gap-2" aria-label="Missions for this idea">
                      {idea.missions.map((m) => (
                        <li key={m.mission_id}>
                          <button type="button" aria-pressed={missionId === m.mission_id} onClick={() => setMissionId(m.mission_id)}
                            className={`flex items-center gap-2 rounded-md border px-2 py-1 text-xs focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-focus ${missionId === m.mission_id ? 'border-accent bg-surface-raised text-fg-strong' : 'border-line-strong text-fg hover:bg-surface-raised'}`}>
                            <span>{m.engine}</span>
                            <Badge label={STATUS_LABEL[m.status]} tone={STATUS_TONE[m.status]} />
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </Card>
              {missionId && (
                <Card title="Council session" id="council-session">
                  <MissionDetail key={missionId} missionId={missionId} onChanged={refreshIdea} />
                </Card>
              )}
              <Card title="Blueprint" id="blueprint" description="The strongest strategy and scaffold across completed missions, with every security finding kept.">
                <BlueprintPanel idea={idea} onChanged={() => { refreshIdea(); ideas.reload(); }} />
              </Card>
            </>
          ) : ideaId ? <Skeleton lines={6} /> : (
            <Empty title="No idea selected">Create or pick an idea to dispatch it to the council.</Empty>
          )}
        </div>
      </div>
    </div>
  );
}
