# Governed rendering

The corrected architecture is implemented as a local typed-primitives vertical slice. This is **not the complete eight-engine platform**. Rough.js SVG is the only implemented profile; seven engine IDs report ADAPTER_NOT_IMPLEMENTED. PNG/video, arbitrary source execution, GPU workers, remote presigned storage and execution-spend approvals are not implemented and cannot be enabled by request wording. No production project foundations or human approvals are synthesized.

## Run

Use the package manager declared by package.json:

```sh
pnpm install --frozen-lockfile
pnpm --filter @amc/creative-renderer build
python -m pip install -e './services/langgraph[dev]'
```

Start the normal backend and web application. Open `/creative`, select a real authorized project, and queue a bounded scene. A separately supervised **trusted control-plane driver** processes its durable job:

```sh
python -m services.langgraph.agency.rendering.worker --job RENDER_JOB_ID
# Or have a process supervisor invoke this bounded command periodically:
python -m services.langgraph.agency.rendering.worker --once
```

The driver has database access; its isolated Node child does not receive database environment variables or credentials. The worker accepts only bounded typed primitives, not JavaScript, TSX, URLs or uploaded source. Its Node permission profile denies filesystem reads outside its generated worker directory, child processes, addons and worker threads. This is not an OS/container network sandbox and does not support untrusted executable sketches. The host Node permission flag is selected by its observed major version.

## Contracts and authority

POST `/foundry/projects/{id}/renders` requires authentication, recorded project scope and Idempotency-Key. GET of that resource is observational. Cancellation revokes the database fence; a late worker can leave immutable orphan bytes but cannot register a canonical artifact. Artifact acceptance composes existing Project OS APIs in an explicit atomic database scope and checks the live fence under a row lock. Normal persistence calls outside this scope retain their previous transaction behavior. Canonical run FSM v2 adds lease-revoked STOPPED transitions for in-flight work; regenerated ABC manifests record the changed transition graph. PostgreSQL and SQLite use the same APIs. No new tables or migrations.

The canonical hash binds tenant/project, workflow/task, scene revision, dimensions, frame clock, seed, strict scene, adapter, worker bytes, runtime version and lockfile. Fences/attempts are absent from semantic identity. SVG verification independently re-reads stored bytes, checks SHA-256, structure, dimensions, allowed elements, active-content restrictions and the admitted scene palette. It does not establish full WCAG conformance or approved brand identity.

Real compute success, artifact verification and human release approval remain separate. The existing approval inbox decides the exact artifact. The explicit resume command applies that authoritative decision; rejection never restarts rendering. No publication occurs. Existing authenticated `/runs/{id}/events` replay is reused; streaming never invokes the renderer. The UI switches to the approval run stream when that resource exists.

## Quarantine

POST `/foundry/projects/{id}/render-quarantine` requires an approver role and a reason. It records an operator-authored project policy record and revokes up to 200 matching active/queued jobs per request; additional work remains blocked at admission and canonical acceptance. Repeat bounded administrative cleanup if needed. PostgreSQL policy locks serialize quarantine with artifact acceptance. Existing accepted artifact bytes/history are retained; release checks consult current quarantine. No Redis keys or direct operator SQL are required.

## Verification and rollback

```sh
python -m pytest services/langgraph/tests/test_rendering.py -q
pnpm --filter @amc/creative-renderer test
pnpm typecheck
pnpm test
pnpm build
python scripts/verify_manifest.py
```

Real worker tests skip explicitly when the worker has not been built. A skip is not proof of runtime readiness. Hosted backend jobs do not currently build Node workers; frontend CI builds/tests the real Rough.js worker.

Revert the implementation commit to remove the feature. No database migration is required. Retain already stored artifacts and historical approval/audit records. Manifest regeneration must use scripts.verify_manifest.git_blob_sha on listed file bytes; do not replace Git blob hashes with raw SHA-256.
