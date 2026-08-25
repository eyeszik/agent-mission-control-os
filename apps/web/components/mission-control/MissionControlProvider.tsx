"use client";

import { useEffect, useRef } from 'react';
import type { RunEvent } from '@amc/shared';
import { globalBus } from '../../lib/events/bus';
import { SSEClient } from '../../lib/api/events';
import { getPendingApprovals } from '../../lib/api/approvals';
import { useApprovalStore } from '../../lib/stores/approvalStore';
import { useNodeStatusStore } from '../../lib/stores/nodeStatusStore';
import { useRunStore } from '../../lib/stores/runStore';

declare global {
  interface Window {
    __amcRunStore?: typeof useRunStore;
    __amcApprovalStore?: typeof useApprovalStore;
  }
}

export function MissionControlProvider() {
  const activeRunId = useRunStore((state) => state.activeRunId);
  const updateNodeStatus = useNodeStatusStore((state) => state.updateNodeStatus);
  const upsertApproval = useApprovalStore((state) => state.upsertApproval);
  const removeApproval = useApprovalStore((state) => state.removeApproval);
  const setApprovals = useApprovalStore((state) => state.setApprovals);
  const sseRef = useRef<SSEClient | null>(null);

  useEffect(() => {
    window.__amcRunStore = useRunStore;
    window.__amcApprovalStore = useApprovalStore;
    return () => {
      delete window.__amcRunStore;
      delete window.__amcApprovalStore;
    };
  }, []);

  useEffect(() => {
    const handleEvent = (event: RunEvent) => {
      if (event.event_type === 'node_complete' && event.node_id) {
        updateNodeStatus(event.run_id, event.node_id, 'completed');
      } else if (event.event_type === 'node_error' && event.node_id) {
        updateNodeStatus(event.run_id, event.node_id, 'failed');
      } else if (event.event_type === 'approval_requested') {
        const payload = event.safe_payload as Record<string, unknown>;
        if (payload.approval_id && typeof payload.approval_id === 'string') {
          upsertApproval({
            approval_id: payload.approval_id,
            run_id: event.run_id,
            tenant_id: event.tenant_id,
            project_id: event.project_id,
            reason: typeof payload.reason === 'string' ? payload.reason : 'Approval requested',
            confidence: typeof payload.confidence === 'number' ? payload.confidence : null,
            status: 'pending',
            reviewer: null,
            decision: null,
            created_at: event.observed_at,
            decided_at: null,
          });
        }
        globalBus.emit('lifecycle_event_received', event);
      } else if (event.event_type === 'approval_decided') {
        const payload = event.safe_payload as Record<string, unknown>;
        if (payload.approval_id && typeof payload.approval_id === 'string') {
          removeApproval(payload.approval_id);
        }
        globalBus.emit('lifecycle_event_received', event);
      } else if (['recovery_case_updated', 'outbox_updated', 'run_remediation_updated'].includes(event.event_type)) {
        globalBus.emit('lifecycle_event_received', event);
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

  useEffect(() => {
    if (!activeRunId) return;
    let cancelled = false;
    getPendingApprovals()
      .then((approvals) => {
        if (!cancelled) setApprovals(approvals);
      })
      .catch((err) => {
        console.warn('Initial approval sync failed', err);
      });
    return () => {
      cancelled = true;
    };
  }, [activeRunId, setApprovals]);

  return null;
}
