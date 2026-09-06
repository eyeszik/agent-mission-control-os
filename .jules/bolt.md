## 2026-08-20 - Zustand derived state rendering optimization
**Learning:** Returning freshly allocated arrays such as `Object.values(state.approvals)` from a Zustand selector can trigger unnecessary React re-renders and, with React 19/useSyncExternalStore, can contribute to update loops.
**Resolution:** The agency branch selects the stable `approvals` record and derives arrays/counts during render. `useShallow` is also valid when a selector must return derived arrays/objects; prefer the smallest selector that preserves stable equality semantics.
## 2026-08-21 - Zustand Primitive Selector Optimization
**Learning:** Selecting a full object in Zustand just to compute a primitive like `.length` in the component causes unnecessary re-renders.
**Action:** Compute and return the primitive value directly inside the selector.

## 2026-09-06 - Static Layout Hoisting
**Learning:** Computing layout maps (like `positions`, `width`, `height`) based entirely on constants inside a React component creates unnecessary memory allocation and garbage collection on every render.
**Action:** Hoist static layout calculations, arrays, and coordinate math derived solely from constants outside of React components.
