"use client";

import { AGENCY_PIPELINE_STAGES } from '@amc/shared';
import { useNodeStatusStore } from '../../lib/stores/nodeStatusStore';
import { useRunStore } from '../../lib/stores/runStore';

// ⚡ Bolt: Extracted child component to subscribe directly to its specific node status
// preventing the parent LiveStepProgressPanel from re-rendering on single-item updates.
function LiveStepItem({ runId, node }: { runId: string; node: string }) {
  const status = useNodeStatusStore((state) => state.statuses[runId]?.[node] || 'idle');
  if (status === 'idle') return null;

  return (
    <div className="flex items-center gap-3">
      <div className={`w-2 h-2 rounded-full ${status === 'completed' ? 'bg-emerald-500' : status === 'running' ? 'bg-amber-500 animate-pulse' : 'bg-red-500'}`} />
      <div className="text-sm text-zinc-300 capitalize">
        {node} <span className="text-xs text-zinc-500 lowercase">({status})</span>
      </div>
    </div>
  );
}

export function LiveStepProgressPanel() {
  const activeRunId = useRunStore((state) => state.activeRunId);

  return (
    <div className="h-full bg-zinc-900/40 border border-zinc-800/60 rounded-xl p-4 flex flex-col">
      <span className="text-xs font-mono text-zinc-500 uppercase tracking-wider mb-4">Step Checkpoints</span>
      <div className="flex-1 flex flex-col gap-2 overflow-y-auto">
        {!activeRunId && <div className="text-xs text-zinc-600 font-mono">Awaiting execution trace...</div>}
        {activeRunId && AGENCY_PIPELINE_STAGES.map((node) => (
          <LiveStepItem key={node} runId={activeRunId} node={node} />
        ))}
      </div>
    </div>
  );
}
