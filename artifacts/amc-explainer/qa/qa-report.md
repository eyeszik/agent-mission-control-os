# QA report — "Agent Mission Control OS, Explained" (2026-11-09)

Deliverable: `artifacts/amc-explainer/final.mp4`
Build: run `run-20261109-222039-37a408` · seed `20261109` · commit `f947863a85dfb31f56f06b37b0dfeafaf9de0149`
Reviewer: automated pipeline checks + human (agent) frame review at 100% (all 8 extracts in `qa/frames/`).

## 0. This build supersedes the espeak-ng delivery

The explainer merged in #244 (run `run-20261109-122818-4225db`, commit `6144f03`)
shipped espeak-ng formant narration. This package is a **full re-render** with a local
Piper neural voice (`en_US-joe-medium`, CC0) after the user opted for the Piper track.
Visuals (scene plan, motifs, camera, transitions, seeds) are deterministic and unchanged;
what changed is the narration track, the narration-derived caption cue times, every
byte of `final.mp4`/`thumbnail.jpg` is fresh from this run, and all QA below was
re-executed against the new bytes. The committed espeak master is not shipped in this
branch; its numbers remain visible in git history (PR #244) and in the fallback
instructions in `REPRODUCTION.md`.

Honesty notes for this re-render:

- The voice files (~58 MB) are **not** committed; only their SHA-256s are recorded
  (`environment-record.json → voice_models`).
- The voice was installed via the third-party `joe-us-piper-voice` PyPI repackaging,
  not an official rhasspy artifact; upstream voice is CC0, packaging metadata MIT.
  Disclosed in `CREDITS.md` and `README.md`, not hidden.
- The 5 creative QC checks remain `NOT_VERIFIED` and were not re-labelled.
- D-1 (below) reproduces in this build; accepted, not fixed, for the same reasons.
- `qa/decode-check.log` is present in this package (it was absent from the #244 tree
  even though #244's docs referenced it — an inconsistency this build closes).

## 1. Stream inspection (`qa/ffprobe-summary.txt`, `qa/ffprobe-full.json`)

```
format_name : mov,mp4,m4a,3gp,3g2,mj2     size: 8,365,719 bytes (7.98 MB)  bitrate: 2216 kb/s
video       : h264 High, yuv420p, 1080x1920, 30/1 fps, nb_frames 904, duration 30.131 s
audio       : aac LC, 44100 Hz, stereo, 150 kb/s, duration 30.206 s
container   : duration 30.206 s
```

Aspect = 1080/1920 = **0.5625 exactly (9:16)**. `r_frame_rate`=30/1 and
`avg_frame_rate`=4628480/154271 (= 30 fps when reduced); treated as CFR 30.
Notes: `sample_aspect_ratio`/`display_aspect_ratio` report `N/A` — informational, not a
failure. Video stream (30.131 s) is shorter than the audio/container (30.206 s) because
the AAC track pads to its frame duration; `nb_frames=904` at 30 fps = 30.13 s, matching
the video stream. Inside the manifest's 0.480 s drift tolerance.

## 2. Decode check (`qa/decode-check.log`)

`ffmpeg -xerror -i final.mp4 -f null -` → **exit 0**, no `-xerror` output, 904 frames
decoded, muxing overhead reported. PASS.

## 3. Mandatory gate (`quality-report.json`)

`passed: true` · **PASS 21, NOT_VERIFIED 5, mandatory_failures []**.
Notably: `video.aspect` PASS (0.5625), `video.duration` PASS (drift +0.206 s vs 0.480 s
tolerance), `audio.peak` PASS (0.8206), `audio.channels` stereo, `captions.within_duration`
PASS (last cue 28.186 s), `video.decodes` PASS.
**NOT_VERIFIED (never re-labelled):** `creative.subject_continuity`,
`creative.prompt_adherence`, `creative.visual_coherence`, `creative.legibility`,
`creative.pacing` — no perceptual evaluator is installed on this host.

## 4. Captions (`captions.srt`, verified programmatically)

7 cues; ordered, non-overlapping; last cue ends **28.186 s** < 30.206 s; **verbatim match
with `script.json` voiceover text** (all 7 cues checked against the `beats[*].voiceover`
strings). Cue times differ from the superseded espeak build because they are derived
from measured Piper durations. Burned-in captions verified legible on the full-resolution
extracts (§7) and at 320 px downscale.

## 5. Loudness (`qa/loudness-ebur128.txt`, ebur128, peak=true)

- Integrated: **−19.5 LUFS** · LRA 7.0 LU · True peak **−1.9 dBFS**
- No loudness-normalisation was applied post-gate (would invalidate the delivered
  bytes and the QC that ran on them). Below the common −14/−16 LUFS social targets;
  consumers wanting that should normalise at the platform or with a separate,
  re-QC'd master. **Not claimed as EBU R128 / ATSC A/85 compliant.**

## 6. Provenance (`manifest.json`, sanitized copies)

`zero_paid_api_spend: true` · `credentials_used: []` · `remote_fetching_enabled: false`
`technique: procedural_ffmpeg` · `capability_tier: C` · `providers.resolved.speech: "piper"` ·
`providers.narration_is_speech: true` · `voice_quality: "neural"` ·
`voice_model: /tmp/fvf-venv/.../en_US-joe-medium.onnx` (ephemeral build path; hash pinned
in `environment-record.json`) · per-scene seeds `20261109000…20261109005` ·
`config_hash: a1dd4fe0ab0d356d9a0cbdcf1bc27c72d27b059c06def9fb716a48e24c37d0f5` ·
`duration.drift_seconds: +0.206`.
Absolute sandbox paths were replaced by `<run work dir>` / `<run output dir>` after the
run (see `environment-record.json → note`); the ephemeral toolchain paths
(`/tmp/fvf-venv/…`, `/tmp/ffprobe-scratch/…`) are retained verbatim for provenance, as
in the #244 package. `final.mp4`/`thumbnail.jpg` are byte-identical to the pipeline
output (they were copied, not re-encoded, and the hashes in `environment-record.json`
match the run output).

## 7. Frame-by-frame review (`qa/frames/t*.jpg`, full 1080×1920)

| frame (s) | scene | observation | verdict |
| --- | --- | --- | --- |
| 1.5 | s01 | "START HERE / Agent Mission Control, Explained", caption 1 legible | PASS |
| 4.5 | s01 | orbit field mid-drift; caption gap (cue 1 ended 2.740 s, cue 2 starts 5.736 s) — intentional | PASS |
| 6.8 | s02 | "THE STAKES / Why It Matters", contour motif, caption 2 legible | PASS |
| 12.3 | s03 | "THE DETAIL / Agent Mission Control OS", caption 3 legible | PASS |
| **17.0** | **s04** | **strata accent line passes behind the glyph row "Approval is"** (over the headline plate, under the white type — glyph strokes uninterrupted), caption 4 legible | **DEFECT D-1, LOW — accepted** |
| 22.5 | s05 | "THE INSIGHT / One Assumption, Reordered", caption 5 legible | PASS |
| 27.6 | s06 | "IN ONE LINE / End To End", caption 7 legible; frame dark but type readable | PASS (note) |
| 29.9 | s06 | final frame, caption 7 ended 28.186 s; resolve hold; darker, type legible at reduced brightness | PASS (note) |

Global signalstats pass: 904/904 frames decoded; **YAVG never below 32.94 / never above
54.58**; darkest frames coincide with scene-boundary dips (5.66, 15.25, 20.16, 24.80 s).
No frame shows clipping or macroblocking; no text is clipped by the frame edges;
kicker, headline and caption plates all sit inside the vertical safe area. Visual
content is identical in structure to the #244 build (same seeds and plan); only
narration-derived caption timing and audio differ.

### Defects

**D-1 (LOW, accepted) — s04, ~t=15.2–20.1 s:** the deterministic `strata` motif draws a
mint accent line that crosses the headline plate at the "Approval is" row. Enlarged review
of `qa/frames/t170.jpg` shows the line passes **behind** the white glyphs (strokes
uninterrupted) and **over** the plate. Contrast of the white-on-dark glyphs is unaffected.
Root cause: motif-under-text z-order in the stock renderer with a four-line headline
(8-word renderer-derived overlay). Role→motif selection is seed-invariant (verified
across seeds during the #244 investigation), so no seed avoids it. Accepted rather than
fixed by forking the renderer; a proper fix (draw motifs strictly below headline plates)
belongs upstream in `services/freevideoforge/freevideoforge/visuals/` and is recorded
here (this §Defects) as follow-up work; no issue-tracker entry exists for it yet. Severity LOW: no information is lost; legibility gate (perceptual) is
NOT_VERIFIED anyway. Reproduced in this build at the same scene (t170 extract).

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
