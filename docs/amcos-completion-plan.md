# AMCOS unified production — completion plan and working register

Branch: `arena/13d8169f-agent-mission-control-os` • Base: `04258078f409269867dc25a50dffcdfe711717af` • Updated: 2026-11-09 UTC.

This is the working plan for the **unified-production Q01–Q38 / M01–M42** contract in `amcos-unified-production-status.md`. Those M-numbers are specific to this contract; they are not the differently numbered milestones in `production_completion_plan.md`. The older status file is historical, not current evidence. **Overall: PARTIAL.** A checklist item is complete only when implementation, adversarial tests and applicable real-tool evidence exist; a local test, prompt, simulation or synthetic approval is not production activation or real-client approval.

## Execution order and definition of done

1. **Reproduce and secure the working environment.** Install disposable development dependencies; retain only reproducible source and intended deliverables. Confirm the current branch, original test baseline and applicable subsystem owners. Prevent regressions in isolation, authority, tenancy, idempotency, path handling and data integrity. Re-pin the critical-file manifest only after reviewing security changes.
2. **Finish the core production contract.** Bounded deliverable declarations are now represented in the existing delivery contract, but **verified inventory binding is not implemented**: a blocking declaration deliberately escalates and cannot be approved away. Implement only against server-derived ProjectOS artifact heads, scope, immutable hashes, evidence and relevant acceptance checks; never accept client-asserted counts, statuses or approval as proof. Preserve hashes of existing v1 contracts and test negative and valid paths.
3. **Connect strategy, brand and revision.** Complete evidence/counterevidence, channel invariants and decision tracing. Extend the existing approved VNEXUS brand → UCPO bridge, validate schema and ownership before dispatch, recheck approval/head freshness at every irreversible boundary, and demonstrate selective invalidation/rebuild. Exercise crash recovery and actual PostgreSQL concurrency as well as SQLite.
4. **Complete web quality and journey evidence.** Generate five core pages and two landing pages from approved data; independently verify all navigation/CTAs, responsive reflow, keyboard, accessibility, contrast, errors and requirement coverage using the **pinned** browser. A diagnostic browser is never a substitute. Seal only a current, fully verified proof and test both permitted and denied generic release paths.
5. **Finish local creative production.** Produce six independently reviewable social deliverables with editable source, dimensions, alt text, source/rights/provenance and rendered layout checks. Avoid silently dropped copy, overlap or unapproved substitutions. Distinguish six outputs from six genuinely distinct creative concepts. Require human creative and accessibility review.
6. **Finish motion and editorial.** Verify the in-progress procedural compositor and exact 30-second master/two 15-second re-edits, actual dissolve overlaps, trims-only source references, independent frame counts, captions/text alternatives, reduced-motion stills and provenance. Do not describe silent procedural drafts as a finished cinematic film, speech transcript, licensed audio, footage or continuity review. Hosted generation, voiceover and third-party assets require selected providers, rights and explicit authorization.
7. **Harden execution and operations.** Close remaining sandbox gaps (including Blender and OS-level isolation review), atomic budget reservations, cancellation, worker deployment/reconciliation, scoped retrieval, validated handoffs and provider routing. Existing fenced leased ticks provide at-least-once processing, not exactly-once execution; do not claim an active persistent worker until deployed and observed.
8. **Finish evidence, delivery and portability.** Bind an exact delivery manifest to verified stored heads, approvals and dependencies; protect readback/release and record staleness. Provide an editable, reproducible Northline package and checksums. OTIO, C2PA, external delivery and source/rights attestations need their own implementation and validation, not labels.
9. **Finish product integration and acceptance.** Integrate dashboards, approval/change-impact views, events, operations, observability and learning with truthful unknowns. Run backend/frontend suites, current manifest and repository gates, cross-tenant and hostile-input tests, recovery tests, and end-to-end acceptance; document exact skips, blockers and remaining human/owner decisions.

### Immediate in-progress checklist

- [x] Approved-brand → seven-page UCPO compilation, transactional idempotency and version/dependency checks implemented; SQLite crash/retry and a narrow set of real PostgreSQL advisory-lock races covered. Full crash/concurrency coverage and a genuine pinned-browser positive proof remain open.
- [x] Local FFmpeg encoding and ffprobe/muxing moved behind an isolated, fail-closed boundary; short audio that would truncate a video is refused. Review and harden resource/TOCTOU limits; Blender is not equivalently isolated.
- [x] Video planner preserves its CTA within the frame budget; blocked requested shots, placeholders or requested audio cannot claim a completed master.
- [x] Poster wrapping refuses silent truncation; CTA contrast and estimated layout fixed. Browser-measured text overlap/bounds checks run locally; independent creative and accessibility review remain open.
- [x] Rendered and independently probed a **silent procedural draft** with a 30-second master, two 15-second source-derived edits and estimated caption sidecars. The overlapping dissolve, media-level quality, real audio, rights and human acceptance are not complete.
- [x] Recreated the fictional Northline run and assembled a portable preview outside ignored `scratch/`; checked its checksums and reports. It is not a final delivery or production release.
- [x] Mitigated reproduced VNEXUS replay and inherited-source access gaps with operation-aware authorization and cross-project tests. The brand graph, other idempotency stores, source ownership changes and permission races still require independent review; keep release blocked.
- [ ] Complete exact-revision acceptance, including final full-suite outcomes, canonical browser, current seven gates, both database recovery paths and all independent human reviews. See the checkpoint for what did and did not run.
- [x] Maintain this Q/M register and the separate [evidence checkpoint](amcos-evidence-checkpoint.md); preserve the unrelated historical `workspace/state_checkpoint.json`.

