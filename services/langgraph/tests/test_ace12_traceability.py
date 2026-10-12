"""ACE v12 traceability: every required test id (T01–T60) and enforceable
invariant (I01–I20) names at least one collected test in the ACE v12 suites, so
a renamed or deleted test cannot silently drop coverage."""

from __future__ import annotations

import ast
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
REQUIRED = [f"t{n:02d}" for n in range(1, 61)] + [f"i{n:02d}" for n in range(1, 21)]


def _test_names() -> list[str]:
    names = []
    for path in sorted(HERE.glob("test_ace12_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names += [n.name for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
    return names


def test_every_required_test_and_invariant_id_has_a_test():
    tokens = {t for name in _test_names() for t in re.findall(r"(?<=_)[ti]\d{2}(?=_)", name + "_")}
    missing = [rid.upper() for rid in REQUIRED if rid not in tokens]
    assert missing == [], f"no test is named for: {', '.join(missing)}"
