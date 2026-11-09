# Reproducing this video from the pinned commit

Target: rebuild `final.mp4` (or your own variant) on a Linux host with Python ≥ 3.10,
Node ≥ 18, and network access **only for dependency installation** (pypi.org,
registry.npmjs.org). The render itself uses no network.

Tested on: Debian-ish x86_64, Python 3.11.2, Node v22.22.3, 2026-11-09.

```bash
# 0. Pin the source
git clone <this-repo> && cd agent-mission-control-os
git checkout f947863a85dfb31f56f06b37b0dfeafaf9de0149

# 1. Python environment (build tools only; never committed, .venv is gitignored)
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install pillow imageio-ffmpeg piper-tts joe-us-piper-voice

# 1a. The Piper voice — installed by pip from PyPI, NOT downloaded by FreeVideoForge.
#     joe-us-piper-voice bundles en_US-joe-medium (CC0). Expected SHA-256:
#       en_US-joe-medium.onnx      58afce0321b8d9c46d7cdf9c16500cc55a793b4220212dba6b70fb788b3baf06
#       en_US-joe-medium.onnx.json 3d6d5410b3795cb1950595247ef8f06190719e6fdbfa3a2356d8ec368e1aad33
python3 - <<'PY'
import hashlib, pathlib
from joe_us_piper_voice import model_path
p = pathlib.Path(model_path())
print(p)
print('onnx  ', hashlib.sha256(p.read_bytes()).hexdigest())
print('config', hashlib.sha256(p.with_suffix('.onnx.json').read_bytes()).hexdigest())
PY
```

```bash
# 2. ffprobe — imageio-ffmpeg ships none. The static build via npm needs no compile:
mkdir -p /tmp/ffprobe-scratch && cd /tmp/ffprobe-scratch
npm init -y >/dev/null && npm install ffprobe-static@3.1.0
FFPROBE=/tmp/ffprobe-scratch/node_modules/ffprobe-static/bin/linux/x64/ffprobe
"$FFPROBE" -version   # expect: ffprobe version 4.0.2-static
cd -

# 3. Piper must be resolvable: the `piper` executable on PATH and FVF_PIPER_MODEL
#    pointing at the .onnx voice. With the steps above:
export PATH="$PWD/.venv/bin:$PATH"
export FVF_PIPER_MODEL="$(.venv/bin/python -c 'from joe_us_piper_voice import model_path; print(model_path())')"

# 4. Preflight doctor — must report "No blockers" and list `+ speech piper`
FVF_FFPROBE="$FFPROBE" PYTHONPATH=services/freevideoforge \
  .venv/bin/python -m freevideoforge doctor

# 5. Render (~2 min on 2 vCPU in the 2026-11-09 rebuild; drift +0.206 s)
artifacts/amc-explainer/source/generate.sh
# equivalent to:
#   PATH="$PWD/.venv/bin:$PATH" FVF_FFPROBE="$FFPROBE" FVF_PIPER_MODEL="$FVF_PIPER_MODEL" \
#   PYTHONPATH=services/freevideoforge .venv/bin/python -m freevideoforge generate \
#     --topic "Agent Mission Control OS" \
#     --brief "$(cat artifacts/amc-explainer/source/brief.txt)" \
#     --duration 30 --aspect 9:16 --preset ffmpeg_motion --style slate \
#     --quality high --seed 20261109
```

The run prints the output directory (default `out/run-<timestamp>/`); the seven output
files land there. Copy them into this package, or compare `final.mp4` against
`environment-record.json → files["final.mp4"].sha256`.

**Determinism.** Same commit + same seed + same inputs ⇒ the same script, storyboard and
frame content. Encoded bytes can differ across FFmpeg/x264 builds; frame content does
not. The scene plan (motifs, camera, transitions, seeds) is unchanged from the superseded
espeak build; **caption cue times differ** because they are derived from measured
narration durations. The loudness numbers (−19.5 LUFS integrated) are not host-independent
in principle — they were not re-tuned between the two builds to avoid cherry-picking.

## Verify the rebuild

```bash
"$FFPROBE" -v error -show_entries format=duration,size:stream=codec_name,width,height,r_frame_rate,pix_fmt,channels,sample_rate \
  -of default=noprint_wrappers=1 out/run-*/final.mp4
.venv/bin/python - <<'PY'
import subprocess, glob
import imageio_ffmpeg; ff = imageio_ffmpeg.get_ffmpeg_exe()
y = sorted(glob.glob("out/run-*/final.mp4"))[-1]
print(subprocess.run([ff, "-xerror", "-i", y, "-f", "null", "-"], capture_output=True).returncode == 0 and "DECODE OK")
PY
```

## Fallback: espeak-ng narration

If Piper cannot be installed, the superseded espeak-ng route remains documented and
functional. It produces robotic formant speech, was fully QC'd when it shipped in #244,
and is **not** interchangeable with this build without re-running QC:

```bash
.venv/bin/pip install espeakng-loader
mkdir -p /tmp/fvf-bin
sed "1s|.*|$PWD/.venv/bin/python|" artifacts/amc-explainer/tools/espeak-ng-shim.py > /tmp/fvf-bin/espeak-ng
chmod +x /tmp/fvf-bin/espeak-ng
PATH=/tmp/fvf-bin:$PATH FVF_FFPROBE="$FFPROBE" PYTHONPATH=services/freevideoforge \
  .venv/bin/python -m freevideoforge generate \
    --topic "Agent Mission Control OS" \
    --brief "$(cat artifacts/amc-explainer/source/brief.txt)" \
    --duration 30 --aspect 9:16 --preset ffmpeg_motion --style slate \
    --quality high --seed 20261109
```

Expected deltas vs this build: scenes plan unchanged; narration is formant speech;
caption timings revert to the #244 values; integrated loudness measured −20.5 LUFS /
−2.4 dBTP / LRA 5.6 LU on that build. Re-run `qa/qa-report.md` end-to-end before treating
it as a delivery.

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
- **voice provenance**: `joe-us-piper-voice` is a third-party repackaging of upstream
  rhasspy `piper-voices` (voice CC0). If you prefer the official artifacts, download
  `en_US-lessac-medium` instead and set `FVF_PIPER_MODEL` to it — fewer questions to
  answer, ~60 MB you choose to fetch. Re-run QC either way.
- **`.venv/` and `out/`** are gitignored; nothing here depends on them being committed.
