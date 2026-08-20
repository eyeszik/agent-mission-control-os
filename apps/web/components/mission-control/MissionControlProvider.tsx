"use client";

import { useEffect, useRef } from 'react';
import type { RunEvent } from '@amc/shared';
import { globalBus } from '../../lib/events/bus';
import { SSEClient } from '../../lib/api/events';
import { getPendingApprovals } from '../../lib/api/approvals';
import { useApprovalStore } from '../../lib/stores/approvalStore';
import { useNodeStatusStore } from '../../lib/stores/nodeStatusStore';
import { useRunStore } from '../../lib/stores/runStore';

const APPROVALS_POLL_INTERVAL_MS = 4000;

export function MissionControlProvider() {
  const activeRunId = useRunStore((state) => state.activeRunId);
  const updateNodeStatus = useNodeStatusStore((state) => state.updateNodeStatus);
  const setApprovals = useApprovalStore((state) => state.setApprovals);
  const sseRef = useRef<SSEClient | null>(null);

  useEffect(() => {
    const handleEvent = (event: RunEvent) => {
      if (!event.node_id) return;
      if (event.event_type === 'node_complete') {
        updateNodeStatus(event.run_id, event.node_id, 'completed');
      } else if (event.event_type === 'node_error') {
        updateNodeStatus(event.run_id, event.node_id, 'failed');
      }
    };

    globalBus.on('run_event_received', handleEvent as any);
    return () => {
      globalBus.off('run_event_received', handleEvent as any);
    };
  }, [updateNodeStatus]);

  useEffect(() => {
    if (!activeRunId) return;
    if (sseRef.current) sseRef.current.disconnect();

    const sse = new SSEClient(activeRunId, globalBus);
    sseRef.current = sse;
    sse.connect();

    return () => {
      sse.disconnect();
      sseRef.current = null;
    };
  }, [activeRunId]);

  // Approval rows are not yet emitted as domain events, so poll the
  // authenticated tenant-scoped endpoint independently from run-event replay.
  useEffect(() => {
    let cancelled = false;

    const poll = async () => {
      try {
        const approvals = await getPendingApprovals();
        if (!cancelled) setApprovals(approvals);
      } catch (err) {
        console.warn('Approval poll failed', err);
      }
    };

    poll();
    const interval = setInterval(poll, APPROVALS_POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [setApprovals]);

  return null;
}
