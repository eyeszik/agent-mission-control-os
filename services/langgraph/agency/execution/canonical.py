from __future__ import annotations

import hashlib
import math
from decimal import Decimal
from typing import Any, Mapping, Sequence

HASH_PROTOCOL = "AMC-CANON-1"


class CanonicalizationError(ValueError):
    pass


def _decimal_text(value: float) -> str:
    if not math.isfinite(value):
        raise CanonicalizationError("non-finite floats are not canonicalizable")
    d = Decimal(str(value))
    if d == 0:
        return "0"
    text = format(d.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def canonical_bytes(value: Any) -> bytes:
    """Encode JSON-like values using an explicit, versioned deterministic protocol.

    AMC-CANON-1 is intentionally not mislabeled as RFC 8785. It uses explicit type
    tags and length prefixes so identical semantic inputs produce identical bytes
    across runtimes that implement this specification.
    """

    def enc(v: Any) -> bytes:
        if v is None:
            return b"N"
        if v is True:
            return b"B1"
        if v is False:
            return b"B0"
        if isinstance(v, int) and not isinstance(v, bool):
            return b"I" + str(v).encode("ascii") + b";"
        if isinstance(v, float):
            return b"F" + _decimal_text(v).encode("ascii") + b";"
        if isinstance(v, str):
            raw = v.encode("utf-8")
            return b"S" + str(len(raw)).encode("ascii") + b":" + raw
        if isinstance(v, (bytes, bytearray)):
            raw = bytes(v)
            return b"Y" + str(len(raw)).encode("ascii") + b":" + raw
        if isinstance(v, Mapping):
            items = []
            for key in v:
                if not isinstance(key, str):
                    raise CanonicalizationError("mapping keys must be strings")
            for key in sorted(v.keys(), key=lambda k: k.encode("utf-8")):
                items.append(enc(key))
                items.append(enc(v[key]))
            return b"D" + str(len(v)).encode("ascii") + b":" + b"".join(items)
        if isinstance(v, Sequence) and not isinstance(v, (str, bytes, bytearray)):
            return b"L" + str(len(v)).encode("ascii") + b":" + b"".join(enc(x) for x in v)
        if hasattr(v, "model_dump"):
            return enc(v.model_dump(mode="json"))
        raise CanonicalizationError(f"unsupported canonical type: {type(v).__name__}")

    return HASH_PROTOCOL.encode("ascii") + b"\0" + enc(value)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def hash_binary(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_multifile_manifest(files: list[dict[str, Any]]) -> str:
    normalized = []
    for item in files:
        normalized.append(
            {
                "path": str(item["path"]),
                "byte_hash": str(item["byte_hash"]),
                "size": int(item["size"]),
                "media_type": str(item.get("media_type") or "application/octet-stream"),
            }
        )
    normalized.sort(key=lambda x: x["path"].encode("utf-8"))
    return canonical_hash(normalized)
