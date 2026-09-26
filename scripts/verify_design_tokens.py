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

Token pipeline checks (fail closed):

* The canonical DTCG source (`apps/web/tokens/amc.tokens.json`) must exist and
  compile; a missing source is a broken pipeline, never "nothing to check".
* The generated CSS (`apps/web/app/tokens.css`) must match a fresh compile of
  that source -- a hand edit or a forgotten rebuild fails here.
* Every `var(--amc-*)` a definition site maps (tailwind config, global CSS) must
  be declared by the generated CSS, so a renamed token cannot dangle.
* Consumer code may reference semantic (T2) and component (T3) tokens only;
  `--amc-primitive-*` belongs to definition sites.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TOKEN_SOURCE = "apps/web/tokens/amc.tokens.json"
GENERATED_CSS = "apps/web/app/tokens.css"
# Definition sites whose var(--amc-*) references must resolve.
MAPPING_FILES = ("apps/web/tailwind.config.ts", "apps/web/app/globals.css")

# Directories whose source consumes tokens. Anything outside this set is either
# a token definition site, generated output, or not a rendering surface.
ENFORCED_DIRS = (
    "apps/web/app",
    "apps/web/components",
    "apps/web/lib",
)

ENFORCED_SUFFIXES = (".ts", ".tsx", ".css")

# Paths that define the palette, so a raw value is correct there. The generated
# token CSS is checked for freshness instead of scanned line by line.
TOKEN_DEFINITION_FILES = frozenset({"apps/web/tailwind.config.ts", GENERATED_CSS})

EXCLUDED_PARTS = frozenset({"node_modules", ".next", "dist", "build", "__pycache__"})

# Test files assert on color math with literal values; that is the assertion,
# not a palette fork.
EXCLUDED_DIR_NAMES = frozenset({"tests", "e2e", "__tests__"})

ALLOW_PRAGMA = "amc-allow-hex"

HEX_COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b")
FUNCTIONAL_COLOR = re.compile(r"\b(?:rgba?|hsla?|oklch)\s*\(")

# A CSS custom property declaration: the token definition itself.
CUSTOM_PROPERTY_DECLARATION = re.compile(r"^\s*--[\w-]+\s*:")
PRIMITIVE_REFERENCE = re.compile(r"--amc-primitive-[\w-]+")
AMC_VAR_REFERENCE = re.compile(r"var\((--amc-[\w-]+)\)")
DECLARED_VAR = re.compile(r"^\s*(--[\w-]+)\s*:", re.M)


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
            primitive = PRIMITIVE_REFERENCE.search(line)
            if primitive and relative.as_posix() not in MAPPING_FILES:
                found.append(
                    f"{relative.as_posix()}:{number}: primitive token '{primitive.group(0)}' consumed "
                    "directly -- use a semantic or component token"
                )
    return found


def token_pipeline_violations() -> list[str]:
    """Source exists and compiles, generated CSS is fresh, mappings resolve."""
    from services.langgraph.agency.design_tokens import TokenError, compile_css

    source = ROOT / TOKEN_SOURCE
    if not source.is_file():
        return [f"{TOKEN_SOURCE}: canonical DTCG token source is missing"]
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
        _, expected = compile_css(document, prefix="amc", tiered=True, source_label=TOKEN_SOURCE)
    except (TokenError, json.JSONDecodeError) as exc:
        return [f"{TOKEN_SOURCE}: does not compile: {exc}"]

    generated = ROOT / GENERATED_CSS
    if not generated.is_file():
        return [f"{GENERATED_CSS}: generated token CSS is missing -- run `pnpm tokens:build`"]
    found: list[str] = []
    actual = generated.read_text(encoding="utf-8")
    if actual != expected:
        found.append(
            f"{GENERATED_CSS}: stale or hand-edited -- regenerate with `pnpm tokens:build`"
        )
    declared = set(DECLARED_VAR.findall(actual))
    for mapping in MAPPING_FILES:
        path = ROOT / mapping
        if not path.is_file():
            found.append(f"{mapping}: token mapping file is missing")
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for name in AMC_VAR_REFERENCE.findall(line):
                if name not in declared:
                    found.append(f"{mapping}:{number}: '{name}' is not declared in {GENERATED_CSS}")
    return found


def main() -> None:
    for directory in ENFORCED_DIRS:
        if not (ROOT / directory).is_dir():
            raise SystemExit(f"design-token gate is scoped to a missing directory: {directory}")

    found = violations()
    pipeline = token_pipeline_violations()
    for item in found + pipeline:
        print(item, file=sys.stderr)
    if found or pipeline:
        raise SystemExit(
            f"design-token gate: {len(found)} consumption violation(s), "
            f"{len(pipeline)} token pipeline violation(s)"
        )

    print(
        "design-token gate: frontend source references tokens, no raw colors; "
        "DTCG source compiles and generated CSS is current"
    )


if __name__ == "__main__":
    main()
