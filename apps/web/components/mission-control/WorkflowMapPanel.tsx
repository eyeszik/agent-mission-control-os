"use client";

import { useNodeStatusStore } from '../../lib/stores/nodeStatusStore';
import { useRunStore } from '../../lib/stores/runStore';
import { useShallow } from 'zustand/react/shallow';

export function WorkflowMapPanel() {
  const activeRunId = useRunStore((state) => state.activeRunId);
  // ⚡ Bolt: Using useShallow to prevent unnecessary re-renders when returning derived objects
  const statuses = useNodeStatusStore(useShallow((state) => activeRunId ? state.statuses[activeRunId] : null));

  const getNodeColor = (nodeId: string) => {
    if (!statuses) return 'text-zinc-700';
    const status = statuses[nodeId];
    if (status === 'completed') return 'text-emerald-500';
    if (status === 'running') return 'text-amber-500 animate-pulse';
    if (status === 'failed') return 'text-red-500';
    return 'text-zinc-700'; // idle
  };

  return (
    <div className="flex-1 flex items-center justify-center p-8 relative">
      <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
        <svg className="w-full h-full" viewBox="0 0 400 200">
          <path d="M 100 100 L 200 100 L 300 100" stroke="#3f3f46" strokeWidth="2" strokeDasharray="4 4" fill="none" />
          
          <circle cx="100" cy="100" r="16" className={`${getNodeColor('ingest')} fill-current transition-colors duration-500`} />
          <circle cx="200" cy="100" r="16" className={`${getNodeColor('planner')} fill-current transition-colors duration-500`} />
          <circle cx="300" cy="100" r="16" className="text-zinc-700 fill-current" />
          
          <text x="100" y="130" textAnchor="middle" className="text-[10px] fill-zinc-500 font-mono">INGEST</text>
          <text x="200" y="130" textAnchor="middle" className="text-[10px] fill-zinc-500 font-mono">PLANNER</text>
          <text x="300" y="130" textAnchor="middle" className="text-[10px] fill-zinc-500 font-mono">END</text>
        </svg>
      </div>
      {!activeRunId && (
        <div className="text-center z-10 bg-zinc-950/80 px-4 py-2 rounded-full backdrop-blur-sm border border-zinc-800">
          <p className="text-sm text-zinc-400 font-mono">Graph Idle</p>
        </div>
      )}
    </div>
  );
}
