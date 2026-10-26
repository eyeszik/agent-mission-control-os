"use client";

import { useEffect, useState } from 'react';
import type { AfApplicability, AfTaskDetail, AfTaskState } from '@amc/shared';
import {
  decideApplicability, getTask, requestTaskApproval, setTaskRefs, settleTask, transitionTask, unblockTask, verifyTask,
} from '../../lib/api/agencyFramework';
import {
  APPLICABILITY_LABEL, MANUAL_TRANSITIONS, MOVE_LABEL, STATE_LABEL, STATE_TONE, parseRefs, shortHash,
} from '../../lib/framework/view';
import { useAgencyStore } from '../../lib/stores/agencyStore';
import { Badge, Button, ErrorNote, Field, KeyValue, RunnerOutput, Skeleton, errorMessage, inputClass, useRunner } from '../agency/ui';

const CAPABILITY_LABEL: Record<string, string> = {
  LOCAL_AVAILABLE: 'Runs locally',
  DRY_RUN_ONLY: 'Dry run only',
  PLANNING_ONLY: 'Planning only',
  HUMAN_ONLY: 'Human work',
  PROVIDER_GAP: 'No provider (gap)',
};

function RefChecks({ detail }: { detail: AfTaskDetail }) {
  if (detail.ref_checks.length === 0) return <p className="text-sm text-fg">No refs attached yet.</p>;
  return (
    <ul className="flex flex-col gap-1 text-xs" aria-label="Reference checks">
      {detail.ref_checks.map((c) => (
        <li key={c.ref} className="flex flex-wrap items-center gap-2">
          <Badge label={c.status === 'OK' ? 'OK' : c.status.replaceAll('_', ' ').toLowerCase()} tone={c.ok ? 'success' : c.attachable ? 'warning' : 'danger'} />
          <code className="break-all font-mono text-fg-strong">{c.ref}</code>
          {c.origin && <Badge label={c.origin === 'SYNTHETIC' ? 'Synthetic (not client evidence)' : c.origin.replaceAll('_', ' ').toLowerCase()} tone={c.origin === 'SYNTHETIC' ? 'warning' : 'neutral'} />}
          {c.fresh_until && <span className="text-fg">fresh until {c.fresh_until.slice(0, 10)}</span>}
        </li>
      ))}
    </ul>
  );
}

