"use client";

import { useEffect, useMemo, useState } from 'react';
import type { ActionPreview, CatalogEntry, MissionPreview, MissionSummary } from '@amc/shared';
import {
  getCatalog, getRecovery, launchMission, listActions, listMissions, newKey, previewAction, previewMission, proposeAction,
  reconcileAction, retryAction,
} from '../../../lib/api/agencyOs';
import { RISK_LABELS, formatMinor, labelOf, riskTone } from '../../../lib/agency/status';
import { useAgencyStore } from '../../../lib/stores/agencyStore';
import { Badge, Button, Card, Empty, ErrorNote, Field, Hash, KeyValue, RunnerOutput, Skeleton, inputClass, useLoad, useRunner } from '../ui';

const DRAFT_KEY = (projectId: string) => `amc.agency.brief.${projectId}`;

interface Draft { text: string; savedAt: number }

function readDraft(projectId: string): Draft | null {
  try {
    const raw = window.localStorage.getItem(DRAFT_KEY(projectId));
    return raw ? (JSON.parse(raw) as Draft) : null;
  } catch {
    return null;
  }
}

function MissionBuilder({ projectId }: { projectId: string }) {
  const refresh = useAgencyStore((s) => s.refresh);
  const [brief, setBrief] = useState('');
  const [loadedAt, setLoadedAt] = useState(0);
  const [conflict, setConflict] = useState<Draft | null>(null);
  const [preview, setPreview] = useState<MissionPreview | null>(null);
  const [result, setResult] = useState<MissionSummary | null>(null);
  const runner = useRunner();

  useEffect(() => {
    const d = readDraft(projectId);
    setBrief(d?.text ?? '');
    setLoadedAt(d?.savedAt ?? 0);
    setPreview(null);
    setResult(null);
  }, [projectId]);

  // Autosave with conflict detection: a draft saved elsewhere (another tab) after
  // this one loaded is never silently overwritten.
  useEffect(() => {
    const t = setTimeout(() => {
      const stored = readDraft(projectId);
      if (stored && stored.savedAt > loadedAt && stored.text !== brief) { setConflict(stored); return; }
      try {
        const savedAt = Date.now();
        window.localStorage.setItem(DRAFT_KEY(projectId), JSON.stringify({ text: brief, savedAt }));
        setLoadedAt(savedAt);
      } catch { /* storage unavailable: the draft lives in this tab only */ }
    }, 600);
    return () => clearTimeout(t);
  }, [brief, projectId, loadedAt]);

  const canLaunch = preview?.outcome === 'READY_TO_LAUNCH' && !runner.busy;
  return (
    <Card id="mission-builder" title="Mission builder" description="Describe the outcome in plain English. You see the plan, its risk and cost before anything runs.">
      {conflict && (
        <div role="alert" className="flex flex-wrap items-center gap-2 rounded-md border border-status-warning p-3 text-sm text-status-warning">
          A newer draft was saved in another tab.
          <Button onClick={() => { setBrief(conflict.text); setLoadedAt(conflict.savedAt); setConflict(null); }}>Use that draft</Button>
          <Button variant="ghost" onClick={() => { setLoadedAt(conflict.savedAt); setConflict(null); }}>Keep mine</Button>
        </div>
      )}
      <Field label="Brief" htmlFor="brief" hint="For example: “Create an SVG logo mark for the spring collection.” Drafts autosave in this browser.">
        <textarea id="brief" rows={4} maxLength={4000} value={brief} onChange={(e) => { setBrief(e.target.value); setPreview(null); }} className={inputClass} />
      </Field>
      <div className="flex flex-wrap gap-2">
        <Button disabled={runner.busy || brief.trim().length < 3} onClick={() => runner.run('Preview plan', async () => {
          const p = await previewMission(brief, projectId); setPreview(p); setResult(null); return `Plan: ${labelOf(p.outcome)}`;
        })}>Preview plan</Button>
        <Button variant="primary" disabled={!canLaunch} onClick={() => runner.run('Launch', async () => {
          const r = await launchMission(brief, projectId, newKey()); setResult(r); refresh(); return `Mission: ${r.status_label}`;
        })}>Launch local work</Button>
      </div>
      <RunnerOutput message={runner.message} error={runner.error} />
      {preview && (
        <div className="flex flex-col gap-4 rounded-md border border-line p-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge status={preview.outcome} />
            <span className="text-sm text-fg">{preview.label}</span>
          </div>
          {preview.reasons.length > 0 && <ul className="list-disc pl-5 text-sm text-fg-strong">{preview.reasons.map((r) => <li key={r}>{r}</li>)}</ul>}
          <KeyValue items={[
            ['Deliverable', String((preview.intent.deliverable as string | null) ?? 'Not recognised')],
            ['Cost', `${formatMinor(preview.cost.amount_minor, preview.cost.currency)} — ${preview.cost.basis}`],
            ['External actions', preview.external_effects.length ? preview.external_effects.map((e) => `${e.effect}: ${e.status_label} (never sent from here)`).join('; ') : 'None requested'],
          ]} />
          {preview.nodes.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-fg-strong">Work plan ({preview.nodes.length} steps)</h3>
              <ol className="mt-2 flex flex-col gap-2">
                {preview.nodes.map((n) => (
                  <li key={n.cell_id} className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-line px-3 py-2 text-sm">
                    <span className="text-fg-strong">{n.wave != null ? `Wave ${n.wave + 1} · ` : ''}{n.artifact_type ?? n.node_id}</span>
                    <Badge status={n.state} label={n.status_label} />
                  </li>
                ))}
              </ol>
            </div>
          )}
          <details>
            <summary className="cursor-pointer text-sm font-semibold text-fg-strong">Acceptance criteria</summary>
            <ul className="mt-2 list-disc pl-5 text-sm">{preview.acceptance_criteria.map((p) => <li key={String(p.predicate_id)}>{String(p.description)}</li>)}</ul>
          </details>
        </div>
      )}
      {result && (
        <div className="flex flex-col gap-2 rounded-md border border-line p-4">
          <div className="flex flex-wrap items-center gap-2"><Badge status={result.status} label={result.status_label} />
            {result.verification && <Badge status={String(result.verification.status)} label={`Verification: ${labelOf(String(result.verification.status))}`} />}</div>
          {result.verification && <p className="text-sm">Artifact <Hash value={String(result.verification.artifact_id)} /> v{String(result.verification.version)} · sha256 <Hash value={String(result.verification.content_hash)} /></p>}
          {result.approval && <p className="text-sm text-fg-strong">An approver must now review this exact version (Approvals).</p>}
          {result.non_actions.length > 0 && <p className="text-sm text-fg">Not done here: {result.non_actions.map((n) => String(n.effect)).join(', ')} — each needs its own governed action.</p>}
        </div>
      )}
    </Card>
  );
}

