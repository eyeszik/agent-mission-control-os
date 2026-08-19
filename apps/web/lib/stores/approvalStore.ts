import { create } from 'zustand';
import type { ApprovalRequest } from '@amc/shared';

interface ApprovalState {
  approvals: Record<string, ApprovalRequest>; // approval_id -> request
  upsertApproval: (req: ApprovalRequest) => void;
  removeApproval: (approvalId: string) => void;
  setApprovals: (reqs: ApprovalRequest[]) => void;
}

export const useApprovalStore = create<ApprovalState>((set) => ({
  approvals: {},
  upsertApproval: (req) => set((state) => ({
    approvals: { ...state.approvals, [req.approval_id]: req }
  })),
  removeApproval: (approvalId) => set((state) => {
    const next = { ...state.approvals };
    delete next[approvalId];
    return { approvals: next };
  }),
  setApprovals: (reqs) => set((state) => {
    const next = { ...state.approvals };
    for (const req of reqs) next[req.approval_id] = req;
    return { approvals: next };
  }),
}));
