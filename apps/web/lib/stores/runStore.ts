import { create } from 'zustand';
import type { AgentRun } from '@amc/shared';

interface RunState {
  activeRunId: string | null;
  runs: Record<string, AgentRun>;
  setActiveRun: (runId: string) => void;
  upsertRun: (run: AgentRun) => void;
}

export const useRunStore = create<RunState>((set) => ({
  activeRunId: null,
  runs: {},
  setActiveRun: (runId) => set({ activeRunId: runId }),
  upsertRun: (run) => set((state) => ({
    runs: { ...state.runs, [run.id]: run }
  })),
}));

declare global {
  interface Window {
    __amcRunStore?: typeof useRunStore;
  }
}

if (typeof window !== 'undefined') {
  window.__amcRunStore = useRunStore;
}
