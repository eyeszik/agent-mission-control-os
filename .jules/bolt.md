## 2026-08-20 - Zustand derived state rendering optimization
**Learning:** Returning freshly allocated arrays such as `Object.values(state.approvals)` from a Zustand selector can trigger unnecessary React re-renders and, with React 19/useSyncExternalStore, can contribute to update loops.
**Resolution:** The agency branch selects the stable `approvals` record and derives arrays/counts during render. `useShallow` is also valid when a selector must return derived arrays/objects; prefer the smallest selector that preserves stable equality semantics.
## 2026-08-20 - Zustand selector optimization for array operations
**Learning:** Moving `.filter().length` and `.find()` operations inside Zustand selectors returns primitive types (number) or stable references (single object), which leverage Zustand's default `Object.is` equality check to prevent unnecessary re-renders in components when other unrelated parts of the store update.
**Action:** When deriving single values or finding specific objects from collections in Zustand stores, compute them inside the selector instead of selecting the whole collection and computing in the component.
