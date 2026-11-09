#!/bin/sh
# Final render — the exact command behind the delivered final.mp4.
# Run from the repository root at the pinned commit. See REPRODUCTION.md.
set -eu
export PATH="/tmp/fvf-bin:$PATH"                 # espeak-ng shim (tools/espeak-ng-shim.py)
export FVF_FFPROBE="${FVF_FFPROBE:-/tmp/ffprobe-scratch/node_modules/ffprobe-static/bin/linux/x64/ffprobe}"
PYTHONPATH=services/freevideoforge .venv/bin/python -m freevideoforge generate \
  --topic "Agent Mission Control OS" \
  --brief "$(cat artifacts/amc-explainer/source/brief.txt)" \
  --duration 30 --aspect 9:16 --preset ffmpeg_motion --style slate \
  --quality high --seed 20261109
