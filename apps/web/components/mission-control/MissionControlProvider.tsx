"use client";

import { useEffect } from 'react';
import { globalBus } from '../../lib/events/bus';
import { useNodeStatusStore } from '../../lib/stores/nodeStatusStore';
import { useRunStore } from '../../lib/stores/runStore';
import { SSEClient } from '../../lib/api/events';
import type { RunEvent } from '@amc/shared';

export function MissionControlProvider({ children }: { children: React.ReactNode }) {
  const activeRunId = useRunStore((state) => state.activeRunId);
  const updateNodeStatus = useNodeStatusStore((state) => state.updateNodeStatus);

  useEffect(() => {
    const handleEvent = (event: RunEvent) => {
      if (event.type === 'node_start') updateNodeStatus(event.run_id, event.node_id, 'running');
      if (event.type === 'node_complete') updateNodeStatus(event.run_id, event.node_id, 'completed');
      if (event.type === 'node_error') updateNodeStatus(event.run_id, event.node_id, 'failed');
    };

    globalBus.on('run_event_received', handleEvent as any);
    return () => globalBus.off('run_event_received', handleEvent as any);
  }, [updateNodeStatus]);

  useEffect(() => {
    if (!activeRunId) return;
    
    const sse = new SSEClient(activeRunId, globalBus);
    sse.connect();
    
    return () => sse.disconnect();
  }, [activeRunId]);

  return <>{children}</>;
}
