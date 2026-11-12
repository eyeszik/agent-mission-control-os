#!/usr/bin/env python3
"""Publish the pending step of a timed-out Playwright test as an annotation.

A Playwright timeout message names only the test. The step that was actually
waiting is in the JUnit ``failure`` body ("at ...visuals.spec.ts:NN:NN" plus the
locator text), together with any console output the test captured. Artifacts
and logs live on a blob host that a reviewer here cannot read, so the useful
part is lifted into a check-run annotation instead.

Usage: annotate-playwright-junit.py <junit.xml>
"""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

MAX_MESSAGE = 900


def _json_case(name: str) -> str:
    """The failing case's own record from the JSON report.

    A junit ``<failure>`` can be empty -- Playwright writes the timeout with no
    text for some failures -- and an annotation with an empty message is dropped
    by GitHub, which is exactly how a 420s timeout reached the check run as
    nothing but "Process completed with exit code 1". The JSON report always
    carries ``error.message`` and ``error.location``, so it is consulted by name
    rather than replacing the junit body when that body exists.
    """
    import glob
    import json

    for path in sorted(glob.glob("apps/web/**/report.json", recursive=True)):
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        found: list[str] = []

        def walk(suite: dict) -> None:
            for spec in suite.get("specs", []) or []:
                for test in spec.get("tests", []) or []:
                    results = test.get("results", []) or []
                    if not results or results[-1].get("status") in (None, "passed", "skipped"):
                        continue
                    if spec.get("title") and spec.get("title") not in name and name not in (spec.get("title") or ""):
                        continue
                    error = results[-1].get("error") or {}
                    where = error.get("location") or {}
                    at = f"pending at line {where.get('line')}:{where.get('column')}. " if where else ""
                    steps = [f"{s.get('title')} {s.get('duration', 0)}ms" for s in (results[-1].get("steps") or [])
                             if s.get("title")]
                    found.append(at + (error.get("message") or "") + (" steps: " + " -> ".join(steps[-4:]) if steps else ""))
            for child in suite.get("suites", []) or []:
                walk(child)

        for suite in data.get("suites", []) or []:
            walk(suite)
        if found:
            return found[0]
    return ""


def emit(level: str, title: str, message: str) -> None:
    flat = " ".join(message.split())[:MAX_MESSAGE]
    print(f"::{level} title={title}::{flat}")


def _from_json() -> int:
    """Fall back to the HTML/JSON report's own record of the pending step.

    Playwright writes ``playwright-report/index.html`` plus a data blob; the
    compact JSON reporter output is easier and is what CI keeps when the XML
    reporter did not run at all. If neither exists this stays a warning rather
    than inventing a cause.
    """
    import glob
    import json

    candidates = sorted(glob.glob("apps/web/**/report.json", recursive=True)
                        + glob.glob("apps/web/**/*.json", recursive=True))
    for path in candidates:
        if "test-results" not in path and "playwright-report" not in path:
            continue
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or "suites" not in data:
            continue
        emitted = 0

        def walk(suite: dict) -> None:
            nonlocal emitted
            for spec in suite.get("specs", []) or []:
                for test in spec.get("tests", []) or []:
                    results = test.get("results", []) or []
                    if not results or results[-1].get("status") in (None, "passed", "skipped"):
                        continue
                    error = (results[-1].get("error") or {}).get("message") or ""
                    location = (results[-1].get("error") or {}).get("location") or {}
                    where = ""
                    if location:
                        where = f"pending at line {location.get('line')}:{location.get('column')}. "
                    emit("error", f"playwright | {spec.get('title')}", where + error)
                    emitted += 1
            for child in suite.get("suites", []) or []:
                walk(child)

        for suite in data.get("suites", []) or []:
            walk(suite)
        if emitted:
            return 0
    emit("warning", "Playwright JUnit missing", "no junit xml and no usable json report")
    return 0


