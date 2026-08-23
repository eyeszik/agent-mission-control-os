## 2026-08-20 - Zustand derived state rendering optimization
**Learning:** Returning freshly allocated arrays such as `Object.values(state.approvals)` from a Zustand selector can trigger unnecessary React re-renders and, with React 19/useSyncExternalStore, can contribute to update loops.
**Resolution:** The agency branch selects the stable `approvals` record and derives arrays/counts during render. `useShallow` is also valid when a selector must return derived arrays/objects; prefer the smallest selector that preserves stable equality semantics.

## 2023-10-27 - Optimizing Zustand Derived State Selectors
**Learning:** Returning array literals, `.filter()`, or `.map()` directly from a Zustand selector allocates a new reference on every call, defeating `useSyncExternalStore`'s default `Object.is` equality check and causing unnecessary component re-renders (and sometimes infinite loops in React 19).
**Action:** Compute derived state primitives directly in the selector, or use `useShallow` from `zustand/react/shallow` when returning arrays/objects to ensure re-renders only occur when the actual shallow values change.
