import { create } from 'zustand';
import type { Artifact } from '@amc/shared';

interface ArtifactState {
  artifacts: Record<string, Artifact[]>; // runId -> Artifact[]
  addArtifact: (runId: string, artifact: Artifact) => void;
}

export const useArtifactStore = create<ArtifactState>((set) => ({
  artifacts: {},
  addArtifact: (runId, artifact) => set((state) => {
    const currentList = state.artifacts[runId] || [];
    // Prevent duplicates
    if (currentList.some(a => a.id === artifact.id)) return state;
    return {
      artifacts: {
        ...state.artifacts,
        [runId]: [...currentList, artifact]
      }
    };
  }),
}));
