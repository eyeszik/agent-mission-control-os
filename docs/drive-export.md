# Project export to Google Drive and Notion

`scripts/export_to_drive.py` packages a project's output folder, uploads it to Google Drive and records the
upload in a Notion database. The code is in `services/langgraph/integrations/drive_export/`. It signs in to
Google either as a **service account** (Google Workspace shared drive) or as **you** (a personal Google account);
see "Choose a Google sign-in" below.

It is an operator tool. It is not part of the agency pipeline, it does not publish anything to an audience,
and it does not touch the AMC approval store. Each Notion record starts with `approvals_state = draft`.

## What a run does

1. **Manifest.** Hash every file under the project folder with SHA-256, sorted by path. Symlinks, files over
   50 MB, and `.git`, `node_modules`, `__pycache__`, `.next`, `.venv` and `.amc-export` are skipped. Skipped
   files are listed in the result. The manifest hash is the SHA-256 of the canonical manifest JSON.
2. **Baseline.** Load the previous manifest. On Drive this is the newest `*.manifest.json` sidecar in the
   project's folder. In a dry run it is the last manifest the dry run wrote locally.
3. **Delta.** The zip holds only new or changed files, plus `manifest.json` (the full manifest),
   `graph.json` (a deterministic index of kinds, folders, prompt files with excerpts, Markdown headings and
   top keywords) and `audit.json` (actor, commit, mode, base manifest hash, files included, files removed).
   The first export, an export with `--full`, or an export with no baseline is a full export.
4. **Upload.** Drive v3 resumable upload into `DRIVE_PARENT_FOLDER_ID/<project-id>/`. The zip and a sidecar
   manifest carry `appProperties`: `amc_project_id`, `amc_kind`, `amc_manifest_hash`, `amc_export_kind`,
   `amc_base_manifest_hash`, `amc_commit_sha` and `amc_encrypted`.
5. **Verify.** Read each upload's metadata back and compare MD5, size and manifest hash with the local file.
   On any mismatch the run stops with exit code 1 and nothing is recorded in Notion.
6. **Record.** Create one Notion page with the properties below, plus blocks for the export summary, the Drive
   link and the prompt excerpts. Prompt excerpts are left out when the export is encrypted.
7. **Retention (optional).** Trash exports older than the Nth most recent full export.

## Modes and outcomes

| `RUNNER_MODE` | What happens |
|---|---|
| `dry_run` (default) | Builds the zip, sidecar and baseline under `--out-dir` (default `./.amc-export`). Reads no credential and makes no network call. |
| `local`, `ci` | Uploads, verifies and records. Requires one Google credential: `GOOGLE_SA_JSON` with `DRIVE_PARENT_FOLDER_ID`, or the three `GOOGLE_OAUTH_*` variables. Requires `NOTION_DATABASE_ID` or `NOTION_PARENT_PAGE_ID` when `NOTION_TOKEN` is set. A missing or conflicting value is a configuration error (exit 2), never a silent skip. |

Result statuses:

- `DRY_RUN`: the zip was built locally.
- `NO_CHANGES`: dry run only; nothing changed since the last dry run.
- `UPLOADED`: uploaded, verified and recorded.
- `ALREADY_UPLOADED`: Drive already holds an export with this manifest hash, so nothing was uploaded. A
  missing Notion record is created. This is how a run that failed after the upload completes.

Exit codes: 0 done, 1 an API call or the verification failed, 2 configuration error.

```bash
python scripts/export_to_drive.py --project-path runtime/foundry/demo                  # dry run
RUNNER_MODE=local python scripts/export_to_drive.py --project-path ... --check         # read-only access check
RUNNER_MODE=local python scripts/export_to_drive.py --project-path ... --brand-id acme # upload
```

`--project-id` names the Drive subfolder and the record; it defaults to the folder name. `--check` fetches the
Drive folder and the Notion database and reports whether the folder is in a shared drive and accepts children.
It writes nothing.

## Choose a Google sign-in

