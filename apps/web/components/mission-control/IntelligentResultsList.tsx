"use client";

import { useArtifactStore } from '../../lib/stores/artifactStore';
import { useRunStore } from '../../lib/stores/runStore';
import type { Artifact } from '@amc/shared';

// ⚡ Bolt: Extract individual list items to subscribe directly to selection state,
// preventing the parent IntelligentResultsList from re-rendering on single-item selection updates.
function ArtifactItem({ artifact }: { artifact: Artifact }) {
  const isSelected = useArtifactStore((state) => state.selectedArtifactId === artifact.id);
  const setSelectedArtifact = useArtifactStore((state) => state.setSelectedArtifact);

  return (
    <button
      onClick={() => setSelectedArtifact(artifact.id)}
      className={`text-left p-3 rounded-lg border transition-colors ${isSelected ? 'bg-zinc-800/80 border-zinc-700' : 'bg-zinc-900/80 border-zinc-800/40 hover:bg-zinc-800/60'}`}
    >
      <div className="text-sm font-medium text-zinc-300 mb-1 capitalize flex justify-between">
        {artifact.type}
        <span className="text-[10px] text-zinc-600">{new Date(artifact.created_at).toLocaleTimeString()}</span>
      </div>
      <div className="text-xs text-zinc-500 truncate">{artifact.content}</div>
    </button>
  );
}

export function IntelligentResultsList() {
  const activeRunId = useRunStore((state) => state.activeRunId);
  const artifacts = useArtifactStore((state) => activeRunId ? state.artifacts[activeRunId] : null);

  const displayArtifacts = artifacts || [];

  return (
    <div className="bg-zinc-900/40 border border-zinc-800/60 rounded-xl p-4 flex flex-col gap-3 min-h-[250px]">
      <div className="flex items-center justify-between pb-2 border-b border-zinc-800/50">
        <span className="text-xs font-mono text-zinc-500 uppercase tracking-wider">Prioritized Results</span>
        <span className="text-xs text-zinc-600 font-mono">{displayArtifacts.length} Items</span>
      </div>
      <div className="flex-1 flex flex-col gap-2 overflow-y-auto max-h-[300px]">
        {displayArtifacts.length === 0 ? (
          <div className="flex-1 flex items-center justify-center opacity-30">
            <p className="text-xs text-zinc-600 font-mono">No artifacts generated</p>
          </div>
        ) : (
          displayArtifacts.map((artifact) => (
            <ArtifactItem key={artifact.id} artifact={artifact} />
          ))
        )}
      </div>
    </div>
  );
}
