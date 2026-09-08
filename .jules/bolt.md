## 2026-08-20 - Zustand derived state rendering optimization
**Learning:** Returning freshly allocated arrays such as `Object.values(state.approvals)` from a Zustand selector can trigger unnecessary React re-renders and, with React 19/useSyncExternalStore, can contribute to update loops.
**Resolution:** The agency branch selects the stable `approvals` record and derives arrays/counts during render. `useShallow` is also valid when a selector must return derived arrays/objects; prefer the smallest selector that preserves stable equality semantics.
## 2026-08-21 - Zustand Primitive Selector Optimization
**Learning:** Selecting a full object in Zustand just to compute a primitive like `.length` in the component causes unnecessary re-renders.
**Action:** Compute and return the primitive value directly inside the selector.
## 2026-09-08 - Hoist Static Layout Collections
**Learning:** Arrays, slice iterations, and math logic based entirely on constants inside React components causes unnecessary memory allocation on every single update cycle.
**Action:** Move entirely static mapping, slice objects, and layout dimensions outside the React function body.
