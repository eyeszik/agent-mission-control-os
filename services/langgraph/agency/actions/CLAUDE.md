# agency/actions

_Guidance for this directory, moved verbatim from the root `CLAUDE.md` so it loads only when working here. Cross-cutting rules stay in the root file._

## ACE v12 action plane and Agency OS — one gateway, sandbox only

`services/langgraph/agency/actions/` + `persistence/actions.py` (migration 16 / `20261012_amc_actions_v1.sql`) +
`api/routes/actions.py` (`/actions`); the client app is `agency/agency_os/` + `api/routes/agency_os.py`
(`/agency-os`) + `apps/web/app/agency` + `components/agency/`:

- **One dispatch owner.** Only `actions.gateway` catalogue entries can be proposed through `/actions`. Fabric and
  VNEXUS entries are described in `catalog.py` but keep their own dispatch (`NOT_GATEWAY_OWNED`). No LangGraph node
  may call the gateway, because interrupted nodes replay; a test enforces this.
- **Approval.** One anchor run per action. Approvals are `approvals` rows with `subject_hash = binding_hash`, decided
  only via `/approvals/{id}/decide`. Spend and governance roles are server-written `approval_policy` in run
  metadata, checked by `assert_may_decide_approval`. Don't add another approval store.
- **State.** `persistence.actions.transition` is the only state writer: CAS on `version`, an allowlisted column
  set, and a hash-chained `action_transitions` row.
- **Effects.** Adapters are sandbox fakes writing only `action_sandbox_effects`; completion needs an independent
  read-back. A timeout becomes `UNKNOWN` and leaves only by reconciliation.
- **LIVE.** `governance.live_enablement()` always returns `DISABLED`. There is no switch.
- **Reserved ids.** EXT-001…090 / ART-001…012 have no source definitions: they are `VOID_DETECTED`. Never invent
  them.
- **Contracts.** Zod twins live in `packages/shared/src/schemas/agencyOs.ts`, with the fixture
  `packages/shared/tests/fixtures/ace12.json` (regenerate with
  `AMC_REGENERATE_FIXTURES=1 pytest services/langgraph/tests/test_ace12_contracts.py`).
  `test_ace12_traceability.py` requires a test named for every T01–T60 and I01–I20.

Details: `docs/ace-v12/README.md`.
