export function IntelligentResultsList() {
  return (
    <div className="bg-zinc-900/40 border border-zinc-800/60 rounded-xl p-4 flex flex-col gap-3 min-h-[250px]">
      <div className="flex items-center justify-between pb-2 border-b border-zinc-800/50">
        <span className="text-xs font-mono text-zinc-500 uppercase tracking-wider">Prioritized Results</span>
      </div>
      <div className="flex-1 flex flex-col gap-2">
        {/* Skeletons for sorted results */}
        {[1, 2].map((i) => (
          <div key={i} className="p-3 bg-zinc-900/80 rounded-lg border border-zinc-800/40 opacity-40">
            <div className="h-4 w-48 bg-zinc-800 rounded mb-2" />
            <div className="h-3 w-full bg-zinc-800 rounded" />
          </div>
        ))}
      </div>
    </div>
  );
}
