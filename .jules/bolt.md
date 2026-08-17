## 2024-10-27 - Zustand Selectors Returning Arrays Break Equality
**Learning:** Returning arrays (e.g., `Object.values(state.approvals)`) or filtering arrays inside a Zustand `useStore` selector breaks the default strict equality check, causing components to re-render on *every* store update, even if the relevant data hasn't changed.
**Action:** Compute derived state directly inside the selector (e.g., `.length`, `.find()`) or use `useShallow` from `zustand/react/shallow` when returning arrays or objects to prevent unnecessary React component re-renders.
