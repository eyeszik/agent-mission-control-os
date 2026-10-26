import { create } from 'zustand';

// Agency OS navigation and selection. Components select single primitives.
export type AgencySection =
  | 'overview' | 'clients' | 'projects' | 'missions' | 'council' | 'framework' | 'websites' | 'visuals' | 'studio' | 'approvals' | 'deliverables' | 'analytics' | 'integrations' | 'settings';

export type Inspected = { kind: 'action'; id: string } | { kind: 'approval'; id: string } | null;

interface AgencyState {
  section: AgencySection;
  projectId: string | null;
  clientId: string | null;
  inspected: Inspected;
  paletteOpen: boolean;
  navOpen: boolean;
  refreshTick: number;
  setSection: (section: AgencySection) => void;
  setProject: (projectId: string | null) => void;
  setClient: (clientId: string | null) => void;
  inspect: (target: Inspected) => void;
  setPaletteOpen: (open: boolean) => void;
  setNavOpen: (open: boolean) => void;
  refresh: () => void;
}

export const useAgencyStore = create<AgencyState>((set) => ({
  section: 'overview',
  projectId: null,
  clientId: null,
  inspected: null,
  paletteOpen: false,
  navOpen: false,
  refreshTick: 0,
  setSection: (section) => set({ section, navOpen: false }),
  setProject: (projectId) => set((s) => (s.projectId === projectId ? s : { projectId })),
  setClient: (clientId) => set({ clientId }),
  inspect: (inspected) => set({ inspected }),
  setPaletteOpen: (paletteOpen) => set({ paletteOpen }),
  setNavOpen: (navOpen) => set({ navOpen }),
  refresh: () => set((s) => ({ refreshTick: s.refreshTick + 1 })),
}));
