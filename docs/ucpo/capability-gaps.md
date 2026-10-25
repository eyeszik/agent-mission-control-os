# UCPO: gaps, exceptions and blockers

Each item is either something this change deliberately does not claim, or something it could not do here. None is reported as done anywhere else.

## Not implemented (exceptions)

| Area | State | Why |
| --- | --- | --- |
| Deployment, publication, hosting | **Not authorized.** No route deploys. | It needs separate, explicit approval. No Vercel project is linked to this repository (see `docs/agency-framework-rollout.md`). |
| Hosted image/video generation | `CAPABILITY_GAP` | No verified provider adapter is installed. Specs and prompt packages stop at `PROMPT_PACKAGE_READY`. |
| Interactive 3D, XR | `CAPABILITY_GAP` | `three`, `@react-three/fiber` and an XR runtime are not installed. Installing them is a dependency decision for the owner. |
| Forms, analytics, consent/privacy pages | Not generated | Listed as not covered for AGM-10-006/009/011. Forms would need a server or a provider. |
| Performance budgets (Lighthouse) | `NOT_MEASURED` | The browser QA records no performance numbers, and no number is invented. |
| Manual WCAG 2.2 AA review | A person's task | The automated checks (axe-core, reflow, zoom, focus, motion, colour) do not certify conformance. |
| Research / strategy / creative-direction stages of the directive's pipeline | Not added | The brief carries the operator's copy. The line never writes copy or claims. Research and strategy stay with the existing owners (Project OS knowledge, compiled planner). |
| Composition-engine extensions (regions, occupancy, constraint strengths LOCKED/SOFT/FREE) | Not added to Foundry `CompositionIR` | `ConstraintWitness` is defined, and the browser checks witness reflow, zoom, focus and motion. Changing `CompositionIR` would ripple through Foundry consumers and needs its own change. |
| Evolution operators (SEED/FORK/MUTATE/CROSSOVER/...) for sites | Not added | Foundry `variants.py` (within `ResourceBudget`: candidates ≤ 4, generations ≤ 2, corrections ≤ 1) remains the variant owner. |
| Advanced intelligence modules | Partial | Implemented: semantic debt ledger, constraint witness contract, release proof binding plus staleness, change impact (the linker's `IMPACT_ANALYSIS`), and artifact history (Project OS versions). Not implemented: counterfactual layout lab, failure rehearsal matrix, adaptive verification radius, creative budget allocator, cross-media meaning compiler. |
| Execution-fabric operation registration | Not registered | The build uses the durable job layer: write-ahead intent, idempotency key, fenced lease, read-back, verify, commit receipt, reconcile. Registering the same operation in the fabric's skill registry would create a second dispatch owner. |
| Observability metrics catalogue | Partial | Events: `UCPO_BUILD_QUEUED`, `UCPO_VERIFIED`, `UCPO_RELEASE_BLOCKED`, plus durable tick telemetry and approval events. No metric is computed from these yet, so all metrics are `NOT_MEASURED`. |
| Optional connectors (Exa, Wolfram, Datadog) | Not used | They are not verified in this environment. Nothing calls them. |

## Environment blockers

| Blocker | Effect |
| --- | --- |
| Hosts without unprivileged user namespaces (common on CI runners with AppArmor restrictions) | `probe_isolation` fails. The build returns `BLOCKED_ISOLATION` and generates source only. The sandbox tests skip with a `NOT_RUN: sandbox unavailable` reason. |
| `apps/web/node_modules` not installed | `BLOCKED_ISOLATION` with the reason "run pnpm install --frozen-lockfile". There is no install step and no network. |
| `prlimit --as` | Not applied, because V8 reserves large virtual address ranges. Memory is bounded by timeouts only. |
