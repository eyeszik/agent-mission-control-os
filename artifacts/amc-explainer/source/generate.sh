#!/bin/sh
# Final render — the exact command behind the delivered final.mp4.
# Run from the repository root at the pinned commit. See REPRODUCTION.md.
# Requires: piper-tts and an explicit, hash-verified local voice (REPRODUCTION.md §1).
set -eu
REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$REPO_ROOT"
export PATH="$REPO_ROOT/.venv/bin:$PATH"       # piper executable
: "${FVF_PIPER_MODEL:?Set FVF_PIPER_MODEL to the recorded local en_US-joe-medium.onnx file}"
export FVF_PIPER_MODEL
"$REPO_ROOT/.venv/bin/python" -I artifacts/amc-explainer/tools/verify_voice.py "$FVF_PIPER_MODEL"
export FVF_FFPROBE="${FVF_FFPROBE:-/tmp/ffprobe-scratch/node_modules/ffprobe-static/bin/linux/x64/ffprobe}"
PYTHONPATH=services/freevideoforge "$REPO_ROOT/.venv/bin/python" -m freevideoforge generate \
  --topic "Agent Mission Control OS" \
  --brief "$(cat artifacts/amc-explainer/source/brief.txt)" \
  --duration 30 --aspect 9:16 --preset ffmpeg_motion --style slate \
  --quality high --seed 20261109
