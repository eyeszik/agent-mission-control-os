# agency/durable

_Guidance for this directory, moved verbatim from the root `CLAUDE.md` so it loads only when working here. Cross-cutting rules stay in the root file._

## Durable runtime — bounded ticks (from the local visual engine and durable runtime section)

`services/langgraph/agency/durable/` + `persistence/durable_runs.py` (migration 14 / `20261009_amc_durable_runtime_v1.sql`):

- **FSM.** A 20-state run FSM (`fsm.py`, pure). `transition()` is the only writer. It is fenced on `lease_token`
  and allowlists the columns it may set.
- **Ticks.** `ticks.run_tick` does: lease → precheck → write-ahead intent with pre-image → dispatch → readback →
  verify → fenced commit → telemetry.
- **Recovery.** Crash recovery adopts or redoes from the pre-image.
- **Guarantee.** At-least-once, **not** exactly-once.
- **Not always on.** No worker is deployed; `RuntimeActive` stays false.

Also in that package:

- **Genome and DAG.** `genome.py` (MissionGenome admission, contradiction engine, proof debt) and `build_dag.py`
  (A00–A11, three separate predicates).
- **Governance.** `governance.py` holds G0–G4; G3/G4 are never allowed.
- **Proofs and observability.** `proofs.py` and `observability.py` (computed only from rows; `NOT_MEASURED` /
  `BASELINE_UNKNOWN` instead of invented numbers).

`runtime/abc/*.yaml` are generated: edit code, then run `python scripts/compile_abc_manifests.py --write`.
`test_t19_abc_manifests_match_code` checks them. `scripts/seal_abc_build.py` writes the unsigned verification
seal from real command results.

Details: `docs/local-visual-engine.md`, `docs/durable-runtime.md`, `docs/abc-v6-traceability.md`,
`docs/abc-v6-runbook.md`.
