# VNEXUS ACE v9 — Brand Genome & Autonomous Creative Intelligence OS

Status: **foundation only / not production-complete**. The companion pure TypeScript module implements approved inheritance, immutable constraints, branch comparison, transitive dependency impact and evidence-gated asset claims. No provider calls, migrations, production UI, approval persistence, or payments are enabled by this change.

## Integration boundary

Extend the existing Creative Search Runtime, five-pass prompt compiler, canonical hashing, flight recorder, approval gates, creative-capability registry, project workspace, and design-style composer. Do not introduce a second workflow orchestrator. Preserve `PROMPT_PACKAGE_READY` as the compiler terminal state; provider execution is a distinct downstream job lifecycle.

Existing integration surfaces to audit before further changes:

- `apps/web/components/mission-control/CreativeFoundryPanel.tsx`
- `apps/web/components/mission-control/DesignStyleComposerPanel.tsx`
- `apps/web/components/mission-control/ProjectWorkspacePanel.tsx`
- `apps/web/lib/design/composer.ts`
- `apps/web/lib/api/design.ts`, `apps/web/lib/api/projects.ts`
- `apps/web/lib/stores/designStore.ts`, `apps/web/lib/stores/projectStore.ts`
- `knowledge/creative-capabilities/registry.json`
- `docs/brand-content-visual-prompt-os.md`, `docs/creative-runtime.md`, `docs/project-os.md`

## Brand genome contract

Genome layers resolve **Brand → Project → Page → Component → Asset**. Only APPROVED layers affect authoritative values. Immutable keys cannot be changed by descendants; conflicting attempts are reported and skipped. A future persistence implementation must enforce tenant/project authorization and bind approvals to immutable canonical guide and artifact hashes, reusing the existing hash/recorder implementation rather than inventing another algorithm.

Proposed chromosomes: strategy, visual, verbal, experience, production. The typed layer resolver is intentionally a small primitive, not a claim to implement the entire genome model.

## Creative Multiverse

Maintain immutable branch ancestry and explicit review states. Fork, mutate, compare, cherry-pick, merge, rebase-on-guide, and archive require durable server-side persistence, provenance and conflict review. The foundation currently provides deterministic branch comparison only; **merge and approval are not implemented**. Subjective design scores remain labeled as model-assisted assessments, never objective facts.

## Experience compiler and art direction

Compile a project brief and approved genome into page objectives, audience intent, content architecture, token bindings, component tree, interaction states, responsive specifications, visual asset requirements, accessibility tests and implementation packages. Incrementally invalidate downstream nodes when a source changes. The foundation implements a dependency impact helper; it does not yet compile pages.

Art-direction contracts should govern typography, palette, composition, imagery, motion, accessibility and brand usage. Deterministic checks and model-assisted reviews must be distinguished.

## Prompt genome

The intended library contains 14 source prompts. Import **only original verified source text**, byte-preserved with a source hash. Do not manufacture missing prompt content. Missing entries must remain `SOURCE_REQUIRED` / `PARTIAL_IMPORT`. Derived prompt variants require separate versioning and ancestry. A prompt is optional according to project requirements, never a mandatory 14-step pipeline.

## Provider-neutral media fabric

Capability discovery precedes provider selection. A ChatGPT plugin connection is not a repository credential. Adobe and OpenArt adapters remain disabled until authentication, scopes, licensing, schema, model availability, cost quotes, and artifact retrieval have been independently verified in the deployed environment. Never hardcode illustrative model pricing.

Downstream production states: PACKAGE_READY → CAPABILITY_VERIFIED → COST_AUTHORIZED → JOB_RESERVED → SUBMITTED → RUNNING → ARTIFACT_RECEIVED → VALIDATION → HUMAN_REVIEW → APPROVED → EXPORTED. On uncertain submission, reconcile the provider job before retrying. Never label an asset generated without validated evidence and a content hash. Enforce server-side authorization, project isolation and explicit spending approval.

## Design immune system and digital twin

Detect brand token drift, invalid marks, unapproved typography, accessibility regressions, missing references, stale dependencies and unauthorized changes. Produce evidence-backed findings and reversible repair proposals. The digital twin should support no-spend simulations of provider outages, budget exhaustion, guide revisions, concurrent edits and failed assets. Simulation is not production evidence or measured audience performance.

## Delivery sequence

1. Audit existing schemas, storage, API contracts, authentication and approval mechanics.
2. Add versioned genome persistence and project-scoped authorization.
3. Connect inheritance and lineage to existing project/creative UI.
4. Implement branching and conflict-safe review/merge.
5. Extend the existing compiler with page-level output and dependency invalidation.
6. Implement drift detection and deterministic quality gates.
7. Add no-spend workflow simulation.
8. Add verified, feature-flagged provider adapters with idempotent paid-job handling.
9. Import the 14 original prompts when their source texts are available.
10. Validate accessibility, tenant isolation, audit integrity, migrations, rollback and CI.

## Acceptance criteria

A new brand inherits approved values; conflicting immutable overrides are blocked; parallel branches compare deterministically; guide changes identify downstream impact; simulations never count as generated assets; missing prompt sources do not get fabricated; unverified providers never spend credits; cross-project reads are denied; approved histories remain immutable. The current PR tests only the pure-function subset.

## Follow-up status

This foundation is a reviewable first slice of the requested system, **not** full implementation of all 30 innovation concepts. Subsequent work should be split into separately reviewable PRs, with feature flags and migration/rollback plans.
