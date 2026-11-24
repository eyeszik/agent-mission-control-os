# Obscura hybrid browser: current setup and limits

Obscura is an optional research/extraction backend. Existing Chromium/Playwright
continues to own E2E, WebGL/WebGPU, SVG rendering, visual QA and compatibility
work. Installing this branch does not replace those browsers or turn the feature
on automatically. No production service is deployed by these changes.

> Current workspace status: the saved profile is configured, but safe Obscura activation is blocked because this host has no enforceable Docker resource controllers. See [the follow-up audit](runtime-followup.md). Earlier successful extraction tests did not verify those controllers.

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

## Repeatable local activation and host readiness

Configuration can be saved without changing authentication, ownership or secrets:

```sh
python -m services.langgraph.agency.obscura_runtime configure \
  --binary-dir /tmp/amc-obscura-v0.2.7 \
  --image "$(docker image inspect amc-obscura-runtime:local --format '{{.Id}}')" --public
python -m services.langgraph.agency.obscura_runtime doctor --probe
```

The optional `--proxy` and `--ssl-cert-file` arguments refer to an explicitly
approved proxy and existing CA trust file. Credential-bearing proxy URLs and
unknown/authority fields are refused. `.amc/obscura-runtime.json` is private and
Git-ignored; it contains no account identity or permission settings. Existing
environment settings take precedence, including emergency disable flags.
Reconfiguration requires explicit `--replace`; no existing file is silently
replaced. This profile persists across process restarts, but it is not an OS
service and does not promise that a hosted workspace will restart processes.

The doctor must report ready with a passing probe before untrusted browsing is
considered available. Both readiness and dispatch now require actual Docker
support for memory, swap, PID and CPU limits, with a working cgroup driver.
**Accepting Docker command-line flags is not proof of enforcement.** Unsupported
rootless daemons may ignore those flags. Such hosts are now refused, even if
previous small extraction tests happened to succeed. Negative readiness results
are cached for five seconds to bound repeated Docker queries; execution checks
resource support again before launching a container.

The inspected ChatGPT coding workspace currently reports `CgroupDriver=none`,
with memory, swap, PID and CPU controls unsupported. Its user systemd manager is
offline. Runtime configuration was saved, but safe Obscura activation here is
BLOCKED. No privileged-container fallback or resource-check bypass was added.
A host administrator must supply an appropriate Linux development host with
working controllers before real worker execution is revalidated. See Docker's
[official rootless resource-limits guidance](https://docs.docker.com/engine/security/rootless/tips/#limiting-resources).

From the checkout, use `bash infra/run/amc-api.sh` and `bash infra/run/amc-web.sh`.
These launchers resolve their own checkout path, preserve explicit configuration
and use installed tools only. API startup loads the saved profile, or an explicit
AMC_OBSCURA_PROFILE. An unavailable optional worker remains blocked while the
independent API can start. AMC_PYTHON_BIN can select an already installed virtual
environment; no Python or Next.js download is performed by these launchers.

The frontend must be built with its intended public configuration. `pnpm build`
now records a fingerprint of the canonical public app configuration, and
`pnpm start` / the web launcher refuse a mismatched API/authentication binding.
Rebuild with matching NEXT_PUBLIC_* values before restarting. The fingerprint
is a consistency check, not an approval or human signature; no secret server
configuration is recorded.

URL idempotency keys are now reserved through the existing tenant/project-scoped
idempotency store: the same key plus different input/runtime returns 409, an
in-progress key returns 409, and a completed exact request replays its stored
response without another retrieval. Use a new key for a deliberate fresh request.
