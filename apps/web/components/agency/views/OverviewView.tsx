"use client";

import { getAttention, getFreezes, getLifecycle, getLive, getUncertainty, listActions } from '../../../lib/api/agencyOs';
import { RISK_LABELS, labelOf, riskTone } from '../../../lib/agency/status';
import { useAgencyStore } from '../../../lib/stores/agencyStore';
import { Badge, Button, Card, Empty, ErrorNote, Skeleton, useLoad } from '../ui';

const CATEGORY_LABEL: Record<string, string> = {
  RECOVERY: 'Check an unknown outcome',
  APPROVAL: 'Decision needed',
  EXPIRING: 'Expiring soon',
  BLOCKED: 'Blocked',
};

export function OverviewView() {
  const projectId = useAgencyStore((s) => s.projectId);
  const inspect = useAgencyStore((s) => s.inspect);
  const setSection = useAgencyStore((s) => s.setSection);
  const attention = useLoad(getAttention, []);
  const live = useLoad(getLive, []);
  const freezes = useLoad(getFreezes, []);
  const debt = useLoad(getUncertainty, []);
  const lifecycle = useLoad(() => (projectId ? getLifecycle(projectId) : Promise.resolve(null)), [projectId]);
  const recent = useLoad(() => listActions(projectId ?? undefined), [projectId]);

  return (
    <div className="flex flex-col gap-6">
      <div className="grid gap-6 xl:grid-cols-3">
        <div className="xl:col-span-2">
          <Card id="attention" title="Needs your attention" description="Decisions only a person can make, in a fixed order: unknown outcomes, approvals, then expiring work.">
            {attention.error && <ErrorNote error={attention.error} onRetry={attention.reload} />}
            {attention.loading && !attention.data && <Skeleton lines={4} />}
            {attention.data && attention.data.length === 0 && <Empty title="Nothing is waiting on you">New approvals and unknown outcomes appear here.</Empty>}
            {attention.data && attention.data.length > 0 && (
              <ul className="flex flex-col divide-y divide-line">
                {attention.data.map((item) => (
                  <li key={`${item.category}-${item.ref}`} className="flex flex-wrap items-center justify-between gap-3 py-3">
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-fg-strong">{CATEGORY_LABEL[item.category]}</p>
                      <p className="truncate text-sm text-fg">{item.title ?? item.ref}</p>
                      {item.expires_at && <p className="text-xs text-fg">Expires {new Date(item.expires_at).toLocaleString()}</p>}
                    </div>
                    <div className="flex items-center gap-2">
                      {item.risk && <Badge tone={riskTone(item.risk)} label={RISK_LABELS[item.risk] ?? item.risk} />}
                      {item.category === 'APPROVAL' ? (
                        <Button onClick={() => setSection('approvals')}>Review</Button>
                      ) : (
                        <Button onClick={() => inspect({ kind: 'action', id: item.ref })}>Open</Button>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
        <Card id="safety" title="Safety state">
          <ul className="flex flex-col gap-3 text-sm">
            <li className="flex items-center justify-between gap-2">
              <span>External actions (publish, send, spend)</span>
              <Badge status="LIVE_GATED" label={live.data?.status === 'DISABLED' ? 'Disabled' : 'Checking…'} />
            </li>
            <li className="flex items-center justify-between gap-2">
              <span>Incident freeze</span>
              {freezes.data ? (
                <Badge status={freezes.data.system_frozen || freezes.data.freezes.length ? 'BLOCKED' : 'READY'}
                  label={freezes.data.system_frozen ? 'System frozen' : freezes.data.freezes.length ? `${freezes.data.freezes.length} active` : 'None'} />
              ) : <span className="text-fg">…</span>}
            </li>
            <li className="flex items-center justify-between gap-2">
              <span>Unconfirmed effects (risky dispatch held while any exist)</span>
              {debt.data ? (
                <Badge status={debt.data.assessment.allow_high_risk_dispatch ? 'READY' : 'ATTENTION'}
                  label={debt.data.assessment.allow_high_risk_dispatch ? 'None' : `${debt.data.assessment.unconfirmed_total} unconfirmed`} />
              ) : <span className="text-fg">…</span>}
            </li>
          </ul>
          {live.data && <p className="text-xs text-fg">{live.data.reasons[0]}.</p>}
        </Card>
      </div>

      <Card id="lifecycle" title="Project lifecycle" description="Each stage is complete only when its evidence exists.">
        {!projectId && <Empty title="No project selected">Create or pick a project to see its lifecycle.</Empty>}
        {lifecycle.error && <ErrorNote error={lifecycle.error} />}
        {projectId && !lifecycle.data && !lifecycle.error && <Skeleton />}
        {lifecycle.data && (
          <ol className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            {lifecycle.data.stages.map((s) => (
              <li key={s.stage} className="flex min-w-0 flex-col items-start gap-1 rounded-md border border-line p-3">
                <span className="text-xs text-fg">{s.depends_on.length ? `after ${s.depends_on.map((d) => d.toLowerCase()).join(', ')}` : 'start'}</span>
                <span className="text-sm font-medium text-fg-strong">{labelOf(s.stage)}</span>
                <Badge status={s.status} wrap />
              </li>
            ))}
          </ol>
        )}
      </Card>

      <Card id="recent" title="Recent actions">
        {recent.data && recent.data.length === 0 && <Empty title="No actions yet">Governed actions you propose appear here.</Empty>}
        {recent.data && recent.data.length > 0 && (
          <ul className="flex flex-col divide-y divide-line">
            {recent.data.slice(0, 8).map((a) => (
              <li key={a.action_id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <button type="button" onClick={() => inspect({ kind: 'action', id: a.action_id })} className="text-left text-sm text-fg-strong underline-offset-2 hover:underline">
                  {a.capability_id}
                </button>
                <Badge status={a.state} label={a.status_label} />
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
