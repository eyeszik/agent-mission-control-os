## 2026-08-20 - Zustand derived state rendering optimization
**Learning:** Returning freshly allocated arrays such as `Object.values(state.approvals)` from a Zustand selector can trigger unnecessary React re-renders and, with React 19/useSyncExternalStore, can contribute to update loops.
**Resolution:** The agency branch selects the stable `approvals` record and derives arrays/counts during render. `useShallow` is also valid when a selector must return derived arrays/objects; prefer the smallest selector that preserves stable equality semantics.
## 2026-08-21 - Zustand Primitive Selector Optimization
**Learning:** Selecting a full object in Zustand just to compute a primitive like `.length` in the component causes unnecessary re-renders.
**Action:** Compute and return the primitive value directly inside the selector.
## 2026-08-22 - Static Calculations Outside Render Loop
**Learning:** Computing static layout values or arrays (e.g., node positions and SVG dimensions derived from constant workflow stages) inside a React component's render body causes unnecessary redundant calculations and allocates new object/array references on every render.
**Action:** Move static data mappings and derived calculations outside of the component render function so they are only evaluated once at module load time.
## 2026-08-23 - Subscribing Child Components to Specific Dictionary Keys
**Learning:** Selecting a full dictionary (e.g. state.statuses[activeRunId]) in a parent component to render a list or graph causes the parent and all siblings to re-render whenever any single item in the dictionary changes.
**Action:** Extract items into individual child components that subscribe directly to their specific keys in the Zustand store to prevent unnecessary parent and sibling re-renders.
