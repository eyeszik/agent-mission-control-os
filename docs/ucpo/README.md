# Website production line (UCPO)

A `WebsiteBrief` becomes a verified, approval-gated static website. The website is real: it has a Next.js static-export source tree, built in a sandbox and exercised in real Chromium. It is never deployed. The line extends existing owners instead of adding parallel ones:

| Need | Owner it reuses |
| --- | --- |
| Visual system | Foundry: the `psem_editorial` grammar (13th) and `foundry/psem.py` (locked palette, computed pairings) |
| Tokens | `agency/design_tokens` (the one DTCG compiler) |
| Persistence, versions, invalidation | Project OS artifacts via `foundry.studio.store`: CAS versions, `depends_on`, blast-radius invalidation |
| Untrusted execution, recovery | Durable jobs: `agency/durable/ticks.run_tick`, write-ahead intents, fenced leases |
| Role authority | N3 `assert_role_may_produce` on every stage |
| Approval and release verdict | `intake/release.open_artifact_approval` / `artifact_release_verdict`, decided only via `/approvals/{id}/decide` |
| Framework tasks | Agency Operating Framework refs (`artifact:<id>@v<n>`), proposed only |

No migration, table, approval store or event store is added.

## Flow

```
WebsiteBrief ─► RequirementsPackage ─► PSEM CreativeGenome ─► DTCG tokens ─► procedural plates
   (product_manager)   (product_manager)      (design_lead)        (design_lead)   (creative_director)
                                   └────────────► SiteArchitecture + WebsiteIR (design_lead)
                                                     └► source tree + manifest (implementation_lead)
   ── durable job ucpo_site_build (sandbox) ──────────────────────────────────────────────────────
     build (implementation_lead) ─► browser QA (brand_safety_reviewer) ─► semantic coverage
       ─► release proof (release_manager) ─► approval request (only if every gate is PASS)
```

Each box is a Project OS artifact named `foundry-ucpo-<site>-<stage>` with `depends_on` edges. A changed brief revises only the stages whose bytes change. Everything downstream is invalidated by the existing propagation. An artifact that is unchanged but was invalidated is re-confirmed as a new version, so lineage stays current. Pending approvals on changed artifacts go stale through the existing path. An approved proof whose inputs moved fails `stale_reasons` (`PROOF_STALE:<stage>`).

## Modules (`services/langgraph/agency/ucpo/`)

| Module | What it does |
| --- | --- |
| `contracts.py` | Strict, frozen, hashed contracts: brief, requirements, site IR, source manifest, build, browser verification, coverage, debt, release proof. |
| `requirements.py` | Brief → requirements. Ids are structural (`req.<page>.s<n>.<field>`), so a copy edit is a *change*, not an omission. Contract requirements (a11y, reflow, zoom, motion, focus, console, network) apply to every site. |
| `site.py` | Charcoal/paper grounds alternate. There is one accent per page, and accents appear only on charcoal. `check_colour_plan` runs every implied pairing through `psem.check_usage`, so an illegal pairing is a compile error. |
| `source.py` | Fixed templates plus one data file (`content/site.json`). Every element carries `data-req`. Paths are allowlisted with traversal refused. Code and SVG are scanned for injection, eval, dynamic code, process access, network calls and external URLs. Dependencies are the exact versions installed in `apps/web`. `reconcile_tree` / `export_tree` preserve human edits. |
| `sandbox.py` | `probe_isolation` *demonstrates* user, mount and network namespaces (`unshare -rmn`), a read-only repository re-mount, `env -i`, `prlimit` and `timeout`. Any failure means `BLOCKED_ISOLATION` and nothing runs. |
| `build.py` | Source policy → isolation → exact-version dependency check → `tsc --noEmit` → `next build --webpack` → output check (one HTML file per route, quota, digest). Each step is recorded with its exit status, duration and log tail. |
| `qa.py`, `qa_runner.cjs` | Real Chromium in the same sandbox. Pages are route-fulfilled from the export on `http://amc-preview.invalid`, and every other origin is aborted and recorded. Checks: axe-core (WCAG 2.0/2.1/2.2 A/AA tags), headings, landmarks, reflow at 320/768/1280, 200% text and 200% page zoom, reduced motion (compared against the default so the check is discriminating), keyboard focus (skip link first, visible indicator), console errors, external requests, PSEM colour pairings from computed styles, full-page screenshots (SHA-256), and `data-req` DOM evidence. A missing observation is `NOT_RUN`, and a runner failure is `BLOCKED`. Neither ever counts as PASS. |
| `semantic.py` | Each stage is evaluated against what it actually produced: IR, source tree, DOM evidence and checks. Statuses are PRESERVED / APPROVED_CHANGE / UNAPPROVED_CHANGE / OMITTED / UNRESOLVED / NOT_APPLICABLE, plus the loss stage. Coverage is mandatory resolved / mandatory applicable, with a zero denominator reported as `NOT_APPLICABLE`. Also holds the debt ledger and the `IntentLinker` (TRACE, INSPECT, COMPARE, FIND_OMISSIONS, IMPACT_ANALYSIS, PROPOSE_REPAIR; it proposes and never applies). |
| `release.py` | `seal_proof` binds the revisions of brief, requirements, genome, tokens, IR, source, build, browser QA and coverage. A proof is eligible only when every gate is PASS. `deployment` is always `NOT_AUTHORIZED`. |
| `service.py` | Stage persistence, the durable handler `SiteBuildHandler` (`RETRY_SAFE`: a static build has no external effect), the read models, and the linker over persisted evidence. |
| `preview.py` | Loopback-only static server for an export whose digest equals the verified build output. Returns a `PreviewResult` (endpoint, matching build revision, cleanup state). |
| `framework.py` | Proposed refs for AGM-08/10/20 tasks, plus the tasks the line cannot evidence and why. Nothing writes the task ledger. |
| `disciplines.py` | Fifteen disciplines. Each declares its contract fields and is routed over discovered capabilities, or reports `CAPABILITY_GAP` with a spec-only fallback. See [capability-matrix.md](capability-matrix.md). Routing is a decision; execution stays with the existing owners (Foundry, visual engine, this line). |
| `presentation.py` | Five presentation systems are slot schemas rendered *through this line*. Each ships a real example. Comparison is by requirement diff. |
| `prompt_modules.py` | Sixteen modules with all fourteen fields. The compact variant is a projection of the expanded one and keeps every rule, acceptance criterion and failure verbatim (tested). Both stop at `PROMPT_PACKAGE_READY`. |
| `multimodal.py` | ImageSpec, VideoSpec and StoryboardShot compile to prompt packages. No provider adapter is installed, so generation is `CAPABILITY_GAP` and nothing is fabricated. |