def _from_log() -> int:
    """Last resort: the reporter's stdout, which holds the call log.

    Playwright prints the pending locator and the spec line to stdout, not to
    the junit xml. CI tees it to /tmp/playwright-e2e.log precisely so this can
    read it when the structured reports do not carry the detail.
    """
    log = Path("/tmp/playwright-e2e.log")
    if not log.is_file():
        emit("warning", "Playwright log missing", "no /tmp/playwright-e2e.log")
        return 0
    text = log.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    emitted = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not (stripped.startswith("1) ") or stripped.startswith("2) ") or stripped.startswith("3) ")):
            continue
        title = stripped.split(")", 1)[1].strip()
        window = " ".join(part.strip() for part in lines[index:index + 25])
        emit("error", f"playwright | {title}"[:120], window[:MAX_MESSAGE])
        emitted += 1
        if emitted >= 5:
            break
    if not emitted:
        # Nothing structured at all: say what the tail looked like.
        emit("warning", "Playwright log", " ".join(lines[-12:])[:MAX_MESSAGE] or "empty log")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        emit("warning", "Playwright annotations", "usage: annotate-playwright-junit.py <junit.xml>")
        return 0
    report = Path(argv[1])
    if not report.is_file():
        # Never report "missing" without also saying what *is* there: the
        # previous silent run cost a cycle because the path was assumed rather
        # than observed. Look for any junit xml near the project and name it.
        import glob

        found = sorted(glob.glob("apps/web/**/junit*.xml", recursive=True)
                       + glob.glob("apps/web/**/*junit*.xml", recursive=True))
        guess = sorted(glob.glob("apps/web/test-results/**/*.xml", recursive=True))[:10]
        detail = f"no report at {report}; junit-like: {found[:5] or 'none'}; xml under test-results: {guess or 'none'}"
        emit("warning", "Playwright JUnit missing", detail)
        if found:
            report = Path(found[0])
        else:
            json_status = _from_json()
            return _from_log() if json_status == 0 else json_status
    try:
        root = ET.parse(report).getroot()
    except ET.ParseError as exc:
        emit("warning", "Playwright JUnit unparsable", str(exc))
        return 0

    if root.tag != "testsuites" and root.tag != "testsuite":
        # XML reporter can emit a bare <testcase> root; handle it the same way.
        pass
    cases = list(root.iter("testcase"))
    emit("notice", "playwright report", f"parsed {report} with {len(cases)} case(s)")
    for case in cases:
        failures = list(case.iter("failure")) + list(case.iter("error"))
        if not failures:
            continue
        name = case.get("name") or "(unnamed)"
        body = (failures[0].text or "") or failures[0].get("message") or ""
        if not body.strip():
            # An empty <failure> becomes an empty annotation, and GitHub drops
            # those: the case is reported failed with no reason at all.
            body = _json_case(name) or f"case failed with an empty <failure> element; no JSON record for {name!r}"
        # The last frame before the timeout points at the locator that never
        # resolved; earlier frames are Playwright internals.
        where = re.findall(r"at .*?\.spec\.ts:(\d+):(\d+)", body)
        payload = body
        if where:
            line, col = where[0]
            payload = f"pending at spec line {line}:{col}. " + body
        emit("error", f"playwright | {name}", payload[:MAX_MESSAGE])

    # Always say what the report contained. A run that fails while the report
    # holds no failing case is itself the finding -- it means Playwright exited
    # non-zero for a reason outside any test (a fatal reporter error, a browser
    # launch failure, a killed process), and silence there is what turned this
    # into several wasted cycles.
    cases = list(root.iter("testcase"))
    skipped = sum(1 for case in cases if list(case.iter("skipped")))
    failed = sum(1 for case in cases if list(case.iter("failure")) or list(case.iter("error")))
    passed = len(cases) - skipped - failed
    emit("notice", "playwright summary",
         f"{len(cases)} case(s): {passed} passed, {failed} failed, {skipped} skipped"
         + ("" if failed else " -- no failing case, so the non-zero exit came from outside a test"))
    durations = []
    for suite in root.iter("testsuite"):
        for case in suite.iter("testcase"):
            try:
                durations.append((float(case.get("time") or 0), case.get("name") or "?"))
            except ValueError:
                continue
    if durations:
        slowest = sorted(durations, reverse=True)[:3]
        emit("notice", "playwright slowest",
             "; ".join(f"{name} {seconds:.1f}s" for seconds, name in slowest))
    if not failed:
        _from_log()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