## Q01–Q38: detailed remaining work

| ID | Requirement | What remains to finish |
|---|---|---|
| Q01 | Request and needs | Audit required intake fields, rights, destinations, missing information and ambiguity; validate exact project/tenant binding. |
| Q02 | Counterevidence | Add evidence-backed claims, opposing evidence, freshness and unresolved uncertainty; never invent research. |
| Q03 | Finite scope | Bind quantities, formats and acceptance to verified server-owned inventory. Current declarations intentionally return NOT_MEASURED. |
| Q04 | Omission detection | Connect requirements → plan → work → artifacts → tests; flag missing links and stale evidence without manufacturing edges. |
| Q05 | Brand representation | Revalidate immutable approved versions, resolution provenance and cross-project boundaries through every consumer. |
| Q06 | Invariants | Specify and enforce approved brand/channel invariants; report conflicts and permitted adaptation. |
| Q07 | Traits to decisions | Trace source brand traits into design/copy decisions and counterfactual checks. |
| Q08 | Revision propagation | Prove affected descendants stale/rebuild and unrelated work remains untouched, including concurrent races. |
| Q09 | Distinct concepts | Produce genuinely distinct directions and assess them against the brief, rather than counting template variants. |
| Q10 | Hard gates | Retain non-compensable safety/rights/quality gates and adversarial proof. |
| Q11 | Blind review | Preserve lineage-blind evaluation; state evaluator independence and bias limitations. |
| Q12 | Cross-media adaptation | Connect approved brand and content to web/social/motion while recording per-channel choices and losses. |
| Q13 | Executable paths | Prove real bytes and job receipts per supported capability; leave missing providers blocked. |
| Q14 | Production methods | Harden and verify local image/video paths; select and authorize providers/rights before any hosted call. |
| Q15 | Asset completion | Bind each deliverable to verified bytes, format, quality, rights, dependencies and human review. |
| Q16 | Forgotten essentials | Add explicit captions, alt text, rights, source/editability, QA and delivery obligations to finite contracts. |
| Q17 | UCPO mapping | Extend approved-brand mapping and validate stale/missing, cross-tenant and successful proof cases. |
| Q18 | Buyer journeys | Test entry, intent, navigation, every CTA, destination and landing-page path in the canonical browser. |
| Q19 | Functioning pages | Run pinned-browser accessibility, responsive, keyboard, console, network and interaction QA on actual export. |
| Q20 | Client isolation | Finish explicit brand/project sharing policy and graph/twin project binding; review newly added source/target authorization and verify workspaces, storage, credentials, provider context, logs and exports across tenants and clients. |
| Q21 | Provider translation | Validate selected provider dialects and record unsupported features/translation loss before dispatch. |
| Q22 | Composition | Connect shot-level composition, framing, copy and reference intent to actual output. |
| Q23 | Provenance | Bind content hashes, tool/version, source, synthetic status, rights and dependency lineage end to end. |
| Q24 | Reuse | Enforce scope, license, expiry, consent and version on reuse; invalidate when upstream terms change. |
| Q25 | Treatment | Connect a reviewed treatment and storyboard to timed, approved shot sources. |
| Q26 | Shot graph | Verify frame-exact structure, source references, roles, rights and real transition behavior. |
| Q27 | Text-to-video detail | Compile a full shot specification; no paid/hosted calls without selected, authorized provider. |
| Q28 | Continuity | Perform media-level character, scene, lighting and temporal continuity review; prompt checks alone do not prove it. |
| Q29 | Alternatives | Preserve bounded concept alternatives and genuinely distinct edit choices. |
| Q30 | Local repair | Demonstrate bounded defect-specific repair and re-verification on actual media. |
| Q31 | Synchronization | Verify exact video/audio/caption timing and overlaps from rendered media; silence is not voiceover. |
| Q32 | Finished film | Produce and human-review a rights-cleared 30 s master and two 15 s cutdowns; procedural drafts are not completion. |
| Q33 | Ambiguous effects | Pause ambiguous/external actions and prove no publish, send or spend without a current exact permit. |
| Q34 | Budget | Add transactional cross-worker reservations, caps, release and uncertainty handling; prove concurrency. |
| Q35 | Authority | Recheck actor, action, exact target, artifact/version, approval, expiry and project at each effect and replay boundary; independently review other receipt stores, resource transfers and permission races. VNEXUS's operation matrix is a mitigation, not global proof. |
| Q36 | Portability | Provide editable sources, explicit dependencies, manifests and readback; separately implement OTIO/C2PA if required. |
| Q37 | Learning | Add measured baselines and consented feedback promotion; absent metrics remain NOT_MEASURED. |
| Q38 | Unsupported handoffs | Return explicit capability gaps before dispatch; validate schemas and never silently substitute/simulate. |

