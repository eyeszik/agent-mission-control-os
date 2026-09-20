"use client";

import { useEffect, useState, useMemo } from 'react';
import type { AgencyRun, TrustSnapshot } from '@amc/shared';
import { getAgencyRun } from '../../lib/api/agency';
import {
  compensateAmbiguousRun,
  getProjectTrust,
  regenerateRunApproval,
  reviseProtectedRunArtifact,
  replayOutboxMessage,
  resolveRecoveryCase,
  retryBlockedRun,
} from '../../lib/api/runtime';
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

  const handleRetryBlockedRun = async (recoveryId: string) => {
    if (!run?.run_id) return;
    const key = `retry:${recoveryId}`;
    setBusyKey(key);
    setError(null);
    try {
      const result = await retryBlockedRun(run.run_id, recoveryId, generateIdempotencyKey());
      setRun(result.run);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to retry blocked run');
    } finally {
      setBusyKey(null);
    }
  };

  const handleCompensateRun = async (recoveryId: string) => {
    if (!run?.run_id) return;
    const key = `compensate:${recoveryId}`;
    setBusyKey(key);
    setError(null);
    try {
      const result = await compensateAmbiguousRun(run.run_id, recoveryId, generateIdempotencyKey());
      setRun(result.run);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to compensate ambiguous result');
    } finally {
      setBusyKey(null);
    }
  };

  const handleRegenerateApproval = async (approvalId?: string) => {
    if (!run?.run_id) return;
    const key = `approval:${approvalId ?? 'latest'}`;
    setBusyKey(key);
    setError(null);
    try {
      const result = await regenerateRunApproval(run.run_id, approvalId, generateIdempotencyKey());
      setRun(result.run);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to regenerate approval');
    } finally {
      setBusyKey(null);
    }
  };

  const handleSimulateLineageChange = async () => {
    if (!run?.run_id) return;
    const key = 'lineage:simulate';
    setBusyKey(key);
    setError(null);
    try {
      const trustSnapshot = await reviseProtectedRunArtifact(run.run_id, 'e'.repeat(64));
      setTrust(trustSnapshot);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to revise protected artifact');
    } finally {
      setBusyKey(null);
    }
  };

  if (!activeRunId || !trust || !run) {
    return (
      <div className="flex-1 bg-zinc-900/40 border border-zinc-800/60 rounded-xl p-4 flex flex-col gap-3 min-h-[300px]">
        <span className="text-xs font-mono text-zinc-500 uppercase tracking-wider">Consequential Lifecycle</span>
        <div className="flex-1 border border-zinc-800/40 rounded-lg p-3 flex items-center justify-center opacity-40">
          <p className="text-xs text-zinc-600 font-mono">Awaiting run-scoped trust state...</p>
        </div>
      </div>
    );
  }

  const {
    approvalRows,
    outboxRows,
    recoveryRows,
    auditRows,
    staleApprovals,
    activeRunLineageRemediations,
    activeRunObligations,
    retryableRecoveries,
    compensatableRecoveries,
    openLineageCount,
    resolvedLineageCount,
    openObligationsCount,
    hookGapsCount,
  } = useMemo(() => {
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

    const staleApprovals = (run.approvals ?? []).filter((approval) => approval.status === 'stale');

    let openLineageCount = 0;
    let resolvedLineageCount = 0;
    const activeRunLineageRemediations = trust.recent_lineage_remediations.filter((item) => {
      if (item.run_id !== run.run_id) return false;
      if (item.status === 'OPEN') openLineageCount++;
      else resolvedLineageCount++;
      return true;
    });

    let openObligationsCount = 0;
    let hookGapsCount = 0;
    const activeRunObligations = trust.recent_invalidation_obligations.filter((item) => {
      if (item.run_id !== run.run_id) return false;
      if (item.state === 'OPEN') openObligationsCount++;
      else if (item.state === 'HOOK_GAP') hookGapsCount++;
      return true;
    });

    const retryableRecoveries = trust.recent_recovery_cases.filter(
      (recovery) =>
        recovery.status === 'OPEN' &&
        recovery.reason !== 'AMBIGUOUS_EXTERNAL_RESULT' &&
        recovery.execution_ref === run.run_id &&
        run.status === 'failed'
    );

    const compensatableRecoveries = trust.recent_recovery_cases.filter(
      (recovery) =>
        recovery.status === 'OPEN' &&
        recovery.reason === 'AMBIGUOUS_EXTERNAL_RESULT' &&
        recovery.execution_ref === run.run_id
    );

    return {
      approvalRows,
      outboxRows,
      recoveryRows,
      auditRows,
      staleApprovals,
      activeRunLineageRemediations,
      activeRunObligations,
      retryableRecoveries,
      compensatableRecoveries,
      openLineageCount,
      resolvedLineageCount,
      openObligationsCount,
      hookGapsCount,
    };
  }, [trust, run]);

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
        <Section
          title="Lineage Remediation Queue"
          rows={[
            { label: 'open queue', value: String(openLineageCount), tone: openLineageCount > 0 ? 'warn' : 'default' },
            { label: 'resolved queue', value: String(resolvedLineageCount), tone: resolvedLineageCount > 0 ? 'success' : 'default' },
          ]}
        />
        <div className="flex justify-end">
          <button
            type="button"
            onClick={handleSimulateLineageChange}
            disabled={busyKey === 'lineage:simulate'}
            className="rounded-md border border-zinc-700/60 bg-zinc-900/70 px-2 py-1 text-[10px] font-mono text-zinc-200 disabled:opacity-50"
          >
            {busyKey === 'lineage:simulate' ? 'Working…' : 'Simulate protected artifact change'}
          </button>
        </div>
        {activeRunLineageRemediations.slice(0, 3).map((item) => (
          <div key={item.remediation_id} className="rounded-lg border border-zinc-800/50 bg-zinc-950/40 px-3 py-2 flex items-center justify-between gap-3">
            <div className="flex flex-col">
              <span className="text-[11px] font-mono text-zinc-300">{item.changed_version_ref}</span>
              <span className="text-[10px] font-mono text-zinc-600">{item.artifact_id} · {item.status}</span>
            </div>
            {item.status === 'OPEN' && item.approval_id ? (
              <button
                type="button"
                onClick={() => handleRegenerateApproval(item.approval_id ?? undefined)}
                disabled={busyKey === `approval:${item.approval_id}`}
                className="rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-[10px] font-mono text-amber-300 disabled:opacity-50"
              >
                {busyKey === `approval:${item.approval_id}` ? 'Working…' : 'Regenerate approval'}
              </button>
            ) : null}
          </div>
        ))}
      </div>
      <div className="flex flex-col gap-2">
        <Section
          title="Run Remediation"
          rows={[
            { label: 'run status', value: run.status },
            { label: 'compile gate', value: trust.compile_blocked ? 'BLOCKED' : 'CLEAR', tone: trust.compile_blocked ? 'warn' : 'success' },
            { label: 'open obligations', value: String(openObligationsCount), tone: openObligationsCount > 0 ? 'warn' : 'default' },
            { label: 'hook gaps', value: String(hookGapsCount), tone: hookGapsCount > 0 ? 'danger' : 'default' },
            { label: 'open retry paths', value: String(retryableRecoveries.length), tone: retryableRecoveries.length > 0 ? 'warn' : 'default' },
            { label: 'ambiguous recoveries', value: String(compensatableRecoveries.length), tone: compensatableRecoveries.length > 0 ? 'warn' : 'default' },
            { label: 'stale approvals', value: String(staleApprovals.length), tone: staleApprovals.length > 0 ? 'warn' : 'default' },
          ]}
        />
        {activeRunObligations.slice(0, 4).map((item) => (
          <div key={item.obligation_id} className="rounded-lg border border-zinc-800/50 bg-zinc-950/40 px-3 py-2 flex items-center justify-between gap-3">
            <div className="flex flex-col">
              <span className="text-[11px] font-mono text-zinc-300">{item.event_class}</span>
              <span className="text-[10px] font-mono text-zinc-600">{item.node_id} · {item.state}</span>
            </div>
            <span className={`text-[10px] font-mono ${item.state === 'HOOK_GAP' ? 'text-red-300' : item.state === 'OPEN' ? 'text-amber-300' : 'text-emerald-300'}`}>
              {item.demanded ? 'demanded' : 'optional'}
            </span>
          </div>
        ))}
        {retryableRecoveries.map((recovery) => (
          <div key={`retry-${recovery.recovery_id}`} className="flex justify-end">
            <button
              type="button"
              onClick={() => handleRetryBlockedRun(recovery.recovery_id)}
              disabled={busyKey === `retry:${recovery.recovery_id}`}
              className="rounded-md border border-sky-500/30 bg-sky-500/10 px-2 py-1 text-[10px] font-mono text-sky-300 disabled:opacity-50"
            >
              {busyKey === `retry:${recovery.recovery_id}` ? 'Retrying…' : 'Retry blocked run'}
            </button>
          </div>
        ))}
        {compensatableRecoveries.map((recovery) => (
          <div key={`compensate-${recovery.recovery_id}`} className="flex justify-end">
            <button
              type="button"
              onClick={() => handleCompensateRun(recovery.recovery_id)}
              disabled={busyKey === `compensate:${recovery.recovery_id}`}
              className="rounded-md border border-fuchsia-500/30 bg-fuchsia-500/10 px-2 py-1 text-[10px] font-mono text-fuchsia-300 disabled:opacity-50"
            >
              {busyKey === `compensate:${recovery.recovery_id}` ? 'Working…' : 'Compensate ambiguity'}
            </button>
          </div>
        ))}
        {staleApprovals.map((approval) => (
          <div key={`approval-${approval.approval_id}`} className="flex justify-end">
            <button
              type="button"
              onClick={() => handleRegenerateApproval(approval.approval_id)}
              disabled={busyKey === `approval:${approval.approval_id}`}
              className="rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-[10px] font-mono text-amber-300 disabled:opacity-50"
            >
              {busyKey === `approval:${approval.approval_id}` ? 'Working…' : 'Regenerate approval'}
            </button>
          </div>
        ))}
      </div>
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
