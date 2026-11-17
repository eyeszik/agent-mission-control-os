# Runtime activation and workflow follow-up — 2026-11-17

Baseline: `f46e93df579600c2be7942ec0e70ee486dbdb33f`, branch
`remediate/obscura-hybrid-browser`. The checkout was clean at audit start.
The [baseline CI run](https://github.com/eyeszik/agent-mission-control-os/actions/runs/44029057546)
completed successfully: all nine jobs passed. This is historical evidence for
that revision; it does not validate the new changes or this host's controllers.

## Executed task prompt

Recover the verified branch and preserve existing work. Repair non-portable
startup, persist a strict non-secret runtime profile without changing identity,
expose real readiness failures, and enforce request-key binding through existing
persistence. Validate compilation, affected contracts and safety paths. Activate
only where actual isolation/resource prerequisites hold. Do not push until the
requested operational-verification condition is satisfied.

## Verified findings and changes

| Requirement | Observed gap | Repair / canonical owner | Verification |
|---|---|---|---|
| Portable API/web startup | Both `infra/run` scripts hard-coded another checkout path; two relocated-checkout tests failed | Script-relative roots; explicit Python override; installed Next.js only | Both launcher tests pass, including paths with spaces |
| Repeatable configuration | One-off shell exports and processes did not survive workspace restart | Strict private `.amc/obscura-runtime.json`; runtime CLI; launcher loads profile | Private mode, no-overwrite, no authority fields, environment override and secret-safe error tests pass |
| Honest availability | Flags and an image setting alone reported availability | Binary integrity, actual image presence, bounded/cached daemon prerequisites | Missing image/tampering/controller refusal tests pass; live doctor reports blocked here |
| Actual resource enforcement | Rootless Docker reports unsupported memory/swap/PID/CPU limits | Readiness and every worker launch check real daemon support and cgroup driver; mandatory CI precheck | Negative tests pass; current host refused before page execution |
| Optional failure isolation | Stopping the entire API for an unavailable optional worker would break independent work | API may start; provider remains blocked through canonical availability gates | Real API health/project access and the blocked browser panel were checked |
| URL request-key binding | Same key with a different URL performed a second extraction | Existing tenant/project-scoped idempotency reservation and conflict/replay API | Reproduced 200 instead of 409, then regression passed; exact replay performs no new execution |
| Frontend API/auth binding | Next.js public values were inlined at build time, while start script suggested runtime values changed the bundle | Build metadata/fingerprint and checked `pnpm start` / launcher | Matching build starts; API URL, auth mode and public Supabase-binding mismatches are refused before startup |
| Configuration-probe overhead | Repeated unavailable-runtime reads could repeat Docker probes | Five-second positive and negative metadata cache; dispatch guard remains fresh | Two readiness reads cause one probe in the regression test |

These extend existing owners; no planner, scheduler, approval system, identity,
canonical table or migration was added. Existing authentication, tenant/project
checks, mTLS handling, execution fabric and ProjectOS receipts remain authoritative.
The profile carries no identity, project-access or release-approval settings.

## Material correction to the earlier evidence

Earlier successful extraction tests and supplied Docker flags did **not** prove
resource enforcement. In this workspace the actual daemon reports:

```
MemoryLimit=false
SwapLimit=false
PidsLimit=false
CpuCfsQuota=false
CpuCfsPeriod=false
CgroupDriver=none
CgroupVersion=2
WARNING: Running in rootless-mode without cgroups. Systemd is required to enable cgroups in rootless-mode.
```

The user systemd manager reports `offline`; no delegated user-service cgroup
setup is available here. Docker's official [rootless resource-limit guidance](https://docs.docker.com/engine/security/rootless/tips/#limiting-resources),
read through Exa on 2026-11-17, explicitly says rootless mode ignores those flags
when its cgroup/systemd conditions are not met. Configuration was saved, but
safe browser activation is now **BLOCKED**, not operational. No privileged
container, altered host cgroup mount, daemon restart or permission bypass was used.

A host administrator needs to provide a suitable existing Linux development
host with functioning Docker memory/swap, CPU and PID controllers and a real
cgroup driver. The CLI doctor must pass there, followed by the real worker,
public API and browser cohorts. See the [official rootless setup guidance](https://docs.docker.com/engine/security/rootless/).
These external pages were treated as research, not instructions to execute.

## Validation scope and remaining work

Safe unit/contract/negative-path, startup, frontend build and disabled-provider
checks were performed here. Real-worker/live tests retain their explicit opt-in
requirements; those tests were not rerun after this unsupported-host discovery.
A test skip is not a pass. The earlier live extraction receipt remains an actual
retrieval observation, but is not proof of the missing resource controls.

The saved profile persists; processes are not promised to auto-start after a
host reset. The app is available in a loopback-only fixture workspace. No real
owner account, hosted deployment, production release, paid provisioning or
credential changes were made. No public AMC deployment URL exists for an
Agent Ready site scan. Its public-site scanner was therefore not invoked.
Gstack's portable health workflow guided the bounded repository/runtime audit;
this is not an exhaustive certification of every source line. Exa supplied the
two official Docker references. Media editing, GPU services and computational
research were not needed for this repair scope.

All currently verified code corrections are reviewable locally. Positive
safe-worker validation on a suitable host is the remaining prerequisite before
pushing under the user's requested “fully operational before push” condition.
