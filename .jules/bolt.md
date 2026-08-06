## 2024-05-18 - Zustand Selector Array Creation Anti-Pattern
**Learning:** Using `Object.values()` or `.filter()` directly inside a Zustand selector without `useShallow` or returning a primitive causes unnecessary re-renders on every store update, because the selector returns a new reference every time.
**Action:** Always return primitives (like counts) from selectors when only a count is needed. For derived arrays, use `useShallow` from `zustand/react/shallow` to preserve reference equality when the array contents haven't changed.
