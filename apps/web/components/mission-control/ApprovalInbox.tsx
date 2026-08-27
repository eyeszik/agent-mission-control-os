"use client";

import { useApprovalStore } from '../../lib/stores/approvalStore';

export function ApprovalInbox() {
  // Optimization: Select the primitive count directly. Zustand uses Object.is for
  // equality checks, so returning a number prevents unnecessary re-renders when
  // non-pending approvals update.
  const pendingCount = useApprovalStore((state) => Object.values(state.approvals).filter(a => a.status === 'pending').length);

  return (
    <div className={`flex items-center gap-2 px-3 py-1.5 rounded-md border transition-colors ${pendingCount > 0 ? 'bg-amber-500/10 border-amber-500/20' : 'bg-zinc-900/60 border-zinc-800/60'}`}>
      <div className={`w-2 h-2 rounded-full ${pendingCount > 0 ? 'bg-amber-500' : 'bg-zinc-600'}`} />
      <span className="text-sm font-medium text-zinc-300">Inbox <span className="text-zinc-500 font-mono text-xs">({pendingCount})</span></span>
    </div>
  );
}
