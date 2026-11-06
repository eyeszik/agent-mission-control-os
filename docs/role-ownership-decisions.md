# Role ownership decisions: the five framework modules without an N3 role

Status: **PROPOSED, NOT ACTIVATED.** Nothing in this document changes a role contract, a binding or a permission. Each decision below needs an owner or admin to accept it. Accepting one is a separate, reviewed change.

## How the gap was verified

Verified on `master` @ `6548bea4`:

- `services/langgraph/agency/operating_framework/bindings.py` marks five modules `NO_N3_ROLE`: AGM-11, 16, 17, 22 and 23.
- Those five modules hold 61 catalog tasks.
- The N3 registry (`agency/kernel/roles.py`, `ROLE_REGISTRY`) has 13 role contracts. None of them names these disciplines.
- Each of the five modules is bound to the nearest role whose `produces` includes the module's artifact type. `verify_bindings` checks that against the live kernel.

So the gap is real, but no role is missing for **authorization**: every binding already resolves to a role that may produce the artifact type. What is missing is a role whose *purpose* matches the discipline.

## Principles

1. **Reuse before adding.** A new N3 role would change N1/N3 parity (Zod twins, `verify_ontology_parity.py`), the integrity manifest and every planner that walks `produces`/`consumes`. That is only worth it if no existing role can carry the work without granting new authority.
2. **No new authority.** None of the five modules may publish, send, spend or contact anyone from this repository. Any proposed owner must keep `external_side_effect` unchanged.
3. **Evidence floors only go up.** A proposed owner's `min_evidence` must be at least the current binding's.
4. **Humans keep the decision.** Every proposal keeps `requires_human_approval=True`, except where the current binding already has it `False`. That is `brand_safety_reviewer`, whose output is a finding rather than a deliverable.

## Decisions

### AGM-11: SEO, Local Search & AI Discovery

**Current state**

| Field | Value |
| --- | --- |
| Tasks | 15, all at gate 03 Production |
| Catalog owner | `SearchDiscovery` |
| Binding | `brand_safety_reviewer` → `qa_report` |
| Native owner | `execution_fabric.seo_checks` (local SEO checks) |
| Capability | `LOCAL_AVAILABLE` |
| External effect | none |
| Deliverable | Technical SEO audit, content discovery map, localized visibility plan |

**Candidates**

- **`brand_safety_reviewer`** (current): produces `qa_report`; evidence floor 0; no human approval needed. An audit is a finding, which suits it. Its capability `brand_safety_review` under-describes "content discovery map".
- **`implementation_lead`**: produces `app_build_spec`/`implementation_plan`. Technical SEO fixes are implementation work. Requires human approval.
- **`analytics_lead`**: produces `measurement_plan`. Visibility *measurement* belongs here.

**Proposal: split by output, no new role.**

| Task type | Owner | Artifact | Inputs |
| --- | --- | --- | --- |
| Audit tasks | `brand_safety_reviewer` (unchanged) | `qa_report` | fabric SEO check results, `app_build_spec` |
| Remediation tasks | `implementation_lead` | `implementation_plan` | `qa_report` findings |
| Visibility measurement tasks | `analytics_lead` | `measurement_plan` | `campaign_package` |

- Evidence floor: unchanged for audits; 1 for measurement (matching `analytics_lead`).
- Approval boundary: remediation and measurement need human approval; audits stay findings.
- Conflicts: none. Rankings and AI citations are never promised. That rule already lives in the binding note.
- Migration impact: a per-task override map in `bindings.py` (new data, no schema change), plus tests.
- Alternative rejected: a new `search_specialist` N3 role. It would add parity, manifest and planner churn for no new authority.

**Decision: PROPOSED.** Accept → implement per-task overrides.

### AGM-16: Partnerships, Influencers & Referral Programs

**Current state**

| Field | Value |
| --- | --- |
| Tasks | 11, at gate 04 Activation |
| Catalog owner | `Partnerships` |
| Binding | `growth_lead` → `campaign_package` |
| Native owner | `agency_kernel.decisions` |
| Capability | `PLANNING_ONLY` |
| External effect | outreach, never dispatched |
| Deliverable | Partnership shortlist, referral economics, disclosure policy |

**Candidates**

- **`growth_lead`** (current): `campaign_planning`; consumes the design brief, concept and copy; requires human approval.
- **`brand_strategist`**: `offer_definition` covers referral economics.

**Proposal: keep `growth_lead` as owner.**

- Route referral-economics tasks through a `decision:` with alternatives, owned by `brand_strategist`. The framework already requires decision refs to carry alternatives.
- Disclosure policy needs a human-reviewed `qa_report` from `brand_safety_reviewer` before any partner material.
- Outreach stays `PLANNING_ONLY`. No role here may contact a third party, and contacting one needs a provider adapter that does not exist.
- Evidence floor: growth 0 → **1** for shortlist tasks, since a partner fit claim needs a source.
- Migration impact: per-task evidence override (data), plus tests.

**Decision: PROPOSED.**

### AGM-17: PR, Reputation & Social Proof

**Current state**

