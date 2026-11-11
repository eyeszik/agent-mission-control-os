# Production brief — "Agent Mission Control OS, Explained" (30s vertical explainer)

**Status:** frozen for the 2026-11-09 delivery (Piper re-render supersedes the espeak-ng build merged in #244) · **Branch:** `arena/734654d8-agent-mission-control-os` · **Pinned source revision:** `f947863a85dfb31f56f06b37b0dfeafaf9de0149` (`git rev-parse HEAD`) · **Date:** 2026-11-09

This brief defines the outcome, style, specification, assets, audio, budget and mandatory
acceptance checks for one deliverable: a ~30-second, 9:16, 1080×1920 local render that
explains what Agent Mission Control OS is, built entirely on the host with no paid API.

---

## 1. Viewer outcome

After 30 seconds, a technical decision-maker or repository visitor should:

- know what Agent Mission Control OS **is**: the execution and governance layer for an
  autonomous branding, marketing, product and digital-delivery agency;
- know the one condition that matters: **human approval is required before anything is
  delivered** — and that publication stays dry-run while paid media stays planning-only;
- correctly label the artifact as a locally rendered motion-graphics short, not a
  generative-video product;
- feel the intended impression — *measured, governed, calm engineering* — and be willing
  to read the repository or ask for a walkthrough.

Explicit non-outcomes: the video does **not** claim production deployment, does **not**
quote benchmark metrics (there are none to quote), and does **not** simulate a customer
story. Comprehension was checked on the animatic (§TIMING below): the two fact-bearing
beats carry the product definition and the approval condition; the remaining framing
beats are labelled stock narrative scaffolding in `script.json → content_source = "brief"`
and `content_source_note`.

## 2. Reference style

Tonal references (for direction only — no third-party asset, footage, logo or music is
used or reproduced):

- **Linear / Vercel launch keynotes** — dark field, one rationed accent, huge type, no clutter.
- **Monocle / Kinfolk restraint** — the calm of print editorial translated to motion; nothing shouts.
- **Control-room documentary** — the calm of observability tooling: grids, contours, orbits,
  unless the accent needs to speak.

What we deliberately avoid: gradient-mesh SaaS clichés, neon-on-navy synthwave, fake
photoreal product shots, invented dashboard UIs, and any "AI video" aesthetic.

## 3. Duration and delivery specification

| Field | Value |
| --- | --- |
| Duration | 30 s target; **30.206 s** delivered (copy drives duration; drift +0.206 s, tolerance 0.480 s) |
| Aspect / resolution | 9:16 · **1080×1920** (balanced+high presets); animatic draft was 404×720 |
| Frame rate | 30 fps CFR |
| Video stream | H.264 (libx264), High profile, `yuv420p`, CRF 17, preset `slow` |
| Audio stream | AAC, 44.1 kHz, stereo, 160 kbps |
| Captions | Burned in (safe-area lower third) **and** sidecar `captions.srt`; cues derived from measured narration |
| Container | MP4 (`mov,mp4,m4a,3gp,3g2,mj2`) |
| Thumbnail | `thumbnail.jpg` — generated title card, not a frame grab |
| Safe for | 9:16 social/short-form placement; also readable muted (burned captions) |

## 4. Assets

Everything visible is **procedural** (generated at render time by FreeVideoForge's
`ffmpeg_motion` tier from seeded Python + Pillow + FFmpeg). There are **no raster
photographs, no stock assets, no third-party marks, no fonts embedded, no icons,
no Lottie/GL.** Specifically:

- Palette `slate`: `#101418` → `#1C232B` gradient field, accent `#5FD3A6`, ink `#EDF2F6`,
  muted `#7C8B99`. WCAG contrast between ink and field ≈ 14:1; captions sit on a darkened
  caption plate with ink-picked-by-contrast logic in the renderer.
- Type: host **DejaVu Sans / DejaVu Sans Bold** (libre, Bitstream Vera license), resolved
  by the renderer's font discovery; `mono` role maps to DejaVu Sans Mono.
- Background motifs: `orbit` (s01), `contour` (s02, s03), `strata` (s04), `orbit` (s05),
  `beam` (s06) — abstract rhythms; they make no depiction claim.
- Continuity is explicit per scene (`storyboard.json → continuity` strings), each scene
  records the end state it hands to the next.
- Audio is generated: Piper neural speech (`en_US-joe-medium`, CC0, local) + synthesized ambient pad. Nothing is sampled.

## 5. Audio needs

- **Narration:** local, offline, zero-cost **Piper neural TTS** — voice
  `en_US-joe-medium` (CC0; a lessac-family finetune from the rhasspy `piper-voices`
  v1.0.0 collection), installed via the third-party `joe-us-piper-voice` PyPI package
  (1.0.0; MIT packaging metadata — the voice files are the upstream CC0 artifacts,
  bit-identical per the SHA-256s in `environment-record.json`). The manifest records
  `speech: "piper"`, `voice_quality: "neural"`, and `voice_model` pointing at the local
  `.onnx`. The voice model (~58 MB) is **not** committed to this repository. The
  previous espeak-ng formant route is retained as a documented fallback
  (`REPRODUCTION.md §Fallback: espeak-ng`, `tools/espeak-ng-shim.py`).
- **Music:** synthesized ambient pad (`--music ambient`), no licensed track.
- **Loudness:** measured, not certified — **−19.5 LUFS integrated / −1.9 dBTP / LRA 7.0 LU**
  (ebur128, `qa/loudness-ebur128.txt`). No claim of EBU R128 / ATSC A/85 compliance is made.
- **Captions:** 7 cues, max two lines, timed from measured per-scene speech durations;
  parallel `captions.srt` delivered.
- The espeak-ng master was retired when this Piper build passed the same gate; if Piper
  is ever unavailable, re-render via `REPRODUCTION.md §Fallback: espeak-ng` — never by
  quietly swapping the track under the existing captions.

## 6. Budget

| Item | Planned | Actual (measured) |
| --- | --- | --- |
| Paid APIs / credentials / network at render time | none | **none** (`manifest.json → zero_paid_api_spend: true`, `credentials_used: []`, `remote_fetching_enabled: false`) |
| Compute | CPU-only, 2 vCPU sandbox | preflight 8 s draft: 2.49 s wall, 72.7 MB peak RSS · 30 s draft animatic: 7.74 s wall, 117 MB peak RSS · final render: ~2 min wall on 2 vCPU; see `qa/qa-report.md` |
| Money | $0.00 | $0.00 |
| Wall clock from brief to packaged delivery | < 1 hour | within session, 2026-11-09 |

## 7. Mandatory acceptance checks

All must pass on the **delivered file**; results recorded in `qa/qa-report.md`.

1. `ffprobe` container = `mov,mp4,m4a,...`; duration within 0.480 s of 30.000 s (manifest tolerance).
2. Video stream: `h264`, `yuv420p`, 1080×1920, CFR 30 fps, aspect 0.5625 (exact 9:16).
3. Audio stream: `aac`, 44100 Hz, stereo.
4. Full decode pass `ffmpeg -xerror -i final.mp4 -f null -` exits 0 with empty stderr.
5. `quality-report.json → mandatory_failures == []`; every mandatory structural check `PASS`.
6. `quality-report.json` creative checks reported `NOT_VERIFIED` — never re-labelled PASS.
7. `script.json → content_source == "brief"`; no factual claim beyond the supplied brief and the repository README.
8. Captions: cues non-overlapping, inside the timeline, match `script.json` voiceover text verbatim; legible at full resolution on extracted frames.
9. `manifest.json` records `technique: "procedural_ffmpeg"`, `capability_tier: "C"`, per-scene seeds, SHA-256 asset hashes, and `zero_paid_api_spend: true`.
10. Thumbnail is a generated title card > 10 KB and visually verified.
11. No network fetches occurred during render (all providers are local; doctor output archived in `qa/`).
12. The package (video, source, assets, credits, reproduction steps, environment record, QA) is complete per `README.md`.

## 8. Honesty boundaries (non-negotiable)

- The renderer produces **procedural motion graphics** — never described as AI-generated,
  diffusion or generative video.
- The 5 creative QC checks are `NOT_VERIFIED` (no perceptual evaluator installed). They are
  reported as such, never as "passed".
- Piper narration here uses the third-party `joe-us-piper-voice` repackaging of the CC0
  `en_US-joe-medium` voice — disclosed, hashes pinned, never passed off as a house voice.
- No production-readiness, traffic, revenue or customer claims are made or implied.
- "Local-first" and "human approval" are product facts from the repository README, not aspirations.
