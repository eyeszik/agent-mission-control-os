## 2026-08-20 - Zustand derived state rendering optimization
**Learning:** Returning freshly allocated arrays such as `Object.values(state.approvals)` from a Zustand selector can trigger unnecessary React re-renders and, with React 19/useSyncExternalStore, can contribute to update loops.
**Resolution:** The agency branch selects the stable `approvals` record and derives arrays/counts during render. `useShallow` is also valid when a selector must return derived arrays/objects; prefer the smallest selector that preserves stable equality semantics.

## 2026-08-21 - Derived primitives and static array setup optimization
**Learning:** Returning fresh array mappings or computing values off unoptimized Zustand store selectors (like arrays, lists, records where only one object inside changes) can trigger component re-renders that lead to infinite update loops or sluggish interaction.
**Action:** Always compute derived states (like `.length` or `.find()`) inside the Zustand selector so it returns a primitive or stable object, rather than deriving it during render. In NextJS functional components, make sure static mapping variables that don't depend on states or props are hoisted out of the render loop.
