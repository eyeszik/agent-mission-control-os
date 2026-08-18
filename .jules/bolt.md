## 2024-08-15 - Zustand Selectors Returning Derived Arrays/Objects
**Learning:** Returning dynamically created arrays (e.g., `Object.values(state)`) or finding objects inside a component from a general state slice in Zustand causes the component to re-render on *every* store update, even if the relevant data hasn't changed.
**Action:** Compute derived state (like `.length` or `.find()`) directly inside the Zustand selector, or use `useShallow` from `zustand/react/shallow` when returning arrays/objects to prevent unnecessary React component re-renders.
