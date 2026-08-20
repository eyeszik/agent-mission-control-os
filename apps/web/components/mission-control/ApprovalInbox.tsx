"use client";

import { useShallow } from 'zustand/react/shallow';
import { useApprovalStore } from '../../lib/stores/approvalStore';

export function ApprovalInbox() {
  // ⚡ Bolt: Use useShallow to prevent unnecessary re-renders when returning derived arrays
  const approvals = useApprovalStore(useShallow((state) => Object.values(state.approvals)));
  const pendingCount = approvals.filter(a => a.status === 'pending').length;

  return (
    <div className={`flex items-center gap-2 px-3 py-1.5 rounded-md border transition-colors ${pendingCount > 0 ? 'bg-amber-500/10 border-amber-500/20' : 'bg-zinc-900/60 border-zinc-800/60'}`}>
      <div className={`w-2 h-2 rounded-full ${pendingCount > 0 ? 'bg-amber-500' : 'bg-zinc-600'}`} />
      <span className="text-sm font-medium text-zinc-300">Inbox <span className="text-zinc-500 font-mono text-xs">({pendingCount})</span></span>
    </div>
  );
}
