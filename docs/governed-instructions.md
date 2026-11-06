# Governed instruction packages

## Reconciliation and decision record

Baseline: `d0c78fc7` (master observed during implementation, after PR #192).
This extension compiles instruction **data** and checks its binding to existing
work; it does not add an autonomous agent, model executor, scheduler or approval.
The user-selected scope is opt-in compilation and enforcement, existing execution
paths only, and principles-only use of the named coding-agent systems. No claims
about their implementations, origins or licenses have been imported.

ADR: reuse the existing compiled-agency → PCWO → fabric path. Store package bytes
through the existing scoped content-addressed adapter, record references through
Project OS events, and bind the full package to the existing input hash, dispatch
permit and execution receipt. Recompile from current trusted sources immediately
before dispatch, retry and commit. Package hashes prove content relationships,
not authority, signatures, source authenticity or human approval.

### Requirement / owner / implementation / acceptance map

| Requirement | Existing owner and reuse disposition | Extension and acceptance test |
|---|---|---|
| R-AUTHORITY | N1–N4, AuthorityBridge, server ExecutionContext; preserve | Recompile capability and role binding; reject forged/self-consistent packages |
| R-ROLE | RoleResolver and N3 role registry; reuse | Resolve exact canonical specialist; compare N3 and RoleOS namespaces separately |
| R-SCOPE | Tenant/project authorization and scoped storage; preserve | Package scope changes invalidate binding; cross-scope enrollment refused |
| R-PROVENANCE | AMC-CANON-1 and dependency/context hashes; reuse | Bind policy, guidance, adapter and optional profile; stale packages refused |
| R-METHOD | Existing deterministic guidance router; reuse | Select only relevant advisory sections; explain injection and budget exclusions |
| R-TOOLS | Skill dispatcher and provider gates; preserve | No extra tools or providers; missing executor/provider remains blocked |
| R-GOVERNANCE | N2 release guards and authenticated approvals; preserve | Successful bound work still stops at NEEDS_HUMAN |
| R-OUTPUT | Existing artifact contracts and independent verifiers; preserve | Same supported artifact bytes with/without instructions; no release claim |
| R-ACCEPTANCE | Work-order acceptance criteria; reuse | Included in typed package and diff, never manufactured as passed evidence |
| R-STOP | Fabric budgets and dependency invalidation; reuse | Mandatory-section overflow blocks; no recursion or tool calls in compiler |
| R-REPLAY | Existing WAL/permits/receipt reconciliation; reuse | Same package replays; changed package gets a new key; crash recovery adopts only matching output |
| R-COMPAT | Optional server selection; new | Omitted selection preserves legacy context serialization, hashes and execution keys |
| R-REPORT | New strict delivery schema | Runtime JSON Schema validation and Python/Zod fixtures; unknown metrics remain null |
| R-ROLLBACK | Existing run metadata; extend monotonically | Enrolled run cannot resume with an omitted selection |

The definitions, references, runtime entry points and regressions were inspected;
absence from documentation was not used as evidence of a missing implementation.
Existing method envelopes already enforce delegation depth and bounded retries.
This release does not delegate or create specialist agents. It does not add new
MCP gateways, compaction engines, telemetry providers or live model skills.

## Contract and usage

`agency/compiled/instruction_models.py` defines frozen extra-forbidden packages,
selections, compilation reports, diff certificates and delivery reports. The
package is bound to tenant/project, work order, contract/context/dependencies,
canonical roles, current policy source bytes, selected guidance and the optional
pinned model-profile identity. Timestamps and credentials are not semantic inputs.

Add this selection to a **trusted local** `fabric-run` request:

```json
{"instructions": {"task_type": "implementation", "max_sections": 16, "max_bytes": 32768}}
```

Task types: research, architecture, implementation, validation and delivery.
These labels narrow instructions; they do not introduce new N3 roles or grant
permissions. A deterministic skill retains its existing behavior and output
contract. Research/architecture/validation text is advisory task discipline,
not a claim that arbitrary code execution has been sandboxed by a prompt.

Compile without execution:

```bash
python orchestrate_brand_pipeline.py compile-instructions \
  --input /path/to/fabric-request.json --output /path/to/instructions.json
```

The artifact contains each cell's package, rejected sections, budgets, blockers
and initial diff certificate. Stdout is a validated strict delivery report.
`COMPLETE` with operation `PROMPT` means compilation completed, never execution
or production readiness. Missing selection is an input error. Ordinary `fabric-run`
accepts the same optional selection and enforces its packages before dispatch.
There is no new HTTP endpoint or browser-supplied authoritative package input.

Mandatory sections are ROLE, OBJECTIVE, INPUT, AUTHORITY, TOOLS, CONSTRAINTS,
OUTPUT, ACCEPTANCE and STOP_RULE. Remaining space admits deterministically routed
advisory guidance, ordered by stable section key. Context limits count UTF-8 bytes
of section headings and text, **not tokens**. Mandatory overflow fails closed;
optional exclusions have reason codes. The existing injection scanner is a narrow
defense, not proof that arbitrary source text is safe. No imported instruction
can populate trusted capabilities or approvals.

Provider descriptors identify plain-text instruction formatting for the existing
OpenAI, Anthropic, Gemini and Ollama profile vocabulary. They make no provider
calls and establish no availability or advanced feature support. Model-profile
changes alter package identity; existing provider degradation and release gates
remain in force. N3 capability checks and RoleOS expertise are recorded in separate
namespaces; copying a RoleOS skill name into N3 is never a capability grant.

## Evidence, evaluation and rollback

Selected package JSON is persisted as scoped object bytes. Events expose only
its location, byte hash, semantic hash and execution key, not instruction text.
Existing permits and receipts bind the input hash containing the package.
Changing instructions produces a new execution key; uncertain prior writes are
reconciled by the existing WAL. Package verification is independently repeated
from current sources, including for self-consistent but forged package hashes.

Evaluation uses matched deterministic work with/without selection: compare actual
artifact bytes, hard gate outcomes, execution keys and observed replay behavior.
Mandatory sections cannot be removed without invalidating the package. Optional
sections survive only when the existing guidance router selects them and the
budget admits them; relevance is not a measured quality improvement. No latency,
token, dollar-cost or quality gains are claimed. No Datadog integration is added.
Live provider evidence was not used; no production provider-readiness claim is made.

Run focused Python compiler/fabric/CLI regressions, shared contract fixtures and
all seven repository gates. Full backend and hosted CI results must be reported
against their actual revision; skips are not passing coverage. Finite regressions
do not prove universal security. A real project is not configured by these tests.

Regenerate schema/parity fixtures deliberately after compiler/policy edits:

```bash
AMC_REGENERATE_FIXTURES=1 python -m pytest \
  services/langgraph/tests/test_instruction_packages.py -q
```

The fixture is explicitly fictional and binds the current compiler/policy bytes.
After any covered source edit, refresh only affected manifest entries with
`scripts.verify_manifest.git_blob_sha`, preserving all coverage, then run gates.

Rollback: omit the selection for **new** missions. Once enrolled, a run retains
`instructions_required` in existing run metadata; silently omitting selection on
that run is refused. Resume with its reviewed selection or create a separately
identified new mission. Reverting code must not downgrade or falsely adopt an
in-flight bound run; retain its receipts and reconcile it before removal.
