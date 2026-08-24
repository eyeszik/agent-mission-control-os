"use client";

import { useEffect, useState } from 'react';
import type { AgencyRun, TrustSnapshot } from '@amc/shared';
import { getAgencyRun } from '../../lib/api/agency';
import { getProjectTrust, replayOutboxMessage, resolveRecoveryCase } from '../../lib/api/runtime';
import { globalBus } from '../../lib/events/bus';
import { useRunStore } from '../../lib/stores/runStore';
import { generateIdempotencyKey } from '../../lib/utils/idempotency';

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
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!activeRunId) {
      setRun(null);
      setTrust(null);
      return;
    }
    let cancelled = false;
    const refreshRun = async () => {
      try {
        const value = await getAgencyRun(activeRunId);
        if (!cancelled) setRun(value);
      } catch {
        if (!cancelled) {
          setRun(null);
          setTrust(null);
        }
      }
    };
    const onLifecycle = (event: { run_id: string }) => {
      if (event.run_id === activeRunId) void refreshRun();
    };
    void refreshRun();
    globalBus.on('lifecycle_event_received', onLifecycle as any);
    return () => {
      cancelled = true;
      globalBus.off('lifecycle_event_received', onLifecycle as any);
    };
  }, [activeRunId]);

  useEffect(() => {
    if (!run?.project_id) {
      setTrust(null);
      return;
    }
    let cancelled = false;
    const refreshTrust = async () => {
      try {
        const value = await getProjectTrust(run.project_id!);
        if (!cancelled) setTrust(value);
      } catch {
        if (!cancelled) setTrust(null);
      }
    };
    const onLifecycle = (event: { project_id: string }) => {
      if (event.project_id === run.project_id) void refreshTrust();
    };
    void refreshTrust();
    globalBus.on('lifecycle_event_received', onLifecycle as any);
    return () => {
      cancelled = true;
      globalBus.off('lifecycle_event_received', onLifecycle as any);
    };
  }, [run?.project_id]);

  const handleResolveRecovery = async (
    recoveryId: string,
    status: 'RECONCILED' | 'COMPENSATED' | 'ESCALATED'
  ) => {
    if (!trust || !run?.run_id) return;
    const key = `recovery:${recoveryId}:${status}`;
    setBusyKey(key);
    setError(null);
    try {
      await resolveRecoveryCase(trust.project_id, recoveryId, status, generateIdempotencyKey(), run.run_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update recovery case');
    } finally {
      setBusyKey(null);
    }
  };

  const handleReplayOutbox = async (messageId: string) => {
    if (!trust || !run?.run_id) return;
    const key = `outbox:${messageId}`;
    setBusyKey(key);
    setError(null);
    try {
      await replayOutboxMessage(trust.project_id, messageId, generateIdempotencyKey(), run.run_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to replay outbox message');
    } finally {
      setBusyKey(null);
    }
  };

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
      {error && (
        <div className="rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-400">
          {error}
        </div>
      )}
      <Section title="Approval Decisions" rows={approvalRows} />
      <div className="flex flex-col gap-2">
        <Section title="Outbox Delivery" rows={outboxRows} />
        {trust.recent_outbox_messages.slice(0, 3).map((message) => (
          message.status !== 'DELIVERED' ? (
            <div key={message.message_id} className="flex justify-end">
              <button
                type="button"
                onClick={() => handleReplayOutbox(message.message_id)}
                disabled={busyKey === `outbox:${message.message_id}`}
                className="rounded-md border border-sky-500/30 bg-sky-500/10 px-2 py-1 text-[10px] font-mono text-sky-300 disabled:opacity-50"
              >
                {busyKey === `outbox:${message.message_id}` ? 'Replaying…' : 'Replay'}
              </button>
            </div>
          ) : null
        ))}
      </div>
      <div className="flex flex-col gap-2">
        <Section title="Recovery Cases" rows={recoveryRows} />
        {trust.recent_recovery_cases.slice(0, 3).map((recovery) => (
          recovery.status === 'OPEN' ? (
            <div key={recovery.recovery_id} className="flex gap-2 justify-end">
              <button
                type="button"
                onClick={() => handleResolveRecovery(recovery.recovery_id, 'RECONCILED')}
                disabled={busyKey === `recovery:${recovery.recovery_id}:RECONCILED`}
                className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-[10px] font-mono text-emerald-300 disabled:opacity-50"
              >
                {busyKey === `recovery:${recovery.recovery_id}:RECONCILED` ? 'Working…' : 'Resolve'}
              </button>
              <button
                type="button"
                onClick={() => handleResolveRecovery(recovery.recovery_id, 'ESCALATED')}
                disabled={busyKey === `recovery:${recovery.recovery_id}:ESCALATED`}
                className="rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-[10px] font-mono text-amber-300 disabled:opacity-50"
              >
                {busyKey === `recovery:${recovery.recovery_id}:ESCALATED` ? 'Working…' : 'Escalate'}
              </button>
            </div>
          ) : null
        ))}
      </div>
      <Section title="Audit Chain" rows={auditRows} />
    </div>
  );
}
