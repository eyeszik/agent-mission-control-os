## 2026-08-20 - Zustand derived state rendering optimization
**Learning:** Returning arrays via `Object.values(state.approvals)` or `state.approvals.filter()` inside a Zustand selector causes unnecessary React re-renders on every store update, even if the result array is conceptually the same, because a new array reference is created every time.
**Action:** Use `useShallow` from `zustand/react/shallow` when returning arrays, objects, or computing derived state in Zustand selectors to ensure components only re-render when the actual content changes.
