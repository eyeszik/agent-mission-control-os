"use client";

import { useState } from 'react';
import type { AutonomyLevel } from '@amc/shared';
import { createFreeze, getAutonomy, getFreezes, getMe, liftFreeze, setAutonomy, simulateBudget } from '../../../lib/api/agencyOs';
import { useAgencyStore } from '../../../lib/stores/agencyStore';
import { Badge, Button, Card, ErrorNote, Field, KeyValue, RunnerOutput, Skeleton, inputClass, useLoad, useRunner } from '../ui';

const LEVELS: { id: AutonomyLevel; title: string; body: string }[] = [
  { id: 'OBSERVE', title: 'Observe', body: 'Only reading and research runs without a person.' },
  { id: 'DRAFT', title: 'Draft', body: 'Local work (R1) runs; anything external is blocked.' },
  { id: 'PREPARE', title: 'Prepare', body: 'Unpublished external drafts (R2) run too.' },
  { id: 'REQUEST_APPROVAL', title: 'Request approval', body: 'As Prepare, and anything riskier asks for approval instead of being blocked.' },
];

function AutonomyDial({ projectId, canRaise }: { projectId: string; canRaise: boolean }) {
  const current = useLoad(() => getAutonomy(projectId), [projectId]);
  const runner = useRunner();
  const level = current.data?.autonomy;
  return (
    <Card id="autonomy" title="Autonomy dial" description="An upper bound on what may run without a person. It never grants authority: publishing, sending and spending always need approval.">
      {current.error && <ErrorNote error={current.error} />}
      {!current.data && !current.error && <Skeleton lines={4} />}
      {current.data && (
        <fieldset className="flex flex-col gap-2">
          <legend className="sr-only">Autonomy level</legend>
          {LEVELS.map((l, i) => {
            const raising = level ? i > LEVELS.findIndex((x) => x.id === level) : false;
            return (
              <label key={l.id} className={`flex items-start gap-3 rounded-md border p-3 ${level === l.id ? 'border-accent' : 'border-line'}`}>
                <input type="radio" name="autonomy" value={l.id} checked={level === l.id} disabled={runner.busy || (raising && !canRaise)}
                  onChange={() => runner.run('Change autonomy', async () => { const r = await setAutonomy(projectId, l.id); current.reload(); return `Autonomy is now ${r.autonomy.toLowerCase()} (up to ${r.auto_ceiling} without a person)`; })} />
                <span><span className="block text-sm font-medium text-fg-strong">{l.title}</span><span className="block text-sm text-fg">{l.body}</span>
                  {raising && !canRaise && <span className="block text-xs text-fg">Raising needs an owner or admin.</span>}</span>
              </label>
            );
          })}
        </fieldset>
      )}
      <RunnerOutput message={runner.message} error={runner.error} />
    </Card>
  );
}

function Freezes({ projectId }: { projectId: string | null }) {
  const me = useLoad(getMe, []);
  const freezes = useLoad(getFreezes, []);
  const [reason, setReason] = useState('');
  const runner = useRunner();
  return (
    <Card id="freeze" title="Incident freeze" description="Stops every new dispatch at once. Checking outcomes of work already in flight continues. Lifting needs a second owner or admin.">
      {freezes.error && <ErrorNote error={freezes.error} />}
      {freezes.data?.system_frozen && <p role="alert" className="text-sm text-status-danger">The whole system is frozen by configuration.</p>}
      <ul className="flex flex-col gap-2">
        {(freezes.data?.freezes ?? []).map((f) => (
          <li key={String(f.freeze_id)} className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-status-danger p-3 text-sm">
            <span><Badge status="BLOCKED" label={`${String(f.scope_kind).toLowerCase()} frozen`} /> {String(f.reason)} — by {String(f.frozen_by)}</span>
            <Button disabled={runner.busy || !me.data?.can.lift_freeze || me.data?.user_id === f.frozen_by}
              onClick={() => runner.run('Lift freeze', async () => { await liftFreeze(String(f.freeze_id), 'resolved'); freezes.reload(); return 'Freeze lifted'; })}>Lift</Button>
          </li>
        ))}
      </ul>
      <Field label="Reason" htmlFor="freeze-reason"><input id="freeze-reason" value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} className={inputClass} /></Field>
      <div className="flex flex-wrap gap-2">
        <Button variant="danger" disabled={runner.busy || reason.trim().length < 3 || !me.data?.can.freeze_dispatch}
          onClick={() => runner.run('Freeze workspace', async () => { await createFreeze({ scope_kind: 'TENANT', reason }); setReason(''); freezes.reload(); return 'All new dispatch is frozen'; })}>Freeze workspace</Button>
        {projectId && <Button variant="danger" disabled={runner.busy || reason.trim().length < 3 || !me.data?.can.freeze_dispatch}
          onClick={() => runner.run('Freeze project', async () => { await createFreeze({ scope_kind: 'PROJECT', scope_ref: projectId, reason }); setReason(''); freezes.reload(); return 'New dispatch is frozen for this project'; })}>Freeze this project</Button>}
      </div>
      <RunnerOutput message={runner.message} error={runner.error} />
    </Card>
  );
}

function PolicySimulator({ projectId }: { projectId: string | null }) {
  const [ceiling, setCeiling] = useState('10000');
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const runner = useRunner();
  return (
    <Card id="policy-sim" title="Policy simulator" description="See what a spend ceiling would block before anyone changes it. Nothing is saved.">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Per-project ceiling (USD, minor units)" htmlFor="sim-ceiling"><input id="sim-ceiling" inputMode="numeric" value={ceiling} onChange={(e) => setCeiling(e.target.value.replace(/\D/g, ''))} className={inputClass} /></Field>
      </div>
      <Button disabled={runner.busy || !projectId || !ceiling} onClick={() => runner.run('Simulate', async () => {
        const r = await simulateBudget({ scope_kind: 'PROJECT', scope_ref: projectId ?? '', currency: 'USD', ceiling_minor: Number(ceiling) });
        setResult(r); return String(r.label);
      })}>Simulate</Button>
      {result && <KeyValue items={[
        ['Current usage', String(result.current_usage_minor)],
        ['Headroom', String(result.headroom_minor)],
        ['Would block', (result.would_block as unknown[]).length ? `${(result.would_block as unknown[]).length} pending action(s)` : 'Nothing pending'],
      ]} />}
      <RunnerOutput message={runner.message} error={runner.error} />
    </Card>
  );
}

export function SettingsView() {
  const projectId = useAgencyStore((s) => s.projectId);
  const me = useLoad(getMe, []);
  return (
    <div className="grid gap-6 xl:grid-cols-2">
      {projectId && <AutonomyDial projectId={projectId} canRaise={Boolean(me.data?.can.raise_autonomy)} />}
      <Freezes projectId={projectId} />
      <PolicySimulator projectId={projectId} />
      <Card id="authority" title="Your authority" description="What your role may do here. The server checks every request regardless of what this page shows.">
        {me.data && (
          <ul className="grid gap-2 text-sm sm:grid-cols-2">
            {Object.entries(me.data.can).map(([k, v]) => <li key={k} className="flex items-center justify-between gap-2"><span>{k.replace(/_/g, ' ')}</span><Badge status={v ? 'READY' : 'NOT_STARTED'} label={v ? 'Yes' : 'No'} /></li>)}
          </ul>
        )}
        {me.data && <p className="text-xs text-fg">Never: {me.data.never.join('; ')}.</p>}
      </Card>
    </div>
  );
}
