export function FileOrganizationPanel() {
  return (
    <div className="flex-1 bg-zinc-900/40 border border-zinc-800/60 rounded-xl p-4 flex flex-col gap-3 min-h-[300px]">
      <span className="text-xs font-mono text-zinc-500 uppercase tracking-wider">Context Tree</span>
      <div className="flex-1 border border-zinc-800/40 rounded-lg p-3 opacity-30 flex flex-col gap-2">
        <div className="h-3 w-24 bg-zinc-800 rounded" />
        <div className="h-3 w-32 bg-zinc-800 rounded ml-4" />
        <div className="h-3 w-28 bg-zinc-800 rounded ml-4" />
        <div className="h-3 w-20 bg-zinc-800 rounded" />
      </div>
    </div>
  );
}
