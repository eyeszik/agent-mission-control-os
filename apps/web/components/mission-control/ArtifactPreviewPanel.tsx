"use client";

import { useState } from 'react';
import { useArtifactStore } from '../../lib/stores/artifactStore';
import { useRunStore } from '../../lib/stores/runStore';
import { useApprovalStore } from '../../lib/stores/approvalStore';
import { useShallow } from 'zustand/react/shallow';
import { resolveApproval } from '../../lib/api/approvals';
import { resumeAgencyRun } from '../../lib/api/agency';
import { useNodeStatusStore } from '../../lib/stores/nodeStatusStore';
import { generateIdempotencyKey } from '../../lib/utils/idempotency';

export function ArtifactPreviewPanel() {
  const activeRunId = useRunStore((state) => state.activeRunId);

  // Optimization: Compute derived state (.find()) directly inside the selector.
  // This prevents the component from re-rendering every time ANY artifact is added
  // to the active run. It will now only re-render if the selected artifact itself changes.
  const selectedArtifact = useArtifactStore((state) => {
    if (!activeRunId || !state.selectedArtifactId) return null;
    const runArtifacts = state.artifacts[activeRunId];
    return runArtifacts ? runArtifacts.find(a => a.id === state.selectedArtifactId) || null : null;
  });
  const addArtifact = useArtifactStore((state) => state.addArtifact);

  // Optimization: useShallow prevents unnecessary re-renders by returning the same
  // array reference if the content of pendingApprovals hasn't structurally changed,
  // even if other non-pending approvals update in the record.
  const pendingApprovals = useApprovalStore(useShallow((state) => Object.values(state.approvals).filter(a => a.status === 'pending')));
  const removeApproval = useApprovalStore((state) => state.removeApproval);
  const updateNodeStatus = useNodeStatusStore((state) => state.updateNodeStatus);

  const [resolvingId, setResolvingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleResolve = async (approvalId: string, runId: string, decision: 'approve' | 'reject') => {
    setResolvingId(approvalId);
    setError(null);
    try {
      await resolveApproval(approvalId, decision, generateIdempotencyKey());

      if (decision === 'approve') {
        const resumed = await resumeAgencyRun(runId, generateIdempotencyKey());
        updateNodeStatus(runId, 'hitl_gate', 'completed');
        if (resumed.delivery) {
          updateNodeStatus(runId, 'delivery', 'completed');
          addArtifact(runId, {
            id: crypto.randomUUID(),
            run_id: runId,
            node_id: 'delivery',
            type: 'document',
            content: JSON.stringify(resumed.delivery, null, 2),
            created_at: resumed.delivery.delivered_at,
          });
        }
      }

      removeApproval(approvalId);
    } catch (err) {
      console.error('Failed to resolve approval', err);
      setError(err instanceof Error ? err.message : 'Failed to resolve approval');
    } finally {
      setResolvingId(null);
    }
  };

  return (
    <div className="h-full p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between pb-2 border-b border-zinc-800/50">
        <span className="text-xs font-mono text-zinc-500 uppercase tracking-wider">Inspector</span>
        {selectedArtifact && <span className="text-xs bg-zinc-800 px-2 py-0.5 rounded text-zinc-400 font-mono">{selectedArtifact.type}</span>}
      </div>

      {error && (
        <div className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded px-3 py-2">{error}</div>
      )}

      <div className="flex-1 overflow-y-auto">
        {selectedArtifact ? (
          <div className="text-sm text-zinc-300 whitespace-pre-wrap font-mono bg-zinc-950/50 p-4 rounded-lg border border-zinc-800/60 overflow-x-auto">
            {selectedArtifact.content}
          </div>
        ) : pendingApprovals.length > 0 ? (
          <div className="flex flex-col gap-3">
            <h3 className="text-sm font-medium text-amber-500 mb-2">Pending Approvals</h3>
            {pendingApprovals.map(approval => {
              const isResolving = resolvingId === approval.approval_id;
              return (
                <div key={approval.approval_id} className="bg-amber-500/10 border border-amber-500/20 rounded-lg p-4">
                  <p className="text-sm text-zinc-200 mb-1">{approval.reason}</p>
                  <p className="text-xs text-zinc-500 mb-4 font-mono">
                    run {approval.run_id.slice(0, 8)} · confidence {approval.confidence != null ? approval.confidence.toFixed(2) : 'n/a'}
                  </p>
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleResolve(approval.approval_id, approval.run_id, 'approve')}
                      disabled={isResolving}
                      className="px-3 py-1.5 bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30 border border-emerald-500/30 rounded text-xs font-medium transition-colors disabled:opacity-50"
                    >
                      {isResolving ? 'Working…' : 'Approve'}
                    </button>
                    <button
                      onClick={() => handleResolve(approval.approval_id, approval.run_id, 'reject')}
                      disabled={isResolving}
                      className="px-3 py-1.5 bg-red-500/20 text-red-400 hover:bg-red-500/30 border border-red-500/30 rounded text-xs font-medium transition-colors disabled:opacity-50"
                    >
                      {isResolving ? 'Working…' : 'Reject'}
                    </button>
                  </div>
                </div>
              );
            })}
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
