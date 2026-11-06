"""Active gate references must resolve: missing validators fail closed and are
never recreated to satisfy the reference."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def invariants():
    spec = importlib.util.spec_from_file_location("verify_repository_invariants_discovery",
                                                  ROOT / "scripts/verify_repository_invariants.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tree(tmp_path: Path, makefile: str, web_scripts: dict | None = None) -> Path:
    (tmp_path / ".github/workflows").mkdir(parents=True)
    (tmp_path / ".github/workflows/ci.yml").write_text("steps:\n  - run: python scripts/verify_ok.py\n")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/verify_ok.py").write_text("")
    (tmp_path / "Makefile").write_text(makefile)
    (tmp_path / "apps/web").mkdir(parents=True)
    (tmp_path / "apps/web/package.json").write_text(json.dumps({"scripts": web_scripts or {}}))
    return tmp_path


def test_the_repository_has_no_dangling_gate_references(invariants):
    assert invariants.missing_validator_references() == []


def test_missing_validator_is_reported_and_not_created(invariants, tmp_path):
    root = _tree(tmp_path, "gates:\n\t@python3 scripts/verify_gone.py\n")
    problems = invariants.missing_validator_references(root)
    assert problems == ["Makefile: references missing validator/script scripts/verify_gone.py"]
    assert not (root / "scripts/verify_gone.py").exists()


def test_relocated_validator_resolves_through_its_current_path(invariants, tmp_path):
    root = _tree(tmp_path, "gates:\n\t@python3 scripts/verify_ok.py\n")
    assert invariants.missing_validator_references(root) == []


def test_missing_package_script_is_reported(invariants, tmp_path):
    root = _tree(tmp_path, "ui:\n\tpnpm --filter @amc/web verify:ui\n", web_scripts={"test": "vitest"})
    assert invariants.missing_validator_references(root) == [
        "Makefile: `pnpm --filter @amc/web verify:ui` has no such package script"
    ]


def test_missing_gate_definition_file_is_critical(invariants, tmp_path):
    root = _tree(tmp_path, "")
    (root / ".github/workflows/ci.yml").unlink()
    assert invariants.missing_validator_references(root) == [
        ".github/workflows/ci.yml: missing (gate definitions cannot be verified)"
    ]
