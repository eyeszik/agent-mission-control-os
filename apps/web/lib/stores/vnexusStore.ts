import { create } from 'zustand';
import type { VnexusScope } from '@amc/shared';

// Which brand and scope the VNEXUS studio is working on, and which area is
// open. Components select single primitives from this store.
export type VnexusArea =
  | 'overview' | 'genome' | 'history' | 'graph' | 'multiverse' | 'experience' | 'art' | 'graphic' | 'brandbook' | 'video'
  | 'marketing' | 'prompts' | 'jobs' | 'immune' | 'governance';

interface VnexusState {
  brandId: string | null;
  scope: VnexusScope;
  scopeRef: string;
  area: VnexusArea;
  setBrand: (brandId: string | null) => void;
  setScope: (scope: VnexusScope, scopeRef: string) => void;
  setArea: (area: VnexusArea) => void;
}

export const useVnexusStore = create<VnexusState>((set) => ({
  brandId: null,
  scope: 'brand',
  scopeRef: '',
  area: 'overview',
  setBrand: (brandId) => set((s) => (s.brandId === brandId ? s : { brandId, scope: 'brand', scopeRef: brandId ?? '' })),
  setScope: (scope, scopeRef) => set({ scope, scopeRef }),
  setArea: (area) => set({ area }),
}));
