#!/usr/bin/env python3
"""Verify that frontend source consumes design tokens instead of raw colors.

`brand_core` describes color qualitatively; `design_token_set` compiles it into
implementable values. That split only holds if the values land in one place and
everything else references them. A hex literal in a component silently forks the
palette away from the brand object, and nothing downstream can tell.

So this gate draws the line by location rather than by value:

* **Token definition sites** may hold raw colors, because defining them is the
  point -- `tailwind.config.ts` and CSS custom-property declarations (`--name: #hex`).
* **Consumption sites** may not -- components, pages, and app/lib modules
  reference `var(--token)` or a Tailwind class instead.

Enforced here rather than through ESLint: this repository states its invariants
as CI-gated Python scanners (see the sibling `verify_*.py`), and ESLint would
need `typescript-eslint` before it could parse a single `.ts` file here. A sixth
gate costs no dependencies and runs in the job the other five already run in.

Escape hatch: a line carrying `amc-allow-hex` is skipped. It leaves the decision
greppable, which a silent exemption list would not.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Directories whose source consumes tokens. Anything outside this set is either
# a token definition site, generated output, or not a rendering surface.
ENFORCED_DIRS = (
    "apps/web/app",
    "apps/web/components",
    "apps/web/lib",
)

ENFORCED_SUFFIXES = (".ts", ".tsx", ".css")

# Paths that define the palette, so a raw value is correct there.
TOKEN_DEFINITION_FILES = frozenset({"apps/web/tailwind.config.ts"})

EXCLUDED_PARTS = frozenset({"node_modules", ".next", "dist", "build", "__pycache__"})

# Test files assert on color math with literal values; that is the assertion,
# not a palette fork.
EXCLUDED_DIR_NAMES = frozenset({"tests", "e2e", "__tests__"})

ALLOW_PRAGMA = "amc-allow-hex"

HEX_COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b")
FUNCTIONAL_COLOR = re.compile(r"\b(?:rgba?|hsla?|oklch)\s*\(")

# A CSS custom property declaration: the token definition itself.
CUSTOM_PROPERTY_DECLARATION = re.compile(r"^\s*--[\w-]+\s*:")


def _is_comment_line(line: str, suffix: str) -> bool:
    stripped = line.strip()
    if suffix == ".css":
        return stripped.startswith("/*") or stripped.startswith("*")
    return stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("/*")


def _iter_enforced_files():
    for directory in ENFORCED_DIRS:
        base = ROOT / directory
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix not in ENFORCED_SUFFIXES:
                continue
            relative = path.relative_to(ROOT)
            parts = set(relative.parts)
            if parts & EXCLUDED_PARTS or parts & EXCLUDED_DIR_NAMES:
                continue
            if relative.as_posix() in TOKEN_DEFINITION_FILES:
                continue
            yield path, relative


def violations() -> list[str]:
    found: list[str] = []
    for path, relative in _iter_enforced_files():
        suffix = path.suffix
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if ALLOW_PRAGMA in line or _is_comment_line(line, suffix):
                continue
            # A CSS custom property declaration is a token definition, which is
            # exactly where a literal value belongs.
            if suffix == ".css" and CUSTOM_PROPERTY_DECLARATION.match(line):
                continue
            match = HEX_COLOR.search(line) or FUNCTIONAL_COLOR.search(line)
            if match:
                found.append(
                    f"{relative.as_posix()}:{number}: raw color '{match.group(0)}' -- "
                    "reference a design token instead"
                )
    return found


def main() -> None:
    for directory in ENFORCED_DIRS:
        if not (ROOT / directory).is_dir():
            raise SystemExit(f"design-token gate is scoped to a missing directory: {directory}")

    found = violations()
    if found:
        for item in found:
            print(item, file=sys.stderr)
        raise SystemExit(
            f"design-token gate: {len(found)} raw color value(s) outside a token definition site"
        )

    print("design-token gate: frontend source references tokens, no raw colors")


if __name__ == "__main__":
    main()
