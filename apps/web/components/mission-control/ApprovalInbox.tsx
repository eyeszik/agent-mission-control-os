"use client";

import { useApprovalStore } from '../../lib/stores/approvalStore';

export function ApprovalInbox() {
  // ⚡ Bolt: Optimize by selecting only the length instead of mapping entire object and filtering array on every render.
  // 🎯 Why: Returning an array from Object.values creates a new array instance on every store update, triggering re-renders even when the pending count is unchanged.
  // 📊 Impact: O(1) selector derived value prevents unnecessary re-renders of the ApprovalInbox component whenever non-pending approvals are added/removed.
  const pendingCount = useApprovalStore((state) => {
    let count = 0;
    for (const key in state.approvals) {
      if (state.approvals[key].status === 'pending') count++;
    }
    return count;
  });

  return (
    <div className={`flex items-center gap-2 px-3 py-1.5 rounded-md border transition-colors ${pendingCount > 0 ? 'bg-amber-500/10 border-amber-500/20' : 'bg-zinc-900/60 border-zinc-800/60'}`}>
      <div className={`w-2 h-2 rounded-full ${pendingCount > 0 ? 'bg-amber-500' : 'bg-zinc-600'}`} />
      <span className="text-sm font-medium text-zinc-300">Inbox <span className="text-zinc-500 font-mono text-xs">({pendingCount})</span></span>
    </div>
  );
}