| | Service account | Signed-in user (OAuth) |
|---|---|---|
| Best for | Google Workspace, automation without a person | A free personal Google account |
| Where files go | A folder in a **shared drive** | **My Drive**, folder `AMC exports/<project>/` |
| Storage used | The shared drive's | Your own |
| Variables | `GOOGLE_SA_JSON`, `DRIVE_PARENT_FOLDER_ID` | `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REFRESH_TOKEN` |

Set one set, never both. A service account has no Drive storage of its own and a personal account cannot create
shared drives, so a personal account must use the signed-in-user option.

### Option A: signed-in user (personal Google account)

1. In console.cloud.google.com, create a project and enable the **Google Drive API** (APIs & Services -> Library).
2. Open **Google Auth platform** (older consoles: APIs & Services -> OAuth consent screen). Choose **External**,
   fill in the app name and your email, and add the scope `.../auth/drive.file`.
3. **Publish the app** (set the publishing status to **In production**). While it is in *Testing*, Google expires
   refresh tokens after 7 days and the export fails with "run scripts/drive_authorize.py again". The `drive.file`
   scope is not a sensitive scope, so publishing it for your own use needs no review; Google may still show an
   "unverified app" page, where you choose Advanced -> continue.
4. Create **Credentials -> OAuth client ID -> Desktop app**. Copy the client id and client secret.
5. On your own computer, in a checkout of this repository, run:
   ```bash
   python -m pip install httpx
   GOOGLE_OAUTH_CLIENT_ID=... GOOGLE_OAUTH_CLIENT_SECRET=... python scripts/drive_authorize.py
   ```
   A browser opens; sign in and approve. The script prints a **refresh token** once. It is not saved anywhere.
6. Store the three values as `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET` and `GOOGLE_OAUTH_REFRESH_TOKEN`
   in your secret store (for GitHub Actions, see below). Leave `DRIVE_PARENT_FOLDER_ID` empty.

The token has the `drive.file` scope: it can only see files and folders this tool created, never the rest of your
Drive. For the same reason it cannot use a folder you made by hand, so leave `DRIVE_PARENT_FOLDER_ID` empty and let
the runner create `AMC exports`. You may move that folder elsewhere in Drive afterwards. To revoke access, remove
the app at myaccount.google.com/permissions.

### Option B: service account (Google Workspace)

1. In Google Cloud, enable the **Google Drive API** and create a **service account** with a JSON key.
2. Put the destination folder in a **shared drive** and add the service account's email as **Content manager**. With
   domain-wide delegation you can instead set `GOOGLE_IMPERSONATE_SUBJECT` to a user, and files are then owned by
   that user.
3. Set `DRIVE_PARENT_FOLDER_ID` to the folder id: the last path segment of the folder's URL.
4. Set `GOOGLE_SA_JSON` to the key JSON, or to a path to the key file. Keep it in a secret store; never commit it.
   `*.key`, `.env` and `.env.*` are already git-ignored.

Exports are never shared publicly unless `UPLOAD_PUBLIC=true`, which grants "anyone with the link" read access.
The GitHub Actions workflow always sets it to `false`.

## Notion setup

Create an internal integration, then create a database with these properties and share it with the
integration. The names and types must match exactly.

| Property | Type | Value written |
|---|---|---|
| `Title` | Title | `<project-id> · <UTC timestamp>` |
| `project_id` | Text | Project id |
| `brand_id` | Text | `--brand-id` |
| `commit_sha` | Text | `REPO_COMMIT_SHA` |
| `timestamp` | Date | Run time (UTC) |
| `drive_file_id` | Text | Drive file id of the zip |
| `drive_web_view_link` | URL | Drive link |
| `manifest_hash` | Text | Manifest SHA-256; used to find an existing record |
| `artifacts_count` | Number | Files in the manifest |
| `approvals_state` | Select (`draft`, `pending`, `approved`) | Always `draft` |
| `tags` | Multi-select | `amc-export`, `full` or `delta`, `encrypted` |
| `short_summary` | Text | File counts by kind |
| `graph_index` | URL | Left empty; `graph.json` is inside the zip |

With only `NOTION_PARENT_PAGE_ID`, the runner creates a child page holding the same blocks and no properties,
and it cannot detect duplicates. A database is the preferred setup.

