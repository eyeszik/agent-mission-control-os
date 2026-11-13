"""The CI annotation scripts are the only readable failure signal here.

Hosted logs and artifacts sit behind a blob host that a reviewer in this
environment cannot read, so a check-run annotation is the evidence channel. A
script that silently emits nothing -- which happened with the Playwright
annotator, for two runs -- costs a whole cycle. These tests run the scripts the
way CI does and assert on what they print.
"""

from __future__ import annotations

import re
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


def _run(script: Path, report: Path, cwd: Path | None = None) -> str:
    # cwd matters: both annotators resolve their fallback reports relative to the
    # working directory, exactly as the CI step does from the repository root.
    # Pinning it here (rather than chdir-ing the test process) is what makes the
    # difference between reading a report and reporting that none exists.
    proc = subprocess.run([sys.executable, str(script), str(report)],
                          capture_output=True, text=True, timeout=60, cwd=str(cwd or REPO))
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def test_annotations_use_a_level_the_runner_actually_accepts(tmp_path):
    """"::failure" is not a workflow command.

    It is printed, and then ignored: the case is reported failed with no reason
    at all. Only error, warning and notice become annotations, so every level
    this script emits is asserted here.
    """
    report = tmp_path / "junit.xml"
    report.write_text(JUNIT, encoding="utf-8")
    out = _run(PLAYWRIGHT, report)
    levels = set(re.findall(r"^::(\w+) ", out, re.M))
    assert levels <= {"error", "warning", "notice"}, levels
    assert "error" in levels


def test_playwright_annotation_names_the_pending_locator_and_line(tmp_path):
    report = tmp_path / "junit.xml"
    report.write_text(JUNIT, encoding="utf-8")
    out = _run(PLAYWRIGHT, report)
    assert "::error title=playwright | Compile, refuse a stale edit::" in out
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


def test_playwright_annotation_always_reports_a_summary(tmp_path):
    """A failing run whose report holds no failing case is itself the finding.

    The run exits non-zero for a reason outside any test -- a fatal reporter
    error, a browser launch failure, a killed process -- and reporting nothing
    is what made that indistinguishable from a clean run.
    """
    report = tmp_path / "junit.xml"
    report.write_text(
        '<testsuites><testsuite name="s">'
        '<testcase name="fast one" time="2.5"/>'
        '<testcase name="slow one" time="88.2"/>'
        '<testcase name="skipped one"><skipped/></testcase>'
        "</testsuite></testsuites>", encoding="utf-8")
    out = _run(PLAYWRIGHT, report)
    assert "::notice title=playwright summary::3 case(s): 2 passed, 0 failed, 1 skipped" in out
    assert "non-zero exit came from outside a test" in out
    # The slowest case is reported, because "which journey is slow" is the
    # question a duration-driven failure asks.
    assert "::notice title=playwright slowest::slow one 88.2s" in out


def test_playwright_annotation_falls_back_to_the_runner_log(tmp_path, monkeypatch):
    """The call log with the pending locator exists only on stdout."""
    log = Path("/tmp/playwright-e2e.log")
    log.write_text(
        "  1) visuals.spec.ts:51:5 > Compile, refuse a stale edit\n\n"
        "Error: Test timeout of 420000ms exceeded.\n"
        "  - waiting for locator('label')\n    at visuals.spec.ts:88:5\n",
        encoding="utf-8")
    try:
        out = _run(PLAYWRIGHT, tmp_path / "absent.xml")
        assert "Compile, refuse a stale edit" in out
        assert "waiting for locator" in out
    finally:
        log.unlink(missing_ok=True)

EMPTY_FAILURE = """<testsuites><testsuite name="visuals">
  <testcase name="Compile, refuse a stale edit, apply a current one, request approval" time="422.5">
    <failure/>
  </testcase>
</testsuite></testsuites>
"""

# What Playwright's JSON reporter writes for the same timed-out case: the error
# message and the step durations that the junit body left empty.
REPORT_JSON = """{"suites": [{"title": "visuals.spec.ts", "specs": [
  {"title": "Compile, refuse a stale edit, apply a current one, request approval",
   "tests": [{"results": [{"status": "failed", "duration": 422500,
     "error": {"message": "Test timeout of 420000ms exceeded.",
               "location": {"file": "visuals.spec.ts", "line": 96, "column": 47}},
     "steps": [{"title": "open the visual compiler", "duration": 900},
               {"title": "the compiled asset renders and evaluates", "duration": 419000}]}]}]}]}]}
"""


def test_an_empty_failure_still_names_the_case_and_its_location(tmp_path):
    """A 420s timeout reached the check run as "exit code 1" and nothing else.

    Playwright can write ``<failure/>`` with no text; GitHub drops an annotation
    whose message is empty, so the one readable channel went blank. The JSON
    report carries what the XML omitted, and the annotation must use it.
    """
    (tmp_path / "apps" / "web").mkdir(parents=True)
    (tmp_path / "apps" / "web" / "report.json").write_text(REPORT_JSON, encoding="utf-8")
    report = tmp_path / "junit.xml"
    report.write_text(EMPTY_FAILURE, encoding="utf-8")
    out = _run(PLAYWRIGHT, report, cwd=tmp_path)
    assert "::error title=playwright | Compile, refuse a stale edit" in out
    assert "line 96:47" in out, f"empty failure lost its location:\n{out}"
    assert "no JSON record" not in out, f"the JSON report was not consulted:\n{out}"
    # The step durations say which phase ate the budget.
    assert "the compiled asset renders and evaluates" in out
