## 2026-08-20 - Zustand derived state rendering optimization
**Learning:** Returning freshly allocated arrays such as `Object.values(state.approvals)` from a Zustand selector can trigger unnecessary React re-renders and, with React 19/useSyncExternalStore, can contribute to update loops.
**Resolution:** The agency branch selects the stable `approvals` record and derives arrays/counts during render. `useShallow` is also valid when a selector must return derived arrays/objects; prefer the smallest selector that preserves stable equality semantics.

## 2026-09-01 - Render Loop Extraction
**Learning:** In React components like WorkflowMapPanel, iterating over constant arrays to calculate positions (e.g. mapping grid coordinates) inside the render loop causes unnecessary recalculations and object allocations on every render.
**Action:** Move static layout calculations (like grid position objects) outside of the component scope into constant variables when the data they depend on is static, reducing render-time overhead.
