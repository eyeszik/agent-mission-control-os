# Capability Assurance and Reproducibility System (CARS)

CARS integrates existing capability probes, environment fingerprints, and
execution evidence into a unified, machine-readable contract. It does **not**
replace `agency/visual/capabilities.py`, `agency/durable/proofs.py`, or
`freevideoforge/doctor.py`; it composes them.

## Capability contract

Each capability exposes:

```json
{
  "capability": "webgl",
  "required": true,
  "available": false,
  "version": null,
  "provider": "chromium",
  "platform": "linux-x86_64",
  "provenance": null,
  "health": "UNAVAILABLE",
  "reason": "NO_WEBGL_CONTEXT",
  "remediation": "apt install ...",
  "checked_at": "2026-11-06T..."
}
```

Health values:
- `VERIFIED` - capability passed its defined contract (e.g. shader compiled AND pixels read back)
- `AVAILABLE_BUT_FAILED` - capability exists but operation failed
- `AVAILABLE_UNVERIFIED` - capability exists but required behavior not proven
- `UNAVAILABLE` - prerequisite does not exist

## Environment fingerprint

`agency.capability_assurance.environment_fingerprint()` returns:

- repository_commit, OS, architecture, runtime_versions (python/node/pnpm)
- dependency_lock_hash (pnpm-lock.yaml), ffprobe_version, browser_version
- tts_engine, database_engine, configuration_hash, etc.

Use it to compare failing vs passing environments and detect configuration drift.

## WebGL / shader execution

Three contracts are validated separately:

1. **Context**: required WebGL context can be created (probe_browser + capture_webgl error field)
2. **Compilation**: known-good shader compiles and links (compile.ok / link.ok)
3. **Rendering**: shader executes and produces pixel output (pixels.stddev, framebuffer completeness)

Execution profiles:
- `hardware-backed` - GPU available (recorded renderer string)
- `software-rendered` - SwiftShader / Mesa llvmpipe (renderer contains "SwiftShader" or "llvmpipe")
- `unavailable` - NO_WEBGL_CONTEXT

Never claim hardware GPU validation after substituting software rendering.

## FFprobe reproducibility

Deterministic binary discovery order (see `freevideoforge/ffmpeg.py`):

1. explicit override (`FVF_FFMPEG` / `FVF_FFPROBE` or Settings)
2. system PATH
3. imageio-ffmpeg wheel (ffmpeg only; does not ship ffprobe)

Provisioning:

```bash
sudo apt-get update && sudo apt-get install -y ffmpeg   # provides ffmpeg + ffprobe
# OR
pip install imageio-ffmpeg  # ffmpeg only; ffprobe still needs apt
```

Doctor reports `ffprobe_version` and lists missing ffprobe as a blocker.
Clean-environment test: `test_ffprobe_provisioning.py`.

Never depend on `/tmp/ffprobe-static` or undocumented PATH.

## SQLite migration lock

`services/langgraph/persistence/sqlite_db.py::_migration_lock()` serializes
schema migration across worker processes via `fcntl.flock` on
`{db_path}.migrate.lock`.

- `amc_local.db.migrate.lock` is a runtime artifact, not a dependency lock
- `.gitignore` excludes `*.migrate.lock` (not `pnpm-lock.yaml` or other dep locks)
- Active lock is never deleted to clean Git status
- Crash-recovery: flock releases on file close / process exit; no permanent ownership

Concurrent migration safety is tested in `test_sqlite_migration_concurrency.py`.

## Distributed security (ASI03 / ASI10)

- `security/distributed.py` provides shared `asi10_halts` and `capability_jtis` tables
- Both MCP and local gateway must pass through `ToolExecutionPolicy`
- Halt scopes: global, tenant, agent, job, tool
- JTI uniqueness is enforced atomically (DB constraint / ON CONFLICT); two workers cannot both accept same token
- Tenant isolation: Tenant A cannot affect Tenant B
- Restart persistence: halt/JTI survive process restart (tested via subprocess)
- Retention: JITs expire with token TTL; halts have optional `expires_at`

## Heuristic quality (framing / goal-drift)

- Versioned dataset `agency/heuristics_evaluation.py::DATASET` (v1, 7+ cases)
- Metrics: precision, recall, FPR, FNR, F1 (calibration only when probabilistic)
- Shadow evaluation: `ShadowEvaluation` records predictions without affecting live decisions
- Promotion gate: `should_promote_threshold()` requires explicit criteria + sample_size ≥ 20
- Unmeasured detectors remain `UNVALIDATED`

## Artifact provenance

For generated audio/media, record provider, engine version, voice/model id,
input text hash, artifact hash, duration, sample rate, format, QC results.
See `test_tts_narration.py::test_artifact_provenance_recorded`.

## Tracing

Distributed execution evidence (`execution_trace.schema.json` + `durable_runs`):
- request_id / trace_id / tenant_id / job_id / worker_id / lease_epoch
- lifecycle events: receipt, claim, execution, completion, commit

Stale workers cannot commit after reassignment (fencing_token check).

## Brand lineage

`agency/brand_lineage.py` implements synthetic lineage contracts:
parent → child → grandchild with inheritance, override precedence, provenance,
branch isolation, invalidation, cycle rejection, deletion integrity, etc.
Covered in `test_brand_lineage.py`. Northline integration remains UNVERIFIED
until real contract/fixtures appear; no API is invented.
