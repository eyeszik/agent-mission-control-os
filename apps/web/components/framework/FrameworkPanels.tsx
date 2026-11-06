"use client";

import type { AfGate, AfPlanView } from '@amc/shared';
import { getAudit, getMetrics, requestGateApproval, revalidatePlan } from '../../lib/api/agencyFramework';
import { GATE_LABEL, GATE_TITLE, GATE_TONE, ratioLabel, shortHash } from '../../lib/framework/view';
import { useAgencyStore } from '../../lib/stores/agencyStore';
import { Badge, Button, Card, Empty, ErrorNote, RunnerOutput, Skeleton, useLoad, useRunner } from '../agency/ui';

function GateCard({ planId, gate, counts }: { planId: string; gate: AfGate; counts: AfPlanView['progress']['stage_gates'][string] }) {
  const refresh = useAgencyStore((s) => s.refresh);
  const runner = useRunner();
  const ready = gate.status === 'NEEDS_HUMAN' || gate.status === 'STALE';
  return (
    <li className="flex min-w-0 flex-col gap-2 rounded-lg border border-line bg-surface p-4" aria-label={`${GATE_TITLE[gate.stage_gate]} gate: ${GATE_LABEL[gate.status]}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium text-fg-strong">{GATE_TITLE[gate.stage_gate]}</span>
        <Badge label={GATE_LABEL[gate.status]} tone={GATE_TONE[gate.status]} />
      </div>
      <p className="text-xs text-fg">{gate.criteria}</p>
      <p className="text-xs text-fg-strong">{ratioLabel(counts)}</p>
      {gate.unassessed.length > 0 && <p className="text-xs text-fg">{gate.unassessed.length} task(s) not assessed for applicability</p>}
      {gate.unmet.length > 0 && (
        <details className="text-xs text-fg">
          <summary className="cursor-pointer text-fg-strong">{gate.unmet.length} unmet requirement(s)</summary>
          <ul className="mt-1">{gate.unmet.slice(0, 20).map((u) => <li key={u.task_id}><span className="font-mono">{u.task_id}</span> · {u.state.toLowerCase().replace('_', ' ')}</li>)}</ul>
        </details>
      )}
      {gate.synthetic_only && <Badge label="Synthetic evidence only: never client proof" tone="warning" wrap />}
      {gate.reasons.map((r) => <p key={r} className="text-xs text-status-danger">{r}</p>)}
      {gate.approval_id && <p className="text-xs text-fg">Approval {shortHash(gate.approval_id)} · decide it under Approvals</p>}
      {ready && (
        <Button variant="primary" disabled={runner.busy}
          onClick={() => runner.run('Request gate approval', async () => {
            const out = await requestGateApproval(planId, gate.stage_gate);
            refresh();
            return `Approval requested (${shortHash(out.approval.approval_id)}); another person decides it.`;
          })}>
          Request gate approval
        </Button>
      )}
      <RunnerOutput message={runner.message} error={runner.error} />
    </li>
  );
}

export function GatesPanel({ view }: { view: AfPlanView }) {
  const refresh = useAgencyStore((s) => s.refresh);
  const runner = useRunner();
  return (
    <Card title="Stage gates" id="afw-gates"
      description="Gates pass in order, only through an approval bound to the exact evidence each required task was verified on."
      actions={(
        <Button disabled={runner.busy} onClick={() => runner.run('Re-check evidence', async () => {
          const out = await revalidatePlan(view.plan.plan_id);
          refresh();
          return out.invalidated.length ? `${out.invalidated.length} task(s) invalidated: ${out.invalidated.map((i) => i.task_id).join(', ')}` : 'All verified work still matches its evidence.';
        })}>
          Re-check evidence
        </Button>
      )}>
      <RunnerOutput message={runner.message} error={runner.error} />
      <ul className="grid grid-cols-1 gap-3 md:grid-cols-2 2xl:grid-cols-5" aria-label="Stage gates">
        {view.gates.map((g) => <GateCard key={g.stage_gate} planId={view.plan.plan_id} gate={g} counts={view.progress.stage_gates[g.stage_gate]} />)}
      </ul>
    </Card>
  );
}

export function MetricsPanel({ planId }: { planId: string }) {
  const metrics = useLoad(() => getMetrics(planId), [planId]);
  return (
    <Card title="KPIs" id="afw-kpis" description="Computed only from recorded measurements. Unknown inputs and zero denominators stay Not measured; synthetic inputs are labelled.">
      {metrics.error ? <ErrorNote error={metrics.error} onRetry={metrics.reload} /> : !metrics.data ? <Skeleton /> : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[36rem] text-left text-sm">
            <caption className="sr-only">KPI values with their sources</caption>
            <thead className="text-xs text-fg"><tr><th scope="col" className="py-1 pr-3 font-medium">KPI</th><th scope="col" className="py-1 pr-3 font-medium">Value</th><th scope="col" className="py-1 pr-3 font-medium">Origin</th><th scope="col" className="py-1 font-medium">Note</th></tr></thead>
            <tbody>
              {metrics.data.metrics.map((m) => (
                <tr key={m.metric_id} className="border-t border-line">
                  <th scope="row" className="py-1.5 pr-3 font-normal text-fg-strong">{m.label}<span className="block text-xs text-fg">{m.category} · {m.unit}</span></th>
                  <td className="py-1.5 pr-3 font-mono text-fg-strong">{m.value === 'NOT_MEASURED' ? 'Not measured' : m.unit === 'ratio' ? `${(m.value * 100).toFixed(1)}%` : m.value.toLocaleString()}</td>
                  <td className="py-1.5 pr-3">{m.origin ? <Badge label={m.origin === 'SYNTHETIC' ? 'Synthetic' : m.origin.toLowerCase()} tone={m.origin === 'SYNTHETIC' ? 'warning' : 'neutral'} /> : '—'}</td>
                  <td className="py-1.5 text-xs text-fg">{m.reason ?? (m.window_consistent === false ? 'inputs cover different windows' : '')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

export function AuditPanel({ planId }: { planId: string }) {
  const audit = useLoad(() => getAudit(planId), [planId]);
  return (
    <Card title="Audit trail" id="afw-audit" description="From the project event stream; every task write appends one event in the same transaction.">
      {audit.error ? <ErrorNote error={audit.error} onRetry={audit.reload} /> : !audit.data ? <Skeleton /> : audit.data.length === 0 ? <Empty title="No events yet" /> : (
        <ol className="flex flex-col gap-1 text-xs text-fg" aria-label="Plan events">
          {audit.data.map((e) => (
            <li key={e.event_id} className="flex flex-wrap gap-2">
              <span className="font-mono">#{e.sequence}</span>
              <span className="text-fg-strong">{String(e.payload.kind ?? e.event_type).replace('agency_framework.', '').replaceAll('_', ' ')}</span>
              {typeof e.payload.task_id === 'string' && <span className="font-mono">{e.payload.task_id}</span>}
              <span>{e.actor}</span>
              <time dateTime={e.created_at}>{e.created_at.slice(0, 19).replace('T', ' ')}</time>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}
