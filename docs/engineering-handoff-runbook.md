# Engineering handoff — local runbook (partial)

**Status: local engineering scaffolding only.** This is not an active agency route, registered worker, production executor, or deployed service. The reference policy under `services/langgraph/agency/engineering/execution-policy.example.json` is deliberately disabled and is not loaded by the application. No provider, MCP, GitHub, browser, deployment, or remote-write operation is part of this runbook.

## Implemented path

```text
authenticated Principal + project scope
  -> HandoffRequest validation
  -> canonical deterministic key
  -> persistence.durable_runs.create_job (existing durable_jobs + initial transition)
  -> immutable ContextRecord / PlanRecord hashes (in-memory fixture inputs)
  -> disposable user/mount/network/PID namespace + minimal chroot
  -> fixed stdlib-unittest controller against caller-supplied synthetic files
  -> ExecutionResultRecord bound to plan, context, patched tree, environment and checks
```

The accepted intake record requests work; it does **not** grant authority to execute its requested actions. `submit_handoff` records an explicit `UNVERIFIED` authority gate and a disabled live-GitHub gate. No new table, scheduler, state machine, or transition writer was added. `persistence.durable_runs.create_job` creates the durable job and its first transition; future moves must use the existing `agency.durable.ticks.run_tick` / `durable_runs.transition` path. The FSM guarantee remains at-least-once with reconciliation, not exactly-once.

## Prerequisites and verification

Use a supported Linux host with Python 3.10+, `unshare`, `mount`, and permission to create user, mount, network, and PID namespaces. The sandbox probes the controls it uses and returns `BLOCKED` if a required probe fails. It never retries a failed isolation launch on the host.

The repository currently has unbounded Python dependency constraints and no Python lockfile. These commands are useful for local verification, not a reproducible production installation:

```bash
python -m venv .venv
.venv/bin/python -m pip install -e 'services/langgraph[dev]'
.venv/bin/python -m pytest \
  services/langgraph/tests/test_engineering_contracts.py \
  services/langgraph/tests/test_engineering_intake.py \
  services/langgraph/tests/test_engineering_sandbox.py -q
```

Probe the local namespace without enabling any product worker:

```bash
.venv/bin/python - <<'PY'
from services.langgraph.agency.engineering.sandbox import probe_isolation
receipt = probe_isolation()
print(receipt.model_dump_json(indent=2))
if not receipt.available:
    raise SystemExit(2)
PY
```

`probe_isolation` compares user, mount, network, and PID namespace identities with the parent; it also verifies PID 1 in the private PID namespace, no non-loopback network interface or route, read-only workspace/runtime/root paths, writable `/tmp` with the configured byte/inode bounds, the scrubbed environment, capability drop, `no_new_privs`, and effective per-process rlimits. It performs a bounded fork probe to check that `RLIMIT_NPROC` is enforced. The recorded environment hash includes namespace observations, tmpfs facts, interpreter/kernel facts, the fixed runner source hash, limits, and fixed environment. The synthetic tests exercise `RLIMIT_AS` and `RLIMIT_CPU`; none of these controls establish aggregate cgroup limits or a production boundary.

## Fixture execution contract

`execute_synthetic_fixture_patch` is intentionally only a local synthetic-fixture helper. The caller supplies a complete, non-empty UTF-8 text snapshot, a `ContextRecord`, a `PlanRecord`, and a non-empty patch. Before launching anything it verifies:

- exact context path set, byte sizes, blob hashes, context manifest hash, base revision, base tree hash, and plan hash;
- path allowlist, no traversal/sensitive runtime paths, no file/ancestor conflicts, bounded file count/size, and no binary or no-op patch;
- declared checks use the fixed `python -S -m unittest -v <module>` contract, test modules exist in the original immutable snapshot, and tests are unchanged by the patch;
- only the fixed in-chroot controller is invoked; the controller must discover and run at least one test and emit its structured result.

The sandbox contains no host checkout, `.git`, home directory, credentials, API client, MCP process, or external network route. It does not install dependencies, run npm/pnpm, compile a real product, create a patch in the host tree, or call a provider. Raw output is transient and not persisted; only bounded bytes, output hash where complete, and a short generic summary are recorded. The temporary root is discarded.

## Important isolation limits

This kernel exposes `/sys/fs/cgroup` read-only. The receipt therefore states that aggregate cgroup CPU, memory, and PID limits are unavailable. The available controls are per-process `RLIMIT_AS`, `RLIMIT_CPU`, `RLIMIT_NPROC`, file-size/open-file/core limits, a private PID namespace, a read-only root/workspace/runtime, and a size/inode-bounded tmpfs. `seccomp` is not configured; the kernel is shared. These controls are **not** an authorization to run arbitrary model-generated or attacker-controlled code. `model_generated_code` must remain blocked until a separately reviewed executor has appropriate aggregate resource controls and syscall filtering, with production threat-model and deployment evidence.

## Supplemental design guardrail helpers

`agency/design/guardrails/filters.py` is standalone utility code, not an active DesignSync subsystem or a wired policy boundary. It redacts selected email/token patterns, enforces the exact HTTPS hostname allowlist, accepts optional resolved-address checks, applies thread-safe process-local sliding windows, and returns the requested visual/accessibility review decision. It makes no network request, persists no quota, pauses no durable job, and sends no Slack notification.

For a real outbound request, resolve and validate all addresses, pin the same addresses in the transport, re-check every redirect, and enforce egress controls outside this helper. Use an authenticated server-derived client identity; a multi-worker deployment needs a shared quota owner. Run redaction before log persistence/export, but do not treat regex scrubbing as comprehensive DLP. A HITL result must be connected to AMC's canonical approval/FSM owners; the percentage threshold is not a WCAG conformance assertion.

## Intake and recovery

- Identical canonical handoffs from the same principal, tenant, and project resolve to the same deterministic job id and spec hash. A changed source, brief, objective, budget, action, requester, or project produces a different identity.
- Project scope and tenant are taken from the authenticated `Principal` and function argument; they are not accepted from the handoff body.
- There is no registered engineering job handler. A bounded local `run_tick` with an empty handler map transitions the job to `BLOCKED_ENVIRONMENT` and creates no intent. Do not add an implicit host or provider fallback.
- No engineering retry/worker/recovery loop is active. For any future side effect, persist intent first and reconcile an ambiguous outcome before retrying, using the existing durable tick protocol.
- Drift in the base tree, context, plan, policy, or tested tree invalidates dependent checks/approvals. The current fixture executor refuses a stale context/plan and never applies a patch to the real checkout.

## Start / stop / deployment

There is no engineering-specific HTTP route, UI surface, worker registration, scheduler, MCP server, provider adapter, GitHub client, or deployed process to start or stop. **Do not deploy or enable the example policy.** Existing AMC services and creative/marketing workflows are unchanged.

A future local draft PR must remain a local artifact until a separate approval binds the exact base revision, plan/context hashes, tested tree hash, patch hash, target repository, and `CREATE_DRAFT_PR` action; that approval must be rechecked for expiry, revocation, scope, policy drift, and separation of duties immediately before delivery. No such review or delivery operation is implemented here.

## Operations owner

No engineering runtime owner is configured in the repository. Until an explicit owner and production isolation implementation are assigned, this runbook is for repository maintainers running synthetic tests locally only.
