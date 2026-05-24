export function CommandInputPanel() {
  return (
    <div className="bg-zinc-900/60 border border-zinc-800/60 rounded-xl p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-mono text-zinc-500 uppercase tracking-wider">Terminal</span>
      </div>
      <div className="relative">
        <textarea 
          disabled
          placeholder="Awaiting directive..."
          className="w-full bg-zinc-950/50 border border-zinc-800/80 rounded-lg p-3 text-sm text-zinc-300 placeholder:text-zinc-600 focus:outline-none focus:border-emerald-500/50 transition-colors resize-none h-24"
        />
        {/* Typewriter cursor skeleton */}
        <div className="absolute top-4 left-3 w-1.5 h-4 bg-emerald-500/80 animate-pulse hidden" />
      </div>
      <div className="flex justify-end">
        <button disabled className="px-4 py-1.5 bg-zinc-100 text-zinc-900 text-sm font-medium rounded-md opacity-50 cursor-not-allowed">
          Execute
        </button>
      </div>
    </div>
  );
}
