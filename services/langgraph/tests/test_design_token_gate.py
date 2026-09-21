from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
GATE_PATH = ROOT / "scripts" / "verify_design_tokens.py"


def _load_gate():
    spec = importlib.util.spec_from_file_location("verify_design_tokens", GATE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gate():
    return _load_gate()


def test_the_repository_currently_passes_the_gate(gate):
    assert gate.violations() == []


class TestScoping:
    def test_the_tailwind_config_is_treated_as_a_token_definition_site(self, gate):
        # It holds the palette; raw values there are the definition, not a fork.
        assert "apps/web/tailwind.config.ts" in gate.TOKEN_DEFINITION_FILES

    def test_enforced_directories_all_exist(self, gate):
        for directory in gate.ENFORCED_DIRS:
            assert (ROOT / directory).is_dir(), f"gate scoped to missing dir {directory}"

    def test_generated_output_is_excluded(self, gate):
        assert ".next" in gate.EXCLUDED_PARTS
        assert "node_modules" in gate.EXCLUDED_PARTS


class TestDetection:
    def test_a_hex_literal_in_a_component_is_flagged(self, gate, tmp_path, monkeypatch):
        component = ROOT / "apps/web/components/__gate_probe__.tsx"
        component.write_text("export const c = '#ff0000';\n", encoding="utf-8")
        try:
            found = gate.violations()
            assert any("__gate_probe__" in item for item in found)
        finally:
            component.unlink()

    def test_a_functional_color_in_a_component_is_flagged(self, gate):
        component = ROOT / "apps/web/components/__gate_probe__.tsx"
        component.write_text("export const c = 'rgb(1, 2, 3)';\n", encoding="utf-8")
        try:
            assert any("__gate_probe__" in item for item in gate.violations())
        finally:
            component.unlink()

    def test_a_css_custom_property_declaration_is_allowed(self, gate):
        # :root token definitions are exactly where literal values belong.
        stylesheet = ROOT / "apps/web/app/__gate_probe__.css"
        stylesheet.write_text(":root {\n  --probe: #123456;\n}\n", encoding="utf-8")
        try:
            assert not any("__gate_probe__" in item for item in gate.violations())
        finally:
            stylesheet.unlink()

    def test_a_css_hex_outside_a_custom_property_is_flagged(self, gate):
        stylesheet = ROOT / "apps/web/app/__gate_probe__.css"
        stylesheet.write_text(".probe {\n  color: #123456;\n}\n", encoding="utf-8")
        try:
            assert any("__gate_probe__" in item for item in gate.violations())
        finally:
            stylesheet.unlink()

    def test_the_allow_pragma_exempts_a_line(self, gate):
        component = ROOT / "apps/web/components/__gate_probe__.tsx"
        component.write_text(
            f"export const c = '#ff0000'; // {gate.ALLOW_PRAGMA} deliberate\n",
            encoding="utf-8",
        )
        try:
            assert not any("__gate_probe__" in item for item in gate.violations())
        finally:
            component.unlink()

    def test_a_commented_out_color_is_not_flagged(self, gate):
        component = ROOT / "apps/web/components/__gate_probe__.tsx"
        component.write_text("// was #ff0000 before tokens\nexport const c = 1;\n", encoding="utf-8")
        try:
            assert not any("__gate_probe__" in item for item in gate.violations())
        finally:
            component.unlink()
