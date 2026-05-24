import { create } from 'zustand';
import type { Artifact } from '@amc/shared';

interface ArtifactState {
  artifacts: Record<string, Artifact[]>; // runId -> Artifact[]
  selectedArtifactId: string | null;
  addArtifact: (runId: string, artifact: Artifact) => void;
  setSelectedArtifact: (id: string | null) => void;
}

export const useArtifactStore = create<ArtifactState>((set) => ({
  artifacts: {},
  selectedArtifactId: null,
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
  setSelectedArtifact: (id) => set({ selectedArtifactId: id }),
}));
