"use client";

import { useApprovalStore } from '../../lib/stores/approvalStore';
import { useShallow } from 'zustand/react/shallow';

export function ApprovalInbox() {
  // ⚡ Bolt: using useShallow to prevent unnecessary re-renders when approvals are added/removed
  // Prevents re-rendering when the derived array reference changes but contents are shallowly equal.
  const approvals = useApprovalStore(useShallow((state) => Object.values(state.approvals)));
  const pendingCount = approvals.filter(a => a.status === 'pending').length;

  return (
    <div className={`flex items-center gap-2 px-3 py-1.5 rounded-md border transition-colors ${pendingCount > 0 ? 'bg-amber-500/10 border-amber-500/20' : 'bg-zinc-900/60 border-zinc-800/60'}`}>
      <div className={`w-2 h-2 rounded-full ${pendingCount > 0 ? 'bg-amber-500' : 'bg-zinc-600'}`} />
      <span className="text-sm font-medium text-zinc-300">Inbox <span className="text-zinc-500 font-mono text-xs">({pendingCount})</span></span>
    </div>
  );
}
