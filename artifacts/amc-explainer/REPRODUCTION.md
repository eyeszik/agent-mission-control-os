# Reproducing this video from the pinned commit

Target: rebuild `final.mp4` (or your own variant) on a Linux host with Python ≥ 3.10,
Node ≥ 18, and network access **only for dependency installation** (pypi.org,
registry.npmjs.org). The render itself uses no network.

Tested on: Debian-ish x86_64, Python 3.11.2, Node v22.22.3, 2026-11-09.

```bash
# 0. Pin the source
git clone <this-repo> && cd agent-mission-control-os
git checkout 6144f03d907949d6b701e8eb93bcc87de1e90cf9

# 1. Python environment (build tools only; never committed, .venv is gitignored)
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install pillow imageio-ffmpeg espeakng-loader

# 2. ffprobe — imageio-ffmpeg ships none. The static build via npm needs no compile:
mkdir -p /tmp/ffprobe-scratch && cd /tmp/ffprobe-scratch
npm init -y >/dev/null && npm install ffprobe-static@3.1.0
FFPROBE=/tmp/ffprobe-scratch/node_modules/ffprobe-static/bin/linux/x64/ffprobe
"$FFPROBE" -version   # expect: ffprobe version 4.0.2-static
cd -

# 3. espeak-ng CLI shim (apt is unavailable/offline here; the wheel bundles the real
#    engine, libespeak-ng, and the shim exposes the CLI FreeVideoForge expects)
mkdir -p /tmp/fvf-bin
sed "1s|.*|$PWD/.venv/bin/python|" artifacts/amc-explainer/tools/espeak-ng-shim.py > /tmp/fvf-bin/espeak-ng
chmod +x /tmp/fvf-bin/espeak-ng
/tmp/fvf-bin/espeak-ng --version

# 4. Preflight doctor — must report "No blockers"
PATH=/tmp/fvf-bin:$PATH FVF_FFPROBE="$FFPROBE" \
  PYTHONPATH=services/freevideoforge .venv/bin/python -m freevideoforge doctor

# 5. Render (takes ~80 s on 2 vCPU; measured 79.24 s, peak RSS ~654 MB)
artifacts/amc-explainer/source/generate.sh
# equivalent to:
#   PATH=/tmp/fvf-bin:$PATH FVF_FFPROBE="$FFPROBE" PYTHONPATH=services/freevideoforge \
#   .venv/bin/python -m freevideoforge generate \
#     --topic "Agent Mission Control OS" \
#     --brief "$(cat artifacts/amc-explainer/source/brief.txt)" \
#     --duration 30 --aspect 9:16 --preset ffmpeg_motion --style slate \
#     --quality high --seed 20261109
```

The run prints the output directory (default `out/run-<timestamp>/`); the seven output
files land there. Copy them into this package, or compare `final.mp4` against
`environment-record.json → files["final.mp4"].sha256`.

**Determinism.** Same commit + same seed + same inputs ⇒ the same script, storyboard,
captions and frame content. Encoded bytes can differ across FFmpeg/x264 builds; frame
content does not. The quality/loudness numbers (−20.5 LUFS, drift +0.206 s) are
host-independent because narration is measured, not assumed.

## Verify the rebuild

```bash
"$FFPROBE" -v error -show_entries format=duration,size:stream=codec_name,width,height,r_frame_rate,pix_fmt,channels,sample_rate \
  -of default=noprint_wrappers=1 out/run-*/final.mp4
.venv/bin/python - <<'PY'
import subprocess, glob, os
ff = os.path.join(os.environ.get('IMAGEIO', ''), '')  # imageio-ffmpeg path:
import imageio_ffmpeg; ff = imageio_ffmpeg.get_ffmpeg_exe()
y = sorted(glob.glob("out/run-*/final.mp4"))[-1]
print(subprocess.run([ff, "-xerror", "-i", y, "-f", "null", "-"], capture_output=True).returncode == 0 and "DECODE OK")
PY
```

## Optional: Piper narration (not used in this delivery)

FreeVideoForge auto-selects Piper only if the `piper` executable is on PATH and
`FVF_PIPER_MODEL` points at a local `.onnx` voice. Downloading a voice is a deliberate
user action — this delivery ships formant synthesis instead. With Piper present, the
script, scene durations and captions regenerate from the measured neural-voice durations;
re-run the full QA (`qa/qa-report.md`) before treating it as a new delivery.

## Optional: different look, same pipeline

`--style` accepts `editorial|neon|clean|warm|slate`; `--quality draft|balanced|high`;
`--seed` re-rolls motifs/camera/transition picks within the role rules; `--scenes`
overrides scene count (≥ 2; body copy consumes brief sentences in order). Re-run QC
after any change. Do not hand-edit `script.json`/`captions.srt` — that breaks the
one-timing-authority invariant the QC gate enforces.

## Known rebuild caveats

- **fonts**: headline/body faces come from the host (DejaVu family expected). If absent,
  the renderer degrades to Pillow's bitmap font — output still renders but typography
  changes and the QA frame evidence no longer applies.
- **ffprobe version**: the QC gate runs whatever `FVF_FFPROBE` resolves to; results
  recorded here used ffprobe 4.0.2-static (render encoder was FFmpeg n9.0.2). Mixing
  eras is supported by the gate but is called out for honesty.
- **`.venv/` and `out/`** are gitignored; nothing here depends on them being committed.
