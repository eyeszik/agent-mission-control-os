## 2026-08-20 - Zustand derived state rendering optimization
**Learning:** Returning freshly allocated arrays such as `Object.values(state.approvals)` from a Zustand selector can trigger unnecessary React re-renders and, with React 19/useSyncExternalStore, can contribute to update loops.
**Resolution:** The agency branch selects the stable `approvals` record and derives arrays/counts during render. `useShallow` is also valid when a selector must return derived arrays/objects; prefer the smallest selector that preserves stable equality semantics.

## 2024-05-18 - Zustand primitive selectors
**Learning:** Returning a primitive value (like a count) directly from a Zustand selector prevents React components from re-rendering unless that exact value changes. Using a selector that returns an object/array, even if stable initially, can trigger renders when deep fields change.
**Action:** When computing counts or finding specific items in a store, extract that primitive directly in the Zustand `useStore(state => ...)` call to maximize rendering performance without needing `useShallow`.
