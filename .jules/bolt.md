## 2026-08-20 - Zustand derived state rendering optimization
**Learning:** Returning freshly allocated arrays such as `Object.values(state.approvals)` from a Zustand selector can trigger unnecessary React re-renders and, with React 19/useSyncExternalStore, can contribute to update loops.
**Resolution:** The agency branch selects the stable `approvals` record and derives arrays/counts during render. `useShallow` is also valid when a selector must return derived arrays/objects; prefer the smallest selector that preserves stable equality semantics.

## 2026-08-20 - Playwright E2E local execution vs Next.js HMR
**Learning:** Running Playwright E2E tests against a Next.js `dev` server (`next dev`) causes tests asserting on `page.on('pageerror')` or `console` to fail because browser navigations disrupt Hot Module Replacement (HMR) WebSocket connections, yielding unhandled browser errors. Furthermore, strict alignment on hostname strings (e.g. consistently `localhost` vs `127.0.0.1`) is critical to avoid CORS 403 Forbidden errors between the frontend and FastAPI backend.
**Action:** When validating E2E tests locally, always compile a production build (`pnpm build`) and run it using the production server (`pnpm start`), ensuring host bindings and API Base URLs are strictly matched to the CI contract.
