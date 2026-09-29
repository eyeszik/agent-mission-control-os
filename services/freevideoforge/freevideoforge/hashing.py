"""Content hashing used for idempotency and provenance.

Scene assets are reused across resumed runs when their *input hash* matches, so
the hash must cover everything that can change the rendered bytes: the creative
spec, the render spec, the provider identity and the seed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .models import to_jsonable

_CHUNK = 1024 * 1024


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_obj(value: Any) -> str:
    payload = json.dumps(to_jsonable(value), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def short(digest: str, length: int = 12) -> str:
    return digest[:length]


def scene_input_hash(scene, render, provider: str, extra: Any = None) -> str:
    """Stable identity of everything that determines a scene's rendered bytes."""
    return sha256_obj(
        {
            "provider": provider,
            "duration": round(float(scene.duration), 3),
            "seed": scene.seed,
            "content": to_jsonable(scene.content),
            "visual": to_jsonable(scene.visual),
            "motion": to_jsonable(scene.motion),
            "render": to_jsonable(render),
            "extra": to_jsonable(extra),
        }
    )
