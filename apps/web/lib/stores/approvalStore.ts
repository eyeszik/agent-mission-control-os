import { create } from 'zustand';
import type { ApprovalRequest } from '@amc/shared';

interface ApprovalState {
  approvals: Record<string, ApprovalRequest>; // id -> request
  upsertApproval: (req: ApprovalRequest) => void;
  removeApproval: (id: string) => void;
}

export const useApprovalStore = create<ApprovalState>((set) => ({
  approvals: {},
  upsertApproval: (req) => set((state) => ({
    approvals: { ...state.approvals, [req.id]: req }
  })),
  removeApproval: (id) => set((state) => {
    const next = { ...state.approvals };
    delete next[id];
    return { approvals: next };
  }),
}));
