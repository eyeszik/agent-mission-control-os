## 2024-05-24 - Zustand Selector Optimization
**Learning:** Returning derived arrays or objects (like `Object.values(state.approvals)`) in Zustand selectors causes unnecessary re-renders on every store update because Zustand uses `Object.is` for equality checks by default.
**Action:** Always return primitives if only primitive values (like `.length`) are needed, or use `useShallow` from `zustand/react/shallow` when returning derived objects/arrays to prevent unnecessary React re-renders.
