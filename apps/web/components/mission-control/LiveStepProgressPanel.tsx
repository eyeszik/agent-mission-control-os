export function LiveStepProgressPanel() {
  return (
    <div className="h-full bg-zinc-900/40 border border-zinc-800/60 rounded-xl p-4 flex flex-col">
      <span className="text-xs font-mono text-zinc-500 uppercase tracking-wider mb-4">Step Checkpoints</span>
      <div className="flex-1 flex flex-col gap-2 overflow-y-auto">
        {/* Skeleton items representing step logs */}
        {[1, 2, 3].map((i) => (
          <div key={i} className="flex items-center gap-3 opacity-30">
            <div className="w-2 h-2 rounded-full bg-zinc-700" />
            <div className="h-3 w-32 bg-zinc-800 rounded" />
          </div>
        ))}
      </div>
    </div>
  );
}
