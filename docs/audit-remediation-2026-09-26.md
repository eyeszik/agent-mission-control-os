# Full-Service Agency Audit Remediation — 2026-09-26

Status: implementation in progress on `remediate/full-service-audit-2026-09-26`.

This document is the current truth boundary for the full-service agency audit
remediation. Earlier root planning artifacts remain available as provenance,
but statements in those files that the repository was unavailable are
historical and must not be interpreted as current runtime facts.

## Audited baseline

- baseline commit: `a36bc5e16afdfbd9d3c1efab6a5a7bd89e2e9beb`
- baseline tree: `57454d9bafbb97c9c139cda64cf09518447b9151`
- baseline finding: CI #214 failed three backend delivery/proof tests
- mutation policy: remediation branch only; no external publication, spend,
  infrastructure deployment, credential mutation, or production activation

## Repository-level remediation implemented on this branch

1. Delivery release guards evaluate intrinsic degraded-provider release
   invariants before derived invalidation state, while both remain fail-closed.
2. Delivery preserves deterministic post-generation workspace/artifact
   enrichment so successful delivery does not change the approved subject
   merely by dropping persisted fields.
3. Every live agency stage resolves an N3 role through
   `LIVE_STAGE_ROLE_BINDINGS`; artifact-producing stages call
   `assert_role_may_produce` before producing their canonical artifact.
4. Campaign intake now carries explicit `market`, `language`, and `locale`
   fields through backend, shared schemas, OpenAPI, and Mission Control UI.
5. Campaign assembly compiles `amc-agency-operations/v1`, which contains:
   research coverage, interview guide, stakeholder map, claim-proof records,
   rights/handoff records, accessibility evidence status, media-planning
   handoff, observability requirements, SLO records, and model-card records.
6. Missing evidence is never upgraded to proof. Competitive research,
   perception research, legal rights, portfolio permission, contrast evidence,
   assistive-technology verification, external telemetry binding, SLO
   baselines, and independent model evaluations remain explicit GAP/UNKNOWN/
   NOT_MEASURED states until real evidence is attached.
7. Browser CI includes an accessibility smoke for semantic labels, duplicate
   IDs, keyboard focus order, reduced-motion preference, and a measured text
   contrast target.

## External release gates that repository code cannot self-certify

The following require evidence outside a source-code-only audit and therefore
must remain human/environment gates:

- counsel/qualified review where claims, rights, regulated content, or other
  legal-readiness conditions require it;
- ownership/license/portfolio/territory/expiry evidence for final assets;
- manual assistive-technology testing for relevant production surfaces;
- a deployed observability backend or equivalent runtime evidence for
  service-level logs/metrics/traces;
- measured production baselines before numeric SLO targets are promoted from
  `UNSET`;
- provider/model evaluation evidence before a model-card evaluation status can
  become `SOURCE_ATTACHED`;
- production deployment approval and separate activation of any external
  publication or paid-media adapter.

These are not implementation failures and must not be silently converted to
PASS. They are explicit acceptance dependencies.

## Release acceptance

The remediation is not release-accepted until the branch's final revision
passes the complete repository CI suite, including backend tests, shared/web
tests, typecheck/build, browser E2E, dependency audit, repository verifier
gates, and the integrity manifest. The integrity manifest must be regenerated
only after the protected-file change set stabilizes.
