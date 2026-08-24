"use client";

import { useEffect, useState } from 'react';
import type { AgencyRun, TrustSnapshot } from '@amc/shared';
import { getAgencyRun } from '../../lib/api/agency';
import { getProjectTrust } from '../../lib/api/runtime';
import { useRunStore } from '../../lib/stores/runStore';

type RowTone = 'default' | 'success' | 'warn' | 'danger';

function Section({
  title,
  rows,
}: {
  title: string;
  rows: Array<{ label: string; value: string; tone?: RowTone }>;
}) {
  const toneClass = (tone?: string) => {
    switch (tone) {
      case 'success':
        return 'text-emerald-400';
      case 'warn':
        return 'text-amber-400';
      case 'danger':
        return 'text-red-400';
      default:
        return 'text-zinc-300';
    }
  };

  return (
    <div className="flex flex-col gap-2">
      <span className="text-[10px] font-mono uppercase tracking-wider text-zinc-500">{title}</span>
      {rows.length === 0 ? (
        <div className="rounded-lg border border-zinc-800/50 bg-zinc-950/40 px-3 py-2 text-[11px] font-mono text-zinc-600">
          none
        </div>
      ) : (
        rows.map((row, index) => (
          <div key={`${title}-${index}`} className="rounded-lg border border-zinc-800/50 bg-zinc-950/40 px-3 py-2 flex items-center justify-between gap-3">
            <span className="text-[11px] font-mono text-zinc-500">{row.label}</span>
            <span className={`text-[11px] font-mono text-right ${toneClass(row.tone)}`}>{row.value}</span>
          </div>
        ))
      )}
    </div>
  );
}

export function ConsequentialLifecyclePanel() {
  const activeRunId = useRunStore((state) => state.activeRunId);
  const [run, setRun] = useState<AgencyRun | null>(null);
  const [trust, setTrust] = useState<TrustSnapshot | null>(null);

  useEffect(() => {
    if (!activeRunId) {
      setRun(null);
      setTrust(null);
      return;
    }
    getAgencyRun(activeRunId).then(setRun).catch(() => {
      setRun(null);
      setTrust(null);
    });
  }, [activeRunId]);

  useEffect(() => {
    if (!run?.project_id) {
      setTrust(null);
      return;
    }
    getProjectTrust(run.project_id).then(setTrust).catch(() => setTrust(null));
  }, [run?.project_id]);

  if (!activeRunId || !trust) {
    return (
      <div className="flex-1 bg-zinc-900/40 border border-zinc-800/60 rounded-xl p-4 flex flex-col gap-3 min-h-[300px]">
        <span className="text-xs font-mono text-zinc-500 uppercase tracking-wider">Consequential Lifecycle</span>
        <div className="flex-1 border border-zinc-800/40 rounded-lg p-3 flex items-center justify-center opacity-40">
          <p className="text-xs text-zinc-600 font-mono">Awaiting run-scoped trust state...</p>
        </div>
      </div>
    );
  }

  const approvalRows = trust.recent_policy_decisions.slice(0, 3).map((decision) => ({
    label: decision.action,
    value: `${decision.target} · ${decision.effect}`,
    tone: (decision.target === 'reject' ? 'danger' : decision.target === 'approve' ? 'success' : 'default') as RowTone,
  }));

  const outboxRows = trust.recent_outbox_messages.slice(0, 3).map((message) => ({
    label: message.topic,
    value: `${message.status} · attempt ${message.attempts}`,
    tone: (
      message.status === 'DELIVERED'
        ? 'success'
        : message.status === 'FAILED'
          ? 'danger'
          : message.status === 'CLAIMED'
            ? 'warn'
            : 'default'
    ) as RowTone,
  }));

  const recoveryRows = trust.recent_recovery_cases.slice(0, 3).map((recovery) => ({
    label: recovery.reason,
    value: recovery.status,
    tone: (recovery.status === 'OPEN' ? 'warn' : recovery.status === 'ESCALATED' ? 'danger' : 'success') as RowTone,
  }));

  const auditRows = trust.recent_audit_events.slice(0, 4).map((event) => ({
    label: `#${event.seq}`,
    value: event.event_type,
  }));

  return (
    <div className="flex-1 bg-zinc-900/40 border border-zinc-800/60 rounded-xl p-4 flex flex-col gap-4 min-h-[300px]">
      <div className="flex items-center justify-between">
        <span className="text-xs font-mono text-zinc-500 uppercase tracking-wider">Consequential Lifecycle</span>
        <span className="text-[10px] font-mono text-zinc-600">project {trust.project_id}</span>
      </div>
      <Section title="Approval Decisions" rows={approvalRows} />
      <Section title="Outbox Delivery" rows={outboxRows} />
      <Section title="Recovery Cases" rows={recoveryRows} />
      <Section title="Audit Chain" rows={auditRows} />
    </div>
  );
}