## Use it

```bash
# Local run, no database: source + evidence + report.json; exit 0 = every gate passed, 1 = blocked, 3 = BLOCKED_ISOLATION
python3 orchestrate_brand_pipeline.py website --input sample_ucpo_website.json --out /tmp/site --preview-seconds 60
python3 orchestrate_brand_pipeline.py website --board visual_identity_board --out /tmp/board
```

API (`/ucpo`): `GET /capabilities`; `GET|POST /projects/{p}/sites` (POST needs `Idempotency-Key` and an operator role); `GET /projects/{p}/sites/{s}`; `POST .../build` (one durable tick, operator role); `GET .../trace/{req}`, `GET .../inspect/{target}`, `GET .../omissions`, `POST .../impact`, `GET .../repair/{req}`, `GET .../framework-bindings`. The UI is the **Website Production** section of `/agency`.

Approval: the requester cannot approve. Another approver decides via `/approvals/{id}/decide`, and the release verdict then reports `allowed` with `deployment: NOT_AUTHORIZED`. Deploying, publishing or exporting to a host is a separate act that no route here performs.

## Security model

- The brief is data. Copy is rendered as React text from `content/site.json`, never as markup.
- Generated source is untrusted. It never runs outside the demonstrated sandbox, and a temporary directory alone is never treated as isolation.
- The sandbox has no network (`unshare -n`). The repository is mounted read-only inside it, so `apps/web/node_modules` is usable but not writable. The environment holds only `PATH`, `HOME`, `LANG`, `CI` and `NEXT_TELEMETRY_DISABLED`; no credentials are passed. Limits: file size 256 MiB, 4096 open files, no core dumps, per-step timeouts with kill, and a 50 MiB output quota.
- `prlimit --as` is deliberately not used, because it breaks V8. Memory is bounded by time. That is a stated limit, not a claim.
- The stored source bundle is re-checked when unpacked (paths, scan, manifest). A tampered bundle never reaches the build.
- Tests: `test_ucpo_pipeline.py`, `test_ucpo_build.py` (sandbox, defective-generator detection, tamper refusal, approval, separation of duties, staleness), `test_ucpo_api.py` (cross-tenant, viewer, smuggled fields, idempotency), `test_ucpo_registry.py`, `test_ucpo_contracts.py` (Zod parity, fixture `packages/shared/tests/fixtures/ucpo.json`; regenerate with `AMC_REGENERATE_FIXTURES=1`), and `apps/web/e2e/websites.spec.ts`.

## Limits

See [capability-gaps.md](capability-gaps.md). In short: there are no forms or analytics, there is no performance budget measurement and no hosted generation, and automated a11y checks are not certification. On hosts without unprivileged user namespaces (for example some CI runners), the build reports `BLOCKED_ISOLATION` and the sandbox tests skip as `NOT_RUN`.
