# ACE v7.1 Brand Production — Initial Integration

Status: **foundation only; review required**.

## Verified integration boundaries

- `docs/creative-runtime.md` owns the bounded local creative runtime, approval gate and hash-chained flight recorder.
- `docs/prompt-compiler.md` owns five-pass evidence auditing and the `PROMPT_PACKAGE_READY` boundary.
- `knowledge/creative-capabilities/registry.json` owns the creative capability registry.
- `apps/web/lib/design/composer.ts` owns pure client-side style composition prechecks; backend composition remains authoritative.

## This branch

Adds side-effect-free brand/project/style-guide planning primitives, conditional capability routing, project-specific page prompt contexts, and weighted coverage with critical gates. These are **not wired into production APIs, persistence, UI, provider execution or the existing prompt compiler**. The local digest is explicitly limited to standalone manifest planning; integrate with AMC-CANON-1 before sealing runtime artifacts.

## Remaining implementation work

1. Inspect and integrate with actual persistence, auth and API boundaries.
2. Recover the 14 original prompt source texts, preserving them byte-for-byte; source inventory remains incomplete.
3. Add immutable approved style-guide version persistence and project authorization checks.
4. Connect conditional routing to existing topology selection and prompt compiler without changing its no-spend contract.
5. Add Creative Foundry panels and API integration.
6. Verify provider SDK/CLI/API credentials, capabilities, budgets and terms before enabling execution.
7. Reuse existing approval and recorder; implement chargeable job reconciliation only after provider contract verification.
8. Run unit, integration, UI and security tests in CI.

## Verification

Suggested command from repository root:

`python3 -m unittest tests.test_brand_production_foundation -v`

The GitHub connector can commit source files but does not execute repository tests; test outcomes remain **NOT_RUN** until verified in a checkout or CI.

## Risk register

- **Critical:** No verified chargeable-provider idempotency contract. Execution disabled.
- **High:** Persistent project ownership and isolation not yet integrated.
- **High:** Original 14-prompt library not recovered or imported.
- **High:** Existing AMC-CANON-1 sealing not yet reused in new foundation.
- **Medium:** UI, API and end-to-end workflows pending.

This document is an implementation inventory, not a certification of completed end-to-end integration.
