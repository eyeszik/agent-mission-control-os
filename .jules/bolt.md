## 2024-08-18 - Zustand Array Return Re-renders
**Learning:** Returning dynamically generated arrays (like from `Object.values().filter()`) from Zustand selectors causes unnecessary re-renders whenever the store updates, even if the underlying values haven't fundamentally changed, because the reference is always new.
**Action:** Compute primitives directly in the selector (e.g., return `.length`) or use `useShallow` from `zustand/react/shallow` to shallowly compare returned arrays or objects.