export function TaskInspector({ planId, taskId, onClose }: { planId: string; taskId: string; onClose: () => void }) {
  const refresh = useAgencyStore((s) => s.refresh);
  const [detail, setDetail] = useState<AfTaskDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const [refs, setRefs] = useState({ evidence: '', artifacts: '', decisions: '' });
  const [reason, setReason] = useState('');
  const [applicability, setApplicability] = useState<AfApplicability>('REQUIRED');
  const runner = useRunner();

  useEffect(() => {
    let alive = true;
    getTask(planId, taskId)
      .then((d) => {
        if (!alive) return;
        setDetail(d);
        setError(null);
        setRefs({ evidence: d.instance.evidence_refs.join('\n'), artifacts: d.instance.artifact_refs.join('\n'), decisions: d.instance.decision_refs.join('\n') });
        if (d.instance.applicability !== 'UNASSESSED') setApplicability(d.instance.applicability);
      })
      .catch((err) => { if (alive) setError(errorMessage(err)); });
    return () => { alive = false; };
  }, [planId, taskId, tick]);

  if (error) return <ErrorNote error={error} onRetry={() => setTick((n) => n + 1)} />;
  if (!detail) return <Skeleton lines={8} />;
  const { definition: d, instance: t, binding: b } = detail;
  const act = (label: string, fn: () => Promise<unknown>) => runner.run(label, async () => {
    await fn();
    setTick((n) => n + 1);
    refresh();
  });
  const moves = MANUAL_TRANSITIONS[t.state as AfTaskState] ?? [];
  const canEditRefs = ['READY', 'ACTIVE', 'INVALIDATED'].includes(t.state);
  return (
    <section aria-labelledby="task-inspector-title" className="flex min-w-0 flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-mono text-xs text-fg">{d.task_id} · {d.module_id} · {d.output_class}</p>
          <h3 id="task-inspector-title" className="text-base font-semibold text-fg-strong">{d.title}</h3>
        </div>
        <Button variant="ghost" onClick={onClose}>Close</Button>
      </div>
      <div className="flex flex-wrap gap-2">
        <Badge label={STATE_LABEL[t.state as AfTaskState]} tone={STATE_TONE[t.state as AfTaskState]} />
        <Badge label={APPLICABILITY_LABEL[t.applicability as AfApplicability]} tone={t.applicability === 'REQUIRED' ? 'info' : 'neutral'} />
        <Badge label={CAPABILITY_LABEL[b.capability] ?? b.capability} tone={b.capability === 'PROVIDER_GAP' ? 'danger' : 'neutral'} />
        {b.external_effect !== 'none' && <Badge label={`Live ${b.external_effect} disabled`} tone="warning" />}
        {d.definition_source === 'user_supplied' && <Badge label="From the supplied checklist" tone="neutral" />}
      </div>
      {t.status_reason && <p role="status" className="text-sm text-status-warning">{t.status_reason}</p>}
      <KeyValue items={[
        ['Acceptance', d.acceptance],
        ['Deliverable', d.module_deliverable],
        ['Owner (catalog)', d.owner_role],
        ['N3 role', `${b.n3_role} (${b.coverage === 'EXACT' ? 'exact' : b.coverage === 'NEAREST' ? 'nearest role' : 'no N3 role; nearest producer'})`],
        ['Native owner', b.native_owner],
        ['Needs', detail.required_ref_kinds.join(', ') + ' refs before review'],
        ['Version', String(t.version)],
      ]} />

      <fieldset className="flex flex-col gap-2 rounded-md border border-line p-3">
        <legend className="px-1 text-sm font-medium text-fg-strong">Applicability</legend>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-[12rem_1fr_auto] sm:items-end">
          <Field label="Decision" htmlFor="afw-applicability">
            <select id="afw-applicability" className={inputClass} value={applicability} onChange={(e) => setApplicability(e.target.value as AfApplicability)}>
              <option value="REQUIRED">Required</option>
              <option value="CONDITIONAL">Conditional</option>
              <option value="NOT_APPLICABLE">Not applicable</option>
            </select>
          </Field>
          <Field label="Reason" htmlFor="afw-applicability-reason">
            <input id="afw-applicability-reason" className={inputClass} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why this applies (or not)" />
          </Field>
          <Button disabled={runner.busy || reason.trim().length < 3}
            onClick={() => act('Record applicability', async () => {
              const out = await decideApplicability(planId, [{ task_id: d.task_id, applicability, reason: reason.trim() }]);
              if (out.skipped.length) throw new Error(out.skipped[0].detail);
            })}>
            Save
          </Button>
        </div>
        {t.applicability_reason && <p className="text-xs text-fg">Current: {APPLICABILITY_LABEL[t.applicability as AfApplicability]} — {t.applicability_reason} ({t.applicability_by})</p>}
      </fieldset>

      <div className="flex flex-col gap-2">
        <h4 className="text-sm font-semibold text-fg-strong">Work</h4>
        <div className="flex flex-wrap gap-2">
          {moves.filter((m) => m !== 'BLOCKED').map((m) => (
            <Button key={m} disabled={runner.busy} onClick={() => act(MOVE_LABEL[m] ?? m, () => transitionTask(planId, d.task_id, m, t.version))}>
              {MOVE_LABEL[m] ?? m}
            </Button>
          ))}
          {moves.includes('BLOCKED') && (
            <Button variant="danger" disabled={runner.busy || reason.trim().length < 3}
              title="Enter a reason above first"
              onClick={() => act('Block task', () => transitionTask(planId, d.task_id, 'BLOCKED', t.version, reason.trim()))}>
              Block (uses the reason above)
            </Button>
          )}
          {t.state === 'BLOCKED' && <Button disabled={runner.busy} onClick={() => act('Unblock', () => unblockTask(planId, d.task_id, t.version))}>Unblock</Button>}
          {t.state === 'IN_REVIEW' && (
            <Button variant="primary" disabled={runner.busy} onClick={() => act('Verify', () => verifyTask(planId, d.task_id, t.version))}>
              Verify (second person)
            </Button>
          )}
          {t.state === 'VERIFIED' && !t.approval_ref && (
            <Button variant="primary" disabled={runner.busy} onClick={() => act('Request approval', () => requestTaskApproval(planId, d.task_id, t.version))}>
              Request approval
            </Button>
          )}
          {t.state === 'VERIFIED' && t.approval_ref && (
            <Button disabled={runner.busy} onClick={() => act('Apply decision', () => settleTask(planId, d.task_id, t.version))}>
              Apply recorded decision
            </Button>
          )}
        </div>
        <p className="text-xs text-fg">
          Verified and approved are never set by hand: a second person verifies on the server, and an approver decides under Approvals.
        </p>
        <RunnerOutput message={runner.message} error={runner.error} />
      </div>

      <fieldset className="flex flex-col gap-2 rounded-md border border-line p-3" disabled={!canEditRefs || runner.busy}>
        <legend className="px-1 text-sm font-medium text-fg-strong">References {canEditRefs ? '' : '(locked in this state)'}</legend>
        <Field label="Evidence (knowledge:… or evidence:…, one per line)" htmlFor="afw-evidence">
          <textarea id="afw-evidence" className={`${inputClass} min-h-16 font-mono text-xs`} value={refs.evidence} onChange={(e) => setRefs({ ...refs, evidence: e.target.value })} />
        </Field>
        <Field label="Artifacts (artifact:<id>@v<n>, one per line)" htmlFor="afw-artifacts">
          <textarea id="afw-artifacts" className={`${inputClass} min-h-16 font-mono text-xs`} value={refs.artifacts} onChange={(e) => setRefs({ ...refs, artifacts: e.target.value })} />
        </Field>
        <Field label="Decisions (decision:… or genome:<approved version>, one per line)" htmlFor="afw-decisions">
          <textarea id="afw-decisions" className={`${inputClass} min-h-12 font-mono text-xs`} value={refs.decisions} onChange={(e) => setRefs({ ...refs, decisions: e.target.value })} />
        </Field>
        <div>
          <Button onClick={() => act('Save references', () => setTaskRefs(planId, d.task_id, t.version, {
            evidence_refs: parseRefs(refs.evidence), artifact_refs: parseRefs(refs.artifacts), decision_refs: parseRefs(refs.decisions),
          }))}>
            Save references
          </Button>
        </div>
      </fieldset>

      <div className="flex flex-col gap-2">
        <h4 className="text-sm font-semibold text-fg-strong">Checks against the owning stores</h4>
        <RefChecks detail={detail} />
        {t.verification && (
          <p className="text-xs text-fg">
            Last verification: <span className={t.verification.result === 'PASSED' ? 'text-status-success' : 'text-status-danger'}>{t.verification.result}</span> by {t.verification.verified_by} · proof {shortHash(t.verification.proof_hash)}
          </p>
        )}
        {detail.approval && (
          <p className="text-xs text-fg">Approval {shortHash(detail.approval.approval_id)}: {detail.approval.status}{detail.approval.decision ? ` (${detail.approval.decision} by ${detail.approval.reviewer})` : ''}{detail.approval.stale_reason ? ` — ${detail.approval.stale_reason}` : ''}</p>
        )}
      </div>

      <div className="flex flex-col gap-1 text-xs text-fg">
        <h4 className="text-sm font-semibold text-fg-strong">Dependencies</h4>
        {Object.keys(detail.upstream_modules).length === 0 ? <p>No upstream modules.</p> : (
          <ul>{Object.entries(detail.upstream_modules).map(([m, c]) => <li key={m}>{m}: {c.verified} of {c.required} required verified</li>)}</ul>
        )}
        <p>Feeds: {detail.downstream_modules.join(', ') || 'none'}</p>
      </div>

      <details className="text-xs text-fg">
        <summary className="cursor-pointer text-sm text-fg-strong">History ({detail.events.length})</summary>
        <ol className="mt-2 flex flex-col gap-1">
          {detail.events.map((e) => (
            <li key={e.event_id}><span className="font-mono">#{e.sequence}</span> {String(e.payload.kind ?? e.event_type).replace('agency_framework.', '')} · {e.actor}</li>
          ))}
        </ol>
      </details>
    </section>
  );
}