| Field | Value |
| --- | --- |
| Tasks | 11, at gate 04 Activation |
| Catalog owner | `Communications` |
| Binding | `copywriter` → `copy_variant` |
| Native owner | `project_os.publishing` (dry run) |
| Capability | `DRY_RUN_ONLY` |
| External effect | publish |
| Deliverable | PR narrative, verified proof library, response and disclosure playbook |

**Candidates**

- **`copywriter`** (current): narrative copy.
- **`brand_safety_reviewer`**: proof verification.
- **`release_manager`**: the only role with `external_side_effect=True` for releases. Rejected for authoring: it would put publish authority next to the author.

**Proposal: split author from verifier.**

| Task type | Owner | Artifact |
| --- | --- | --- |
| Narrative and playbook tasks | `copywriter` | `copy_variant` |
| "Verified proof library" tasks | `brand_safety_reviewer` | `qa_report` |

- A proof or testimonial counts only with a consent record and substantiation evidence.
- The framework's claim inventory (`claims.py`) routes every testimonial and quotation (`THIRD_PARTY_QUOTE`) to human review, and never treats a quotation as substantiation.
- Publication stays dry run.
- Migration impact: per-task overrides (data), plus tests.

**Decision: PROPOSED.**

### AGM-22: AI, Creative Operations & Automation Governance

**Current state**

| Field | Value |
| --- | --- |
| Tasks | 12, at gate 03 Production |
| Catalog owner | `AIQualitySecurity` |
| Binding | `brand_safety_reviewer` → `qa_report` |
| Native owner | model profiles and the provider capability registry |
| Capability | `LOCAL_AVAILABLE` |
| External effect | none |
| Deliverable | AI capability registry, prompt governance, controlled automation procedures |

**Candidates**

- **`brand_safety_reviewer`** (current): governance findings.
- **`implementation_lead`**: produces `automation_spec`, which covers the "controlled automation procedures" output.

**Proposal: split by output.**

| Task type | Owner | Artifact |
| --- | --- | --- |
| Registry and prompt-governance tasks | `brand_safety_reviewer` (unchanged) | `qa_report` |
| Automation procedure tasks | `implementation_lead` | `automation_spec` |

- Hard rule, already enforced: degraded generation (`FALLBACK_DEGRADED`) stays blocked from release, and no task here may enable a hosted provider or `ENABLE_REAL_MODELS`. That is an operator configuration decision.
- Migration impact: per-task overrides (data), plus tests.

**Decision: PROPOSED.**

### AGM-23: Agency Delivery, Finance & Client Governance

**Current state**

| Field | Value |
| --- | --- |
| Tasks | 12, at gate 02 Strategy |
| Catalog owner | `ClientOperations` |
| Binding | `implementation_lead` → `implementation_plan` |
| Native owner | `agency_kernel.decisions` + approvals |
| Capability | `HUMAN_ONLY` |
| External effect | none |
| Deliverable | Delivery charter, resourcing, financial controls, client approval matrix |

**Candidates**

- **`implementation_lead`** (current): owns delivery plans.
- **`release_manager`**: owns release records. Rejected: it carries release side-effect authority.

**Proposal: keep `implementation_lead` for the charter and resourcing.**

- Approval-matrix tasks are **not** role work. They configure who may decide. They must change the existing `approval_policy` / `AMC_APPROVER_ROLES` only through an owner/admin governance action (ACE v12 governance roles), never through a framework task transition.
- Financial controls are planning-only. Paid media stays planning-only.
- Evidence floor: 0 → **1** for financial-control tasks, which need a client-signed source.
- Migration impact: per-task evidence override, plus a guard test that no framework route can write approval policy.

**Decision: PROPOSED.**

## Summary

| Module | Proposed owner(s) | New N3 role? | New authority? | Evidence floor change |
| --- | --- | --- | --- | --- |
| AGM-11 | `brand_safety_reviewer` / `implementation_lead` / `analytics_lead` by task | No | No | Measurement tasks → 1 |
| AGM-16 | `growth_lead` (+ `brand_strategist` decisions, `brand_safety_reviewer` disclosure) | No | No | Shortlist tasks → 1 |
| AGM-17 | `copywriter` authoring, `brand_safety_reviewer` proof | No | No | Unchanged |
| AGM-22 | `brand_safety_reviewer` / `implementation_lead` by task | No | No | Unchanged |
| AGM-23 | `implementation_lead`; approval matrix stays owner/admin governance | No | No | Financial controls → 1 |

## What happens on acceptance

1. **Data:** add per-task overrides to `bindings.py`: role, artifact type and evidence floor.
2. **Checks:** `verify_bindings` checks each override against `ROLE_REGISTRY` (produces + capability).
3. **Tests:**
   - each override resolves;
   - no override raises `external_side_effect`;
   - no framework route writes approval policy.
4. **Manifest:** regenerate the manifest if `bindings.py` is pinned.
5. **Activation:** none. No module's external effect changes.

Alternative, if the owner prefers named disciplines: add five N3 roles. That changes N1/N3 parity, the Zod twins, `verify_ontology_parity.py`, the compiled planner's expansion and the manifest. **Not recommended** while the reuse option grants no less control.