## M01–M42: implementation and acceptance work

| ID | Area | Remaining acceptance work |
|---|---|---|
| M01 | Assessment | Refresh baseline, owners, environment and evidence for this branch. |
| M02 | Traceability | Machine-check requirement-to-artifact/test coverage and current evidence. |
| M03 | Intake | Validate needs, project scope, missing inputs, rights and ambiguity. |
| M04 | Strategy | Connect claims, support, counterevidence, assumptions and freshness. |
| M05 | Deliverables | Bind finite contracts to trusted inventory and independent checks; preserve old contract hashes. |
| M06 | Brand | Verify current approved genome, constraints, lineage and authority through production. |
| M07 | Adaptation | Add cross-channel invariant and trait-to-decision traces. |
| M08 | Creative | Demonstrate distinct alternatives, hard gates and unbiased review limits. |
| M09 | Production graph | Link requirements, work orders, shot sources, artifacts, checks and dependencies. |
| M10 | Handoffs | Validate typed, scoped and fresh input contracts before execution. |
| M11 | Revision | Prove blast radius, approval staleness and selective rebuilding under concurrency. |
| M12 | Worker | Deploy/observe only after a reviewed activation; persistently reconcile leased work. |
| M13 | Reliability | Test crash windows, fencing, retries and reconciliation across SQLite/PostgreSQL. |
| M14 | Cancellation | Implement state-aware cancellation and recovery without duplicating external effects. |
| M15 | Isolation | Harden all untrusted execution paths, OS resource limits, filesystem/network boundaries and review. |
| M16 | Engineering | Expand beyond the current Python-only patch validator or explicitly block unsupported execution. |
| M17 | Retrieval | Enforce tenant/project, provenance, freshness and rights before retrieval/usage. |
| M18 | Routing | Validate capabilities, budgets and fallback truthfulness across providers. |
| M19 | Budgets | Add atomic reservations, rolling caps and settlement under concurrent workers. |
| M20 | GitHub | Implement/test scoped webhook and PR workflows without activating external effects by default. |
| M21 | Brand → web | Complete approved mapping, transactionality, revalidation and cross-system proof tests. |
| M22 | Web | Build seven pages with requirement lineage, safe reproducible source and evidence. |
| M23 | Function | Run pinned-browser buyer journeys, WCAG and responsive gates on actual output. |
| M24 | Client isolation | Verify tenant, storage, secrets, context and provider separation. |
| M25 | Prompt compiler | Track provider translation and loss; do not equate prompts with generated assets. |
| M26 | Assets | Verify six reviewed social deliverables, layout, rights and editable source. |
| M27 | Provenance | Bind byte hashes, tools, source rights and derivation into stored artifacts. |
| M28 | Reuse | Validate licenses, expiry, tenant and lineage on each reuse. |
| M29 | Film | Complete treatment, story, real shot sources, direction and human review. |
| M30 | Prompts | Create precise shot specs and provider mapping with unsupported-feature reporting. |
| M31 | Media execution | Finish/test isolated local rendering; hosted generation remains gated. |
| M32 | Continuity | Validate continuity and local repairs against rendered media, not only prompts. |
| M33 | Finishing | Verify 30 s master, two 15 s cutdowns, actual transitions, captions and audio/rights. |
| M34 | Portability | Package editable inputs, exports, checksums and manifest; OTIO/C2PA remain separate work. |
| M35 | Dashboard | Integrate progress, blockers, lineage, review and truthful action state. |
| M36 | Events | Extend existing replayable events to all new production stages and recovery. |
| M37 | Governance | Maintain one existing authority for approvals, scope, separation of duties and exact targets. |
| M38 | Delivery | Seal/read back exact verified artifact heads and receipts; block stale or incomplete releases. |
| M39 | Observability | Add redacted metrics/traces and current measured coverage without claiming unconfigured integrations. |
| M40 | Learning | Establish baselines and consented evaluation; unsupported metrics remain NOT_MEASURED. |
| M41 | Operations | Provide setup, recovery, backup, activation and incident runbooks, then exercise them. |
| M42 | Acceptance | Complete end-to-end, adversarial, multi-tenant, cross-database and human acceptance evidence. |

## Non-negotiable boundaries

No deployment, publication, customer contact, paid provider use, or external data transfer is implied by this plan. Synthetic approvals and synthetic brand statements are test fixtures only. Pinned Chromium website QA, a real generic UCPO proof, **complete** PostgreSQL crash/concurrency coverage, cross-project graph isolation, verified inventory binding, secure Blender execution, production worker activation, media-level creative review and real client approval remain open until independently demonstrated. Narrow local PostgreSQL advisory-lock races have passed; they are not Supabase coverage. If unavailable, label work BLOCKED or NOT_RUN rather than PASS.
