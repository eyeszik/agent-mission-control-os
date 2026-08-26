## 2026-08-20 - Zustand derived state rendering optimization
**Learning:** Returning freshly allocated arrays such as `Object.values(state.approvals)` from a Zustand selector can trigger unnecessary React re-renders and, with React 19/useSyncExternalStore, can contribute to update loops.
**Resolution:** The agency branch selects the stable `approvals` record and derives arrays/counts during render. `useShallow` is also valid when a selector must return derived arrays/objects; prefer the smallest selector that preserves stable equality semantics.

## 2024-05-18 - Zustand Array Derivation Optimization
**Learning:** Extracting an entire array from a Zustand store (`state.items`) and applying `.find()` during component render causes unnecessary re-renders whenever the array's reference changes (e.g., when a new item is added), even if the found item itself hasn't changed.
**Action:** Compute derived state (like a specific item using `.find()`) directly inside the Zustand selector so the component only re-renders if the actual selected item changes.
