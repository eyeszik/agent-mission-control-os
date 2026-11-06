# Creative production, DAM, video and workstreams

## Digital asset management

The DAM is a view over the N4 registry: `GET /projects/{id}/artifacts?media_type=&channel=&artifact_type=&q=`. Each rendered or uploaded media file is a `media_asset` artifact (the one N1 type this work added, owned by **creative** and produced by `creative_director`). Its bytes live in content-addressed object storage. Its v2 metadata carries:

- format, MIME type, dimensions and duration;
- language, locale and channel;
- master and variant links;
- source, prompt and evidence refs;
- the rights ref and provenance.

**Uploads** (`POST /projects/{id}/uploads`):

- The format is sniffed from magic bytes. Allowed: PNG, JPEG, GIF, WebP, MP4, MP3, WAV, PDF and UTF-8 text.
- The client's declared type is never trusted.
- **SVG, HTML and XML are rejected**: they can carry script, and no sanitizer is shipped.
- The maximum size is 15 MB.

**Rights** (`POST …/artifacts/{id}/rights`) record the licence, territory, usage scope, attribution, source and expiry. `GET /projects/{id}/rights` includes the **RightsExpirationRadar**: expired rights, rights expiring within N days, and media with no rights record. Expired or missing rights block scheduled publication of media.

## Video factory bridge

```
cinematic compiler (ProjectIR, ShotIR, prompts) ──▶ video.plan_video_production
     └─ stops at its generation firewall (PROMPT_PACKAGE_READY)
FreeVideoForge GenerateRequest ──▶ local render (out of band) ──▶ video.read_freevideoforge_output
     └─ seven-file output contract                           └─▶ ingest_video_run → artifacts
```

- **Plan:** `POST /projects/{id}/video/plan` runs the cinematic pipeline and normalizes shot metadata. The metadata covers shot and scene ids, character state, start and end state, camera, lens, movement, lighting, environment, performance, dialogue, duration, references, prompt, model profile, seed and continuity. The endpoint then builds a FreeVideoForge request and reports a status for each of the 30 pipeline stages.
- **Renderer discovery:** `freevideoforge_capability()` checks for the package, Pillow, FFmpeg and ffprobe. When any is missing, GENERATION reads `BLOCKED_NO_LOCAL_RENDERER` and the plan says exactly what to install. It never assumes a capability.
- **Render:** run `freevideoforge generate …` or the `video-production` skill.
- **Ingest:** `POST /projects/{id}/video/ingest` only reads directories inside `AMC_VIDEO_INGEST_ROOT` (default `<export root>/freevideoforge`). It requires all seven output files. It refuses any run whose manifest does not certify `zero_paid_api_spend`.
- **Ingested artifacts:** the master video (`media_asset/video_master`, depending on the script and storyboard), the thumbnail (a variant of the master), captions, a `video_qc` report and a reproducibility record. A failed QC check raises `QA_BLOCKED`.

FreeVideoForge is read through its file contract, not imported, because its package loads Pillow at import time.

## Workstreams

`GET /projects/{id}/workstreams[/{kind}]` expresses each discipline as stages over existing N1 types with a `subtype`. It does not add new types:

| Workstream | Stages (examples) |
| --- | --- |
| product | opportunity, JTBD, competitive, PRD, roadmap, user stories, IA, flows, usability, architecture, API contracts, backlog, QA, telemetry, release, post-launch |
| creative | brief, reference board, style invariants, creative BOM, concepts, prompt package, masters, brand lint, derivatives |
| video | premise, bible, treatment, script, storyboard, shot prompts, render master, QC, platform variants, thumbnails |
| content | strategy, topic inventory, editorial briefs, fact cores, derivatives, calendar, measurement |
| search | SEO audit, intent map, entity map, topic graph, content gap map, SEO brief, AI discoverability brief, technical SEO plan, measurement plan |
| social | platform strategy, channel voice, templates, calendar, posts, community playbook, listening, performance |
| growth | GTM, funnel, segmentation, experiments, landing pages, CRO |
| crm | journey map, lifecycle messages, trigger schedule, measurement |
| web_app | discovery, content model, UI system, tokens, CMS schema, component inventory, page contracts, API contracts, test plan, a11y/performance QA, deployment manifest, post-deploy smoke |

Every stage resolves to N3 roles allowed to produce its type (verified by test), and readiness comes from the project's real artifacts:

- **DONE:** approved or released;
- **IN_PROGRESS**;
- **STALE:** invalidated or under review;
- **READY:** dependencies done;
- **WAITING**.

Externally measured search data is evidence and enters through KnowledgeOps or M5 memory. No search volume, ranking or performance figure is ever fabricated.

## Brand stewardship

`POST /projects/{id}/brand-drift` takes brand facts: palette, banned terms, deprecated names and current prices. It reads the project's artifacts, content items and rights. Findings cover:

- colours outside the palette;
- off-voice terms and deprecated names;
- old prices;
- unverified claims;
- artifacts left stale by upstream changes;
- expired rights;
- duplicate content;
- creative repetition (a prompt reused four or more times).

Categories with no input to judge them (logo misuse, typography, old screenshots, accessibility) are listed in `not_evaluated`. They are never reported as clean.

`refresh_candidates` lists what should be refreshed. The report's `autonomous_overwrites` is the literal `0`: drift analysis never edits an approved artifact.
