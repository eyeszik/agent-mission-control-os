# ACE v12 — governed Agency OS

ACE v12 adds a governed action plane and a client-facing Agency OS on top of the existing Agent Mission Control
primitives. **LIVE execution is disabled.** Every external effect (publish, send, spend, delete, permission change)
runs only against sandbox fakes, through one gateway, after exact human approval, and is read back before it
counts.

| Document | What it answers |
|---|---|
| [ADR-0001](adr-0001-governed-action-plane.md) | What was added, what was reused, and the alternatives that were rejected |
| [Architecture](architecture.md) | Components, data flow and the ActionRequest state machine (diagrams) |
| [Provider matrix](provider-matrix.md) | Every catalogue entry: owner, risk class, implementation status, live status |
| [Security controls and threat model](security-controls.md) | Each threat, the control that stops it, and the test that proves it |
| [Failure matrix](failure-matrix.md) | Each failure mode, the state it lands in, how it recovers, the test |
| [User guide](user-guide.md) | Using `/agency`: clients, briefs, approvals, evidence, exports |
| [Runbooks](runbooks.md) | Freeze, recover UNKNOWN work, budgets, signing key, offboarding |
| [Test evidence](test-evidence.md) | The commands that were run and their recorded results |

## Status vocabulary

The brief's statuses mean exactly this here:

| Status | Meaning in this repository |
|---|---|
| DEFINED | A descriptor exists; no code dispatches it |
| IMPLEMENTED | Code exists and is reachable |
| TESTED | Implemented, with named tests that exercise it |
| VERIFIED | A result was read back independently and matched |
| LIVE_GATED | Would touch the outside world; refused by the LIVE gate |
| UNAVAILABLE | A dependency is switched off or missing on this host |
| BLOCKED | A rule refused it; the reasons are recorded |
| VOID_DETECTED | A name exists with no source definition (EXT-001…090, ART-001…012) |
| PROVIDER_GAP | No provider adapter is installed, so nothing is simulated in its place |

## Where the code is

| Area | Path |
|---|---|
| Action plane | `services/langgraph/agency/actions/` |
| Agency OS services (clients, missions, deliverables, lifecycle) | `services/langgraph/agency/agency_os/` |
| Persistence (migration 16) | `services/langgraph/persistence/actions.py`, `supabase/migrations/20261012_amc_actions_v1.sql` |
| API | `services/langgraph/api/routes/actions.py` (`/actions`), `services/langgraph/api/routes/agency_os.py` (`/agency-os`) |
| Contracts (Zod twins) | `packages/shared/src/schemas/agencyOs.ts`, fixture `packages/shared/tests/fixtures/ace12.json` |
| UI | `apps/web/app/agency/page.tsx`, `apps/web/components/agency/` |
| Tests | `services/langgraph/tests/test_ace12_*.py`, `apps/web/e2e/agency-os.spec.ts`, `apps/web/tests/agency-status.test.ts`, `packages/shared/tests/agencyOs.test.ts` |
