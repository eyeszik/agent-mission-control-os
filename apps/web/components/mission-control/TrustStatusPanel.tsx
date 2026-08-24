"use client";

import { useEffect, useState } from 'react';
import type { AgencyRun, RoleOSManifest, TrustSnapshot } from '@amc/shared';
import { getAgencyRun } from '../../lib/api/agency';
import { getProjectTrust, getRoleOSManifest } from '../../lib/api/runtime';
import { globalBus } from '../../lib/events/bus';
import { useRunStore } from '../../lib/stores/runStore';

export function TrustStatusPanel() {
  const activeRunId = useRunStore((state) => state.activeRunId);
  const [manifest, setManifest] = useState<RoleOSManifest | null>(null);
  const [trust, setTrust] = useState<TrustSnapshot | null>(null);
  const [run, setRun] = useState<AgencyRun | null>(null);

  useEffect(() => {
    getRoleOSManifest().then(setManifest).catch(() => setManifest(null));
  }, []);

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
        if (!cancelled) setRun(null);
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

  return (
    <div className="flex items-center gap-4 text-sm">
      <div className="flex items-center gap-1.5">
        <span className="text-zinc-500 text-xs uppercase font-mono">RoleOS</span>
        <div className="px-2 py-0.5 bg-sky-500/10 text-sky-400 border border-sky-500/20 rounded font-mono text-xs">
          {manifest ? `${manifest.role_count} roles` : 'unavailable'}
        </div>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="text-zinc-500 text-xs uppercase font-mono">Trust</span>
        <div className="px-2 py-0.5 bg-violet-500/10 text-violet-400 border border-violet-500/20 rounded font-mono text-xs">
          {trust ? `${trust.policy_decisions}/${trust.open_recovery_cases}/${trust.pending_outbox}` : 'no-project'}
        </div>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="text-zinc-500 text-xs uppercase font-mono">Proof</span>
        <div className="px-2 py-0.5 bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 rounded font-mono text-xs">
          {run?.proof ? `${run.proof.summary.execution_count}/${run.proof.summary.observation_count}/${run.proof.summary.failure_count}` : 'no-run'}
        </div>
      </div>
      {trust && (
        <div className="hidden lg:flex items-center gap-3 text-[10px] font-mono text-zinc-400">
          <span>approval={trust.recent_policy_decisions[0]?.target ?? 'n/a'}</span>
          <span>outbox={trust.delivered_outbox}/{trust.failed_outbox}</span>
          <span>recovery={trust.open_recovery_cases}/{trust.resolved_recovery_cases}</span>
        </div>
      )}
    </div>
  );
}
