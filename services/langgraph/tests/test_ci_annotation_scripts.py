"""The CI annotation scripts are the only readable failure signal here.

Hosted logs and artifacts sit behind a blob host that a reviewer in this
environment cannot read, so a check-run annotation is the evidence channel. A
script that silently emits nothing -- which happened with the Playwright
annotator, for two runs -- costs a whole cycle. These tests run the scripts the
way CI does and assert on what they print.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PLAYWRIGHT = REPO / ".github" / "scripts" / "annotate-playwright-junit.py"
PYTEST_ANNOTATOR = REPO / ".github" / "scripts" / "annotate-junit-failures.py"

JUNIT = """<testsuites>
  <testsuite name="visuals">
    <testcase name="Compile, refuse a stale edit" classname="visuals.spec.ts">
      <failure message="Test timeout of 420000ms exceeded.">
Error: Test timeout of 420000ms exceeded.
Call log:
  - waiting for locator('label').filter({ hasText: 'Palette colour' })
    at /repo/apps/web/e2e/visuals.spec.ts:88:5
      </failure>
    </testcase>
    <testcase name="opens fine" classname="ok.spec.ts"/>
  </testsuite>
</testsuites>
"""


def _run(script: Path, report: Path) -> str:
    proc = subprocess.run([sys.executable, str(script), str(report)],
                          capture_output=True, text=True, timeout=60, cwd=str(REPO))
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def test_playwright_annotation_names_the_pending_locator_and_line(tmp_path):
    report = tmp_path / "junit.xml"
    report.write_text(JUNIT, encoding="utf-8")
    out = _run(PLAYWRIGHT, report)
    assert "::failure title=playwright | Compile, refuse a stale edit::" in out
    assert "line 88:5" in out
    assert "Palette colour" in out
    # A passing case must not be annotated as a failure.
    assert "opens fine::" not in out


def test_playwright_annotation_reports_absence_instead_of_silence(tmp_path):
    """The bug that cost two runs: no output at all when the report is absent."""
    out = _run(PLAYWRIGHT, tmp_path / "does-not-exist.xml")
    assert "::warning title=Playwright JUnit missing::" in out
    assert "junit-like" in out  # says what it looked for


def test_pytest_annotation_survives_a_missing_report(tmp_path):
    out = _run(PYTEST_ANNOTATOR, tmp_path / "nope.xml")
    assert out.strip(), "an absent report must be reported, never silent"
