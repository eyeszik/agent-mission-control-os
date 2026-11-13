"""Dependency-layout regressions; fixture packages do not claim real browser QA."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from services.langgraph.agency.ucpo import qa
from services.langgraph.agency.ucpo.sandbox import Isolation


@pytest.fixture
def modules(tmp_path, monkeypatch):
    web, tools, cache = (tmp_path / name for name in ("web", "tools", "browser-cache"))
    monkeypatch.setattr(qa, "WEB_NODE_MODULES", web)
    # Make host /opt installs irrelevant while exercising both supported roots.
    def fixture_path(value):
        return {"/opt/node-tools/node_modules": tools, "/opt/pw-browsers": cache}.get(str(value), Path(value))
    monkeypatch.setattr(qa, "Path", fixture_path)
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return web, tools, cache


def package(root, name):
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "package.json").write_text(json.dumps({"name": name, "main": "index.js"}))
    return folder


@pytest.mark.parametrize("root_index", (0, 1))
@pytest.mark.parametrize("name", ("@playwright/test", "playwright"))
def test_discovers_scoped_and_legacy_packages_in_either_root(modules, root_index, name, monkeypatch):
    selected = package(modules[root_index], name)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/fixture/custom-browsers")
    assert qa._playwright_paths() == (str(modules[root_index]), "/fixture/custom-browsers", str(selected))


def test_declared_scoped_package_wins_over_leftover_legacy_install(modules):
    web, tools, _ = modules
    package(tools, "playwright")
    selected = package(web, "@playwright/test")
    assert qa._playwright_paths() == (str(web), None, str(selected))


def test_scoped_package_symlink_and_default_browser_cache(modules, tmp_path):
    web, _, cache = modules
    actual = package(tmp_path / ".pnpm" / "fixture", "@playwright/test")
    (web / "@playwright").mkdir(parents=True)
    (web / "@playwright" / "test").symlink_to(actual, target_is_directory=True)
    cache.mkdir()
    assert qa._playwright_paths() == (str(web), "/opt/pw-browsers", str(web / "@playwright/test"))


def test_user_default_browser_cache_is_passed_into_the_scrubbed_sandbox(modules, tmp_path):
    web, _, _ = modules
    selected = package(web, "@playwright/test")
    default = tmp_path / "home" / ".cache" / "ms-playwright"
    default.mkdir(parents=True)
    assert qa._playwright_paths() == (str(web), str(default), str(selected))


def test_missing_dependency_remains_unavailable(modules):
    assert qa._playwright_paths() == (None, None, None)


def test_verify_build_passes_selected_package_to_runner(modules, tmp_path, monkeypatch):
    web, _, _ = modules
    selected = package(web, "@playwright/test")
    axe = tmp_path / "axe.min.js"
    axe.write_text("/* fixture */")
    monkeypatch.setattr(qa, "axe_path", lambda: axe)
    export = tmp_path / "export"
    export.mkdir()
    (export / "index.html").write_text("<html></html>")
    observed = []
    def runner(argv, **kwargs):
        config = json.loads(Path(argv[-1]).read_text())
        observed.append(config["playwright_module"])
        # A deliberately empty fixture observation must stay BLOCKED, never PASS.
        Path(config["result_path"]).write_text('{"routes": {}}')
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(qa, "wrap", lambda command, **kwargs: command)
    monkeypatch.setattr(qa.subprocess, "run", runner)
    result = qa.verify_build(export, routes=["/"], expected_output_hash=qa.output_digest(export)[0],
                             isolation=Isolation(True, (), node="fixture-node"))
    assert observed == [str(selected)]
    assert result.status == "BLOCKED"


def test_node_runner_loads_the_selected_package_instead_of_ambient_playwright(modules, tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("NOT_RUN: Node is unavailable")
    web, _, _ = modules
    selected = package(web, "@playwright/test")
    legacy = package(web, "playwright")
    (selected / "index.js").write_text("exports.chromium = {launch: async () => {throw new Error('FIXTURE_SELECTED_SCOPED_PACKAGE')}};")
    (legacy / "index.js").write_text("throw new Error('FIXTURE_WRONG_LEGACY_PACKAGE');")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"out_dir": str(tmp_path), "playwright_module": str(selected)}))
    result = subprocess.run([node, str(qa.RUNNER), str(config)], capture_output=True, text=True, timeout=10,
                            env={"NODE_PATH": str(web)})
    assert result.returncode != 0  # Fixture stops before any browser launch.
    assert "FIXTURE_SELECTED_SCOPED_PACKAGE" in result.stderr
    assert "FIXTURE_WRONG_LEGACY_PACKAGE" not in result.stderr


def test_click_evidence_is_not_assumed_and_a_failed_navigation_blocks():
    """Synthetic runner observations exercise interpretation, not browser execution."""
    def selected(row):
        checks, _, _ = qa.interpret({"routes": {"/": row}}, ["/"], {})
        return {c.check: c for c in checks}

    missing = selected({})
    assert missing["cta_navigation"].result == "NOT_RUN"
    assert missing["nav_navigation"].result == "NOT_RUN"
    failed = selected({"cta_interactions": [{"href": "/contact/#connect", "req": "req.index.s1.cta", "ok": False}],
                       "nav_interactions": [{"href": "/about/", "req": "req.nav.about", "ok": True}]})
    assert failed["cta_navigation"].result == "FAIL"
    assert failed["cta_navigation"].req_refs == ("req.index.s1.cta",)
    assert failed["nav_navigation"].result == "PASS"
    assert failed["nav_navigation"].req_refs == ("req.nav.about",)
    empty = selected({"cta_interactions": [], "nav_interactions": []})
    assert empty["nav_navigation"].result == "FAIL"
    assert "cta_navigation" not in empty  # no link was clicked
    assert empty["cta_discovery"].result == "PASS" and not empty["cta_discovery"].req_refs
    assert "no clicks" in empty["cta_discovery"].detail


@pytest.mark.parametrize("observation", [None, {}, "", [None], [{"unexpected": "object"}],
                                         [{"href": "/about/", "req": "req.nav.about", "ok": "true"}],
                                         [{"href": None, "req": "req.nav.about", "ok": True}]])
def test_missing_or_malformed_interaction_observations_do_not_pass(observation):
    checks, _, _ = qa.interpret({"routes": {"/": {"cta_interactions": observation, "nav_interactions": observation}}},
                                ["/"], {})
    selected = {c.check: c for c in checks}
    assert selected["cta_navigation"].result == "NOT_RUN" and not selected["cta_navigation"].req_refs
    assert selected["nav_navigation"].result == "NOT_RUN" and not selected["nav_navigation"].req_refs


@pytest.mark.parametrize("observation", [None, {}, "", [None], [{"unexpected": "object"}]])
def test_missing_or_malformed_browser_console_and_network_observations_do_not_pass(observation):
    """A missing runner observation is not equivalent to an observed clean list."""
    checks, _, blocked_requests = qa.interpret({"routes": {"/": {"console": observation, "aborted": observation}}},
                                                ["/"], {})
    selected = {c.check: c for c in checks}
    assert selected["console_clean"].result == "NOT_RUN"
    assert selected["no_external_requests"].result == "NOT_RUN"
    assert blocked_requests == ()


def test_observed_console_and_network_lists_are_interpreted_explicitly():
    checks, _, blocked_requests = qa.interpret(
        {"routes": {"/": {"console": [], "aborted": ["https://example.test/"]}}}, ["/"], {})
    selected = {c.check: c for c in checks}
    assert selected["console_clean"].result == "PASS"
    assert selected["no_external_requests"].result == "FAIL"
    assert blocked_requests == ("https://example.test/",)
