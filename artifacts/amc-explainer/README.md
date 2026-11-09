# Agent Mission Control OS, Explained — 30 s vertical explainer

A complete, locally rendered short film explaining what **Agent Mission Control OS** is:
the execution and governance layer for an autonomous branding, marketing, product and
digital-delivery agency — work runs inside durable, tenant-scoped projects, and human
approval is required before anything is delivered.

**Watch:** `final.mp4` (H.264/AAC, 1080×1920, 30 fps, 9:16, 30.206 s, burned-in captions;
`captions.srt` alongside).

Everything in this directory was produced on the delivery host on 2026-11-09 from a
checkout of this repository at `f947863a85dfb31f56f06b37b0dfeafaf9de0149` (branch
`arena/734654d8-agent-mission-control-os`, identical tree to `master` at the time), at
**zero cost, with no credentials and no network access at render time.**
This is the **Piper-narrated re-render** of the explainer: the espeak-ng build originally
merged in #244 has been superseded by a locally installed neural voice
(`en_US-joe-medium`, CC0). See `REPRODUCTION.md` and `qa/qa-report.md §0`.

## What this is — and what it is not

- It **is** a procedural motion-graphics short: typography, colour, abstract motifs and
  camera drift rendered by FreeVideoForge's `ffmpeg_motion` tier, with local Piper
  neural narration (`en_US-joe-medium`, CC0) and a synthesized ambient pad.
- It is **not** AI-generated/diffusion video, not a simulated UI demo, not a customer
  story, and makes no claim of production deployment, traffic, revenue or customer count.
- The narration is deliberately plain. Beats 1/3/4 carry the (repository README-sourced)
  facts; beats 2/5/6 are the deterministic template engine's stock narrative scaffolding.
  `script.json → content_source = "brief"` and the framing lines are **not** authored copy.
  This is stated plainly in the delivery instead of disguised.

## Package contents

| Path | What it is |
| --- | --- |
| `final.mp4` | The deliverable video (byte-identical to the pipeline output; SHA-256 in `environment-record.json`) |
| `thumbnail.jpg` | Purpose-built title card (generated, not a frame grab) |
| `captions.srt` | Sidecar captions, verbatim with the narration, measured against scene audio |
| `script.json` / `storyboard.json` | Script beats and the full shot plan (seeded, deterministic) |
| `manifest.json` / `quality-report.json` | Provenance (providers, seeds, hashes) and the QC gate result |
| `BRIEF.md` | The production brief: viewer outcome, reference style, duration, delivery spec, assets, audio, budget, mandatory acceptance checks |
| `DESIGN.md` | Treatment, style rules, references, signature moment, shot plan, cue map, timing resolution |
| `REPRODUCTION.md` | Exact environment and commands to rebuild this video from the pinned commit |
| `environment-record.json` | Host, toolchain versions, render parameters, per-file SHA-256 |
| `CREDITS.md` | Third-party components and licences |
| `source/brief.txt`, `source/generate.sh` | The exact creative input and render command |
| `tools/espeak-ng-shim.py` | The ~90-line `espeak-ng` CLI shim — **fallback only**, not used in this build |
| `qa/` | ffprobe streams, decode log, loudness measurement, doctor output, frame extracts, this QA report |

## Known limitations (part of the delivery)

1. **Voice:** Piper neural TTS, `en_US-joe-medium` (CC0), installed via the third-party
   `joe-us-piper-voice` PyPI repackaging (MIT metadata; upstream files from rhasspy
   `piper-voices` v1.0.0). The manifest records `speech: "piper"`, `voice_quality:
   "neural"`. Voice model SHA-256s are pinned in `environment-record.json`. The voice
   files (~58 MB) are deliberately **not** committed. If Piper is unavailable, the
   previous espeak-ng formant path is retained as a documented fallback
   (`REPRODUCTION.md §Fallback: espeak-ng`) — never hot-swap the track under the
   existing captions.
2. **Creative QC is NOT_VERIFIED** (5 checks): no perceptual/legibility evaluator is
   installed. They are reported as NOT_VERIFIED, not "passed".
3. **Loudness** is −19.5 LUFS integrated / −1.9 dBTP / LRA 7.0 LU — not normalized, not certified.
4. **Defect D-1 (LOW, accepted):** a background strata line passes behind the headline
   glyphs in s04 (t≈15.2–20.1 s). See `qa/qa-report.md §7`.
5. **Copy:** only 2 of the 5 supplied brief sentences fit the word budget and appear on
   screen (the rest are listed in `script.json → unused_brief_sentences`).
6. Abstract motifs depict nothing; there are no characters, no product UI screenshots,
   and no invented dashboards.

## Credits

See `CREDITS.md`. Headlines: DejaVu (free license). Speech: Piper (`piper-tts`, MIT) with
the `en_US-joe-medium` CC0 voice (third-party `joe-us-piper-voice` repackaging, MIT
metadata). Render: FFmpeg + Pillow. Tool: FreeVideoForge (this repository; no top-level
LICENSE file is present — nothing here grants rights beyond the repository's own terms).
No third-party image, footage, music, logo or trademark is used.

## Reproducing or extending

See `REPRODUCTION.md`. Fixed seed `20261109` + same inputs ⇒ same plan and same frame
content (bytes may vary across FFmpeg builds; content does not). Caption timings derive
from measured narration, so they differ from the superseded espeak build.
