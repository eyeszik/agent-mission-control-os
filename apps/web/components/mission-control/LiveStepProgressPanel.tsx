"use client";

import { useNodeStatusStore } from '../../lib/stores/nodeStatusStore';
import { useRunStore } from '../../lib/stores/runStore';
import { useShallow } from 'zustand/react/shallow';

export function LiveStepProgressPanel() {
  const activeRunId = useRunStore((state) => state.activeRunId);
  // ⚡ Bolt: Using useShallow to prevent unnecessary re-renders when returning derived objects
  const statuses = useNodeStatusStore(useShallow((state) => activeRunId ? state.statuses[activeRunId] : null));

  const nodes = ['ingest', 'planner'];

  return (
    <div className="h-full bg-zinc-900/40 border border-zinc-800/60 rounded-xl p-4 flex flex-col">
      <span className="text-xs font-mono text-zinc-500 uppercase tracking-wider mb-4">Step Checkpoints</span>
      <div className="flex-1 flex flex-col gap-2 overflow-y-auto">
        {!activeRunId && <div className="text-xs text-zinc-600 font-mono">Awaiting execution trace...</div>}
        {activeRunId && nodes.map((node) => {
          const status = statuses ? statuses[node] || 'idle' : 'idle';
          if (status === 'idle') return null;
          
          return (
            <div key={node} className="flex items-center gap-3">
              <div className={`w-2 h-2 rounded-full ${status === 'completed' ? 'bg-emerald-500' : status === 'running' ? 'bg-amber-500 animate-pulse' : 'bg-red-500'}`} />
              <div className="text-sm text-zinc-300 capitalize">
                {node} <span className="text-xs text-zinc-500 lowercase">({status})</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
