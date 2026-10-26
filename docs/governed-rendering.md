# Governed rendering

The corrected architecture is implemented as a local typed-primitives vertical slice. This is **not the complete eight-engine platform**. Three data-only SVG profiles are implemented: Rough.js seeded paths, Paper.js headless paths, and SVG.js PathArray geometry. Five engine IDs report ADAPTER_NOT_IMPLEMENTED. Paper.js does not run PaperScript, import SVG, use Canvas or render text; SVG.js does not provide a browser DOM/export adapter. PNG/video, arbitrary source execution, GPU workers, remote presigned storage and execution-spend approvals are not implemented and cannot be enabled by request wording. No production project foundations or human approvals are synthesized.

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


## Completion pass and remaining specification work

The completion pass adds independently observed compute outcomes, fenced durable candidate
receipts, and recovery by read-back instead of unconditional re-rendering. Rejected output
can correctly have compute `succeeded` and artifact `rejected`. Candidate writes after
cancellation or lease takeover are refused. Corrupt or missing persisted output invalidates
release eligibility on subsequent reads. The exact release subject, purpose, policy and
version remain separate from compute state. SVG verification rejects unreviewed attributes
and missing paths; it is not a visual-equivalence or accessibility audit.

The creative browser smoke test uses a clearly fictional local project. It exercises actual
capabilities, unavailable-engine refusal, scoped queueing and cancellation through the real
UI/API. Rendering and human review are tested separately in the database-backed cohort;
the browser test does not claim to approve or render a production brand.

The complete corrected design is still **PENDING_IMPLEMENTATION** beyond these profiles:

| Requirement | Current implementation / smallest remaining action |
| --- | --- |
| p5, Pixi, R3F, Remotion, Motion Canvas | No adapters; implement and validate each runtime/profile individually. Do not enable from package declarations. |
| Raster/video and codecs | No renderer/encoder/verifier; select exact output profile and validate decoded persisted bytes. |
| Executable scene source and GPU | Not supported by typed-primitives isolation; select and validate an OS/worker isolation substrate before admitting code. |
| Execution budget approvals | No spend is dispatched here. Add purpose-bound execution grants before introducing paid/high-resource dispatch. |
| Remote worker transport/presigned storage | Local trusted driver only. A reviewed staging/promotion adapter and worker authentication are still required. |
| Real brand foundations | No scoped source artifacts or approval records were supplied. Use the existing intake/planning evidence gates; generic geometric fixtures establish no brand readiness. |
| Brand/accessibility verification | No production claim. Bind actual approved token/artifact versions and execute the required rendered checks for the selected profile. |

Missing live project evidence must be reported as: “Live evidence was unavailable. This
claim remains unverified.” Human creative-direction acceptance and artifact release are
separate approvals. None of the tests or generic geometry requests supplies either.

Regenerate manifest hashes after reviewing changed tracked files with
`scripts.verify_manifest.git_blob_sha`; preserve every existing entry. Run
`python scripts/verify_manifest.py` afterward. Dependency bumps on master had left five
entries stale; this pass refreshes those alongside its own files and updates the explicit
PostCSS lockfile invariant from 8.5.28 to the installed 8.5.31.
