# FFprobe provisioning (reproducible)

FreeVideoForge's structural QC needs `ffprobe` (frame inspection, codec
validation). `ffmpeg` alone is insufficient because `imageio-ffmpeg` does not
ship `ffprobe`.

## Discovery order

Implemented in `services/freevideoforge/freevideoforge/ffmpeg.py`:

1. Explicit override: `FVF_FFMPEG` / `FVF_FFPROBE` env vars or `Settings(ffmpeg_path=...)`
2. System `PATH` (`shutil.which("ffprobe")`)
3. Sibling of a real `ffmpeg` binary (if ffmpeg found, look for `ffprobe` next to it)
4. `imageio-ffmpeg` wheel — **ffmpeg only**, not ffprobe (documented fallback; QC remains blocked without ffprobe)

Never rely on `/tmp/ffprobe-static` or manually-installed machine state.

## Developer setup

```bash
# Debian/Ubuntu (CI and local)
sudo apt-get update && sudo apt-get install -y ffmpeg
ffmpeg -version   # must succeed
ffprobe -version  # must succeed

# Optional imageio fallback (ffmpeg only)
pip install imageio-ffmpeg
```

## CI consistency

`freevideoforge/doctor.py` reports `toolchain.ffprobe_version` and lists missing
ffprobe as a blocker. `.github/workflows/ci.yml` should ensure `ffmpeg` is
installed where QC tests run (add `sudo apt-get install -y ffmpeg` to relevant jobs
if not already via base image).

## Verification

```bash
ffprobe -version
python -c "from freevideoforge.ffmpeg import FFTools; print(FFTools().version('ffprobe'))"
python -m pytest services/langgraph/tests/test_ffprobe_provisioning.py -q
```
