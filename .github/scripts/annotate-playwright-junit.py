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
                    emit("failure", f"playwright | {spec.get('title')}", where + error)
                    emitted += 1
            for child in suite.get("suites", []) or []:
                walk(child)

        for suite in data.get("suites", []) or []:
            walk(suite)
        if emitted:
            return 0
    emit("warning", "Playwright JUnit missing", "no junit xml and no usable json report")
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
            return _from_json()
    try:
        root = ET.parse(report).getroot()
    except ET.ParseError as exc:
        emit("warning", "Playwright JUnit unparsable", str(exc))
        return 0

    if root.tag != "testsuites" and root.tag != "testsuite":
        # XML reporter can emit a bare <testcase> root; handle it the same way.
        pass
    for case in root.iter("testcase"):
        failures = list(case.iter("failure")) + list(case.iter("error"))
        if not failures:
            continue
        name = case.get("name") or "(unnamed)"
        body = (failures[0].text or "") or failures[0].get("message") or ""
        # The last frame before the timeout points at the locator that never
        # resolved; earlier frames are Playwright internals.
        where = re.findall(r"at .*?\.spec\.ts:(\d+):(\d+)", body)
        payload = body
        if where:
            line, col = where[0]
            payload = f"pending at spec line {line}:{col}. " + body
        emit("failure", f"playwright | {name}", payload[:MAX_MESSAGE])

    skipped = sum(1 for case in root.iter("testcase") if list(case.iter("skipped")))
    total = sum(1 for _ in root.iter("testcase"))
    if not skipped:
        emit("notice", "playwright coverage", f"no test was skipped ({total} cases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
