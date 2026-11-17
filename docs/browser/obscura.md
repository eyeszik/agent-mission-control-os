> Historical engineering log. See [current setup and supported public extraction](README.md) for the current feature. Earlier disabled/unfinished statements below describe earlier milestones.

# Obscura integration preflight (partial implementation)

Baseline: dcae954438f1db652f50e0ade5d056bec25616dd.

The release API and README at v0.2.7 were accessed on 2026-11-15.
Sources: https://github.com/h4ckf0r0day/obscura/releases/tag/v0.2.7,
https://github.com/h4ckf0r0day/obscura/blob/v0.2.7/README.md,
and https://github.com/h4ckf0r0day/obscura/blob/v0.2.7/LICENSE.
The API reports Apache-2.0 and official Linux/macOS ARM64/x64 assets.
`obscura-release.json` preserves the reported archive SHA-256 digests.
These are upstream assertions: no binary was downloaded, inspected or executed.
License compatibility and transitive dependencies have not been fully reviewed.

Upstream documents `fetch URL --dump html`, `--eval`, screenshots and a CDP
server. These APIs have not been runtime-verified here. Stealth artifacts are
excluded from the recorded candidates. No private-network override is enabled.

## Implemented

Pure typed preflight only, disabled by default. Compatibility-sensitive tasks
retain Chromium. An enabled Obscura request returns BLOCKED or
UNSUPPORTED_PLATFORM. No execution permission is derived from caller flags.
No production route, environment flag, dashboard control or fallback is wired.
Existing browser owners and authorization remain unchanged.

## Security integration gap

UCPO's existing namespace/chroot boundary intentionally disables networking;
it cannot directly perform public research. A reviewed canonical execution
adapter needs controlled egress for redirects, DNS changes and every page
subresource, not just validation of the initial URL. Simply allowing network
access in the existing sandbox would weaken its boundary. Browser execution
must remain unavailable until that adapter and its negative tests exist.

## Verification and remaining work

Run `python -m pytest services/langgraph/tests/test_obscura_preflight.py -q`.
Observed: 12 passed. `python scripts/verify_manifest.py`: passed, 353 pins.
No binary installation, live browsing, extraction, screenshot, MCP/CDP,
benchmark, API/UI integration or existing Chromium browser regression was run.
Benchmarks: NOT_MEASURED. This preflight is not a completed browser backend.

Next: verify release archive bytes against the recorded digest; inspect CLI
and source security behavior; implement a canonical isolated worker with
restricted egress, limits and cancellation before connecting authenticated
project APIs or enabling browsing. Keep fixtures offline and explicitly scoped.

## Follow-up verification — 2026-11-17

The official Linux x64 v0.2.7 archive was downloaded locally to
`/workspace/scratch/obscura/release.tar.gz`. Its measured SHA-256 is
`11b53d27cd743e00e196e216920e7f3f794cf378e3f1792b8d25d3beabaf9cad`,
matching the recorded release digest. The archive contains two regular files:

- obscura: 80,903,256 bytes; SHA-256 `547f9d8a60048983f0e45c310f160d1239575af062af28e4f6755e361f8abcbf`.
- obscura-worker: 75,983,952 bytes; SHA-256 `6956274a7e517666386493962866f95a39ace2f71d864ad2e3bac7640145c311`.

The verified CLI's `--help` ran successfully and listed fetch, serve, scrape,
and mcp. This establishes executable startup only, not browser functionality.
The earlier statement that no binary was downloaded is historical and is
superseded by this observation. Other platforms remain untested.

`agency/obscura_artifact.py` now validates the pinned archive digest, bounded
archive size and declared unpacked size, exact member set, regular file types,
and duplicate/path rejection. It returns verified bytes without writing archive
paths to disk. Tests use explicitly synthetic archives; they establish refusal
behavior, not upstream authenticity.

Verification: 19 focused tests passed with
`python -m pytest services/langgraph/tests/test_obscura_artifact.py services/langgraph/tests/test_obscura_preflight.py -q`.
The actual release was also independently loaded through `verified_members`.

The actual `ucpo.sandbox.probe_isolation()` reports available=false:
`sandbox boundary probe exited 32: mount: /: permission denied`.
In addition, the canonical sandbox rejects network=True by design. No sandbox
policy was weakened. The execution adapter, restricted egress, authenticated
extraction API and UI remain unfinished. A capable isolated development worker
and tested network mediation are prerequisites for their safe runtime
verification. No live pages were fetched, benchmarks measured, or providers
enabled; no push, deployment, paid call or secret change occurred.

