# FreeVideoForge

Turn a topic or a creative brief into a finished video on your own machine.

**No paid API. No API key. No account. No network access at render time.**

```
BRIEF → SCRIPT → STORYBOARD → SHOTS → MEDIA → VOICE → CAPTIONS → COMPOSE → QC → EXPORT
```

Every run produces the same seven artifacts:

| File | What it is |
| --- | --- |
| `final.mp4` | The video: H.264 + AAC, correct aspect, burned-in captions |
| `thumbnail.jpg` | A purpose-built title card (not a frame grab) |
| `script.json` | Narration, beats, pacing, and where the content came from |
| `storyboard.json` | Per-scene content / visual / motion specs with continuity |
| `captions.srt` | Caption cues timed against the measured narration |
| `manifest.json` | Full provenance: providers, seeds, asset hashes, drift |
| `quality-report.json` | Every QC check with an explicit PASS / FAIL / NOT_VERIFIED |

---

## Quick start

```bash
# 1. Check what this machine can do and what (if anything) is missing.
python -m freevideoforge doctor

# 2. Make a video.
freevideoforge generate --topic "Why the moon changes shape" \
    --duration 30 --aspect 9:16 --preset auto
```

That is the whole setup. If `doctor` reports blockers it prints the exact
command to fix each one.

### Requirements

| | Needed for | Install |
| --- | --- | --- |
| Python ≥ 3.10 | everything | — |
| **Pillow** | frame rendering | `pip install pillow` |
| **FFmpeg** (with `ffprobe`) | encoding + the QC gate | `sudo apt-get install -y ffmpeg` · `brew install ffmpeg` · `winget install Gyan.FFmpeg` |

Pillow is the only third-party Python dependency. Everything else is the
standard library.

If you cannot install FFmpeg system-wide, `pip install imageio-ffmpeg` provides
a static `ffmpeg` binary that FreeVideoForge finds automatically. That wheel
ships no `ffprobe`, so the structural QC gate needs a real FFmpeg install.

### Optional, and genuinely optional

| Add-on | Gives you | FreeVideoForge will… |
| --- | --- | --- |
| `espeak-ng` | real local voiceover | use it if present; otherwise narration is *timed silence* and says so |
| Piper + a voice | better local neural voiceover | use it if installed — **never** download a voice model for you |
| Ollama + a model | LLM-written narration | use it if running — otherwise the deterministic script engine runs |
| ComfyUI + checkpoints | tier A/B generative media | detect it only — **never** download checkpoints or start services |

Nothing above is required. With none of it installed you still get a complete,
valid video.

---

## CLI

```
freevideoforge generate   Produce a video from a brief
freevideoforge doctor     Diagnose this host, with fixes for anything missing
freevideoforge providers  List provider capabilities
freevideoforge runs       List recent runs
freevideoforge status ID  Inspect one run (state, scenes, events)
freevideoforge resume ID  Resume an interrupted or failed run
freevideoforge serve      Start the local web UI
freevideoforge bootstrap  Check and prepare the local environment
```

### `generate` flags

| Flag | Default | Notes |
| --- | --- | --- |
| `--topic` | *required* | What the video is about |
| `--brief` | `""` | Source material. Its sentences become the body beats |
| `--duration` | `30` | Target seconds (3–600) |
| `--aspect` | `9:16` | `9:16`, `1:1`, `16:9`, `4:5` |
| `--preset` | `auto` | `auto`, `local_video`, `image_motion`, `ffmpeg_motion` |
| `--style` | `auto` | `editorial`, `neon`, `clean`, `warm`, `slate` |
| `--quality` | `balanced` | `draft` (720p, fast), `balanced`, `high` |
| `--seed` | random | Same seed + same inputs → byte-identical plan |
| `--scenes` | auto | Override the scene count |
| `--fps` / `--height` | `30` / preset | Override the render spec |
| `--voice` / `--language` | `auto` / `en` | TTS voice and language |
| `--music` | `ambient` | `ambient` (synthesised pad) or `none` |
| `--no-burn-captions` | off | Keep `captions.srt` as a sidecar only |
| `--json` | off | Machine-readable output for automation |

Exit codes: `0` success · `1` failure · `2` usage error · `3` environment blocked.

---

## Local web UI

```bash
freevideoforge serve --port 8765
```

One self-contained page on `127.0.0.1`, built on the standard library. No CDN,
no external asset, no telemetry. It binds to loopback by default and warns
loudly if you bind it anywhere else — there is no authentication, because this
is a local tool.

---

## Programmatic interface

The same pipeline, callable directly. This is the stable contract for
automation — a job queue, an agent, a cron, an n8n node:

```python
from freevideoforge.api import generate, GenerateRequest

result = generate(GenerateRequest(
    topic="Why the moon changes shape",
    brief="The moon is always a sphere lit from one side. What changes is how "
          "much of the lit half faces Earth.",
    duration=30,
    aspect="9:16",
    seed=42,
))

if result.ok:
    print(result.final_video, result.duration)
else:
    print("failed:", result.error, "— resume with", result.run_id)
```

