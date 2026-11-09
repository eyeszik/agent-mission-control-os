# QA report — "Agent Mission Control OS, Explained" (2026-11-09)

Deliverable: `artifacts/amc-explainer/final.mp4`
Build: run `run-20261109-122818-4225db` · seed `20261109` · commit `6144f03d907949d6b701e8eb93bcc87de1e90cf9`
Reviewer: automated pipeline checks + human (agent) frame review at 100% and 320 px-wide downscale.

## 1. Stream inspection (`qa/ffprobe-summary.txt`, `qa/ffprobe-full.json`)

```
format_name : mov,mp4,m4a,3gp,3g2,mj2     size: 8,377,437 bytes (7.99 MB)  bitrate: 2218 kb/s
video       : h264 High, yuv420p, 1080x1920, 30/1 fps, nb_frames 904, duration 30.131 s
audio       : aac LC, 44100 Hz, stereo, 150 kb/s, duration 30.206 s
container   : duration 30.206 s
```

Aspect = 1080/1920 = **0.5625 exactly (9:16)**. `r_frame_rate`=30/1 and
`avg_frame_rate`=4628480/154271 (= 30 fps when reduced); treated as CFR 30.
Notes: `sample_aspect_ratio`/`display_aspect_ratio` report `N/A` (no colour/aspect
metadata beyond defaults) — informational, not a failure. Video stream (30.131 s) is
shorter than the audio/container (30.206 s) because the AAC track pads to its frame
duration; this is normal and inside the manifest's 0.480 s drift tolerance.
`nb_frames=904` at 30 fps = 30.13 s — matches the video stream duration.

## 2. Decode check (`qa/decode-check.log`)

`ffmpeg -xerror -i final.mp4 -f null -` → **exit 0**, no `-xerror` output, 904 frames
decoded, muxing overhead reported. PASS.

## 3. Mandatory gate (`quality-report.json`)

`passed: true` · **PASS 21, NOT_VERIFIED 5, mandatory_failures []**.
Notably: `video.aspect` PASS (0.5625 expected at 1080×1920), `video.duration` PASS
(drift +0.206 s vs 0.480 s tolerance), `audio.peak` PASS (0.5655), `audio.channels`
stereo, `captions.within_duration` PASS, `video.decodes` PASS.
**NOT_VERIFIED (never re-labelled):** `creative.subject_continuity`,
`creative.prompt_adherence`, `creative.visual_coherence`, `creative.legibility`,
`creative.pacing` — no perceptual evaluator is installed on this host.

## 4. Captions (`qa/`, verified programmatically)

7 cues; ordered, non-overlapping; last cue ends 28.272 s < 30.206 s; **verbatim match
with `script.json` narration** (checked after fixing a naive-regex undercount in the
first pass — all 7 cues confirmed, verbatim True). Burned-in captions verified legible
on full-resolution frame extracts (§7) and at 320 px downscale.

## 5. Loudness (`qa/loudness-ebur128.txt`, ebur128, peak=true)

- Integrated: **−20.5 LUFS** · LRA 5.6 LU · True peak **−2.4 dBFS**
- No loudness-normalisation was applied post-gate (would invalidate the delivered
  bytes and the QC that ran on them). This sits below the common −14/−16 LUFS social
  targets; consumers wanting that should normalise at the platform or with a separate,
  re-QC'd master. **Not claimed as EBU R128 / ATSC A/85 compliant.**

## 6. Provenance (`manifest.json`, sanitized copies)

`zero_paid_api_spend: true` · `credentials_used: []` · `remote_fetching_enabled: false`
`technique: procedural_ffmpeg` · `capability_tier: C` · `narration_is_speech: true`
per-scene seeds `20261109000…20261109005` · SHA-256 asset hashes present ·
`duration.drift_seconds: +0.206` · `config_hash` present.
Absolute sandbox paths were replaced by `<repo>` / `<run work dir>` / `<run output dir>`
after the run (see `environment-record.json → note`). `final.mp4`/`thumbnail.jpg` are
byte-identical to the pipeline output (verified with `cmp`).

## 7. Frame-by-frame review (`qa/frames/t*.jpg`, full 1080×1920)

