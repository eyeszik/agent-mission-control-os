"use client";

import { useShallow } from 'zustand/react/shallow';
import { useArtifactStore } from '../../lib/stores/artifactStore';
import { useRunStore } from '../../lib/stores/runStore';
import { useApprovalStore } from '../../lib/stores/approvalStore';

export function ArtifactPreviewPanel() {
  const activeRunId = useRunStore((state) => state.activeRunId);

  // ⚡ Bolt: Optimize selectors to only trigger re-renders when the actual selected artifact changes
  // rather than any time ANY artifact is added to the active run
  const selectedArtifactId = useArtifactStore((state) => state.selectedArtifactId);
  const selectedArtifact = useArtifactStore((state) => {
    if (!activeRunId || !selectedArtifactId) return null;
    const runArtifacts = state.artifacts[activeRunId];
    return runArtifacts ? runArtifacts.find(a => a.id === selectedArtifactId) : null;
  });
  
  // ⚡ Bolt: Use useShallow to prevent re-renders when pending approvals list is structurally identical
  const pendingApprovals = useApprovalStore(
    useShallow((state) => Object.values(state.approvals).filter(a => a.status === 'pending'))
  );
  const removeApproval = useApprovalStore((state) => state.removeApproval); 

  const handleResolve = (id: string, action: 'approved' | 'rejected') => {
    // In a real implementation this would call the resolveApproval API via api/approvals.ts
    // For now we optimistically remove it from the UI inbox
    removeApproval(id);
  };

  return (
    <div className="h-full p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between pb-2 border-b border-zinc-800/50">
        <span className="text-xs font-mono text-zinc-500 uppercase tracking-wider">Inspector</span>
        {selectedArtifact && <span className="text-xs bg-zinc-800 px-2 py-0.5 rounded text-zinc-400 font-mono">{selectedArtifact.type}</span>}
      </div>
      
      <div className="flex-1 overflow-y-auto">
        {selectedArtifact ? (
          <div className="text-sm text-zinc-300 whitespace-pre-wrap font-mono bg-zinc-950/50 p-4 rounded-lg border border-zinc-800/60 overflow-x-auto">
            {selectedArtifact.content}
          </div>
        ) : pendingApprovals.length > 0 ? (
          <div className="flex flex-col gap-3">
            <h3 className="text-sm font-medium text-amber-500 mb-2">Pending Approvals</h3>
            {pendingApprovals.map(approval => (
              <div key={approval.id} className="bg-amber-500/10 border border-amber-500/20 rounded-lg p-4">
                <p className="text-sm text-zinc-200 mb-1">{approval.description}</p>
                <p className="text-xs text-zinc-500 mb-4 font-mono">Action: {approval.action_type}</p>
                <div className="flex gap-2">
                  <button 
                    onClick={() => handleResolve(approval.id, 'approved')}
                    className="px-3 py-1.5 bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30 border border-emerald-500/30 rounded text-xs font-medium transition-colors"
                  >
                    Approve
                  </button>
                  <button 
                    onClick={() => handleResolve(approval.id, 'rejected')}
                    className="px-3 py-1.5 bg-red-500/20 text-red-400 hover:bg-red-500/30 border border-red-500/30 rounded text-xs font-medium transition-colors"
                  >
                    Reject
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="h-full flex items-center justify-center opacity-30">
            <p className="text-xs text-zinc-600 font-mono">No artifact selected</p>
          </div>
        )}
      </div>
    </div>
  );
}
