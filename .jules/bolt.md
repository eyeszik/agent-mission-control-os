## 2024-06-25 - React Component Re-render optimization
**Learning:** Zustand selectors mapping large objects like `approvals` trigger re-renders even when the derived state (`pendingCount`) remains unchanged. Using `useShallow` with complex objects and scalar specific selections prevents unnecessary component re-renders.
**Action:** Always prefer selecting scalar values directly in Zustand selectors. For object/array returns, wrap them with `useShallow` when the derived object has the same structure but new references.
