import { create } from 'zustand';

interface SessionState {
  userId: string | null;
  tenantId: string | null;
  roles: string[];
  setSession: (userId: string, tenantId: string, roles: string[]) => void;
  clearSession: () => void;
}

export const useSessionStore = create<SessionState>((set) => ({
  userId: null,
  tenantId: null,
  roles: [],
  setSession: (userId, tenantId, roles) => set({ userId, tenantId, roles }),
  clearSession: () => set({ userId: null, tenantId: null, roles: [] }),
}));