Also available: `resume(run_id)`, `run_status(run_id)`, `list_runs()`,
`describe_providers()`. An n8n adapter lives in
[`integrations/n8n/`](integrations/n8n/).

---

## How it works

### The script engine is a structure compiler, not a fact generator

With **no brief**, the engine writes a real narrative arc — hook, context,
body, turn, payoff — phrased around your topic, and marks
`content_source: "scaffold"`. It does not assert facts about the topic.

With a **brief**, your sentences become the body beats and
`content_source: "brief"`. Structure, pacing and framing are still generated.

With **Ollama** running, narration comes from your local model and
`content_source: "local_llm"`. Timing and arc stay with the deterministic
planner, because it is the part that knows the real speaking rate.

You can always tell which one produced the copy you are looking at.

### Copy drives duration, not the other way round

A beat is never shorter than the time its own narration takes to speak. If the
copy needs more room than `--duration` allows, scenes are extended and
`manifest.json` records the drift. Narration is never truncated to hit a clock.

### The renderer is honest about what it is

The mandatory renderer composes procedural motion graphics — gradient fields,
seeded geometric motifs, typographic layout, Ken Burns moves, parallax,
burned-in captions — with Pillow, and encodes with FFmpeg. It is labelled
`technique: "procedural_ffmpeg"` everywhere. It is **not** diffusion video and
is never described as such.

Frames stream to FFmpeg over a pipe as raw RGB, one scene at a time, so temp
storage stays bounded and each scene clip is independently reusable.

### Runs are resumable and idempotent

Every scene artifact is content-addressed by a hash covering its creative spec,
render spec, provider and seed. On resume, a scene is reused when its hash
matches **and** the file is still on disk. Kill a render mid-way and
`freevideoforge resume <run_id>` picks up from the last valid artifact.

State lives in `.freevideoforge/state.db` (SQLite, authoritative) with a
`state.json` mirror so another process, session or tool can read progress
without speaking SQL.

### Quality control separates what it can prove from what it cannot

**Structural checks are mandatory and deterministic**: artifact presence,
stream presence, dimensions, aspect, fps, duration tolerance, a full decode
pass, caption bounds and ordering, audio peak sanity. A structural failure
fails the run — a video that does not validate is never reported as success.

**Creative checks report `NOT_VERIFIED`.** FreeVideoForge ships no perceptual
evaluator, so it does not invent a prompt-adherence or visual-coherence score.
The slots exist so an evaluator can be added without changing the schema.

### Capability tiers

| Tier | Needs | Status here |
| --- | --- | --- |
| **A** `local_video` | GPU + local video backend + a workflow you configured | detected only |
| **B** `image_motion` | local image backend + a workflow you configured | detected only |
| **C** `ffmpeg_motion` | CPU + FFmpeg + Pillow | **always available, mandatory** |

`--preset auto` walks down this ladder and lands on whatever actually works.
Tier C is the floor and never depends on AI inference of any kind.

---

## Configuration

All optional. Defaults are safe.

| Variable | Default | Purpose |
| --- | --- | --- |
| `FVF_WORKSPACE` | cwd | Workspace root |
| `FVF_OUTPUT_DIR` | `<workspace>/out` | Where runs are written |
| `FVF_FFMPEG` / `FVF_FFPROBE` | auto-discovered | Explicit binary paths |
| `FVF_FONT_DIRS` | system paths | Extra font directories |
| `FVF_RENDER_WORKERS` | auto | Scene render parallelism |
| `FVF_RETRY_LIMIT` | `3` | Per-scene repair attempts |
| `FVF_MAX_SCENES` / `FVF_MAX_DURATION` | `40` / `600` | Resource governor bounds |
| `FVF_MIN_FREE_DISK_MB` | `512` | Refuse to start below this |
| `FVF_ALLOW_REMOTE_FETCH` | `false` | Remote URL fetching, off by design |
| `FVF_OLLAMA_URL` / `FVF_OLLAMA_MODEL` | loopback | Optional local LLM |
| `FVF_PIPER_MODEL` | — | Path to a Piper `.onnx` voice |
| `FVF_COMFYUI_URL` | loopback | Optional local media backend |

---

## Security posture

- No secret is read, logged or written. There is nothing to leak.
- No `shell=True`. Every subprocess is an argv list; no user string reaches a shell.
- Remote URL fetching is **off** by default.
- Model output (from Ollama) is parsed as untrusted data: type-checked, length-capped, never executed.
- The web UI binds to loopback, caps request bodies, validates every request against a typed schema, and refuses any media path outside the output root.
- A detected local backend is never auto-started, and no model checkpoint is ever downloaded on your behalf.

## Tests

```bash
pip install pytest
python -m pytest services/freevideoforge/tests -q
```

The suite renders real video through the real encoder — there is no mocked
FFmpeg, because the claim under test is "this produces a valid video on a bare
CPU". Gates `G1`–`G9` in `tests/test_gates.py` map to the acceptance contract.
`G9` (local generative media) is **skipped as NOT_APPLICABLE** on a host with no
local backend, never reported as a pass.

## Licence inventory

See [`LICENSES.md`](LICENSES.md). Everything FreeVideoForge depends on is free
and redistributable; nothing requires a commercial licence to run.
