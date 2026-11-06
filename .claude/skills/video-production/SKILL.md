---
name: video-production
description: Produce a finished video locally from a topic or creative brief using FreeVideoForge - script, storyboard, voiceover, captions, render and QC with no paid API, no API key and no network at render time. Use when asked to make, generate, render or storyboard a video, short, reel, explainer or social clip, or to turn a brief, script or article into video.
---

# Local video production with FreeVideoForge

FreeVideoForge lives at `services/freevideoforge/`. It turns a brief into
`final.mp4` plus six sidecar artifacts, entirely on this machine.

## Before anything else

```bash
python -m freevideoforge doctor
```

It prints the capability tier and, for anything missing, the exact command that
fixes it. Do not start a render while `doctor` reports a blocker — fix the
blocker or tell the user what it is.

## Make a video

```bash
freevideoforge generate --topic "<topic>" --duration 30 --aspect 9:16 --preset auto
```

Useful flags: `--brief` (source material), `--style`
(`editorial|neon|clean|warm|slate`), `--quality` (`draft|balanced|high`),
`--seed` (reproducibility), `--json` (machine-readable output).

From Python, prefer the API over shelling out:

```python
from freevideoforge.api import generate, GenerateRequest
result = generate(GenerateRequest(topic="...", brief="...", duration=30, seed=42))
```

## Get better output

**Always pass `--brief` when real content exists.** Without one, the script
engine emits a *structural scaffold* — a real narrative arc phrased around the
topic that deliberately asserts no facts. `script.json` records which happened
in `content_source` (`scaffold` / `brief` / `local_llm`). Never present
scaffolded copy to a user as researched content.

- `--duration` is a target, not a guarantee. Copy drives duration: a beat is
  never shorter than the time its narration takes to speak. Check
  `manifest.json → duration.drift_seconds`.
- `--quality draft` (720p) is right for iterating; re-render at `balanced` once
  the copy is settled.
- Use `--seed` when the user wants to tweak one thing without the whole video
  changing underneath them.

## Report results honestly

Read `quality-report.json` before saying a render succeeded.

- Structural checks are **mandatory**. Any FAIL means the run failed; the
  pipeline already marks it `FAILED` rather than shipping it.
- Creative checks report `NOT_VERIFIED` because no perceptual evaluator is
  installed. Do not translate `NOT_VERIFIED` into "passed".
- The renderer produces **procedural motion graphics**, labelled
  `technique: "procedural_ffmpeg"`. Never describe its output as AI-generated,
  diffusion or generative video.
- If `manifest.json → providers.narration_is_speech` is `false`, there was no
  local TTS engine and the audio is timed silence. Say so.

## When a run fails

Runs are resumable and scene artifacts are content-addressed:

```bash
freevideoforge status <run_id>    # state, per-scene progress, recent events
freevideoforge resume <run_id>    # picks up from the last valid artifact
```

Resume reuses every scene whose inputs are unchanged. Never delete the run
directory to "start clean" — that throws away work that is still good.

## Boundaries

FreeVideoForge never downloads a model checkpoint, starts a local service, uses
a credential or contacts a paid API. If a user wants tier A/B generative media,
tell them what `doctor` says is missing and let them decide — installing a
multi-gigabyte checkpoint is their call, not yours.

## Local media tools in this sandbox (verified)
- `ffmpeg`: provided by the PyPI package `imageio-ffmpeg` (installed in the venv). FreeVideoForge resolves it automatically.
- `ffprobe`: not shipped by `imageio-ffmpeg`. The npm package `ffprobe-static@3.1.0` bundles a static binary and needs no
  install script. Install it into a scratch directory outside the repo, then run tests with `FVF_FFPROBE=<path>`.
- Without `ffprobe`, 40 FreeVideoForge tests skip (`ffmpeg/ffprobe not installed`). With it, 182 pass, 1 fails, 1 skips.
- The failing test is `tests/test_gates.py::TestG7QualityControl::test_a_good_render_passes_every_mandatory_gate`.
  Cause: no local TTS engine is installed, so the narration track is timed silence (`bootstrap.py`). The QC gate correctly
  flags it as effectively silent. Do not weaken the gate. The fix is a real TTS engine, not a QC change.
- Generative video and image need a local backend at `127.0.0.1:8188` (ComfyUI). None is present, so those tests are
  `NOT_APPLICABLE`. Paid providers are not authorized.
