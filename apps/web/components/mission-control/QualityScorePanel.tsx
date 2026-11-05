import { useRunStore } from '../../lib/stores/runStore';

export function QualityScorePanel() {
  const activeRunId = useRunStore((state) => state.activeRunId);
  
  // Show placeholder when no active run
  if (!activeRunId) {
    return (
      <div className="flex items-center gap-4 text-sm">
        <div className="flex items-center gap-1.5">
          <span className="text-zinc-500 text-xs uppercase font-mono">Quality</span>
          <div className="px-2 py-0.5 bg-zinc-800/50 text-zinc-500 border border-zinc-700/30 rounded font-mono text-xs">
            —
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-4 text-sm">
      <div className="flex items-center gap-1.5">
        <span className="text-zinc-500 text-xs uppercase font-mono">Quality</span>
        <div className="px-2 py-0.5 bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 rounded font-mono text-xs">
          {/* Quality score will be populated from run data when available */}
          Pending
        </div>
      </div>
    </div>
  );
}
