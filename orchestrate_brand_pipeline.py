#!/usr/bin/env python3
"""Repo-root entry point for the agency CLI.

The implementation lives in ``services.langgraph.agency.cli`` so it is
importable and testable alongside the kernel it drives. This file exists only
so ``make brand-orchestrate`` and ``pnpm run brand:orchestrate`` keep working
from the repository root.

    python3 orchestrate_brand_pipeline.py plan --input sample_brief.json
    python3 orchestrate_brand_pipeline.py roles --department brand
    python3 orchestrate_brand_pipeline.py validate
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.langgraph.agency.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
