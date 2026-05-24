export function ArtifactPreviewPanel() {
  return (
    <div className="h-full p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between pb-2 border-b border-zinc-800/50">
        <span className="text-xs font-mono text-zinc-500 uppercase tracking-wider">Inspector</span>
        <div className="h-4 w-16 bg-zinc-800/60 rounded" />
      </div>
      <div className="flex-1 flex items-center justify-center opacity-30">
        <p className="text-xs text-zinc-600 font-mono">No artifact selected</p>
      </div>
    </div>
  );
}
