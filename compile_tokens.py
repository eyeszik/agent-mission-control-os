#!/usr/bin/env python3
"""Compile the canonical DTCG token source into the frontend's CSS variables.

    python3 compile_tokens.py            # write apps/web/app/tokens.css
    python3 compile_tokens.py --check    # dry run: compile, compare, write nothing

The compiler itself lives in services/langgraph/agency/design_tokens.py; this
script only chooses the source and destination. It never invents a source: a
missing token file is an error (exit 2), not a cue to write a default one.

Exit codes: 0 ok / up to date, 1 generated CSS is stale (--check), 2 source
missing or invalid.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.langgraph.agency.design_tokens import TokenError, compile_css  # noqa: E402

DEFAULT_SOURCE = "apps/web/tokens/amc.tokens.json"
DEFAULT_OUTPUT = "apps/web/app/tokens.css"
CSS_PREFIX = "amc"


def build(source: Path, *, source_label: str) -> str:
    document = json.loads(source.read_text(encoding="utf-8"))
    _, css = compile_css(document, prefix=CSS_PREFIX, tiered=True, source_label=source_label)
    return css


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--check",
        action="store_true",
        help="dry run: compile and compare against the output file without writing",
    )
    args = parser.parse_args(argv)

    source = (ROOT / args.source).resolve()
    output = (ROOT / args.output).resolve()
    if not source.is_file():
        print(f"[ERROR] token source not found: {args.source}", file=sys.stderr)
        return 2
    try:
        css = build(source, source_label=args.source)
    except (TokenError, json.JSONDecodeError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    current = output.read_text(encoding="utf-8") if output.is_file() else None
    if args.check:
        if current == css:
            print(f"[OK] {args.output} is up to date with {args.source}")
            return 0
        print(
            f"[STALE] {args.output} does not match {args.source}; run `pnpm tokens:build`",
            file=sys.stderr,
        )
        return 1

    if current == css:
        print(f"[OK] {args.output} already up to date")
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(css, encoding="utf-8")
    print(f"[SUCCESS] compiled {args.source} -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
