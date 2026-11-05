import { create } from 'zustand';

interface ProjectState {
  currentProjectId: string | null;
  setCurrentProject: (projectId: string) => void;
}

export const useProjectStore = create<ProjectState>((set) => ({
  currentProjectId: null,
  setCurrentProject: (projectId) => set({ currentProjectId: projectId }),
}));
