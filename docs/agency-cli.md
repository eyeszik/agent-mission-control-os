# Agency CLI

A command-line surface onto the agency kernel.

The implementation is
[`services/langgraph/agency/cli.py`](../services/langgraph/agency/cli.py);
`orchestrate_brand_pipeline.py` at the repository root is a thin shim so the
`make` and `pnpm` entry points work from a checkout.

## What it does and does not do

It **plans**. Given a brief, it resolves the artifacts you asked for to the
roles N3 says may produce them, checks the evidence floors and consumed inputs
those contracts declare, and walks the N2 engagement matrix applying the real
release guards.

It **generates nothing**. No copy, no imagery, no assets. A plan is a statement
about what the kernel would permit, not a claim that work happened. This matters
because the tool it replaced logged eleven hardcoded `STATE TRANSITION` lines —
including `ASSETS_GENERATED` and `ASSETS_VALIDATED` — and wrote its own input
back out stamped `"status": "SUCCESS"`, while doing none of it.

Blockers are the primary output, and the exit code carries them:

| Exit | Meaning |
| --- | --- |
| `0` | Requested phase reachable, no unmet inputs or evidence gaps |
| `1` | Blocked — a guard, a missing input, or an evidence floor stops it |
| `2` | The brief itself could not be interpreted |

Nothing in this file re-states a rule. Artifact types come from
`resolve_artifact_type`, producers from `ROLE_REGISTRY`, evidence floors from
the role contract, and every lifecycle verdict from `transition_failures`. When
the kernel changes, the CLI changes with it.

## Commands

```bash
python3 orchestrate_brand_pipeline.py plan --input sample_brief.json
python3 orchestrate_brand_pipeline.py plan --input brief.json --json
python3 orchestrate_brand_pipeline.py roles --department brand
python3 orchestrate_brand_pipeline.py validate
```

Or through `make`:

```bash
make brand-plan                    # uses sample_brief.json
make brand-plan BRIEF=mybrief.json
make brand-roles DEPT=growth
make brand-validate
make gates                         # every CI verifier gate
```

`validate` runs the kernel's own structural self-checks — `validate_matrices()`,
`validate_registry()`, and `validate_merge_matrix()` — which otherwise only run
inside the test suite.

## The brief

```json
{
  "project_name": "Northwind Coffee Rebrand",
  "target_artifacts": ["positioning_statement", "brand_core", "campaign_package"],
  "available_inputs": ["research_brief", "market_analysis"],
  "target_phase": "launched",
  "evidence_count": 3,
  "facts": {
    "generation_mode": "PRIMARY",
    "approval_exists": true,
    "approval_resolved": true,
    "approval_decision": "approve",
    "brand_safety_passed": true,
    "spend_authorized": false
  }
}
```

| Field | Meaning |
| --- | --- |
| `target_artifacts` | What the engagement should produce. Validated against the N1 ontology — an unknown name is an error listing the real types, not a silent pass |
| `available_inputs` | Artifact types already in hand, so a consumed input is not reported as a gap merely because this brief does not also ask for it |
| `target_phase` | An `EngagementStatus`. Defaults to `launched` |
| `evidence_count` | Evidence items backing the run, checked against each role's `min_evidence` |
| `facts` | What is known to be true, fed to the lifecycle guards |

`facts` mirrors `TransitionContext`. **Anything absent is unproven** — an
unstated approval is a missing approval, which is the fail-closed direction.
Unknown fields are rejected rather than ignored, so a typo in a fact name
cannot quietly weaken a guard.

## Reading a blocked plan

```
Lifecycle
  ok   build -> launch_ready
  BLOCK launch_ready -> launched
        approval_missing: no human approval exists for this run
```

The code (`approval_missing`) is the kernel's stable guard code from
`RELEASE_GUARDS`, not a string this CLI invented, so it can be matched on
without parsing prose. The guards that can appear here are the same ones that
gate real releases: degraded provenance, missing/unresolved/rejected approval,
failed brand safety, unauthorized external side effects, and unmet hard
dependencies.
