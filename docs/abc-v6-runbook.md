# ABC-v6 operator runbook

## Install the local engine

```bash
python -m pip install -e "./services/langgraph[dev,visual]"   # Pillow + bpy 4.2 (CPython 3.11 only)
sudo apt-get install -y ffmpeg                                # R5; ffprobe ships with it
pnpm install --frozen-lockfile                                # @playwright/test for the browser harness
```

R2 offline diffusion stays blocked until an operator installs all three of the following deliberately.
Nothing is ever downloaded at render time.
- `torch` and `diffusers`;
- a local model directory pointed to by `AMC_LOCAL_DIFFUSION_MODEL_DIR`, containing `model_index.json`;
- an `amc-model.json` file in that directory: `{"license": "...", "weights_sha256": {...}, "source": "..."}`.

R3 Three.js stays blocked until `three` is added to `apps/web` as a reviewed dependency.

## Check what this host can do

```bash
python -c "import json; from services.langgraph.agency.visual.capabilities import probe_all; \
print(json.dumps({r.value: [c.status.value, c.version, list(c.blockers)] for r, c in probe_all().items()}, indent=2))"
```

## Run work

```python
from services.langgraph.agency.durable.visual_job import HANDLERS, submit_visual_job, settle_waiting_approval
from services.langgraph.agency.durable.ticks import run_tick

job = submit_visual_job(principal, project_id, intent, artifact_key="hero", mission_id="launch-q4")
report = run_tick(worker_id="worker-1", handlers=HANDLERS, job_id=job["job_id"])
# ... a different authorized reviewer decides via POST /approvals/{id}/decide ...
settle_waiting_approval(job["job_id"])
```

`run_tick` without `job_id` takes the next due job. Run it from a cron, a queue consumer or a loop. Each call is
bounded and safe to repeat: concurrent callers race on a CAS, and stale callers get `StaleFence`.

No scheduler process is deployed by this change.

## Read state

| Question | Where |
|---|---|
| What is a job doing? | `durable_jobs.state`, `last_reasons`, `next_due_at` |
| How did it get there? | `durable_transitions` (fencing token, logical tick, trace id, reason) |
| Was an effect written? | `durable_intents` (`INTENT` = written before the effect, `COMMITTED` = receipt stored) |
| What did a tick observe? | `durable_ticks.telemetry` |
| Project metrics | `agency.durable.observability.project_metrics(project_id)` |

## Recover

| State | Meaning | Operator action |
|---|---|---|
| `RECONCILING` | A lease expired mid-tick. | None. The next tick adopts or redoes from the pre-image. |
| `RETRY_PENDING` | A transient failure; backoff of 30, 120 or 600 s. | None. |
| `DEAD_LETTER` | Retries are exhausted, a failure repeated in an unchanged environment, or a reconcile diverged. | Read `last_reasons` and `failure_fingerprints`, fix the cause, then move the job `PAUSED → SCHEDULED`. |
| `BLOCKED_PROVIDER` / `BLOCKED_ENVIRONMENT` | A capability is missing. | Install it (see above). `SCHEDULED` re-enters precheck. |
| `BLOCKED_AUTHORITY` | Rights are unknown, the project is archived, or the principal lost access. | Fix the authority, then reschedule. Never bypass. |
| `WAITING_APPROVAL` | A human decision is needed. | The decision goes through `/approvals/{id}/decide`; then `settle_waiting_approval`. |

## Observability contract

Each tick records:
- `trace_id`, `mission_id`, `project_id`, `job_id`, `node_id`;
- `capability`, `execution_mode`, `attempt`, `logical_tick`;
- `latency_ms`, `queue_lag_ms`;
- `observed_cost` (`NOT_MEASURED`), `resource_usage` (render wall ms; GPU memory `NOT_MEASURED`);
- `artifact_hash`, `verification_state`, `failure_fingerprint`;
- `checkpoint_version`, `next_due_at`, `final_state`;
- `wall_started_at` and `wall_finished_at`.

Telemetry never contains prompts, job specs, principals, palettes or secrets. Spans use an attribute allowlist.
OpenTelemetry export requires the SDK and `AMC_OTEL_EXPORT=enabled`. Datadog export is not implemented.

## Build evidence

```bash
python scripts/compile_abc_manifests.py --check   # runtime/abc/*.yaml match code
python scripts/render_abc_samples.py              # real samples via the durable pipeline (about 10 min on 4 CPUs)
python scripts/seal_abc_build.py --full           # runs the checks and writes runtime/abc/verification-seal.json
```

The seal is unsigned. It records each command's exit code, environment, start time, duration and output hash.
`ReleaseEligible` stays false until a human reviews the media and a current approval exists. `RuntimeActive` stays
false until a worker is deployed with authorization.

## Known-blocker register

| Blocker | Effect | Unblock |
|---|---|---|
| R2: no torch, diffusers, local weights or licence record | Concept images are `BLOCKED_LOCAL_MODEL`. | Install and record a licensed local model. |
| R3: `three` is not an `apps/web` dependency | Interactive scenes are `MISSING_DEPENDENCIES`. | Add `three` as a reviewed dependency. |
| No GPU on the reference host | Cycles runs on CPU: a 960×1200 still at 160 samples plus a 36-frame turntable took about 10 minutes. | GPU device selection is not implemented. |
| OpenTelemetry SDK not installed | Spans are built but not exported. | Install the SDK and set `AMC_OTEL_EXPORT=enabled`. |
| No persistent worker | `RuntimeActive` is false. | An authorized deployment that invokes `run_tick`. |
| Q5–Q7 | Visual, realism and brand judgement and approval are human. | Review and approval through the existing route. |
| CI lacks bpy, Chromium (backend job) and possibly `unshare` | T07, T08, T09, T11 and T12 skip as NOT_RUN in CI. | Run them on a host with those tools, or add a CI job. |
