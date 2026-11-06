"use client";

import { useMemo } from 'react';
import { getBudget, getCatalog, getDrift } from '../../../lib/api/agencyOs';
import { RISK_LABELS, formatMinor, labelOf, riskTone } from '../../../lib/agency/status';
import { Badge, Card, ErrorNote, Skeleton, useLoad } from '../ui';

const OWNER_LABEL: Record<string, string> = {
  'actions.gateway': 'Governed actions (sandbox)',
  execution_fabric: 'Local production skills',
  'vnexus.media_fabric': 'Media providers',
  'api.operations': 'Operations',
  'project_os.scheduler': 'Scheduler',
};

export function IntegrationsView() {
  const catalog = useLoad(getCatalog, []);
  const drift = useLoad(getDrift, []);
  const budget = useLoad(getBudget, []);
  const groups = useMemo(() => {
    const out: Record<string, NonNullable<typeof catalog.data>['entries']> = {};
    for (const e of catalog.data?.entries ?? []) (out[e.dispatch_owner] ??= []).push(e);
    return Object.entries(out).sort(([a], [b]) => a.localeCompare(b));
  }, [catalog.data]);

  return (
    <div className="flex flex-col gap-6">
      <Card id="capabilities" title="Integration center" description="What is actually connected, what is only described, and what is disabled. Live status is shown separately for every entry.">
        {catalog.error && <ErrorNote error={catalog.error} onRetry={catalog.reload} />}
        {!catalog.data && !catalog.error && <Skeleton lines={6} />}
        {catalog.data && (
          <p role="status" className="text-sm text-fg-strong">Live external execution: <Badge status="LIVE_GATED" label="Disabled" /> — {catalog.data.live.reasons.join('; ')}.</p>
        )}
        {groups.map(([owner, entries]) => (
          <section key={owner} aria-label={OWNER_LABEL[owner] ?? owner} className="flex flex-col gap-2">
            <h3 className="text-sm font-semibold text-fg-strong">{OWNER_LABEL[owner] ?? owner}</h3>
            <ul className="flex flex-col divide-y divide-line rounded-md border border-line">
              {entries.map((e) => (
                <li key={e.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
                  <div className="min-w-0">
                    <p className="text-sm text-fg-strong">{e.title}</p>
                    <p className="text-xs text-fg">{e.id}{e.status_reasons.length ? ` · ${e.status_reasons[0]}` : ''}</p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={riskTone(e.nominal_risk.effective)} label={RISK_LABELS[e.nominal_risk.effective]?.split(' · ')[0] ?? e.nominal_risk.effective} />
                    <Badge status={e.status} />
                    <Badge status={e.live_status} label={`Live: ${labelOf(e.live_status).toLowerCase()}`} />
                  </div>
                </li>
              ))}
            </ul>
          </section>
        ))}
        {catalog.data && (
          <p className="text-xs text-fg">
            Reserved identifiers {catalog.data.reserved_namespaces.map((n) => n.namespace).join(' and ')} have no source definitions in this repository and are shown as {labelOf('VOID_DETECTED').toLowerCase()}.
          </p>
        )}
      </Card>

      <div className="grid gap-6 xl:grid-cols-2">
        <Card id="drift" title="Capability drift" description="Declared support versus what a probe observes right now.">
          {drift.error && <ErrorNote error={drift.error} />}
          {drift.data && (
            <>
              <p className="text-sm">{drift.data.drifted === 0 ? 'No drift detected.' : `${drift.data.drifted} capability(ies) differ from their declaration.`}</p>
              <ul className="flex flex-col gap-1 text-sm">
                {/* ⚡ Bolt: Removed .filter().map() chain to prevent intermediate array allocation on every render */}
                {drift.data.entries.map((e) => e.drift ? <li key={e.id}><Badge status="ATTENTION" label="Drift" /> {e.id}: declared {e.declared.toLowerCase()}, observed {e.observed.toLowerCase()}</li> : null)}
              </ul>
              <p className="text-xs text-fg">Checked {new Date(drift.data.checked_at).toLocaleString()}</p>
            </>
          )}
        </Card>
        <Card id="budget" title="Budget envelope" description="Ceilings, committed and reserved amounts. Committed amounts come from sandbox read-backs, never real settlements.">
          {budget.error && <ErrorNote error={budget.error} />}
          {budget.data && (
            <>
              {Object.keys(budget.data.currencies).length === 0 && <p className="text-sm">No spend has been reserved.</p>}
              <ul className="flex flex-col gap-2 text-sm">
                {Object.entries(budget.data.currencies).map(([cur, v]) => (
                  <li key={cur}>{cur}: committed {formatMinor(v.committed_minor, cur)}, reserved {formatMinor(v.reserved_minor, cur)}, awaiting approval {formatMinor(v.pending_exposure_minor, cur)}</li>
                ))}
              </ul>
              <p className="text-xs text-fg">{budget.data.policies.length} ceiling(s) configured. With none, every spend is blocked.</p>
            </>
          )}
        </Card>
      </div>
    </div>
  );
}
