"""Brand book page previews survive a retried layout run, and a missing one says why.

Regression witness for the intermittent CI failure test_vnexus_brandbook.py:342 ("404 == 200" on a page preview):
a layout run that failed was replaced wholesale by its retry, so a preview the first run had captured was lost
whenever the retry missed it, and the build recorded nothing about why the preview was absent. These tests drive
the retry helper with a stand-in for measure_layout, so they need no browser.
"""

from pathlib import Path

from services.langgraph.agency.vnexus.brandbook.service import _capture_reasons, _measure_with_one_retry


def _run(status: str, pages: list[str], captures: dict[str, str], findings: list[str]) -> dict:
    return {"status": status, "pages": [{"id": p} for p in pages], "captures": captures, "findings": findings}


def _layout(*runs: dict):
    calls: list[Path] = []

    def measure_layout(html: str, *, out_dir: Path, **kwargs) -> dict:
        calls.append(out_dir)
        return runs[len(calls) - 1]

    return measure_layout, calls


def test_a_clean_run_is_used_once(tmp_path):
    measure, calls = _layout(_run("PASSED", ["p01"], {"p01": "page-p01.png"}, []))
    done = _measure_with_one_retry(measure, "<html/>", tmp_path / "m0")
    assert done.runs == 1 and calls == [tmp_path / "m0"] and done.findings == []
    assert done.captures == {"p01": tmp_path / "m0" / "page-p01.png"}


def test_a_capture_from_the_first_run_survives_a_retry_that_misses_it(tmp_path):
    first = _run("FAILED", ["p01", "p06"], {"p06": "page-p06.png"}, ["CAPTURE_FAILED:p01: Timeout"])
    retry = _run("FAILED", ["p01", "p06"], {"p01": "page-p01.png"}, ["CAPTURE_FAILED:p06: Timeout"])
    measure, calls = _layout(first, retry)
    done = _measure_with_one_retry(measure, "<html/>", tmp_path / "m0")
    assert done.runs == 2 and calls == [tmp_path / "m0", tmp_path / "m0-retry"]
    assert done.captures == {"p06": tmp_path / "m0" / "page-p06.png", "p01": tmp_path / "m0-retry" / "page-p01.png"}
    assert done.run is retry and done.findings == ["CAPTURE_FAILED:p01: Timeout", "CAPTURE_FAILED:p06: Timeout"]


def test_the_retry_wins_for_a_page_both_runs_captured(tmp_path):
    first = _run("FAILED", ["p01"], {"p01": "page-p01.png"}, ["BROWSER_EXIT:1"])
    retry = _run("PASSED", ["p01"], {"p01": "page-p01.png"}, [])
    done = _measure_with_one_retry(_layout(first, retry)[0], "<html/>", tmp_path / "m0")
    assert done.captures == {"p01": tmp_path / "m0-retry" / "page-p01.png"} and done.run is retry


def test_first_run_measurements_stand_when_the_retry_measured_nothing(tmp_path):
    first = _run("FAILED", ["p01", "p02"], {}, ["CAPTURE_FAILED:p02: Timeout"])
    retry = _run("FAILED", [], {}, ["BROWSER_EXIT:1", "LAYOUT_NOT_MEASURED"])
    done = _measure_with_one_retry(_layout(first, retry)[0], "<html/>", tmp_path / "m0")
    assert done.run is first and done.runs == 2


def test_a_retry_that_measured_is_preferred_over_the_first_run(tmp_path):
    first = _run("FAILED", [], {}, ["BROWSER_EXIT:1"])
    retry = _run("PASSED", ["p01"], {"p01": "page-p01.png"}, [])
    assert _measure_with_one_retry(_layout(first, retry)[0], "<html/>", tmp_path / "m0").run is retry


def test_capture_reasons_name_the_page_then_fall_back():
    findings = ["CAPTURE_FAILED:p06: Timeout | retry: Timeout", "CAPTURE_FAILED:p07: hidden", "BROWSER_EXIT:1"]
    assert _capture_reasons("p06", findings) == ["CAPTURE_FAILED:p06: Timeout | retry: Timeout"]
    assert _capture_reasons("p01", findings) == ["BROWSER_EXIT:1"]
    assert _capture_reasons("p01", ["CAPTURE_FAILED:p07: hidden"]) == ["NO_CAPTURE_RECORDED"]
    assert _capture_reasons("p01", []) == ["NO_CAPTURE_RECORDED"]


def test_capture_reasons_never_expose_local_paths():
    raw = ("RUNNER_FAILED: browserType.launch: Target closed\n<launching> /opt/pw-browsers/chromium-1243/chrome "
           "--user-data-dir=/tmp/playwright_x/profile")
    (reason,) = _capture_reasons("p06", [raw])
    assert reason == "RUNNER_FAILED: browserType.launch: Target closed"
    (reason,) = _capture_reasons("p06", ["CAPTURE_FAILED:p06: ENOENT /tmp/amc-brandbook-1/m0/page-p06.png" + "x" * 400])
    assert "/tmp/" not in reason and "<path>" in reason and len(reason) <= 200
