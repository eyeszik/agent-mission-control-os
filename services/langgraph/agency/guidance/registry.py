"""Strict registry for repository-owned guidance packs.

Pack files use the JSON-compatible subset of YAML 1.2. JSON is valid YAML 1.2,
which gives the repository a deterministic stdlib parser with duplicate-key
rejection and no custom tags, aliases, or parser-specific coercions.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .models import GuidancePack

REGISTRY_VERSION = "amc-guidance-registry/v1"
_MAX_CACHED_PACK_BYTES = 1_048_576


def _no_duplicate_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate guidance key: {key}")
        result[key] = value
    return result


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def stable_guidance_hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _validate_pack_json(name: str, data: bytes) -> str:
    payload = json.loads(data.decode("utf-8"), object_pairs_hook=_no_duplicate_object_pairs)
    raw_pack = GuidancePack.model_validate(payload)
    canonical = raw_pack.model_dump(mode="json", exclude={"content_hash"})
    computed = stable_guidance_hash(canonical)
    if raw_pack.content_hash and raw_pack.content_hash != computed:
        raise ValueError(f"{name} content_hash mismatch: expected {raw_pack.content_hash}, got {computed}")
    return raw_pack.model_copy(update={"content_hash": computed}).model_dump_json()


@lru_cache(maxsize=32)
def _cached_pack_json(name: str, data: bytes) -> str:
    """Cache immutable verified serialization, never a caller-owned model."""
    return _validate_pack_json(name, data)


def _read_pack(path: Path) -> GuidancePack:
    # Read actual bytes every time: mtime/size are insufficient integrity keys.
    data = path.read_bytes()
    validate = _cached_pack_json if len(data) <= _MAX_CACHED_PACK_BYTES else _validate_pack_json
    return GuidancePack.model_validate_json(validate(path.name, data))


class GuidanceRegistry:
    def __init__(self, packs: list[GuidancePack]) -> None:
        by_id: dict[str, GuidancePack] = {}
        for pack in packs:
            if pack.id in by_id:
                raise ValueError(f"duplicate guidance pack id: {pack.id}")
            by_id[pack.id] = pack

        known = set(by_id)
        for pack in packs:
            missing = sorted(set(pack.dependencies) - known)
            if missing:
                raise ValueError(f"{pack.id} has unresolved dependencies: {missing}")
            overlap = sorted(set(pack.dependencies) & set(pack.conflicts_with))
            if overlap:
                raise ValueError(f"{pack.id} both depends on and conflicts with: {overlap}")

        self._packs = dict(sorted(by_id.items()))

    @classmethod
    def from_directory(cls, directory: str | Path) -> "GuidanceRegistry":
        root = Path(directory)
        packs = [_read_pack(path) for path in sorted(root.glob("*.yaml"))]
        if not packs:
            raise ValueError(f"no guidance packs found in {root}")
        return cls(packs)

    @property
    def packs(self) -> list[GuidancePack]:
        return list(self._packs.values())

    @property
    def registry_hash(self) -> str:
        return stable_guidance_hash(
            {
                "version": REGISTRY_VERSION,
                "packs": [
                    {"id": pack.id, "content_hash": pack.content_hash}
                    for pack in self.packs
                ],
            }
        )

    def get(self, pack_id: str) -> GuidancePack:
        return self._packs[pack_id]


def default_registry() -> GuidanceRegistry:
    return GuidanceRegistry.from_directory(Path(__file__).parent / "packs")
