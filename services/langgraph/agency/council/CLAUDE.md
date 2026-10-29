# agency/council

_Guidance for this directory, moved verbatim from the root `CLAUDE.md` so it loads only when working here. Cross-cutting rules stay in the root file._

## Mission Council — three engines, one gate

`services/langgraph/agency/council/` + `persistence/council.py` (SQLite migration 19 / `20261022_amc_mission_council_v1.sql`) + `api/routes/missions.py` (`/missions`) + `apps/web/components/missions/` (`/missions`, also the Mission Council section of `/agency`):

- **Mission = run.** A mission is a `runs` row (pipeline `mission_council`). Its events are `run_events` (SSE via `/runs/{id}/events`), and its gate is an `approvals` row decided only via `/approvals/{id}/decide`. Don't add another approval or event store.
- **Engines.** `engines/{langgraph,crewai,autogen}_engine.py` share `engines/base.py` (strategy → audit → gate → prototype).
  - LangGraph uses the shared checkpointer with `interrupt()` + `Command(resume=)`.
  - CrewAI and AutoGen are the optional `council` extra; when it is absent they report `NOT_INSTALLED`, never fake it.
  - AutoGen has no code executor.
- **Models.** Seats run on the deterministic `MockSeatModel` unless `ENABLE_REAL_MODELS=true`. A failed provider fails the seat; it never falls back to mock output.
- **Policy and gate.**
  - `policy.scan` runs first and is deterministic. Model findings only raise risk.
  - The gate subject hash binds mission, thread, requested actions, strategy/risk hashes and policy version.
  - Decisions are single-use per action hash.
- **Tools.** `gateway.invoke` is the only tool path. It is deny-by-default with seat scopes and approval binding for WRITE/EXTERNAL; SHELL is disabled.
  - Every call is audited and redacted.
  - MCP servers come only from `AMC_MCP_SERVERS`.
- **State.** Terminal states never move. `queued → running` happens only under the lease. Checkpoints are hash-chained and verified on read.
- **Contracts.** Zod twins live in `packages/shared/src/schemas/missionCouncil.ts`, with the fixture `packages/shared/tests/fixtures/mission-council.json` (regenerate with `AMC_REGENERATE_FIXTURES=1 pytest services/langgraph/tests/test_council_contracts.py`).

Details: `docs/mission-council.md`.
