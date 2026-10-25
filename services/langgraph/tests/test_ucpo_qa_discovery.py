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
