# Campaign execution without the dashboard

## Scope and safety

Run `examples/campaigns/black-feather-ceremony.json` through the real FastAPI/LangGraph agency pipeline. This is a separate local/Actions campaign, not a Base44 dashboard submission. No Base44 session is required, no repository application code is deployed, and no approval is submitted. The process stops at `needs_approval` and shuts down its API.

The example preserves the proposed creative direction, deliverable counts, workflow, and factual caveats from the campaign brief. It is not a verified Instagram audit. The engine may produce fewer deliverables than requested: inspect the output rather than equating brief requirements with completed work.

The runner uses a fresh SQLite database, sanitized process environment, OS-assigned loopback socket and separate export directory. A virtual environment isolates Python dependencies, not hostile code or filesystem access. Use an isolated machine/container for untrusted repositories. Do not expose local authentication to a network.

## Path A: direct backend execution

Run from a reviewed checkout of this repository on a POSIX host with Python 3.11+:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e './services/langgraph[dev]'
.venv/bin/python -m pytest services/langgraph/tests/test_headless_campaign.py -q
.venv/bin/python scripts/run_campaign_headless.py --mode dry-run --output scratch/bfc-dry-001
```

Dry run deliberately excludes any inherited model key. It exercises the actual API, persistence and graph with the repository's degraded fallback. Expected receipt: `DEGRADED_DRY_RUN_NOT_DELIVERABLE`. It is a functional rehearsal, not finished creative production.

For real provider generation, configure `OPENAI_API_KEY` securely in the execution environment, optionally set `AMC_OPENAI_MODEL`, then use:

```bash
.venv/bin/python scripts/run_campaign_headless.py --mode live --output scratch/bfc-live-001
```

Do not paste secrets into ChatGPT, tracked files or command arguments. Live generation can incur provider charges; configure provider-side budget/rate limits first. This runner has a time limit but no exact dollar-cost enforcement. Existing backend dependencies use version ranges, not a reproducible Python lockfile; review/pin dependencies before production use.

Inspect `execution.json`, `campaign.json`, `readiness.json`, and `exports/` under the output directory. `campaign.json` includes actual provider provenance, QA and approval records. A successful live runner means generation reached review; it does not mean the work was approved, all requested deliverables were rendered, or anything was published. Local database/checkpoints remain in that private directory. The runner does not provide automated approval/resume.

Never reuse an output directory. After a timeout or partial failure, inspect its receipts/database before deciding whether a new run is appropriate. `IN_DOUBT` means the request may have executed; do not blindly retry and incur duplicate model calls. Do not upload raw logs or SQLite files publicly.

## Path B: GitHub Actions

After reviewing and merging `.github/workflows/campaign-headless.yml` into the default branch, open Actions → Headless campaign → Run workflow → select `dry-run`. The workflow is manual only; pushes and PRs do not execute this campaign. It uploads campaign evidence and exports as a seven-day artifact. These artifacts can be accessible to users with repository/Actions access: use only this non-sensitive example, not confidential client briefs.

Before selecting `live`, an authorized repository administrator must:

1. Create/configure the `campaign-generation` GitHub environment with required reviewers and appropriate deployment-branch restrictions. The YAML environment name alone does NOT create a human-review policy.
2. Store `OPENAI_API_KEY` as a secret scoped to that environment; optionally define `AMC_OPENAI_MODEL` as an environment variable.
3. Set provider-side cost limits and review who may dispatch the workflow and access artifacts.
4. Merge and review the execution code before providing credentials to it. Do not run unreviewed branch code with secrets.

GitHub environment approval authorizes the model job; it is NOT approval of the resulting campaign. This workflow never calls the campaign approval/resume API. The ephemeral Actions database is not uploaded, so approval and delivery from that run are not a persistent production service. Review the exported drafts, then use an authenticated persistent deployment for a production delivery lifecycle.

To launch with an independently authenticated GitHub CLI:

```bash
gh workflow run campaign-headless.yml --repo eyeszik/agent-mission-control-os --ref master -f mode=dry-run
gh run list --repo eyeszik/agent-mission-control-os --workflow campaign-headless.yml --limit 5
gh run download RUN_ID --repo eyeszik/agent-mission-control-os --dir campaign-results
```

Select the actual run ID from the listing. Live mode changes `mode=dry-run` to `mode=live` only after the above security/cost setup. Do not blindly rerun a failed live job: a failure can occur after billable generation. The workflow is not available in the default branch until merged.

## Using it through ChatGPT

For a tool-enabled ChatGPT session with a terminal and repo access, ask:

> Run the Black Feather Ceremony example through scripts/run_campaign_headless.py in dry-run mode from the current reviewed repository revision. Use an isolated Python environment and a new private output directory. Report the run ID, actual generation provenance, QA blockers and exported files. Do not approve, publish, deploy or spend on ads.

For live generation, explicitly request live mode and provide credentials only through a supported secret/environment mechanism. A ChatGPT subscription is not a substitute for the backend's API credential.

For GitHub Actions, ask:

> Dispatch Headless campaign in dry-run mode on master in eyeszik/agent-mission-control-os, then retrieve the run status and artifacts. If workflow dispatch is not exposed by your tools, tell me; do not claim a run occurred or trigger unrelated CI as a substitute.

This ChatGPT session's GitHub connector exposes artifact retrieval and job reruns, but no new-workflow dispatch method. Therefore manual Actions dispatch or an authorized CLI/API execution environment is required here. GitHub repository access does not prove Actions secrets are configured; this session did not inspect their values or establish their existence.

## Verified preparation evidence

Baseline inspected: `258a21d1593df3ddaddad3bc8f42ae90dd68a381`.

A real local POST to `/agency/runs` returned run `f44df36b-c3db-48ac-aac6-4398287956e4`; subsequent GET returned `needs_approval`, `degraded=true`, four `FALLBACK_DEGRADED` provenance records and 30 exported files. All 496 backend tests passed, including seven new boundary tests. Repository invariants and the existing 90-file integrity manifest passed. No provider-backed creative run, GitHub campaign job, approval or publication is claimed by this evidence.
