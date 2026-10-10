# Local visual engine

`services/langgraph/agency/visual/` produces images, video and vector marks **on the host**. There is no hosted
image or video generation API anywhere in this path. Every output is persisted as a Project OS `media_asset`
artifact, reopened from storage by an independent verifier, and released only through the shared approval-bound
release gate.

## Routes

`capabilities.probe_all()` observes what is installed (imports, binaries, files on disk) rather than reading flags.
`router.route(intent, capabilities)` picks exactly one route from the intent's own facts. An unavailable route is
`BLOCKED` with the probe's reasons, and no other kind of output is substituted.

| Route | Used for | Implementation | Requires |
|---|---|---|---|
| R1 `BLENDER_CYCLES` | exact product stills, brand imagery | `blender_runner.py`: procedural geometry, Principled BSDF materials with object-space bump, area lights, 85 mm DOF camera, adaptive sampling, OpenImageDenoise, Filmic view transform, PNG + `scene.json` provenance | `bpy` 4.2 (CPython 3.11), CPU |
| R2 `OFFLINE_DIFFUSION` | approximate concept images | `diffusion_runner.py`: `AutoPipelineForText2Image.from_pretrained(local_files_only=True)`, Hugging Face offline flags, seeded | `torch`, `diffusers`, `AMC_LOCAL_DIFFUSION_MODEL_DIR` with `model_index.json` and an `amc-model.json` licence + weight-hash record |
| R3 `THREE_JS` | interactive scenes | `browser.three_renderer_for()` chooses `WebGPURenderer` (TSL/node materials) or `WebGLRenderer` (legacy `ShaderMaterial`, `onBeforeCompile`, `EffectComposer`); mixed architectures are `BLOCKED` | `three` in `apps/web` |
| R4 `VECTOR` | brand marks | the existing deterministic `agency.assets.render_logo_svg`, unchanged | nothing beyond the backend |
| R5 `LOCAL_VIDEO` | turntables | R1 renders every frame; FFmpeg (libx264, yuv420p) encodes only those frames | `bpy`, `ffmpeg`, `ffprobe` |

Unknown source-asset rights (`SourceAsset.license is None`) block before any route is considered.

On the reference host for this change, R1, R4 and R5 were `VERIFIED_AVAILABLE` (Blender 4.2.0, FFmpeg 6.1.1).
R2 was `BLOCKED_LOCAL_MODEL`: torch, diffusers, weights and a licence record were all absent. R3 was
`MISSING_DEPENDENCIES`: `three` is not an `apps/web` dependency. These are reported states, not hidden gaps.

## Isolation

Renderer processes run under `python -I` with a scrubbed environment: proxies are removed and `HF_HUB_OFFLINE=1`
is set. When the kernel allows it, they also run in their own network namespace (`unshare -rn`), so "no remote
request" is enforced by the kernel. Each receipt records `network_isolated`. Test T08 proves that a socket opened in
that namespace fails.

## Verification ladder

`verify.verify_media()` reopens persisted bytes and never trusts the renderer.

| Level | PNG | MP4 | SVG |
|---|---|---|---|
| Q0 valid file | PNG magic | `ftyp` box | `<svg` / `<?xml` root |
| Q1 decodable | Pillow `verify()` + full `load()` | ffprobe | `svg_safety` (well-formed, no active content, no external refs) |
| Q2 dims/format | exact width × height, PNG | width, height, fps, frame count, h264 | positive `viewBox` |
| Q3 non-blank | luma stddev ≥ 4, ≥ 256 colours, mean in (2, 253) | non-zero duration | geometry present, palette ΔE76 ≤ 2.3, real Chromium renders at 32/128/512 px decoded and non-blank |
| Q4 rights | every source asset licensed (procedural = owned) | same | same |
| Q5–Q7 | **always `human_required`** | | |

The verifier also recomputes SHA-256 against the recorded `content_hash`, and a mismatch fails verification.

A check that could not run (Pillow or the browser is missing) makes the result `INCONCLUSIVE`. Such a check is
never `PASSED`, and it is not reported as a defect either.

Subjective realism and brand fit are never certified from pixels or a single score.

## Browser harness

`browser_runner.cjs` drives the locally installed Chromium through `@playwright/test`. It aborts every request that
is not a `data:` URL, and it runs inside the network namespace. It records what the browser actually did:
- shader compile and link logs;
- `readPixels` statistics;
- `webglcontextlost` / `webglcontextrestored` events from `WEBGL_lose_context`;
- PNG captures.

The headless GPU is SwiftShader (software). The result reports the renderer string; it does not claim hardware
acceleration.

The harness verifies raw WebGL and SVG today. Rendering Three.js scenes waits on the `three` dependency (R3 above).

## Provenance

Each render carries:
- a `RenderReceipt` with the command, exit code, wall time, logical tick, outputs and their SHA-256;
- a `VisualGenome`: renderer and version, scene-spec hash, geometry, materials, camera, lights, seed, samples,
  hardware and colour management.

`RealismContract` states the target, the rights, the lighting, material, camera and colour pipeline, the criteria,
the allowed variance and the required reviews. Cycles + OIDN output is **not** bit-reproducible: re-rendering
produces new bytes and therefore a new artifact version, and deduplication comes from durable intents (see
`docs/durable-runtime.md`).

## Using it

```python
from services.langgraph.agency.visual.contracts import VisualIntent
from services.langgraph.agency.visual.engine import produce, request_approval, release_verdict

result = produce(principal, project_id, VisualIntent(category="product_still", palette=palette),
                 work_dir=Path("exports/.render-work"), artifact_key="hero-still")
```

For scheduled or recurring work, submit a durable job instead (`agency.durable.visual_job.submit_visual_job`).
Install the optional pieces with `pip install -e "./services/langgraph[visual]"` plus a system FFmpeg.
