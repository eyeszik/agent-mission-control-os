"use client";

import { X } from 'lucide-react';
import { useEffect, useRef } from 'react';
import { cancelAction, dispatchAction, getAction, getEvidence, reconcileAction, retryAction } from '../../lib/api/agencyOs';
import { RISK_LABELS, formatMinor, labelOf, riskTone } from '../../lib/agency/status';
import { useAgencyStore } from '../../lib/stores/agencyStore';
import { Badge, Button, ErrorNote, Hash, KeyValue, RunnerOutput, Skeleton, useLoad, useRunner } from './ui';

const PRE_DISPATCH = ['PROPOSED', 'VALIDATED', 'PREPARED', 'AWAITING_APPROVAL', 'AUTHORIZED', 'RESERVED'];

function ActionInspector({ id }: { id: string }) {
  const refresh = useAgencyStore((s) => s.refresh);
  const action = useLoad(() => getAction(id), [id]);
  const evidence = useLoad(() => getEvidence(id), [id]);
  const runner = useRunner();
  if (action.error) return <ErrorNote error={action.error} onRetry={action.reload} />;
  if (!action.data) return <Skeleton lines={6} />;
  const a = action.data;
  const cost = a.binding.cost_minor as number | undefined;
  const currency = (a.binding.currency as string | null | undefined) ?? null;
  const done = (msg: string) => { action.reload(); evidence.reload(); refresh(); return msg; };
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-2">
        <Badge status={a.state} label={a.status_label} />
        <Badge tone={riskTone(a.effective_class)} label={RISK_LABELS[a.effective_class] ?? a.effective_class} />
        <Badge status="LIVE_GATED" label={`${a.environment === 'SANDBOX' ? 'Sandbox' : a.environment} · live disabled`} />
      </div>
      <KeyValue items={[
        ['Action', a.capability_id],
        ['Target', <span key="t" className="break-all">{a.target_ref}</span>],
        ['Requested by', a.actor_ref],
        ['Cost', formatMinor(cost ?? 0, currency)],
        ['Expires', new Date(a.expires_at).toLocaleString()],
        ['Attempts', `${a.attempts} of 3`],
        ['Binding', <Hash key="b" value={a.binding_hash} />],
      ]} />
      {a.reasons.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-fg-strong">Why it stopped</h3>
          <ul className="mt-1 list-disc pl-5 text-sm text-fg-strong">{a.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
        </div>
      )}
      {a.binding_diff.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-status-warning">Changed since approval</h3>
          <ul className="mt-1 flex flex-col gap-1 text-sm">
            {a.binding_diff.map((d) => <li key={d.field}><span className="font-medium text-fg-strong">{d.field}</span> no longer matches what was approved</li>)}
          </ul>
        </div>
      )}
      {a.approvals && (
        <div>
          <h3 className="text-sm font-semibold text-fg-strong">Approvals</h3>
          <ul className="mt-1 flex flex-col gap-1 text-sm">
            {a.approvals.approvals.map((ap) => (
              <li key={ap.approval_id} className="flex flex-wrap items-center gap-2">
                <span className="text-fg-strong">{ap.subject.replace('ACTION_', '').toLowerCase()}</span>
                <Badge status={ap.decision ?? ap.status ?? 'pending'} label={ap.decision ? `${ap.decision}d by ${ap.reviewer}` : labelOf(ap.status ?? 'pending')} />
              </li>
            ))}
          </ul>
        </div>
      )}
      <details>
        <summary className="cursor-pointer text-sm font-semibold text-fg-strong">Why this risk class</summary>
        <ul className="mt-2 flex flex-col gap-1 text-sm">
          {a.risk.explanations.map((e, i) => <li key={`${e.rule}-${i}`}><code className="text-xs text-fg">{e.rule}</code> {e.reason} <span className="text-fg">→ {e.effect}</span></li>)}
        </ul>
        <p className="mt-2 text-xs text-fg">Controls applied: {a.risk.controls.join(', ')}</p>
      </details>
      <div className="flex flex-wrap gap-2">
        {['AUTHORIZED', 'RESERVED', 'AWAITING_APPROVAL'].includes(a.state) && (
          <Button variant="primary" disabled={runner.busy} onClick={() => runner.run('Run', async () => done(labelOf((await dispatchAction(id)).state)))}>Run in sandbox</Button>
        )}
        {a.state === 'UNKNOWN' || a.state === 'NEEDS_HUMAN' ? (
          <Button disabled={runner.busy} onClick={() => runner.run('Check outcome', async () => done(labelOf((await reconcileAction(id)).state)))}>Check outcome</Button>
        ) : null}
        {a.state === 'FAILED' && a.retry_eligible && (
          <Button disabled={runner.busy} onClick={() => runner.run('Retry', async () => done(labelOf((await retryAction(id)).state)))}>Retry</Button>
        )}
        {PRE_DISPATCH.includes(a.state) && (
          <Button variant="danger" disabled={runner.busy} onClick={() => runner.run('Cancel', async () => done(labelOf((await cancelAction(id, 'cancelled from the inspector')).state)))}>Cancel</Button>
        )}
      </div>
      <RunnerOutput message={runner.message} error={runner.error} />
      <div>
        <h3 className="text-sm font-semibold text-fg-strong">Evidence</h3>
        {evidence.error && <ErrorNote error={evidence.error} />}
        {!evidence.data && !evidence.error && <Skeleton />}
        {evidence.data && (
          <>
            <p className="mt-1 text-sm">
              History chain {evidence.data.chain.intact ? <Badge status="VERIFIED" label="intact" /> : <Badge status="FAILED" label="broken" />}
              <span className="ml-2 text-fg">{evidence.data.chain.entries} entries · {evidence.data.observation_receipts.length} read-back(s)</span>
            </p>
            <ol className="mt-2 flex flex-col gap-2 border-l border-line-strong pl-4">
              {evidence.data.transitions.map((t) => (
                <li key={String(t.entry_hash)} className="text-sm">
                  <span className="font-medium text-fg-strong">{labelOf(String(t.to_state))}</span>
                  <span className="text-fg"> — {String(t.reason)}</span>
                  <div className="text-xs text-fg">{new Date(String(t.created_at)).toLocaleString()} · {String(t.actor)}</div>
                </li>
              ))}
            </ol>
          </>
        )}
      </div>
    </div>
  );
}

export function Inspector() {
  const inspected = useAgencyStore((s) => s.inspected);
  const inspect = useAgencyStore((s) => s.inspect);
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => { closeRef.current?.focus(); }, [inspected]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') inspect(null); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [inspect]);
  if (!inspected) return null;
  return (
    <aside aria-label="Inspector" className="fixed inset-0 z-40 overflow-y-auto border-l border-line bg-surface p-4 sm:p-6 xl:static xl:inset-auto xl:w-[26rem] xl:shrink-0">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-base font-semibold text-fg-strong">{inspected.kind === 'action' ? 'Action details' : 'Approval'}</h2>
        <Button ref={closeRef} variant="ghost" aria-label="Close inspector" onClick={() => inspect(null)}><X aria-hidden="true" size={18} /></Button>
      </div>
      {inspected.kind === 'action' && <ActionInspector id={inspected.id} />}
    </aside>
  );
}