| frame (s) | scene | observation | verdict |
| --- | --- | --- | --- |
| 0.03–0.17 | s01 | cold open, fade-in from ink | PASS |
| 1.5 | s01 | "START HERE / Agent Mission Control, Explained", caption 1 legible | PASS |
| 4.5 | s02 | mid transition | PASS |
| 5.8 | s02 | "WHY IT MATTERS" card, caption pre-delay | PASS |
| 6.5 | s02 | dip-to-ink trough (text ~40% brightness, <1 s) — by design, still readable | PASS (note) |
| 6.8 | s02 | dip complete, caption 2 visible | PASS |
| 8.0 | s02 | caption 2 "It matters more than it looks." legible | PASS |
| 12.3 | s03 | "THE DETAIL", accent contour below headline, caption 3 legible | PASS |
| 15.2–15.3 | s04 | cut boundary, darkest frames of the timeline (YAVG 32.9) — by design | PASS (note) |
| **17.0** | **s04** | **strata accent line passes behind the glyph row "Approval is…"** (drawn over the headline plate, under the white type) | **DEFECT D-1, LOW — accepted** |
| 20.2 | s05 | cut boundary | PASS |
| 22.5 | s05 | "One Assumption, Reordered" | PASS |
| 24.8 | s06 | cut boundary | PASS |
| 27.6 | s06 | "IN ONE LINE / End To End", right side very dark (beam motif faint at this t) — legible, moody | PASS (note) |
| 29.9 | s06 | final frame, caption 7 ends 28.272 s; resolve hold | PASS |

Global signalstats pass: 904/904 frames decoded; **YAVG never below 32.9 / never above
54.5**; darkest frames coincide with scene-boundary dips (5.63, 15.2, 20.2, 24.8 s).
No frame shows clipping or macroblocking; no text is clipped by the frame edges;
kicker, headline and caption plates all sit inside the vertical safe area.

### Defects

**D-1 (LOW, accepted) — s04, ~t=15.2–20.1 s:** the deterministic `strata` motif draws a
mint accent line that crosses the headline plate at the "Approval is" row. Enlarged crop
(`/tmp` during review, described here) shows the line passes **behind** the white glyphs
(strokes uninterrupted) and **over** the plate. Contrast of the white-on-dark glyphs is
unaffected (>13:1). Root cause: motif-under-text z-order in the stock renderer with a
four-line headline (8-word renderer-derived overlay). Seed re-roll (20261110 and 20261111…
inspected) assigns `strata` to s04 for **every** seed (role→motif selection is invariant),
so the seed lever cannot avoid it. Accepted rather than fixed by forking the renderer;
a proper fix (draw motifs strictly below headline plates) belongs upstream in
`services/freevideoforge/freevideoforge/visuals/` and is logged as follow-up work.
Severity LOW: no information is lost; legibility gate (perceptual) is NOT_VERIFIED anyway.

**Regression check:** after the 20261110 re-render (used to probe D-1), captions, scene
durations, narration and QC are identical; the delivered file remains the seed-20261109
build referenced everywhere in this package. No other frame shows motif/type conflict.

## 8. Acceptance checks (BRIEF §7)

| # | Check | Result |
| --- | --- | --- |
| 1 | ffprobe container, duration within tolerance of 30.000 s | PASS (30.206 s, drift +0.206 ≤ 0.480) |
| 2 | h264 / yuv420p / 1080×1920 / 30 fps / aspect 0.5625 | PASS |
| 3 | aac / 44100 Hz / stereo | PASS |
| 4 | full decode pass exits 0 | PASS (`qa/decode-check.log`) |
| 5 | no mandatory QC failures | PASS (`mandatory_failures: []`) |
| 6 | creative checks reported NOT_VERIFIED, never re-labelled | PASS (5 × NOT_VERIFIED) |
| 7 | `content_source == "brief"`; no facts beyond brief/README | PASS |
| 8 | captions verbatim, ordered, in-timeline, legible | PASS |
| 9 | manifest: procedural_ffmpeg / tier C / seeds / hashes / zero spend | PASS |
| 10 | thumbnail is a generated title card > 10 KB, verified | PASS (192,417 bytes) |
| 11 | no network fetches during render; doctor archived | PASS (`qa/doctor-output.txt`) |
| 12 | package completeness (video, source, assets, credits, repro, env, QA) | PASS (see `README.md`) |

**Overall: DELIVERABLE ACCEPTED for local, internal use.** Known limitations are listed
in `README.md → Known limitations` and are part of the delivery, not omissions.
