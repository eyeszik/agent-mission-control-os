## 2024-08-10 - Zustand State Derivation Re-Renders
**Learning:** Returning array filter results directly from Zustand selectors in React components causes unnecessary re-renders on every store update because array methods (`.filter()`, `.map()`) create new array references.
**Action:** Extract the count directly in the selector if only the length is needed (`(state) => ...length`), or use `useShallow` from `zustand/react/shallow` to wrap the selector when returning arrays/objects so the component only re-renders when the shallow contents change.
