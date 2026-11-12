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

from services.langgraph.agency.visual.browser import headless_shell_for


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


def test_a_shell_from_another_revision_is_never_used(tmp_path):
    """A different build is a different browser; mixing them is the old bug."""
    executable = _install(tmp_path, "1254", with_shell=False)
    _install(tmp_path, "1248")
    assert headless_shell_for(executable) is None


def test_a_chromium_only_install_reports_no_shell(tmp_path):
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
