"""scripts/qa/provision-qa-chromium.sh must follow the lockfile's Playwright, never a hard-coded version.

Regression witness: a hard-coded ``playwright-core@1.65.0`` path survived the 1.65.1 bump, so on a fresh
install the script aborted under ``set -euo pipefail`` before provisioning anything.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/qa/provision-qa-chromium.sh"


def _lockfile_playwright_core() -> set[str]:
    return set(re.findall(r"playwright-core@(\d+\.\d+\.\d+)", (ROOT / "pnpm-lock.yaml").read_text(encoding="utf-8")))


def test_the_script_names_no_playwright_version():
    text = SCRIPT.read_text(encoding="utf-8")
    assert not re.search(r"playwright-core@\d", text), "resolve playwright-core from the install, not a literal"
    assert not re.search(r"Playwright 1\.\d+ expects", text)


@pytest.mark.skipif(not shutil.which("node") or not (ROOT / "apps/web/node_modules/@playwright/test").exists(),
                    reason="NOT_RUN: node or the pnpm-installed apps/web dependencies are absent")
def test_resolution_lands_on_the_lockfile_version_without_provisioning_anything():
    out = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, timeout=60, check=True,
                         env={**os.environ, "AMC_QA_RESOLVE_ONLY": "1"})
    core = Path(out.stdout.strip())
    version = json.loads((core / "package.json").read_text(encoding="utf-8"))["version"]
    assert version in _lockfile_playwright_core()