## Isolated development worker increment — 2026-11-17

A subsequent environment capability check found Docker server 29.9.2 and a
working minimal Bubblewrap user/mount/network namespace. This does not change
the earlier UCPO probe result: its larger boundary still failed. UCPO was not
modified. No container image was pulled or deployed.

`obscura_worker.extract` now executes supplied, bounded HTML through the verified
Linux x64 binaries in Bubblewrap. Verified bytes are copied to private scratch
before mounting, avoiding a hash-check-to-launch race against the source files.
Only system runtime directories and the engine are exposed read-only; home and
temporary storage are private, environment is cleared, network/PID namespaces
are isolated. Wall time, CPU, file output and file descriptor limits are applied.
The process group is killed and reaped after execution; scratch is removed.
This is a development component, not an execution permit.

`obscura_egress` is a separate restricted HTML broker implementation. It accepts
HTTPS port 443 only, rejects credentials, validates all resolved addresses,
pins the numeric connection while verifying TLS for the original hostname,
revalidates redirects, limits hops and HTML size, and ignores environment proxy
and credential configuration. It does not recursively retrieve subresources.
No public page was fetched in this increment. DNS policy tests are local mocks,
not a full adversarial TLS or redirect integration test.

Observed test command:
`TEST_OBSCURA_BIN=/workspace/scratch/obscura/bin python -m pytest services/langgraph/tests/test_obscura_worker.py services/langgraph/tests/test_obscura_egress.py services/langgraph/tests/test_obscura_artifact.py services/langgraph/tests/test_obscura_preflight.py -q`

Result: 36 passed. Real binary tests cover inline-JS-modified Markdown and an
attempted loopback fetch: the page reported refusal and the host canary server
received zero requests. Without TEST_OBSCURA_BIN these real-worker tests are
explicitly skipped. Integrity verification passed with 353 pins.

Not ready for activation: memory/process-count/concurrency ceilings, independent
filesystem containment and cancellation regressions, broker TLS/redirect/slow
response integration tests, execution-fabric permits and persistent receipts,
and authenticated API/UI connections remain unfinished. Browser preflight
intentionally still returns BLOCKED. Do not expose these functions directly to
client requests or infer authority from HTML/page content. This does not establish
full browser compatibility or production sandbox security. Benchmarks remain
NOT_MEASURED. No push, paid call, deployment or secret changes occurred.

## Resource limits and canonical proofs — 2026-11-17

Supersedes the earlier Bubblewrap-only development worker. The worker now uses
a locally built Docker scratch runtime, by immutable image ID only. It never
pulls an image. Container limits: 512 MiB memory, no swap, 64 tasks, one CPU,
64 MiB temporary filesystem, read-only root, UID/GID 65534, all capabilities
dropped, no-new-privileges and no network. The host CLI has bounded output/CPU/
file descriptors; wall timeout kills the client group and explicitly removes
the container. Two file-locked slots bound concurrent calls across processes
sharing the development user. Refusal of a third call and slot release are tested.

A 2 GiB address-space attempt failed real-binary startup; it was replaced, not
silently relaxed. Initial container startup failed because local library modes
were owner-only. The builder now writes explicit readable/executable modes.

Rebuild without network or remote scripts:

```
python scripts/browser/build-obscura-runtime.py /workspace/scratch/obscura/release.tar.gz
export AMC_OBSCURA_RUNTIME_IMAGE=$(docker image inspect amc-obscura-runtime:local --format '{{.Id}}')
TEST_OBSCURA_BIN=/workspace/scratch/obscura/bin python -m pytest services/langgraph/tests/test_obscura_*.py -q
```

The builder verifies archive bytes before copying either executable, and uses
only local Linux x64 runtime libraries. Those libraries remain host-specific;
the resulting image ID must be recorded for each build. No registry publishing
or remote deployment is performed.

`obscura_extract` is registered with the canonical execution fabric as a DRAFT
research-synthesis skill producing a research_brief. Default provider availability
is false. Trusted server configuration must explicitly set AMC_OBSCURA_ENABLED=1,
AMC_OBSCURA_BINARY_DIR and an immutable AMC_OBSCURA_RUNTIME_IMAGE. Inputs accept
supplied HTML and a source reference, not client authority or URLs. The source
status remains UNVERIFIED_SUPPLIED_HTML. The broker is not called by this skill.
Existing fabric authorization, permits, write-ahead idempotency, ProjectOS storage,
execution receipts, independent observation receipts and release guards apply.
No parallel receipt or approval table was added.

