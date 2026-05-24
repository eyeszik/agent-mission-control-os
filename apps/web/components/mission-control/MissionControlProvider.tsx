"use client";

import { useEffect, useRef } from 'react';
import { globalBus } from '../../lib/events/bus';
import { useNodeStatusStore } from '../../lib/stores/nodeStatusStore';
import { useRunStore } from '../../lib/stores/runStore';
import { SSEClient } from '../../lib/api/events';
import type { RunEvent } from '@amc/shared';

export function MissionControlProvider() {
  const activeRunId = useRunStore((state) => state.activeRunId);
  const updateNodeStatus = useNodeStatusStore((state) => state.updateNodeStatus);
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

  return null;
}

