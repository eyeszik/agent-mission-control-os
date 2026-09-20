## 2026-08-20 - Zustand derived state rendering optimization
**Learning:** Returning freshly allocated arrays such as `Object.values(state.approvals)` from a Zustand selector can trigger unnecessary React re-renders and, with React 19/useSyncExternalStore, can contribute to update loops.
**Resolution:** The agency branch selects the stable `approvals` record and derives arrays/counts during render. `useShallow` is also valid when a selector must return derived arrays/objects; prefer the smallest selector that preserves stable equality semantics.
## 2026-08-21 - Zustand Primitive Selector Optimization
**Learning:** Selecting a full object in Zustand just to compute a primitive like `.length` in the component causes unnecessary re-renders.
**Action:** Compute and return the primitive value directly inside the selector.
## 2026-08-22 - Static Calculations Outside Render Loop
**Learning:** Computing static layout values or arrays (e.g., node positions and SVG dimensions derived from constant workflow stages) inside a React component's render body causes unnecessary redundant calculations and allocates new object/array references on every render.
**Action:** Move static data mappings and derived calculations outside of the component render function so they are only evaluated once at module load time.
## 2026-08-23 - Zustand List Item Subscription Optimization
**Learning:** Rendering lists or graphs from a Zustand store dictionary directly in a parent component (e.g., subscribing to the entire `statuses` object) causes the parent and all siblings to re-render whenever a single item updates.
**Action:** Extract list items into individual child components that subscribe directly to their specific keys in the Zustand store to prevent O(N) parent re-renders.
## 2026-08-24 - Zustand List Item Selection Optimization
**Learning:** Re-rendering an entire list component solely because the selected item ID changed in a Zustand store causes O(N) re-renders, wasting CPU cycles on items whose state hasn't changed.
**Action:** Extract list items into their own components and subscribe them directly to a boolean Zustand selector (`state.selectedId === item.id`). This ensures only the newly selected and previously selected items re-render.
## 2026-08-25 - Expensive derived state in render
**Learning:** Re-calculating expensive arrays, slices, maps, and filters inside a component render function on every update can cause unnecessary garbage collection and performance degradation.
**Action:** Wrap complex map/filter chains and array construction logic in a `useMemo` block with appropriate dependencies to avoid re-evaluating them when unrelated state updates trigger a re-render.
