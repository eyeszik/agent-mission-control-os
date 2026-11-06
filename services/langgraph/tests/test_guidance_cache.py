"""Cache optimization must preserve live source integrity and caller isolation."""
from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from services.langgraph.agency.guidance import registry as module

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "services/langgraph/agency/guidance/packs/branding.yaml"


@pytest.fixture(autouse=True)
def clear_cache():
    module._cached_pack_json.cache_clear()
    yield
    module._cached_pack_json.cache_clear()


def fixture_pack(tmp_path):
    path = tmp_path / SOURCE.name
    payload = json.loads(SOURCE.read_text())
    pack = module.GuidancePack.model_validate(payload)
    payload["content_hash"] = module.stable_guidance_hash(pack.model_dump(mode="json", exclude={"content_hash"}))
    path.write_text(json.dumps(payload, ensure_ascii=False))
    return path


def test_warm_load_avoids_repeated_verification_but_returns_independent_models(tmp_path, monkeypatch):
    fixture_pack(tmp_path)
    calls = []
    original = module.stable_guidance_hash
    def counted(value):
        calls.append(value)
        return original(value)
    monkeypatch.setattr(module, "stable_guidance_hash", counted)
    first = module.GuidanceRegistry.from_directory(tmp_path)
    second = module.GuidanceRegistry.from_directory(tmp_path)
    assert len(calls) == 1
    assert first.packs == second.packs and first.packs[0] is not second.packs[0]
    first.packs[0].sections[0].directives.append("caller-local mutation")
    first.packs[0].activation.task_tags.append("caller-local tag")
    third = module.GuidanceRegistry.from_directory(tmp_path)
    assert third.packs == second.packs
    assert "caller-local mutation" not in third.packs[0].sections[0].directives


def test_same_size_same_mtime_tamper_is_not_hidden_by_a_warm_cache(tmp_path):
    path = fixture_pack(tmp_path)
    module.GuidanceRegistry.from_directory(tmp_path)
    before = path.stat()
    data = path.read_bytes()
    assert b'"description"' in data
    # Change a schema-valid value without changing length or the file's timestamp.
    match = re.search(rb'"description":\s*"([A-Za-z])', data)
    assert match is not None
    pos = match.start(1)
    changed = data[:pos] + bytes([data[pos] ^ 32]) + data[pos + 1:]
    assert changed != data
    path.write_bytes(changed)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert path.stat().st_size == before.st_size
    with pytest.raises(ValueError, match="content_hash mismatch"):
        module.GuidanceRegistry.from_directory(tmp_path)


def test_valid_resealed_edit_changes_registry_hash_and_deletion_removes_it(tmp_path):
    path = fixture_pack(tmp_path)
    first = module.GuidanceRegistry.from_directory(tmp_path)
    raw = json.loads(path.read_text())
    raw["description"] += " Fixture revision."
    raw["content_hash"] = ""
    path.write_text(json.dumps(raw))
    second = module.GuidanceRegistry.from_directory(tmp_path)
    assert first.registry_hash != second.registry_hash
    path.unlink()
    with pytest.raises(ValueError, match="no guidance packs"):
        module.GuidanceRegistry.from_directory(tmp_path)


def test_warm_cache_does_not_mask_duplicate_keys_or_poison_corrected_content(tmp_path):
    path = fixture_pack(tmp_path)
    expected = module.GuidanceRegistry.from_directory(tmp_path).registry_hash
    original = path.read_bytes()
    path.write_bytes(b'{"id":"first","id":"second"}')
    with pytest.raises(ValueError, match="duplicate guidance key"):
        module.GuidanceRegistry.from_directory(tmp_path)
    path.write_bytes(original)
    assert module.GuidanceRegistry.from_directory(tmp_path).registry_hash == expected


def test_concurrent_callers_cannot_contaminate_each_other(tmp_path):
    fixture_pack(tmp_path)
    module.GuidanceRegistry.from_directory(tmp_path)
    def load_and_mutate(index):
        registry = module.GuidanceRegistry.from_directory(tmp_path)
        registry.packs[0].sections[0].directives.append(f"fixture-{index}")
        return registry
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(load_and_mutate, range(8)))
    for i, result in enumerate(results):
        assert result.packs[0].sections[0].directives[-1] == f"fixture-{i}"
    assert all(not text.startswith("fixture-") for text in module.GuidanceRegistry.from_directory(tmp_path).packs[0].sections[0].directives)


def test_cache_has_a_fixed_entry_limit_and_large_sources_bypass_it(tmp_path, monkeypatch):
    fixture_pack(tmp_path)
    monkeypatch.setattr(module, "_MAX_CACHED_PACK_BYTES", 0)
    first = module.GuidanceRegistry.from_directory(tmp_path)
    assert first.packs and module._cached_pack_json.cache_info().currsize == 0
    monkeypatch.setattr(module, "_MAX_CACHED_PACK_BYTES", 1_048_576)
    original = SOURCE.read_bytes()
    for i in range(40):
        module._cached_pack_json(f"fixture-{i}.yaml", original)
    assert module._cached_pack_json.cache_info().currsize == 32
    assert module.GuidanceRegistry.from_directory(tmp_path).packs == first.packs
