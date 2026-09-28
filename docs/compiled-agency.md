# Compiled Agency control plane

`services/langgraph/agency/compiled/` compiles *requested outcomes* into a
governed, proof-carrying plan over the existing Agent Mission Control runtime.
It is a planning layer: it never calls a model, writes to the database,
contacts a provider, or reads the wall clock. Given the same canonical request,
the same sealed RoleOS registry and the same policy, it produces the same
`plan_hash`.

It was built from the `SYS:MASTER_COMPILED_AGENCY_OS_vΩ` execution
specification and the `agency-role-os-v2` source archive
(sha256 `d98182dd…a757`, 1,177 files). The keystone constraint holds: **new code
composes existing primitives** and creates no competing RoleOS, lifecycle,
artifact registry, approval store, authorization model, event, tenant or proof
system.

## What it composes

| Existing primitive | How the compiled layer uses it |
| --- | --- |
| `runtime/role_os` sealed registry (1,097 roles) | Specialist selection by exact skill name; `DENY_CONSEQUENTIAL_BY_DEFAULT` sets every side-effect ceiling |
| `role_os.RoleResolver` / `WorkOrderCompiler` | Every PCWO wraps a canonical work order (stable `wo-`/`op-` ids, `MISSING_*` blockers, `retry_limit` 3) |
| N1 `ArtifactType` / N3 `ROLE_REGISTRY` | Backchain expansion: producer = role that `produces`, prerequisites = its `consumes`, evidence floor = `min_evidence` |
| N2 `release_guard_failures` | Release readiness per deliverable (degraded, approval, brand safety, spend, dependencies) |
| N4 `content_fingerprint` | The only canonical hash (`hashing.py`) |
| `kernel.models.EpistemicStatus` | Bridged from genome epistemic statuses |
| `persistence/approvals.py` rows | `scope_from_approval_record` adapts `subject_hash`/`policy_version`/server-bound reviewer into an `ApprovalScope` |
| `persistence/events.py` rows | Measurement and process mining read real `node_complete`/`approval_*`/`artifact_generated` events |
| `app/config.py` publication / paid-media modes | API reports providers `UNAVAILABLE`; no live adapter exists |

## Modules (spec task → file)

| Task | Module | Purpose |
| --- | --- | --- |
| T02/T07 | `role_sources.py`, `data/source_disposition.json` | Disposition ledger for all 1,177 archive files; `RoleSourceIndex` (role_id + skill_path + sha256); hash-verified JIT SKILL loader with prompt-injection quarantine |
| T03/T04 | `evidence.py` | `SourceRecord`, claims, triangulation deficits, `RuleCandidate` promotion (A→B→C, never A→C), volatile requirement firewall |
| T05 | `ontology.py` | S00–S25 process ontology, MB0–MB8 conditional overlays, per-domain process maps, 35-kind exception catalog with failure routes |
| T08/T09 | `context.py` | `CompanyGenome` projection (conflicts/unknowns preserved), minimum-context `ContextCapsule`, `INVALIDATED_CONTEXT` |
| T10 | `backchain.py` | `DeliverableSpec` → Causal Work Graph with CSE, dead/orphan elimination, cycle check, counterfactual necessity |
| T11 | `authority.py` | ASG/AuthorityBridge: RoleOS specialist × N3 contract; grants per the sealed grant contract; `CAPABILITY_GAP` / `AUTHORITY_UNRESOLVED`; RACI kept separate |
| T12 | `validation.py` | EVG obligations, 13 conditional validation profiles, independent review, smallest-causal-producer repair, ≤3 repairs, N2 release delegation |
| T13 | `autonomy.py` | L0–L6 classifier; scores never grant autonomy; L6 only with governance approval (AUTONOMY_ESCROW) |
| T14 | `work_orders.py` | Proof-carrying work orders over `WorkOrderCompiler` |
| T15 | `decisions.py` | DecisionSpine: immutable accepted versions, revision → `DecisionDiff` of stale causal descendants |
| T16/T17 | `execution.py` | MissionCells (lifecycle enforced) and execution waves (parallel PURE/DRAFT, serialized collisions and external actions, held cells with reasons) |
| T18/T19 | `change_control.py` | `BlastRadiusCertificate`, ArtifactDNA, `ApprovalScope` / DeltaApproval (`VALID`, `STALE_APPROVAL`, `FULL_GATE_REPLAY`) |
| — | `planner.py` | `compile_agency_plan`: the §21 `Executable(node)` predicate and the §50 19-dimension node invariant |
| T22 | `measurement.py` | Metrics from actual events; `NOT_MEASURED` otherwise |
| T23 | `learning.py` | Append-only hash-chained, tenant-scoped learning ledger; protected targets become `GovernanceProposal`s |
| T24 | `twin.py` | Digital-twin shadow scenarios S1–S13 |
| T21 | `api/routes/compiled_agency.py` | `/compiled-agency/v1/{profile,rules,plan,twin}` |

## Authority model

* A RoleOS specialist supplies expertise and procedure. The N3 `RoleContract`
  is the permission envelope. The binding's side-effect ceiling is the
  intersection of both, and no title, seniority, department, SKILL text,
  resolver rank or model score can raise it.
