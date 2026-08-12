## 2023-10-24 - Zustand Selectors and Re-renders
**Learning:** Returning arrays or objects from Zustand selectors causes unnecessary React component re-renders on every store update because it creates a new reference.
**Action:** Compute primitives (like `.length`) directly inside the selector or wrap the selector in `useShallow` from `zustand/react/shallow` for arrays/objects.
