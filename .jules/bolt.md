## 2026-08-20 - Zustand derived state rendering optimization
**Learning:** Returning freshly allocated arrays such as `Object.values(state.approvals)` from a Zustand selector can trigger unnecessary React re-renders and, with React 19/useSyncExternalStore, can contribute to update loops.
**Resolution:** The agency branch selects the stable `approvals` record and derives arrays/counts during render. `useShallow` is also valid when a selector must return derived arrays/objects; prefer the smallest selector that preserves stable equality semantics.
## 2026-08-20 - Zustand selector derived state directly
**Learning:** Derived state, like `.length` on arrays or `.find()` operations, can be performed directly inside the Zustand selector to prevent unnecessary React re-renders, rather than calculating it in the component body after pulling the entire object. This allows components to subscribe only to specific primitive values or specific item references.
**Action:** When a component only needs derived data from a large map/array, compute it inside the selector (e.g. `useStore(state => Object.values(state.items).filter(...).length)`).
