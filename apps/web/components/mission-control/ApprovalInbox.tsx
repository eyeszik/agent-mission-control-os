export function ApprovalInbox() {
  return (
    <div className="flex items-center gap-2 px-3 py-1.5 bg-zinc-900/60 border border-zinc-800/60 rounded-md">
      <div className="w-2 h-2 rounded-full bg-amber-500/50" />
      <span className="text-sm font-medium text-zinc-300">Inbox <span className="text-zinc-500 font-mono text-xs">(0)</span></span>
    </div>
  );
}
