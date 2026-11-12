"""The renderer must print with a browser that can print.

The sandbox can rasterize and measure with any Chromium, but printing goes
through a compositor path that fails or hangs here unless Playwright's own
install is used -- and that install ships the browser and its
chrome-headless-shell as two revision-matched directories. Picking a distro
package silently selected the one configuration that cannot print, which is
what these tests pin down.
"""

from __future__ import annotations

from pathlib import Path

from services.langgraph.agency.visual.browser import _playwright_cache_chromium, headless_shell_for


def _install(root: Path, revision: str, *, with_shell: bool = True) -> Path:
    browser = root / f"chromium-{revision}" / "chrome-linux64"
    browser.mkdir(parents=True)
    (browser / "chrome").write_text("#!/bin/sh\n")
    if with_shell:
        shell = root / f"chromium_headless_shell-{revision}" / "chrome-headless-shell-linux64"
        shell.mkdir(parents=True)
        (shell / "chrome-headless-shell").write_text("#!/bin/sh\n")
    return browser / "chrome"


def test_shell_is_found_for_the_same_revision(tmp_path):
    executable = _install(tmp_path, "1254")
    shell = headless_shell_for(executable)
    assert shell is not None and shell.name == "chrome-headless-shell"
    assert "chromium_headless_shell-1254" in str(shell)


def test_a_shell_from_another_revision_is_never_used(tmp_path, monkeypatch):
    """A different build is a different browser; mixing them is the old bug."""
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    executable = _install(tmp_path, "1254", with_shell=False)
    _install(tmp_path, "1248")
    assert headless_shell_for(executable) is None


def test_a_chromium_only_install_reports_no_shell(tmp_path, monkeypatch):
    # Lookup also consults PLAYWRIGHT_BROWSERS_PATH, which on a CI runner holds
    # the real installation. Unset it here, or this would assert about the
    # runner's cache instead of the fixture.
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    executable = _install(tmp_path, "1254", with_shell=False)
    assert headless_shell_for(executable) is None


def test_a_shell_shipped_beside_the_browser_is_found(tmp_path):
    browser = tmp_path / "chromium-1254" / "chrome-linux64"
    browser.mkdir(parents=True)
    (browser / "chrome").write_text("#!/bin/sh\n")
    (browser / "headless_shell").write_text("#!/bin/sh\n")
    shell = headless_shell_for(browser / "chrome")
    assert shell is not None and shell == browser / "headless_shell"


def test_no_browser_means_no_shell():
    assert headless_shell_for(None) is None
    assert headless_shell_for(Path("/nonexistent/chromium-9999/chrome-linux64/chrome")) is None


def test_cache_prefers_the_newest_pair_and_skips_a_browser_without_a_shell(tmp_path, monkeypatch):
    """A browser without its shell is the configuration that cannot print."""
    for revision in ("1248", "1254"):
        browser = tmp_path / f"chromium-{revision}" / "chrome-linux64"
        browser.mkdir(parents=True)
        (browser / "chrome").write_text("#!/bin/sh\n")
        shell = tmp_path / f"chromium_headless_shell-{revision}" / "chrome-headless-shell-linux64"
        shell.mkdir(parents=True)
        (shell / "chrome-headless-shell").write_text("#!/bin/sh\n")
    # Newer, but no shell: must be skipped, not preferred.
    orphan = tmp_path / "chromium-1300" / "chrome-linux64"
    orphan.mkdir(parents=True)
    (orphan / "chrome").write_text("#!/bin/sh\n")

    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    chosen = _playwright_cache_chromium()
    assert chosen is not None and "chromium-1254" in str(chosen)
    assert headless_shell_for(chosen) is not None


def test_the_environment_variable_is_not_required(tmp_path, monkeypatch):
    """The CI step that renders has no PLAYWRIGHT_BROWSERS_PATH set.

    A resolver that returned early without the variable always fell through to
    /usr/bin/chromium there, so this pins that the standard locations are
    checked too.
    """
    # Mirror Playwright's own layout: the browser and its shell are siblings
    # under the cache root, which is what DEFAULT_CHROMIUM's parents describe.
    root = tmp_path / "ms-playwright"
    browser = root / "chromium-1254" / "chrome-linux64"
    browser.mkdir(parents=True)
    (browser / "chrome").write_text("#!/bin/sh\n")
    shell = root / "chromium_headless_shell-1254" / "chrome-headless-shell-linux64"
    shell.mkdir(parents=True)
    (shell / "chrome-headless-shell").write_text("#!/bin/sh\n")

    import services.langgraph.agency.visual.browser as browser_mod

    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    monkeypatch.setattr(browser_mod, "DEFAULT_CHROMIUM", browser / "chrome")
    chosen = browser_mod._playwright_cache_chromium()
    assert chosen is not None and "chromium-1254" in str(chosen)