* Consequential work (`REVERSIBLE_WRITE`, `IRREVERSIBLE_WRITE`) needs an N3 role
  that declares `external_side_effect`, a non-expired, non-self-issued
  `AuthorityGrant` matching operation and target, an exact approval ref, and a
  verified provider. The API **discards** client-supplied approvals, grants and
  provider status, so over HTTP an external action always plans as
  `PROVIDER_UNAVAILABLE` + `AUTHORITY_UNRESOLVED`.
* P11 acceptance and P12 external release are separate nodes.

## Source disposition

`python3 orchestrate_brand_pipeline.py source-disposition --archive <zip> [--check]`
rebuilds or checks the ledger. The invariant `disposition_count ==
verified_source_file_count == 1177` is tested. Current counts:
`JIT_SKILL_SOURCE` 1097, `DOCUMENTATION` 19, `REFERENCE_ONLY` 16,
`ORCHESTRATOR_SOURCE` 14, `SCHEMA_SOURCE` 11, `QUARANTINED_CONFLICT` 8,
`RUNTIME_COMPILED` 3, `SUPERSEDED_BY_REPO` 3, `ADVISORY` 3, `TEST_FIXTURE` 2,
`DUPLICATE_OF_RUNTIME` 1. The quarantined files link to the repository's
existing disposition records (R08, R09, R12–R14, R21). One of them,
`vnexus-operating-prompt.md`, embeds prompt-injection text. The SKILL bodies
(15.7 MB) are **not vendored**. They load just in time from a verified archive
or an extracted directory, and only for selected specialists.

## Usage

```bash
python3 orchestrate_brand_pipeline.py compiled-plan -i sample_compiled_request.json [--source-archive agency-role-os-v2.zip] [--json]
python3 orchestrate_brand_pipeline.py compiled-twin
make compiled-plan / make compiled-twin
```

`compiled-plan` exits 0 when the only holds are human gates. It exits 1 on any
structural blocker, and the sample request deliberately shows the fail-closed
external publish. It exits 2 on invalid input.

## Specification output contract (§49 A–T)

| § | Content | Where / status |
| --- | --- | --- |
| A | Research methodology | `evidence.py` (SourceRecord, claim labels, triangulation). **GAP**: no external research corpus was supplied or retrieved; the numeric citation markers in the spec are unrecoverable |
| B | Source-quality / grounding model | `SourceClass`, `EvidenceStrength`, `RUNTIME_SUFFICIENT_SOURCES`, triangulation deficits |
| C | Rule-promotion ledger | `SPEC_RULE_CANDIDATES` / `GET /compiled-agency/v1/rules`: 13 candidates, 3 runtime-constraint candidates (all repository-evidence), 5 org-policy candidates, 4 GAP, 1 CONFLICTED |
| D | Universal lifecycle | `ontology.LIFECYCLE_STAGES` (S00–S25 → RoleOS P0–P15, advisory) |
| E | Master Builder overlays | `ontology.MASTER_BUILDER_OVERLAYS`, `select_overlays` |
| F | Per-domain process maps | `ontology.DOMAIN_PROCESS_MAPS` (spec-supplied patterns, not verified industry fact) |
| G | Department/capability topology | N3 contracts × `authority.N3_SPECIALISTS` × 1,097 sealed roles |
| H | Artifact encyclopedia | N1 `ArtifactType` (27) with `ontology.ARTIFACT_STAGE`. **GAP**: film masters, packaging and other domain artifacts are not N1 types and surface as `ARTIFACT_TYPE_UNMODELED` |
| I | Task/process registry | Compiled CWG nodes + PCWOs per plan |
| J | Decision/approval topology | `backchain.MATERIAL_DECISIONS`, DecisionSpine, ApprovalScope |
| K | Exception catalog | `ontology.EXCEPTION_CATALOG` (35 kinds → 12 routes) |
| L | Tool ecosystem | `docs/agency-role-os/tool_and_approver_contract.json` (unchanged); binding `permitted_tools` |
| M | Human→AI translation matrix | `autonomy.classify` routes (AUTOMATE … BLOCK_RESEARCH) × L0–L6 |
| N | Compiled runtime architecture | This document |
| O | Governance/security/privacy/IP | Authority model above; validation profiles TRADEMARK, PRIVACY, SECURITY, VIDEO_RIGHTS, CLAIMS_LEGAL, AI_POLICY |
| P | Evaluation/observability | `measurement.py`, digital twin |
| Q | Implementation/staging roadmap | "Open integration work" below |
| R | Deduplicated source registry | `data/source_disposition.json` |
| S | Residual evidence gaps | Below |
| T | Repository implementation evidence | `tests/test_compiled_agency.py`, PR description |

## Residual gaps and open integration work

* **Layer 1 is not wired to this planner.** The live LangGraph pipeline does
  not consume compiled plans. That is a deliberate integration task, as it
  already is for the N1–N4 kernel.
* **Approvals are not bound to compiled node ids.** Persisted approvals bind
  run results. Until a server-side mapping exists the API ignores approvals and
  grants (fail-closed).
* **No research corpus.** Industry-process claims are the specification's own
  patterns, classified `PRACTITIONER_PATTERN`/`CASE_STUDY`. Volatile facts
  (store limits, accessibility and security standard versions) are `GAP` until
  officially re-verified as `VolatileConstraint`s.
* **No real historical project data.** S10 replays a synthetic event log.
* **No live providers.** Publication and paid media stay disabled. Nothing in
  this layer can publish, deploy, send or spend.
* **Optional UI (T25) not built**, and there is no Zod twin for the plan
  response yet.
