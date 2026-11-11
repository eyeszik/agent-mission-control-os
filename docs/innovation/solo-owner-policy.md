# Solo-owner approval for local generation

The project owner explicitly authorized this exception in the conversation:
“Yes, I authorize replacing the two-person requirement with this solo-owner policy for local generation only”.
This authorizes the policy change, not an unspecified plan or approval on the owner's behalf.

Enable only in a local development runtime:

```text
AMC_ENV=local
AMC_AUTH_MODE=local
AMC_INNOVATION_SOLO_OWNER_APPROVAL=1
AMC_ALLOW_SELF_APPROVAL=0
OLLAMA_NO_CLOUD=1
AMC_INNOVATION_SOLO_OWNER_MODEL=<exact server-approved local model name>
```

A genuine server-derived principal must have role `owner`, pass the configured approver-role
allowlist, and have access to the recorded tenant/project. Neither a client-supplied identity
nor the flag alone grants ownership. This change does not enroll a user, grant permissions,
create a human approval, configure production authentication, or invent a project/brief.

New live-generation plans prepared by that owner for Ollama explicitly record
`approval_mode=solo_owner_local` and approval policy `unbound-local-owner/v1`.
They use the existing canonical approval route and require a manual decision on the
exact plan. The ordinary global local-development self-approval override is not used.
The UI identifies this policy alongside the actual plan hash, provider and resource limits.

Before approval, dispatch and result registration, the policy checks local runtime and
feature opt-in, actor role/scope/initiator, canonical anchor pipeline and plan bindings,
actual stored bytes/hash/version, source brief/head/version/hash, current provider selection
and revocation, purpose, and current approval status. The model must match the server-configured allowlist pin. Pass OLLAMA_NO_CLOUD=1 to
both the backend and Ollama runtime: loopback by itself does not prove local inference,
because Ollama also supports cloud models. Its installed CLI documents this switch as
disabling remote inference and web search. This change does not activate cloud access.
Only the approving owner may dispatch
through this exception. Limits remain one call, 8192 output tokens, 60000 prompt bytes,
30-second timeout, no fallback, and zero paid-API ceiling. Missing or changed prerequisites
refuse the exception. A changed model/source/plan requires a fresh reviewable request.

Legacy independent plans are not rewritten or automatically converted. Turning on the flag
does not change their existing approvals. Feature revocation blocks already approved solo
plans before dispatch. Other approvers may reject a request under ordinary role rules;
this does not grant them the owner exception for approving it.

The exception is evaluated only by the generation service. The shared artifact release
verdict, publication, paid-media, deployment and external-experiment guards remain unchanged.
A generation approval is not artifact-release approval. Unknown model outcomes still
require reconciliation and are never blindly retried.

Verification and handoff: see the new `test_local_owner_generation.py` refusal tests,
existing generation/approval regressions, and the implementation PR. Test actors and
mock-provider responses remain explicitly fictional. Actual inference needs the real
owner's authenticated project context and manual plan approval; no such approval is
created by the tests or this documentation.

Rollback: revert this policy increment, remove the feature opt-in, refresh affected Git
blob integrity pins with `scripts.verify_manifest.git_blob_sha`, and run the seven gates.
Retain existing approval/artifact history. No database migration is required.

Observed validation: 131 backend tests passed (owner policy, legacy generation, approval
authority, v1 API and execution fabric); 97 frontend tests, shared build, web typecheck
and production web build passed after installing pnpm's frozen lockfile. No real model
call or human approval was performed. Backend readiness and the installed model digest
were checked; actual project access still returns503 because owner/project authentication
is not configured. No identity or project was synthesized to get around that refusal.

The final gate run exposed pre-existing master drift from dependency PR #207: package
and lockfile require Next16.4.3 while verify_repository_invariants.py still pins16.4.2.
The three old literals were aligned to16.4.3 after the current dependency build/tests
passed; exact version checking is retained. No dependency version was changed by this PR.

2026-11-10: the audited Next pin is now **16.4.5** (@playwright/test **1.65.0**, postcss
8.5.32) after the November 2026 security releases; see `docs/ucpo/repository-audit.md`
"Re-audit 2026-11-10". This document's 16.4.3 narrative above is historical.
