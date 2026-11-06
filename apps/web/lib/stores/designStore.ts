import { create } from 'zustand';
import type { DesignStyleSelection } from '@amc/shared';

// The style direction attached in Design Mode, sent as `style_selection` with
// the next agency run. The backend recomposes it against the catalog, so this
// store only carries the designer's selection and the composition it produced.
export interface AttachedStyleDirection {
  selection: DesignStyleSelection;
  compositionId: string;
  // Short human label, e.g. "Bauhaus + Tenebrism".
  label: string;
}

interface DesignState {
  attached: AttachedStyleDirection | null;
  attach: (direction: AttachedStyleDirection) => void;
  detach: () => void;
}

export const useDesignStore = create<DesignState>((set) => ({
  attached: null,
  attach: (direction) => set({ attached: direction }),
  detach: () => set({ attached: null }),
}));
