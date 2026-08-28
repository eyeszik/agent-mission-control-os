## 2026-08-20 - Zustand derived state rendering optimization
**Learning:** Returning freshly allocated arrays such as `Object.values(state.approvals)` from a Zustand selector can trigger unnecessary React re-renders and, with React 19/useSyncExternalStore, can contribute to update loops.
**Resolution:** The agency branch selects the stable `approvals` record and derives arrays/counts during render. `useShallow` is also valid when a selector must return derived arrays/objects; prefer the smallest selector that preserves stable equality semantics.
## 2026-08-28 - Zustand derived state returning object instances avoids re-renders
**Learning:** If a component only needs a single object from an array in a Zustand store, computing the `.find()` inside the selector returns the same object reference on subsequent store updates (like adding new items to the array), preventing unnecessary React re-renders.
**Action:** Move single-item derived queries (like `.find()`) inside the Zustand selector instead of returning the full array and computing it in the component body.
