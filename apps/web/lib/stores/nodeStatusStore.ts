import { create } from 'zustand';

type NodeStatus = 'idle' | 'running' | 'completed' | 'failed';

interface NodeStatusState {
  statuses: Record<string, Record<string, NodeStatus>>; // runId -> nodeId -> status
  updateNodeStatus: (runId: string, nodeId: string, status: NodeStatus) => void;
}

export const useNodeStatusStore = create<NodeStatusState>((set) => ({
  statuses: {},
  updateNodeStatus: (runId, nodeId, status) => set((state) => {
    const runStatuses = state.statuses[runId] || {};
    return {
      statuses: {
        ...state.statuses,
        [runId]: { ...runStatuses, [nodeId]: status }
      }
    };
  }),
}));