function exampleArgs(entry: CatalogEntry): string {
  const examples: Record<string, unknown> = {
    'sandbox.research.fetch_public': { url: 'https://example.com/', purpose: 'background research' },
    'sandbox.cms.create_draft': { site: 'acme-site', path: '/launch', title: 'Launch page', body: 'Draft copy' },
    'sandbox.cms.publish_page': { site: 'acme-site', path: '/launch', title: 'Launch page', body: 'Final copy' },
    'sandbox.email.send': { to: ['client@example.com'], subject: 'Your review link', body: 'Hello' },
    'sandbox.ads.commit_spend': { campaign: 'spring-launch', amount_minor: 2500, currency: 'USD' },
    'sandbox.storage.delete_assets': { asset_refs: ['asset-1'] },
    'sandbox.governance.grant_role': { user_ref: 'user:dana', role: 'editor' },
  };
  return JSON.stringify(examples[entry.id] ?? {}, null, 2);
}

function ActionConsole({ projectId }: { projectId: string }) {
  const inspect = useAgencyStore((s) => s.inspect);
  const refresh = useAgencyStore((s) => s.refresh);
  const catalog = useLoad(getCatalog, []);
  const actions = useLoad(() => listActions(projectId), [projectId]);
  const own = useMemo(() => (catalog.data?.entries ?? []).filter((e) => e.dispatch_owner === 'actions.gateway'), [catalog.data]);
  const [capability, setCapability] = useState('');
  const [args, setArgs] = useState('{}');
  const [preview, setPreview] = useState<ActionPreview | null>(null);
  const runner = useRunner();
  const entry = own.find((e) => e.id === capability);
  useEffect(() => { if (!capability && own[0]) { setCapability(own[0].id); setArgs(exampleArgs(own[0])); } }, [own, capability]);

  const parsed = (() => { try { return JSON.parse(args) as Record<string, unknown>; } catch { return null; } })();
  const body = { capability_id: capability, project_id: projectId, environment: 'SANDBOX' as const, args: parsed ?? {} };
  return (
    <Card id="actions" title="Governed actions" description="External effects run only through approvals, in the sandbox. Nothing here reaches a real provider.">
      {catalog.error && <ErrorNote error={catalog.error} onRetry={catalog.reload} />}
      <div className="grid gap-3 lg:grid-cols-2">
        <Field label="Action" htmlFor="action-cap">
          <select id="action-cap" value={capability} onChange={(e) => { setCapability(e.target.value); const n = own.find((o) => o.id === e.target.value); if (n) setArgs(exampleArgs(n)); setPreview(null); }} className={inputClass}>
            {own.map((e) => <option key={e.id} value={e.id}>{e.title} ({e.nominal_risk.effective})</option>)}
          </select>
        </Field>
        <Field label="Details (JSON)" htmlFor="action-args" hint={parsed ? 'Validated by the server before anything is stored.' : 'Not valid JSON yet.'}>
          <textarea id="action-args" rows={5} value={args} onChange={(e) => { setArgs(e.target.value); setPreview(null); }} aria-invalid={!parsed} className={`${inputClass} font-mono`} />
        </Field>
      </div>
      {entry && <p className="text-sm text-fg">{entry.approval_policy}. Verification: {entry.verification}.</p>}
      <div className="flex flex-wrap gap-2">
        <Button disabled={runner.busy || !parsed || !capability} onClick={() => runner.run('Preview', async () => { const p = await previewAction(body); setPreview(p); return labelOf(p.outcome); })}>
          Preview effect
        </Button>
        <Button variant="primary" disabled={runner.busy || !preview || preview.outcome === 'WOULD_BE_BLOCKED'}
          onClick={() => runner.run('Propose', async () => { const a = await proposeAction(body, newKey()); setPreview(null); actions.reload(); refresh(); inspect({ kind: 'action', id: a.action_id }); return a.status_label; })}>
          Propose
        </Button>
      </div>
      <RunnerOutput message={runner.message} error={runner.error} />
      {preview && (
        <div className="rounded-md border border-line p-4">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <Badge status={preview.outcome} />
            <Badge tone={riskTone(preview.risk.effective)} label={RISK_LABELS[preview.risk.effective] ?? preview.risk.effective} />
          </div>
          <KeyValue items={[
            ['Effect', `${preview.effect.toLowerCase()} at ${preview.target_ref}`],
            ['Reversibility', `${preview.reversibility.toLowerCase()}${preview.compensation.supported ? ` (undo: ${String(preview.compensation.operation)})` : ''}`],
            ['Cost', `${formatMinor(preview.cost.amount_minor, preview.cost.currency)} — ${preview.cost.basis}`],
            ['Approvals', preview.approvals_required.length ? preview.approvals_required.map((s) => s.replace('ACTION_', '').toLowerCase()).join(' + ') : 'None'],
            ['Blocked by', preview.blockers.length ? preview.blockers.join('; ') : 'Nothing'],
            ['Frozen', preview.frozen.length ? preview.frozen.join('; ') : 'No'],
          ]} />
        </div>
      )}
      <div>
        <h3 className="text-sm font-semibold text-fg-strong">Actions in this project</h3>
        {actions.data && actions.data.length === 0 && <Empty title="No actions yet" />}
        <ul className="mt-2 flex flex-col divide-y divide-line">
          {(actions.data ?? []).map((a) => (
            <li key={a.action_id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <button type="button" className="text-left text-sm text-fg-strong underline-offset-2 hover:underline" onClick={() => inspect({ kind: 'action', id: a.action_id })}>
                {a.capability_id} <span className="text-fg">· {a.effective_class}</span>
              </button>
              <Badge status={a.state} label={a.status_label} />
            </li>
          ))}
        </ul>
      </div>
    </Card>
  );
}

function RecoveryWorkbench() {
  const refresh = useAgencyStore((s) => s.refresh);
  const inspect = useAgencyStore((s) => s.inspect);
  const items = useLoad(getRecovery, []);
  const runner = useRunner();
  return (
    <Card id="recovery" title="Recovery workbench" description="Outcomes that are unknown are checked by reading the provider back. They are never re-sent blindly.">
      {items.error && <ErrorNote error={items.error} onRetry={items.reload} />}
      {items.loading && !items.data && <Skeleton />}
      {items.data && items.data.length === 0 && <Empty title="Nothing to recover" />}
      <ul className="flex flex-col divide-y divide-line">
        {(items.data ?? []).map((i) => (
          <li key={i.action_id} className="flex flex-wrap items-center justify-between gap-3 py-3">
            <div className="min-w-0">
              <button type="button" className="text-left text-sm font-medium text-fg-strong underline-offset-2 hover:underline" onClick={() => inspect({ kind: 'action', id: i.action_id })}>{i.capability_id}</button>
              <p className="text-xs text-fg">{i.next_step}</p>
            </div>
            <div className="flex items-center gap-2">
              <Badge status={i.state} label={i.status_label} />
              {(i.state === 'UNKNOWN' || i.state === 'NEEDS_HUMAN') && <Button disabled={runner.busy} onClick={() => runner.run('Check outcome', async () => { const a = await reconcileAction(i.action_id); items.reload(); refresh(); return a.status_label; })}>Check outcome</Button>}
              {i.state === 'FAILED' && i.retry_eligible && <Button disabled={runner.busy} onClick={() => runner.run('Retry', async () => { const a = await retryAction(i.action_id); items.reload(); refresh(); return a.status_label; })}>Retry</Button>}
            </div>
          </li>
        ))}
      </ul>
      <RunnerOutput message={runner.message} error={runner.error} />
    </Card>
  );
}

function MissionTimeline({ projectId }: { projectId: string }) {
  const missions = useLoad(() => listMissions(projectId), [projectId]);
  return (
    <Card id="timeline" title="Mission timeline">
      {missions.error && <ErrorNote error={missions.error} />}
      {missions.data && missions.data.length === 0 && <Empty title="No missions yet" />}
      <ol className="flex flex-col gap-3">
        {(missions.data ?? []).map((m) => (
          <li key={String(m.mission_id)} className="rounded-md border border-line p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-sm font-medium text-fg-strong">{String(m.deliverable ?? 'Mission')}</span>
              <Badge status={String(m.status)} label={String(m.status_label)} />
            </div>
            <p className="text-xs text-fg">{(m.events as unknown[]).length} checkpoint(s) · started {new Date(String(m.started_at)).toLocaleString()}</p>
          </li>
        ))}
      </ol>
    </Card>
  );
}

export function MissionsView() {
  const projectId = useAgencyStore((s) => s.projectId);
  if (!projectId) return <Empty title="No project selected">Pick or create a project first.</Empty>;
  return (
    <div className="grid gap-6 2xl:grid-cols-2">
      <div className="flex flex-col gap-6">
        <MissionBuilder projectId={projectId} />
        <MissionTimeline projectId={projectId} />
      </div>
      <div className="flex flex-col gap-6">
        <ActionConsole projectId={projectId} />
        <RecoveryWorkbench />
      </div>
    </div>
  );
}
