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


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        emit("warning", "Playwright annotations", "usage: annotate-playwright-junit.py <junit.xml>")
        return 0
    report = Path(argv[1])
    if not report.is_file():
        emit("warning", "Playwright JUnit missing", f"no report at {report}")
        return 0
    try:
        root = ET.parse(report).getroot()
    except ET.ParseError as exc:
        emit("warning", "Playwright JUnit unparsable", str(exc))
        return 0

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