The client uses Notion API version `2022-06-28`. It splits text into runs of at most 2,000 characters and
sends at most 100 blocks per request, appending the rest.

## GitHub Actions

`.github/workflows/export-to-drive.yml` runs the export from the Actions tab. It has no automatic trigger
(manual `workflow_dispatch` only), reads the repository with `contents: read`, and pins every action to a commit.

1. **Create the environment.** Settings -> Environments -> New environment, named `drive-export`. Under
   *Deployment protection rules* add yourself as a **required reviewer**, so every upload waits for your approval.
2. **Add the secrets** to that environment (Add environment secret). Use one Google set:
   - Signed-in user: `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REFRESH_TOKEN`
   - or service account: `GOOGLE_SA_JSON`, `DRIVE_PARENT_FOLDER_ID`
   - Notion: `NOTION_TOKEN`, `NOTION_DATABASE_ID`
   - Optional: `EXPORT_ENCRYPTION_KEY`. Optional variable (not a secret): `EXPORT_RETENTION_FULL_KEEP`.
3. **Run it.** Actions -> *Export project to Google Drive* -> Run workflow. Inputs: `project_path` (a folder inside the
   repository, for example `runtime/foundry/demo`), optional `project_id` and `brand_id`, `mode` and `full`.
4. **Start with `dry_run`.** It runs in a job that has no access to any secret, builds the export, and prints what it
   would upload (file counts, manifest hash). Then run `ci`: it waits for your approval, checks access read-only,
   uploads, verifies and records in Notion.

The workflow exports a folder that is committed in the repository. Outputs that exist only on your computer or in a
cloud session are not on the runner; export those with the script directly. The run log and summary show only the
status, counts and manifest hash, never Drive links or ids, because they are public in a public repository.
A dry run's zip is not kept after the job; the run summary is the record.

## Restore

1. Download the zips for the project, from the newest full export forward. `amc_export_kind` and
   `amc_base_manifest_hash` give the chain.
2. If an export is encrypted (`.zip.enc`), decrypt it with
   `manifest.decrypt_bytes(blob, key)`. The format is `AMCX1 | 12-byte nonce | AES-256-GCM ciphertext`.
3. Unzip in order into `projects/<id>/replay-<timestamp>/`. Later deltas overwrite earlier files. Delete the
   paths listed in each `audit.json`'s `removed_since_base`.
4. Check every file against the final `manifest.json` (SHA-256 per path).

## Retention

Set `EXPORT_RETENTION_FULL_KEEP=N` to keep the N most recent full exports and every delta after the oldest of
them. Anything older is moved to the Drive trash, together with its sidecar. Trashed files stay recoverable
for 30 days, and the runner never deletes permanently. Retention is off when the variable is unset. Run with
`--full` periodically so there are full exports to keep.

## Reliability and security

- Retries: at most 3 after the first attempt, on 429, 5xx or a transport error. Backoff is exponential with
  full jitter, capped at 16 s, and honours `Retry-After`. Error messages carry the method, URL path and status
  only.
- Credentials are read from the environment only, held in memory, excluded from every `repr` and never
  logged. The OAuth refresh token is printed once by `scripts/drive_authorize.py` and never written to disk.
- A lock file under `--out-dir/locks/` stops two concurrent exports of the same project. A lock older than
  two hours is treated as stale.
- `EXPORT_ENCRYPTION_KEY` (base64, 32 bytes) encrypts the zip and the sidecar with AES-256-GCM before upload.
  The key stays with you; without it the export cannot be restored.
- If a resumable chunk fails mid-transfer, it is resent with the same byte range. If retries are exhausted
  the run fails, and the next run starts a new upload.

## Not implemented

The original specification included the items below. This runner does not provide them:

- Creating an AMC approval record. Approvals stay with `/approvals/{id}/decide`; there is no second approval
  path.
- A signed audit log. `audit.json` has `"signature": null` because no signing-key custody is configured
  (see G-37 in `docs/capability_gap_register.md`).
- A JSON-LD provenance graph, semantic (MinHash) deltas, blockchain anchoring and image re-compression.
- An export button in the web app, and keeping a dry run's zip as a workflow artifact.
