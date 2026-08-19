"use client";

import { useEffect, useRef } from 'react';
import { globalBus } from '../../lib/events/bus';
import { useNodeStatusStore } from '../../lib/stores/nodeStatusStore';
import { useRunStore } from '../../lib/stores/runStore';
import { useApprovalStore } from '../../lib/stores/approvalStore';
import { SSEClient } from '../../lib/api/events';
import { getPendingApprovals } from '../../lib/api/approvals';
import type { RunEvent } from '@amc/shared';

// The backend's /runs/{id}/events SSE endpoint is still a fixed 3-event mock
// stream (services/langgraph/api/routes/events.py), so it cannot be relied on
// to surface new approvals. Poll instead until that's wired to real node
// execution events; this can be dropped in favor of SSE-only once it is.
const APPROVALS_POLL_INTERVAL_MS = 4000;

export function MissionControlProvider() {
  const activeRunId = useRunStore((state) => state.activeRunId);
  const updateNodeStatus = useNodeStatusStore((state) => state.updateNodeStatus);
  const setApprovals = useApprovalStore((state) => state.setApprovals);
  const sseRef = useRef<SSEClient | null>(null);

  useEffect(() => {
    const handleEvent = (event: RunEvent) => {
      if (event.type === 'node_start') updateNodeStatus(event.run_id, event.node_id, 'running');
      else if (event.type === 'node_complete') updateNodeStatus(event.run_id, event.node_id, 'completed');
      else if (event.type === 'node_error') updateNodeStatus(event.run_id, event.node_id, 'failed');
    };

    globalBus.on('run_event_received', handleEvent as any);
    return () => {
      globalBus.off('run_event_received', handleEvent as any);
    };
  }, [updateNodeStatus]);

  useEffect(() => {
    if (!activeRunId) return;

    // Clean up existing connection if it exists
    if (sseRef.current) {
      sseRef.current.disconnect();
    }

    const sse = new SSEClient(activeRunId, globalBus);
    sseRef.current = sse;
    sse.connect();

    return () => {
      sse.disconnect();
      sseRef.current = null;
    };
  }, [activeRunId]);

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
