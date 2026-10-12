"use client";

import { useState } from 'react';
import type { ApprovalRequest } from '@amc/shared';
import { getAction, getMe, newKey } from '../../../lib/api/agencyOs';
import { getPendingApprovals, resolveApproval } from '../../../lib/api/approvals';
import { RISK_LABELS, formatMinor, riskTone } from '../../../lib/agency/status';
import { useAgencyStore } from '../../../lib/stores/agencyStore';
import { Badge, Button, Card, Empty, ErrorNote, Hash, KeyValue, RunnerOutput, Skeleton, useLoad, useRunner } from '../ui';

const SUBJECT_LABEL: Record<string, string> = {
  ACTION_EXECUTION: 'Run this exact action',
  ACTION_SPEND: 'Approve the money',
  ACTION_GOVERNANCE: 'Privileged governance review',
  MISSION_ARTIFACT: 'Release this exact artifact version',
};

function ActionBinding({ actionId }: { actionId: string }) {
  const action = useLoad(() => getAction(actionId), [actionId]);
  if (action.error) return <ErrorNote error={action.error} />;
  if (!action.data) return <Skeleton lines={3} />;
  const a = action.data;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-2">
        <Badge tone={riskTone(a.effective_class)} label={RISK_LABELS[a.effective_class] ?? a.effective_class} />
        <Badge status="LIVE_GATED" label="Sandbox only" />
      </div>
      <KeyValue items={[
        ['Action', a.capability_id],
        ['Exactly this target', <span key="t" className="break-all">{a.target_ref}</span>],
        ['Exactly this content', <Hash key="p" value={a.payload_hash} />],
        ['Cost', formatMinor((a.binding.cost_minor as number) ?? 0, (a.binding.currency as string | null) ?? null)],
        ['Expires', new Date(a.expires_at).toLocaleString()],
        ['Requested by', a.actor_ref],
      ]} />
      {a.binding_diff.length > 0 && (
        <p role="alert" className="text-sm text-status-warning">
          Changed since this approval was requested: {a.binding_diff.map((d) => d.field).join(', ')}. Approving now would not apply.
        </p>
      )}
    </div>
  );
}

function ApprovalItem({ approval, onDone }: { approval: ApprovalRequest; onDone: (message: string) => void }) {
  const [confirming, setConfirming] = useState<'approve' | 'reject' | null>(null);
  const runner = useRunner();
  const isAction = String(approval.subject_type ?? '').startsWith('ACTION_');
  return (
    <li className="flex flex-col gap-3 rounded-md border border-line p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-fg-strong">{SUBJECT_LABEL[approval.subject_type ?? ''] ?? approval.subject_type ?? 'Approval'}</p>
          <p className="text-sm text-fg">{approval.reason}</p>
        </div>
        <span className="text-xs text-fg">Requested {new Date(approval.created_at).toLocaleString()}</span>
      </div>
      {isAction && approval.subject_ref ? <ActionBinding actionId={approval.subject_ref} /> : (
        <KeyValue items={[['Subject', approval.subject_ref ?? approval.run_id], ['Exact content', <Hash key="h" value={approval.subject_hash ?? null} />]]} />
      )}
      {confirming ? (
        <div role="alertdialog" aria-label="Confirm decision" className="flex flex-col gap-2 rounded-md border border-line-strong p-3">
          <p className="text-sm text-fg-strong">
            {confirming === 'approve' ? 'Approve exactly what is shown above. Any later change makes this approval stale.' : 'Reject this request. The requester can submit a revised one.'}
          </p>
          <div className="flex gap-2">
            <Button variant={confirming === 'approve' ? 'primary' : 'danger'} disabled={runner.busy}
              onClick={() => runner.run(confirming === 'approve' ? 'Approve' : 'Reject', async () => { const decision = confirming;
                await resolveApproval(approval.approval_id, decision, newKey());
                setConfirming(null);
                // The item leaves the pending list on reload, so the inbox owns the confirmation.
                onDone(`Decision recorded: ${decision === 'approve' ? 'approved' : 'rejected'} ${SUBJECT_LABEL[approval.subject_type ?? '']?.toLowerCase() ?? 'request'}`);
                return 'Decision recorded';
              })}>
              Confirm {confirming}
            </Button>
            <Button variant="ghost" onClick={() => setConfirming(null)}>Back</Button>
          </div>
        </div>
      ) : (
        <div className="flex gap-2">
          <Button variant="primary" onClick={() => setConfirming('approve')}>Approve…</Button>
          <Button variant="danger" onClick={() => setConfirming('reject')}>Reject…</Button>
        </div>
      )}
      <RunnerOutput message={runner.message} error={runner.error} />
    </li>
  );
}

export function ApprovalsView() {
  const refresh = useAgencyStore((s) => s.refresh);
  const me = useLoad(getMe, []);
  const approvals = useLoad(getPendingApprovals, []);
  const [last, setLast] = useState<string | null>(null);
  return (
    <Card id="approval-inbox" title="Approval inbox"
      description={me.data ? (me.data.can.decide_approvals ? `You can decide approvals as ${me.data.role}. You can never approve your own requests.` : `Your role (${me.data.role}) can view but not decide approvals.`) : undefined}>
      {approvals.error && <ErrorNote error={approvals.error} onRetry={approvals.reload} />}
      <RunnerOutput message={last} error={null} />
      {approvals.loading && !approvals.data && <Skeleton lines={5} />}
      {approvals.data && approvals.data.length === 0 && <Empty title="No pending approvals" />}
      <ul className="flex flex-col gap-4">
        {(approvals.data ?? []).map((a) => <ApprovalItem key={a.approval_id} approval={a} onDone={(m) => { setLast(m); approvals.reload(); refresh(); }} />)}
      </ul>
    </Card>
  );
}
