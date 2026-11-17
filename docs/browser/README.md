# Obscura hybrid browser: current setup and limits

Obscura is an optional research/extraction backend. Existing Chromium/Playwright
continues to own E2E, WebGL/WebGPU, SVG rendering, visual QA and compatibility
work. Installing this branch does not replace those browsers or turn the feature
on automatically. No production service is deployed by these changes.

## Supported path

In `/agency`, choose an authorized project, then **Integrations**. An enabled
Obscura panel accepts supplied HTML or a public HTTPS URL. Public extraction:

1. Authenticates the caller and authorizes the project/operator role.
2. Uses the canonical planner, execution permit and write-ahead idempotency.
3. Retrieves HTTPS HTML through a bounded broker, respecting robots policy.
4. Runs that HTML in the network-disabled Obscura container.
5. Persists the output, execution receipt and independent storage observation.

The URL button issues a new request key per click. Retrying the same URL and key
reuses its persisted result; a new key requests fresh retrieval. HTML extraction
continues to reuse its content-bound result. Retrieved text is **RETRIEVED**,
not independently verified or approved. Supplied text remains
**UNVERIFIED_SUPPLIED_HTML**. Neither status authorizes release or external writes.

The API is `/browser/projects/{project_id}/capabilities` and
`POST /browser/projects/{project_id}/extractions`. Supply exactly one of `html`
or `url`, plus `source_ref`. URL requests also require an `Idempotency-Key`
header. Cross-project access, viewer execution and client-injected authority
are refused. No client can choose a binary, image, proxy, permission or budget.

## Install on an authorized Linux x64 development host

Requirements: Python 3.11+, repository dependencies, Docker with working cgroup
memory/process/CPU limits, and the existing AMC development auth/project setup.
Do not grant an untrusted process the Docker socket. The socket is never mounted
into the worker. Other runtime platforms currently return unsupported; release
metadata alone is not a tested macOS or ARM worker.

Download the pinned official archive to a temporary file (never pipe to a shell):

```sh
curl --fail --location --proto '=https' --tlsv1.2 \
  --output /tmp/obscura-v0.2.7.tar.gz \
  https://github.com/h4ckf0r0day/obscura/releases/download/v0.2.7/obscura-x86_64-linux.tar.gz
python -m services.langgraph.agency.obscura_artifact \
  /tmp/obscura-v0.2.7.tar.gz /tmp/amc-obscura-v0.2.7
python scripts/browser/build-obscura-runtime.py /tmp/obscura-v0.2.7.tar.gz
```

Installation verifies the recorded archive SHA-256, member types and sizes, and
refuses an existing destination. The scratch image uses verified executables
and local runtime libraries, with no image pull or network-enabled build. Record
its immutable image ID; builds on different hosts can legitimately differ.

Set these **non-secret** server flags before starting AMC:

```sh
export AMC_ENV=local
export AMC_OBSCURA_ENABLED=1
export AMC_OBSCURA_PUBLIC_ENABLED=1
export AMC_OBSCURA_BINARY_DIR=/tmp/amc-obscura-v0.2.7
export AMC_OBSCURA_RUNTIME_IMAGE=$(docker image inspect amc-obscura-runtime:local --format '{{.Id}}')
```

Keep existing authenticated identity, tenant and project configuration. This
setup does not create an owner, approve decisions or change credentials.
Use the repository's normal backend/frontend startup commands; configure
NEXT_PUBLIC_API_BASE_URL for the backend before building the frontend.
Production-mode activation remains blocked pending a separately reviewed hosting
and release configuration. Merging code does not provision or enable a service.

If your host requires a managed HTTP CONNECT proxy, explicitly set
`AMC_OBSCURA_HTTPS_PROXY` to its non-credential-bearing server URL. The broker
connects the proxy to a validated **numeric public IP**, then verifies TLS for
the original website hostname. It never silently uses ambient proxy credentials,
changes DNS validation or falls back to an unpinned destination. An optional
SSL_CERT_FILE may reference the host's approved certificate trust file.

## Enforced boundaries

- HTTPS port 443 only; no credentials in URL authority, cookies, auth headers,
  uploads, POSTs, downloads to host paths, CAPTCHA bypass or stealth mode.
- Every redirect/DNS result is validated. Private, loopback, link-local,
  multicast, metadata and IPv6 transition ranges are denied. Mixed public/private
  DNS answers fail closed; connections pin the validated numeric address.
- Robots refusal is respected. At most eight total HTTP attempts (including
  robots requests), four hops per resource, 256 KiB of HTML, and 25 seconds total
  across DNS, TLS, headers and body. Invalid responses fail rather than fallback.
- Worker: no network, read-only root/input, private temporary storage, no
  privileges, 512 MiB memory with swap disabled, 64 tasks, one CPU, 64 MiB temp,
  15-second execution deadline, bounded output and explicit container cleanup.
- Two host-level slots bound concurrent operations. Page content cannot change
  trusted routing, tenant access, permissions, approvals or execution policy.

## Deliberate compatibility limits

This is brokered page extraction, not unrestricted interactive Chromium. External
scripts, CSS, images and subresources are not fetched into the isolated page.
Inline JavaScript can execute, but apps requiring external scripts or network
APIs may yield incomplete content. Non-HTML, compressed or non-UTF-8 responses,
oversized pages and prohibited pages are refused. Use the existing Chromium
path for full-page compatibility, screenshots, GPU work and interactive tests.
No new CDP/MCP or arbitrary JS-control endpoint is claimed.

## Verification and rollback

Routine tests require no public network. To include actual installed-worker
checks, set TEST_OBSCURA_BIN and AMC_OBSCURA_RUNTIME_IMAGE. To explicitly include
a real public retrieval test, also set TEST_OBSCURA_LIVE=1. The public browser
journey additionally requires E2E_OBSCURA_PUBLIC=1 and a matching local backend.
Tests label unavailable runtime/live cohorts as skipped, not passed.

```sh
python -m pytest services/langgraph/tests/test_obscura_*.py -q
pnpm --filter @amc/shared test
pnpm --filter @amc/web test
pnpm --filter @amc/web typecheck
pnpm --filter @amc/web build
```

Disable AMC_OBSCURA_PUBLIC_ENABLED to stop URL fetching; disable
AMC_OBSCURA_ENABLED to stop all Obscura dispatch. Restart the server after flag
changes. No schema migration or destructive rollback is required; persisted
ProjectOS artifacts and receipts remain intact. See [the historical engineering
record](obscura.md) for earlier partial milestones; this document describes the
current feature. No production readiness, universal security, performance gain
or guaranteed compatibility is inferred from finite tests.
