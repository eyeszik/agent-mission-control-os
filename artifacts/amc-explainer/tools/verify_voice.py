"""Check local voice bytes against this delivery's recorded identity; no model imports."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys


VOICE = "en_US-joe-medium.onnx"
RECORD = Path(__file__).resolve().parents[1] / "environment-record.json"
CHUNK_SIZE = 1024 * 1024


def _digest(path: Path, size: int) -> str:
    digest = hashlib.sha256()
    remaining = size
    with path.open("rb") as stream:
        for _ in range((size + CHUNK_SIZE - 1) // CHUNK_SIZE):
            chunk = stream.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                raise ValueError("truncated voice file")
            digest.update(chunk)
            remaining -= len(chunk)
        if remaining or stream.read(1):
            raise ValueError("voice file size changed")
    return digest.hexdigest()


def _verify_file(path: Path, expected: dict) -> None:
    size, digest = expected["bytes"], expected["sha256"]
    if type(size) is not int or not 0 < size <= 128 * CHUNK_SIZE:
        raise ValueError("invalid recorded size")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("invalid recorded digest")
    if not path.is_file() or path.stat().st_size != size:
        raise ValueError("voice file missing or size mismatch")
    if _digest(path, size) != digest:
        raise ValueError("voice digest mismatch")


def verify_voice(model: Path) -> None:
    expected = json.loads(RECORD.read_text())["voice_models"]
    _verify_file(model, expected[VOICE])
    _verify_file(Path(str(model) + ".json"), expected[VOICE + ".json"])


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: verify_voice.py LOCAL_MODEL.onnx", file=sys.stderr)
        return 2
    try:
        verify_voice(Path(sys.argv[1]))
    except (OSError, ValueError, KeyError, TypeError):
        print("Piper voice verification failed: local files must match the recorded "
              "sizes and SHA-256 hashes.", file=sys.stderr)
        return 1
    print("Verified the recorded Piper model and sidecar SHA-256 hashes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
