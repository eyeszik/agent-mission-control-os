# Agent Mission Control OS, Explained — 30 s vertical explainer

A complete, locally rendered short film explaining what **Agent Mission Control OS** is:
the execution and governance layer for an autonomous branding, marketing, product and
digital-delivery agency — work runs inside durable, tenant-scoped projects, and human
approval is required before anything is delivered.

**Watch:** `final.mp4` (H.264/AAC, 1080×1920, 30 fps, 9:16, 30.21 s, burned-in captions;
`captions.srt` alongside).

Everything in this directory was produced on the delivery host on 2026-11-09 from a
pinned checkout of this repository (`6144f03d907949d6b701e8eb93bcc87de1e90cf9`), at
**zero cost, with no credentials and no network access at render time.**

## What this is — and what it is not

- It **is** a procedural motion-graphics short: typography, colour, abstract motifs and
  camera drift rendered by FreeVideoForge's `ffmpeg_motion` tier, with local espeak-ng
  formant narration and a synthesized ambient pad.
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
| `tools/espeak-ng-shim.py` | The ~90-line `espeak-ng` CLI shim used for narration (see below) |
| `qa/` | ffprobe streams, decode log, loudness measurement, doctor output, frame extracts, this QA report |

## Known limitations (part of the delivery)

1. **Voice:** espeak-ng formant synthesis — functional, robotic, and honestly labelled
   `formant_synthesis` in the manifest. Not a neural voice. To substitute a local neural
   voice, use Piper (see `REPRODUCTION.md §Optional: Piper narration`) and re-run QC;
   never hot-swap the track under the existing captions.
2. **Creative QC is NOT_VERIFIED** (5 checks): no perceptual/legibility evaluator is
   installed. They are reported as NOT_VERIFIED, not "passed".
3. **Loudness** is −20.5 LUFS integrated / −2.4 dBTP — not normalized, not certified.
4. **Defect D-1 (LOW, accepted):** a background strata line passes behind the headline
   glyphs in s04 (t≈15.2–20.1 s). See `qa/qa-report.md §7`.
5. **Copy:** only 2 of the 5 supplied brief sentences fit the word budget and appear on
   screen (the rest are listed in `script.json → unused_brief_sentences`).
6. Abstract motifs depict nothing; there are no characters, no product UI screenshots,
   and no invented dashboards.

## Credits

See `CREDITS.md`. Headlines: DejaVu (free license). Speech: espeak-ng. Render: FFmpeg +
Pillow. Tool: FreeVideoForge (this repository; no top-level LICENSE file is present —
nothing here grants rights beyond the repository's own terms).
No third-party image, footage, music, logo or trademark is used.

## Reproducing or extending

See `REPRODUCTION.md`. Fixed seed `20261109` + same inputs ⇒ same plan and same frame
content (bytes may vary across FFmpeg builds; content does not).
