# UCPO repository audit (reuse map)

Before writing the website line, each needed capability was checked against what the repository already owns. The rule was: reuse the owner, or record why not.

| Needed | Found | Decision |
| --- | --- | --- |
| Creative genome, grammars, composition | `agency/foundry` (12 grammars, `compile_genome`, `compose`) | Extended: 13th grammar `psem_editorial`, profile `foundry/psem.py`, `psem.plate`. No second Foundry. |
| Design tokens | `agency/design_tokens` (one DTCG compiler) | Reused via `psem.compile_psem_tokens`. |
| Contrast math | `ui_ux.tokens.wcag_contrast_ratio` | Reused for every PSEM pairing. |
| Artifact persistence, versions, invalidation | Project OS + N4 (`create/revise_project_artifact`, `depends_on`, blast radius) via `foundry.studio.store` | Reused. No migration. |
| Untrusted execution with recovery | `agency/durable` (`run_tick`, intents, leases), the pattern used by `agency/rendering` | Reused: one new handler kind. |
| Approval and release verdict | `intake/release.py`, `/approvals/{id}/decide`, separation of duties | Reused. |
| Role authority | N3 `assert_role_may_produce` | Reused for every stage. |
| Browser | Pre-installed Chromium + Playwright; `@axe-core/playwright` / `axe-core` 4.13.0 in `apps/web` | Reused; no install. |
| Website toolchain | `apps/web` Next 16.4.2, React 19.3.1, TypeScript 7.0.2 | Reused by symlink inside the sandbox; exact versions are checked before building. |
| Framework tasks | Agency Operating Framework catalog and refs | Proposed refs only; the ledger is untouched. |
| Capability discovery | `foundry.capabilities.discover` | Reused by the discipline router. |
| Prompt firewall | `prompt_compiler.GENERATION_FIREWALL` | Reused as the terminal state of modules and specs. |

The hosting facts are unchanged from `docs/agency-framework-rollout.md` §1:

- No Vercel project is linked, so a merge deploys nothing.
- The single Supabase project is inactive.
