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
## 2026-08-25 - React Hook Rules for Expensive Derived State
**Learning:** Placing hooks like `useMemo` after conditional early returns violates React's Rules of Hooks. When components derive expensive layout arrays from remote state using maps/filters, they must be wrapped in `useMemo` before any early return to prevent unneeded garbage collection on unrelated local state updates. Handle null checks directly inside the hook.
**Action:** Always declare all `useMemo` hooks at the top level of the component before early returns. If derived values depend on potentially null objects, safely handle the null checks inside the `useMemo` calculation logic and return dummy/empty arrays.
## 2026-10-24 - Zustand Zero-Allocation Selectors
**Learning:** Using `Object.values().filter()` inside Zustand selectors creates unnecessary intermediate arrays on every state update, leading to excessive garbage collection overhead.
**Action:** Replace these chains with a zero-allocation or single-allocation `for...in` loop within the selector.
## 2026-10-25 - React Component Derived Metrics Rendering Optimization
**Learning:** Returning freshly allocated arrays merely to determine their lengths, via patterns like `array.filter().length` inline in React functional component renders, triggers redundant garbage collection loops during state updates.
**Action:** Derived counting should be precomputed efficiently (via `reduce` or loops) within `useMemo` blocks and returned as primitives (e.g. integer counts). This avoids allocating and traversing throwaway arrays during the render cycle.
## 2026-10-26 - React Component Inline Filter Map Optimization
**Learning:** Chaining `.filter().map()` on arrays inside a React functional component render body allocates an intermediate array on every render, causing unnecessary garbage collection pressure and degraded performance.
**Action:** Remove the `.filter()` step and map directly over the array, conditionally returning `null` early for items that should be filtered out. React natively ignores `null` elements during rendering with zero allocation penalty.
## 2026-10-27 - React Component Zero-Allocation Aggregation
**Learning:** Using `Object.values().reduce()` to aggregate or sum object values inside a React functional component render body allocates an intermediate array on every render, causing unnecessary garbage collection pressure and degraded performance.
**Action:** Replace `Object.values().reduce()` with a zero-allocation `for...in` loop. Always include a `.hasOwnProperty()` check within the loop to avoid iterating over inherited prototype properties.
## 2026-10-28 - Composer Array Length Check Optimization
**Learning:** Checking the presence of multiple specific elements in an array using `.filter(condition).length > 1` forces the allocation of an intermediate array which creates unnecessary GC pressure.
**Action:** Replace `.filter(condition).length` with a zero-allocation `.reduce()` count.
## 2026-10-29 - O(N) Array Iteration Optimization
**Learning:** Running four separate passes over an array (using `.reduce()` and `.filter().length`) performs redundant iterations and allocates unnecessary intermediate filtered arrays, causing increased GC pressure.
**Action:** Replace multiple passes with a single `for...of` loop or `.reduce()` to compute multiple aggregations simultaneously.
## 2026-10-30 - React Component Inline Filter Map Optimization in Component Render
**Learning:** Extracting an intermediate filtered array via `artifacts.filter()` inside a functional component's render body, and then mapping over it, forces a new array allocation on every single render cycle. This increases memory pressure and garbage collection overhead unnecessarily.
**Action:** Replace chains like `.filter(condition).map(render)` with a single `.map(item => condition(item) ? render(item) : null)` inside the render body. React natively ignores `null` nodes without rendering empty DOM wrappers, enabling zero-allocation conditional rendering.
