"""A layout run that fails part-way keeps the measurements it already took.

Regression witness: when a capture after measurement threw, the runner's top-level handler overwrote the
result.json that ``finally`` had just persisted, so one failed screenshot discarded the layout of every page.
In the brand book this surfaced as all 22 body pages stored unmeasured and re-rendered on the next build
(test_vnexus_brandbook.py:221, "22 == 0", intermittent in CI).
"""

import pytest

from services.langgraph.agency.visual.browser import measure_layout, probe_browser

NEEDS_BROWSER = pytest.mark.skipif(not probe_browser().get("available", False), reason="NOT_RUN: local Chromium unavailable")

_SECTION = ('<section data-page="{id}" style="width:200px;height:120px{extra}"><div class="body" style="width:180px;height:100px">'
            '<p data-copy="t-{id}">page {id}</p></div><div class="pf">Page {n} of 03</div></section>')


def _book(hidden: str | None = None) -> str:
    parts = [_SECTION.format(id=pid, n=f"{i:02d}", extra=";display:none" if pid == hidden else "")
             for i, pid in enumerate(("p01", "p02", "p03"), start=1)]
    return "<!doctype html><html><body style='margin:0'>" + "".join(parts) + "</body></html>"


@NEEDS_BROWSER
def test_a_failed_capture_keeps_every_page_already_measured(tmp_path):
    run = measure_layout(_book(hidden="p02"), width=200, height=120, out_dir=tmp_path / "m", capture=True, timeout_s=120)
    assert run["status"] == "FAILED", "a capture that failed must still fail the run"
    assert [p["id"] for p in run["pages"]] == ["p01", "p02", "p03"], "measurements taken before the fault survive"
    assert set(run["captures"]) == {"p01", "p03"}, "the other pages are still captured"
    assert any(f.startswith("CAPTURE_FAILED:p02") for f in run["findings"]), run["findings"]
    assert any(f.startswith("CAPTURE_FAILED:p02") and "| retry:" in f for f in run["findings"]), \
        "a failed capture is retried once before it is recorded"


@NEEDS_BROWSER
def test_a_clean_run_is_unchanged(tmp_path):
    run = measure_layout(_book(), width=200, height=120, out_dir=tmp_path / "m", capture=True, timeout_s=120)
    assert run["status"] == "PASSED" and run["findings"] == []
    assert set(run["captures"]) == {"p01", "p02", "p03"}