The integration test actually ran extraction through execute_mission, persisted
one dispatch, execution and observation proof, then replayed the same mission
without producing duplicate proofs. Real TLS fixture tests check hostname TLS,
pinned-address connection, private redirect denial, redirect-loop exhaustion
and response byte limits without public network access. These fixtures replace
DNS/routing only inside tests; no production private-network override exists.

Observed: 42 focused tests passed. A broader execution-fabric run had 58 passes
and three failures in unchanged code_sandbox tests because that host's read-only
mount namespace probe fails. They were not disabled or relabeled as passes.
Public broker end-to-end workloads, slow-response/DNS total-deadline controls,
adversarial resource-exhaustion and cancellation regressions, authenticated
API/UI and hosted CI remain unverified. Activation remains BLOCKED. There is
no production security or readiness claim and no image pull, push, paid call,
secret change or deployment.

## Local supplied-HTML activation — 2026-11-17

The safe offline path is now connected to authenticated project endpoints:

- GET `/browser/projects/{project_id}/capabilities`
- POST `/browser/projects/{project_id}/extractions`, body `{html, source_ref}`.

`source_ref` is a label, never a fetch instruction. Extra authority fields are
rejected; HTML is capped at 16,000 UTF-8 bytes. The server resolves project
ownership, derives the tenant and actor, and requires owner/admin/operator for
execution. Capability reads require project access too. Both endpoints use
canonical authentication. Production-mode activation is refused even if the
feature flag is set. Configuration remains opt-in and disabled by default.

The request goes through the existing compiled planner and execution fabric,
not a new scheduler. Its execution identity binds the supplied content, source
reference and configured runtime image. Replays reuse proofs. Output stays
UNVERIFIED_SUPPLIED_HTML and is never treated as approved or researched evidence.
The response includes the actual run/artifact references and persisted proof
summary. All page content is rendered as escaped text in the UI.

UI: `/agency` → select an authorized project → Integrations → Obscura local
extraction. It shows availability, inputs, errors, output, replay state and proof.
It has no public URL control and no implied remote/capability fallback. Existing
Chromium workflows are unchanged. Python response models and shared Zod schemas
cover the new API boundary; no additional dependencies were introduced.

Local configuration requires existing approved AMC development authentication
and project scope plus:

```
AMC_ENV=local
AMC_OBSCURA_ENABLED=1
AMC_OBSCURA_BINARY_DIR=/path/to/verified/linux-x64/binaries
AMC_OBSCURA_RUNTIME_IMAGE=sha256:<locally-built-immutable-image-id>
```

Use the existing backend/frontend startup commands after setting those values;
set NEXT_PUBLIC_API_BASE_URL to that backend before building the frontend.
This does not create or approve a real owner account. The observed local stack
used an explicitly fictional `obscura-preview-fixture` user/tenant/project with
a separate SQLite database and export root under /tmp.

Observed verification: 47 focused Python tests, 268 shared tests and 105 web
unit tests passed. The real Chromium UI flow passed against the local dev stack,
including extraction and displaying the persisted proof. Frontend type checking
and UI AST gate passed. Added cancellation and adversarial allocation tests
assert refusal/cleanup and slot release; the allocation test does not claim a
measured kernel OOM event. All seven repository gates passed (367 pinned files).
Hosted CI and full pre-existing browser cohorts were not rerun in this increment.

Direct local API evidence is saved outside Git at
`/workspace/scratch/obscura/activation-receipt.json`: run
`fabric-768ef213b84bb6a38552766a`, status SUCCEEDED, with one dispatch, execution,
observation and matching observation; failure_count=0. This is a real local
fixture extraction receipt, not production project or release approval.

Public browsing remains OFF. The broker is not reachable from the active skill
or API. Its total-deadline and broader public-network verification work is still
pending. Full production activation, hosting and hosted verification are not
claimed. No push, publication, paid call, deployment or secret change occurred.

Final frontend verification: production build passed. The Chromium extraction
journey also passed against the production frontend server on loopback. The
local development activation is for supplied HTML only; the older public
browsing preflight remains BLOCKED and now points to the authenticated offline
path instead of reporting that no adapter exists.
