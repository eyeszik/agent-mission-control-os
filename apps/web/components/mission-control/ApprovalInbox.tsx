"use client";

import { useApprovalStore } from '../../lib/stores/approvalStore';

export function ApprovalInbox() {
  // Optimization: Compute derived state (.length) directly inside the selector.
  // This prevents unnecessary re-renders when the count hasn't changed.
  // Returning a primitive (number) also safely avoids the React 19 infinite render
  // loop caused by returning freshly-allocated arrays from selectors.
  const pendingCount = useApprovalStore((state) =>
    Object.values(state.approvals).filter(a => a.status === 'pending').length
  );

  return (
    <div className={`flex items-center gap-2 px-3 py-1.5 rounded-md border transition-colors ${pendingCount > 0 ? 'bg-amber-500/10 border-amber-500/20' : 'bg-zinc-900/60 border-zinc-800/60'}`}>
      <div className={`w-2 h-2 rounded-full ${pendingCount > 0 ? 'bg-amber-500' : 'bg-zinc-600'}`} />
      <span className="text-sm font-medium text-zinc-300">Inbox <span className="text-zinc-500 font-mono text-xs">({pendingCount})</span></span>
    </div>
  );
}
