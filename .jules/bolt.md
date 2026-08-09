## 2024-03-24 - Zustand derived state
**Learning:** Using Object.values() or filtering inside standard Zustand selector in React component causes unnecessary re-renders for every state update.
**Action:** Extract derived state computations inside the store or use useShallow hook.
