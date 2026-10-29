"""AMC-CANON-1 cross-language parity fixture (Python is the reference).

`packages/canonical/tests/fixtures/amc-canon-1.json` records tagged inputs and the
bytes and hash Python produces for each. `@amc/canonical` must reproduce every
entry byte-for-byte. This test checks the stored entries still match Python, so
a change to `agency/execution/canonical.py` fails here before it silently breaks
the TypeScript twin. Regenerate with AMC_REGENERATE_FIXTURES=1.

Tagged inputs: {"$int": "<decimal>"}, {"$float": "<python repr>"} and
{"$bytes": "<base64>"} stand for values JSON cannot carry distinctly, and
{"$utf16": "<hex code units>"} for strings some JSON parsers refuse (lone
surrogates); every other
object is a mapping, every array a sequence.
"""
from __future__ import annotations

import base64
import json
import os
import random
import struct
from pathlib import Path
from typing import Any

import pytest

from services.langgraph.agency.execution.canonical import (
    canonical_bytes,
    canonical_hash,
    hash_multifile_manifest,
)

FIXTURE = Path(__file__).resolve().parents[3] / "packages/canonical/tests/fixtures/amc-canon-1.json"
TAGS = ("$int", "$float", "$bytes", "$utf16")


def decode(node: Any) -> Any:
    if isinstance(node, list):
        return [decode(x) for x in node]
    if not isinstance(node, dict):
        return node
    if len(node) == 1 and next(iter(node)) in TAGS:
        tag, raw = next(iter(node.items()))
        if tag == "$int":
            return int(raw)
        if tag == "$float":
            return float(raw)
        if tag == "$utf16":
            return "".join(chr(int(unit, 16)) for unit in raw.split())
        return base64.b64decode(raw)
    return {k: decode(v) for k, v in node.items()}


def _f(x: float) -> dict[str, str]:
    return {"$float": repr(x)}


def _i(x: int) -> dict[str, str]:
    return {"$int": str(x)}


def _handwritten() -> list[tuple[str, Any]]:
    return [
        ("null", None), ("true", True), ("false", False),
        ("int zero", _i(0)), ("negative int", _i(-42)),
        ("int beyond 2^53", _i(2**53 + 1)), ("int beyond 2^64", _i(-(2**70) - 3)),
        ("integral float", _f(2.0)), ("negative zero float", _f(-0.0)),
        ("small float", _f(1e-05)), ("large float", _f(1e16)), ("huge float", _f(1.7976931348623157e308)),
        ("subnormal float", _f(5e-324)), ("tenth", _f(0.1)), ("third", _f(1 / 3)),
        ("empty string", ""), ("ascii string", "hello"), ("accented string", "café"),
        ("astral string", "brand \U0001f3a8 kit"), ("bytes", {"$bytes": base64.b64encode(b"\x00\xffAMC").decode()}),
        ("empty list", []), ("empty dict", {}), ("nested", {"b": [1, {"c": None}], "a": "x"}),
        ("utf8 key order", {"～": 1, "\U0001f600": 2, "z": 3, "é": 4, "": 5}),
        ("mixed list", [_i(1), _f(1.5), "s", None, True, [], {}]),
    ]


def _random_float(r: random.Random) -> float:
    while True:
        kind = r.randrange(3)
        if kind == 0:
            x = struct.unpack("<d", r.getrandbits(64).to_bytes(8, "little"))[0]
        elif kind == 1:
            x = r.uniform(-1, 1) * 10 ** r.randint(-30, 30)
        else:
            x = round(r.uniform(-1000, 1000), r.randint(0, 6))
        if x == x and abs(x) != float("inf"):
            return x


def _random_text(r: random.Random) -> str:
    alphabet = ["a", "Z", "0", " ", "é", "ß", "中", "～", "\U0001f600", "\U0001f3a8", "\n", '"']
    return "".join(r.choice(alphabet) for _ in range(r.randint(0, 8)))


def _random_value(r: random.Random, depth: int) -> Any:
    kind = r.randrange(8 if depth < 3 else 5)
    leaves = [None, r.random() < 0.5, _i(r.randint(-(2**80), 2**80)), _f(_random_float(r)), _random_text(r)]
    if kind < 5:
        return leaves[kind]
    if kind == 5:
        return {"$bytes": base64.b64encode(r.randbytes(r.randint(0, 6))).decode()}
    if kind == 6:
        return [_random_value(r, depth + 1) for _ in range(r.randint(0, 4))]
    keys = {_random_text(r) for _ in range(r.randint(0, 4))} - set(TAGS)
    return {k: _random_value(r, depth + 1) for k in keys}


def _case(name: str, tagged: Any) -> dict[str, Any]:
    value = decode(tagged)
    return {"name": name, "input": tagged, "bytes_hex": canonical_bytes(value).hex(), "hash": canonical_hash(value)}


def build_fixture() -> dict[str, Any]:
    r = random.Random(1729)
    cases = [_case(n, t) for n, t in _handwritten()]
    cases += [_case(f"random float {i}", _f(_random_float(r))) for i in range(300)]
    cases += [_case(f"random value {i}", _random_value(r, 0)) for i in range(200)]
    files = [{"path": "b/ü.svg", "byte_hash": "ab" * 32, "size": 12, "media_type": "image/svg+xml"},
             {"path": "a.png", "byte_hash": "cd" * 32, "size": 0}]
    return {
        "protocol": "AMC-CANON-1",
        "cases": cases,
        "errors": [{"name": "nan", "input": _f(float("nan"))}, {"name": "infinity", "input": _f(float("inf"))},
                   {"name": "lone surrogate", "input": {"$utf16": "61 d800"}}],
        "manifests": [{"files": files, "hash": hash_multifile_manifest(files)}],
    }


def _load() -> dict[str, Any]:
    if os.environ.get("AMC_REGENERATE_FIXTURES") == "1" or not FIXTURE.exists():
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(json.dumps(build_fixture(), indent=1, ensure_ascii=True) + "\n")
    return json.loads(FIXTURE.read_text())


def test_fixture_cases_match_python_reference() -> None:
    fixture = _load()
    assert len(fixture["cases"]) > 500
    for case in fixture["cases"]:
        value = decode(case["input"])
        assert canonical_bytes(value).hex() == case["bytes_hex"], case["name"]
        assert canonical_hash(value) == case["hash"], case["name"]


def test_fixture_errors_are_rejected_by_python() -> None:
    for case in _load()["errors"]:
        with pytest.raises(ValueError):
            canonical_bytes(decode(case["input"]))


def test_fixture_manifests_match_python_reference() -> None:
    for manifest in _load()["manifests"]:
        assert hash_multifile_manifest(manifest["files"]) == manifest["hash"]
