# Smoke render evidence

A real FreeVideoForge run, committed as verification evidence rather than as a
build output. Nothing in the pipeline reads this directory.

## What produced it

```bash
freevideoforge generate \
    --topic "Why the moon changes shape" \
    --duration 9 --aspect 9:16 --preset ffmpeg_motion \
    --quality balanced --seed 2026
```

Wall clock: 14.3 s on 4 CPU cores, no GPU. Run id
`run-20260915-011010-999588`.

## What ffprobe says about `final.mp4`

```
container : mov,mp4,m4a,3gp,3g2,mj2
duration  : 9.000000 s
size      : 2007268 bytes
video     : h264 High 1080x1920  fps=30/1  frames=270  pix=yuv420p
audio     : aac  ch=2  rate=44100  dur=9.000000
```

A full decode pass (`ffmpeg -xerror -i final.mp4 -f null -`) exits 0 with no
stderr output.

`1080/1920 = 0.5625`, which is 9:16 exactly.

## Quality report

All 21 mandatory structural checks PASS. The 5 creative checks report
`NOT_VERIFIED`, because no perceptual evaluator is installed and the project
does not invent a score it cannot measure. See `quality-report.json`.

## Provenance

`manifest.json` records the resolved providers, per-scene seeds and SHA-256
hashes. Absolute sandbox paths have been replaced with `<run output dir>` and
`<run work dir>` so the file reads cleanly in the repository; nothing else was
edited.

Relevant fields:

- `zero_paid_api_spend: true`, `credentials_used: []`
- `providers.technique: "procedural_ffmpeg"` — designed motion graphics, not
  diffusion video
- `providers.capability_tier: "C"` — no GPU or local model on the render host
- `providers.narration_is_speech: true` — espeak-ng produced real voiceover
- `remote_fetching_enabled: false`
