import { create } from 'zustand';

// The project the operator is working in. Runs, threads, content and assets
// are all read through this id: PROJECT is the durable unit, a run is one
// execution inside it. Components select the primitive id, never the store.
interface ProjectState {
  activeProjectId: string | null;
  activeThreadId: string | null;
  setActiveProject: (projectId: string | null) => void;
  setActiveThread: (threadId: string | null) => void;
}

export const useProjectStore = create<ProjectState>((set) => ({
  activeProjectId: null,
  activeThreadId: null,
  setActiveProject: (projectId) =>
    set((state) => (state.activeProjectId === projectId ? state : { activeProjectId: projectId, activeThreadId: null })),
  setActiveThread: (threadId) => set({ activeThreadId: threadId }),
}));
