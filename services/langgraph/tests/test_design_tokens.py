"""DTCG 2025.10 compiler, the compile_tokens CLI, and the token-pipeline gate."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from services.langgraph.agency.design_tokens import (
    MissingAliasError,
    TokenCycleError,
    TokenSchemaError,
    TokenTierError,
    TokenTypeError,
    compile_css,
    compile_graph,
    css_variable,
    hex_to_color,
)

ROOT = Path(__file__).resolve().parents[3]


def _color(hex_value: str) -> dict:
    return {"$value": hex_to_color(hex_value)}


def _tiered() -> dict:
    return {
        "primitive": {"color": {"$type": "color", "ink": _color("#111111"), "paper": _color("#fafafa")}},
        "semantic": {"color": {"$type": "color", "fg": {"$value": "{primitive.color.ink}"},
                               "bg": {"$value": "{primitive.color.paper}"}}},
        "component": {"card": {"$type": "color", "text": {"$value": "{semantic.color.fg}"}}},
    }


class TestCompiler:
    def test_valid_document_compiles_with_inherited_types(self):
        graph = compile_graph(_tiered(), tiered=True)
        assert graph.get("primitive.color.ink").css == "#111111"
        assert graph.get("component.card.text").type == "color"

    def test_deep_alias_chains_resolve_to_the_literal(self):
        graph = compile_graph(_tiered(), tiered=True)
        token = graph.get("component.card.text")
        assert token.alias_of == "semantic.color.fg"
        assert token.css == "#111111"

    def test_alias_cycle_fails_closed_with_the_path(self):
        doc = {"a": {"$type": "color", "$value": "{b}"}, "b": {"$value": "{c}"}, "c": {"$value": "{a}"}}
        with pytest.raises(TokenCycleError) as info:
            compile_graph(doc)
        assert info.value.chain[0] == info.value.chain[-1]
        assert " -> " in str(info.value)

    def test_missing_alias_names_the_referrer(self):
        doc = {"x": {"$type": "color", "$value": "{nope.missing}"}}
        with pytest.raises(MissingAliasError, match="x: alias references unknown token"):
            compile_graph(doc)

    def test_declared_type_mismatch_with_alias_target_fails(self):
        doc = {
            "size": {"$type": "dimension", "$value": {"value": 4, "unit": "px"}},
            "wrong": {"$type": "color", "$value": "{size}"},
        }
        with pytest.raises(TokenTypeError, match="does not match alias target type"):
            compile_graph(doc)

    @pytest.mark.parametrize(
        "token",
        [
            {"$type": "color", "$value": "#ff0000"},  # string colors are not DTCG 2025.10
            {"$type": "dimension", "$value": "4px"},
            {"$type": "dimension", "$value": {"value": 4, "unit": "vw"}},
            {"$type": "duration", "$value": {"value": -1, "unit": "ms"}},
            {"$type": "cubicBezier", "$value": [2, 0, 0, 1]},
            {"$type": "gradient", "$value": "x"},
            {"$value": {"value": 1, "unit": "px"}},  # no type anywhere
        ],
    )
    def test_invalid_values_fail_typecheck(self, token):
        with pytest.raises((TokenTypeError, TokenSchemaError)):
            compile_graph({"t": token})

    def test_schema_errors(self):
        with pytest.raises(TokenSchemaError, match="unknown token properties"):
            compile_graph({"t": {"$type": "number", "$value": 1, "$bogus": 1}})
        with pytest.raises(TokenSchemaError, match="malformed alias"):
            compile_graph({"t": {"$type": "color", "$value": "{a}.{b}"}})
        with pytest.raises(TokenSchemaError, match="invalid token/group name"):
            compile_graph({"bad name": {"$type": "number", "$value": 1}})

    def test_wide_gamut_colors_require_an_srgb_fallback(self):
        p3 = {"colorSpace": "display-p3", "components": [0.1, 0.8, 0.4]}
        with pytest.raises(TokenTypeError, match="requires an sRGB 'hex' fallback"):
            compile_graph({"c": {"$type": "color", "$value": p3}})
        graph = compile_graph({"c": {"$type": "color", "$value": {**p3, "hex": "#22cc66"}}})
        assert graph.get("c").css == "#22cc66"

    def test_alpha_colors_emit_modern_rgb(self):
        graph = compile_graph({"c": {"$type": "color", "$value": {"colorSpace": "srgb", "components": [1, 0, 0], "alpha": 0.5}}})
        assert graph.get("c").css == "rgb(255 0 0 / 0.5)"


class TestTiers:
    def test_primitives_must_be_literal(self):
        doc = _tiered()
        doc["primitive"]["color"]["alias"] = {"$value": "{primitive.color.ink}"}
        with pytest.raises(TokenTierError, match="primitive"):
            compile_graph(doc, tiered=True)

    def test_semantic_colors_must_alias(self):
        doc = _tiered()
        doc["semantic"]["color"]["raw"] = _color("#123456")
        with pytest.raises(TokenTierError, match="must alias a lower tier"):
            compile_graph(doc, tiered=True)

    def test_component_tokens_may_not_skip_the_semantic_tier(self):
        doc = _tiered()
        doc["component"]["card"]["skip"] = {"$value": "{primitive.color.ink}"}
        with pytest.raises(TokenTierError, match="must alias semantic"):
            compile_graph(doc, tiered=True)

    def test_unknown_top_level_group_is_rejected_when_tiered(self):
        doc = _tiered()
        doc["misc"] = {"x": {"$type": "number", "$value": 1}}
        with pytest.raises(TokenTierError):
            compile_graph(doc, tiered=True)


class TestCss:
    def test_css_is_deterministic_and_order_independent(self):
        doc = _tiered()
        shuffled = json.loads(json.dumps(doc))
        shuffled["semantic"]["color"] = dict(reversed(list(shuffled["semantic"]["color"].items())))
        _, first = compile_css(doc, prefix="amc", tiered=True)
        _, again = compile_css(doc, prefix="amc", tiered=True)
        _, reordered = compile_css(shuffled, prefix="amc", tiered=True)
        assert first == again == reordered

    def test_css_is_namespaced_and_preserves_aliases(self):
        _, css = compile_css(_tiered(), prefix="amc", tiered=True)
        assert "--amc-primitive-color-ink: #111111;" in css
        assert "--amc-semantic-color-fg: var(--amc-primitive-color-ink);" in css
        assert css.startswith("/* GENERATED FILE -- do not edit by hand.")
        assert "source-sha256:" in css

    def test_css_variable_kebab_cases_segments(self):
        assert css_variable("semantic.color.surfaceRaised", "amc") == "--amc-semantic-color-surface-raised"

    def test_themes_override_only_known_tokens(self):
        theme = {"semantic": {"color": {"bg": {"$value": "{primitive.color.ink}"}}}}
        _, css = compile_css(_tiered(), prefix="amc", tiered=True, themes={"inverse": theme})
        assert '[data-amc-theme="inverse"] {' in css
        assert "--amc-semantic-color-bg: var(--amc-primitive-color-ink);" in css.split("[data-amc-theme")[1]
        with pytest.raises(TokenSchemaError, match="absent from the base"):
            compile_css(_tiered(), tiered=True, themes={"x": {"semantic": {"color": {"new": {"$value": "{primitive.color.ink}"}}}}})


class TestRepositoryTokens:
    def test_canonical_source_preserves_the_zinc_emerald_baseline(self):
        doc = json.loads((ROOT / "apps/web/tokens/amc.tokens.json").read_text())
        graph = compile_graph(doc, tiered=True)
        assert graph.get("semantic.color.background").css == "#09090b"
        assert graph.get("semantic.color.foreground").css == "#a1a1aa"
        assert graph.get("semantic.color.accent").css == "#10b981"
        assert graph.get("primitive.color.emerald.900").css == "#064e3b"

    def test_declared_contrast_pairs_meet_their_wcag_requirement(self):
        from services.langgraph.agency.ui_ux.tokens import wcag_contrast_ratio

        thresholds = {"AAA_NORMAL": 7.0, "AA_NORMAL": 4.5, "AA_LARGE": 3.0, "NON_TEXT": 3.0}
        doc = json.loads((ROOT / "apps/web/tokens/amc.tokens.json").read_text())
        graph = compile_graph(doc, tiered=True)
        for pair in doc["$extensions"]["amc"]["contrastPairs"]:
            ratio = wcag_contrast_ratio(graph.get(pair["foreground"]).css, graph.get(pair["background"]).css)
            assert ratio >= thresholds[pair["wcag"]], (pair, ratio)


class TestCompileTokensCli:
    def _run(self, *args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(ROOT / "compile_tokens.py"), *args],
                              cwd=cwd, capture_output=True, text=True, check=False)

    def test_check_passes_on_the_committed_css(self):
        result = self._run("--check")
        assert result.returncode == 0, result.stderr

    def test_check_is_a_dry_run_that_reports_staleness(self, tmp_path):
        output = tmp_path / "tokens.css"
        output.write_text("stale\n")
        result = self._run("--check", "--output", str(output))
        assert result.returncode == 1
        assert output.read_text() == "stale\n"  # nothing written

    def test_missing_source_fails_and_creates_nothing(self, tmp_path):
        missing = tmp_path / "absent.tokens.json"
        output = tmp_path / "out.css"
        result = self._run("--source", str(missing), "--output", str(output))
        assert result.returncode == 2
        assert not missing.exists() and not output.exists()


def _load_gate():
    spec = importlib.util.spec_from_file_location("verify_design_tokens_pipeline", ROOT / "scripts/verify_design_tokens.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestTokenPipelineGate:
    @pytest.fixture()
    def tree(self, tmp_path, monkeypatch):
        gate = _load_gate()
        for relative in ("apps/web/tokens/amc.tokens.json", "apps/web/app/tokens.css",
                         "apps/web/tailwind.config.ts", "apps/web/app/globals.css"):
            target = tmp_path / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / relative, target)
        (tmp_path / "apps/web/components").mkdir(parents=True)
        (tmp_path / "apps/web/lib").mkdir(parents=True)
        monkeypatch.setattr(gate, "ROOT", tmp_path)
        return gate, tmp_path

    def test_repository_pipeline_is_clean(self):
        assert _load_gate().token_pipeline_violations() == []

    def test_missing_canonical_source_is_a_critical_failure(self, tree):
        gate, root = tree
        (root / "apps/web/tokens/amc.tokens.json").unlink()
        assert gate.token_pipeline_violations() == ["apps/web/tokens/amc.tokens.json: canonical DTCG token source is missing"]

    def test_hand_edited_generated_css_is_flagged(self, tree):
        gate, root = tree
        css = root / "apps/web/app/tokens.css"
        css.write_text(css.read_text().replace("#09090b", "#000000"))
        assert any("stale or hand-edited" in item for item in gate.token_pipeline_violations())

    def test_dangling_token_mapping_is_flagged(self, tree):
        gate, root = tree
        config = root / "apps/web/tailwind.config.ts"
        config.write_text(config.read_text() + '\n// "var(--amc-semantic-color-renamed)"\n')
        assert any("--amc-semantic-color-renamed" in item for item in gate.token_pipeline_violations())

    def test_raw_and_primitive_consumption_rejected_but_definition_sites_allowed(self, tree):
        gate, root = tree
        (root / "apps/web/components/Bad.tsx").write_text(
            "export const a = 'var(--amc-primitive-color-zinc-950)';\nexport const b = '#ff0000';\n"
        )
        found = gate.violations()
        assert any("primitive token" in item for item in found)
        assert any("raw color" in item for item in found)
        # tailwind.config.ts (maps primitives) and tokens.css (generated) are definition sites.
        assert not any("tailwind.config.ts" in item or "tokens.css" in item for item in found)
