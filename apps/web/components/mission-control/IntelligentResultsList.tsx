"use client";

import { useArtifactStore } from '../../lib/stores/artifactStore';
import { useRunStore } from '../../lib/stores/runStore';

export function IntelligentResultsList() {
  const activeRunId = useRunStore((state) => state.activeRunId);
  const artifacts = useArtifactStore((state) => activeRunId ? state.artifacts[activeRunId] || [] : []);

  return (
    <div className="bg-zinc-900/40 border border-zinc-800/60 rounded-xl p-4 flex flex-col gap-3 min-h-[250px]">
      <div className="flex items-center justify-between pb-2 border-b border-zinc-800/50">
        <span className="text-xs font-mono text-zinc-500 uppercase tracking-wider">Prioritized Results</span>
      </div>
      <div className="flex-1 flex flex-col gap-2">
        {artifacts.length === 0 ? (
          <div className="flex-1 flex items-center justify-center opacity-30">
            <p className="text-xs text-zinc-600 font-mono">No artifacts generated</p>
          </div>
        ) : (
          artifacts.map((artifact) => (
            <div key={artifact.id} className="p-3 bg-zinc-900/80 rounded-lg border border-zinc-800/40">
              <div className="text-sm font-medium text-zinc-300 mb-1 capitalize">{artifact.type}</div>
              <div className="text-xs text-zinc-500 truncate">{artifact.content}</div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
