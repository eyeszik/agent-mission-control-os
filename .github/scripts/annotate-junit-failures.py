#!/usr/bin/env python3
"""Publish failing test cases as GitHub annotations.

Logs and uploaded artifacts are served from a blob host. A reviewer without
access to that host sees only "Process completed with exit code 1" and cannot
tell which test failed. Annotations come from the API instead, so they name the
failing test and its message where such a reviewer can read them.

Usage: annotate-junit-failures.py <junit.xml> [<junit.xml> ...]

Missing or unparsable reports are reported, not fatal: this runs in a failure()
step and must never mask the real failure with a parse error of its own.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

MAX_MESSAGE = 300


def first_line(text: str) -> str:
    stripped = (text or "").strip()
    if not stripped:
        return "no message"
    return stripped.splitlines()[0][:MAX_MESSAGE]


def cases(path: Path) -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        print(f"::warning title=JUnit unreadable::{path}: {exc}")
        return found
    for case in root.iter("testcase"):
        # <error> is an exception, <failure> an assertion; both fail the run.
        problem = case.find("failure")
        if problem is None:
            problem = case.find("error")
        if problem is None:
            continue
        found.append((
            case.get("classname") or "(unknown class)",
            case.get("name") or "(unnamed test)",
            first_line(problem.get("message") or ""),
        ))
    return found


def main(argv: list[str]) -> int:
    paths = [Path(a) for a in argv[1:]]
    if not paths:
        print("::warning title=JUnit::no report paths were given")
        return 0

    offending: list[tuple[str, str, str]] = []
    read_any = False
    for path in paths:
        if not path.is_file():
            print(f"::warning title=JUnit missing::no report at {path}")
            continue
        read_any = True
        offending.extend(cases(path))

    if not read_any:
        print("No JUnit report was written, so the failing tests are unknown from here.")
        return 0

    summary = Path(__import__("os").environ.get("GITHUB_STEP_SUMMARY") or "/dev/null")
    lines = [f"### {len(offending)} failing test(s)", ""]
    if offending:
        lines += ["```"] + [f"{c}::{n} :: {m}" for c, n, m in offending] + ["```"]
    else:
        lines.append("The report contains no failing or erroring test cases.")
    try:
        with summary.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    except OSError:
        pass

    for classname, name, message in offending:
        # Annotation titles must be single-line and reasonably short.
        title = f"{classname.rsplit('.', 1)[-1]}::{name}"[:200]
        print(f"::error title={title}::{message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
