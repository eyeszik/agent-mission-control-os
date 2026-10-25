"""Build a generated source tree inside the sandbox. Never outside it.

Steps, each recorded with its command, exit status, duration and log tail:

1. ``isolation`` -- ``sandbox.probe_isolation``; failure returns ``BLOCKED_ISOLATION`` and nothing runs;
2. ``dependency_check`` -- the installed ``apps/web`` packages must equal the manifest's exact versions
   (there is no install step; the network is unavailable anyway);
3. ``typecheck`` -- ``tsc --noEmit`` in the sandbox;
4. ``next_build`` -- ``next build --webpack`` (static export) in the sandbox;
5. ``output_check`` -- the export exists, stays under the quota, holds one HTML file per route, and every
   file is hashed into ``output_hash``.

The work directory is a fresh directory outside the repository; the repository is read-only
inside the sandbox. ``keep_output`` returns the export directory for QA and preview; the caller
removes it with ``cleanup``.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

from services.langgraph.agency.execution.canonical import canonical_hash

from .contracts import BuildResult, SourceTreeManifest
from .sandbox import WEB_NODE_MODULES, Isolation, probe_isolation, wrap
from .source import check_path, scan, verify_tree

OUTPUT_QUOTA_BYTES = 50 * 1024 * 1024
STEP_TIMEOUT_S = {"typecheck": 180, "next_build": 420}


def _tail(text: str, n: int = 1500) -> str:
    return text[-n:]


def output_digest(out_dir: Path) -> tuple[str, int, int]:
    """(hash, files, bytes) of an export directory; the hash covers relative paths and contents."""
    entries = []
    total = 0
    for f in (p for p in out_dir.rglob("*") if p.is_file()):
        data = f.read_bytes()
        total += len(data)
        entries.append((f.relative_to(out_dir).as_posix(), hashlib.sha256(data).hexdigest()))
    return canonical_hash(sorted(entries)), len(entries), total


def installed_versions(names: list[str]) -> dict[str, Optional[str]]:
    out: dict[str, Optional[str]] = {}
    for name in names:
        pkg = WEB_NODE_MODULES / name / "package.json"
        try:
            out[name] = json.loads(pkg.read_text())["version"]
        except (OSError, ValueError, KeyError):
            out[name] = None
    return out


def cleanup(work_dir: Optional[Path]) -> None:
    if work_dir and work_dir.name.startswith("amc-ucpo-build-"):
        shutil.rmtree(work_dir, ignore_errors=True)


def build_site(files: dict[str, bytes], manifest: SourceTreeManifest, *, routes: list[str], keep_output: bool = False,
               isolation: Optional[Isolation] = None, work_root: Optional[Path] = None) -> tuple[BuildResult, Optional[Path]]:
    steps: list[dict] = []
    deps = dict(manifest.dependencies)

    def result(status: str, iso: dict, out: Optional[tuple[str, int, int]] = None) -> BuildResult:
        return BuildResult(status=status, source_tree_hash=manifest.tree_hash, isolation=iso, steps=tuple(steps),
                           dependency_manifest=deps, output_hash=out[0] if out else None,
                           output_files=out[1] if out else 0, output_bytes=out[2] if out else 0)

    problems = verify_tree(files, manifest)
    for path, raw in files.items():
        check_path(path)
        problems += scan(path, raw)
    if problems:
        steps.append({"name": "source_policy", "command": "verify_tree+scan", "exit_status": 1, "duration_s": 0,
                      "log_tail": "; ".join(problems)[:1500]})
        return result("FAILED", {"available": None, "reasons": ["source rejected before isolation"]}), None

    iso = isolation or probe_isolation()
    steps.append({"name": "isolation", "command": "probe_isolation", "exit_status": 0 if iso.available else 1,
                  "duration_s": 0, "log_tail": "; ".join(iso.reasons)})
    if not iso.available:
        return result("BLOCKED_ISOLATION", iso.describe()), None

    found = installed_versions(sorted(deps))
    mismatched = {k: {"manifest": v, "installed": found[k]} for k, v in deps.items() if found[k] != v}
    steps.append({"name": "dependency_check", "command": "read apps/web/node_modules/*/package.json",
                  "exit_status": 1 if mismatched else 0, "duration_s": 0,
                  "log_tail": json.dumps(mismatched) if mismatched else "exact versions installed"})
    if mismatched:
        return result("FAILED", iso.describe()), None

    work = Path(tempfile.mkdtemp(prefix="amc-ucpo-build-", dir=str(work_root) if work_root else None))
    keep = False
    try:
        site = work / "site"
        home = work / "home"
        home.mkdir()
        for path, raw in files.items():
            target = site / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        (site / "node_modules").symlink_to(WEB_NODE_MODULES)
        node = iso.node or "node"
        commands = {
            "typecheck": [node, "node_modules/typescript/bin/tsc", "--noEmit", "-p", "."],
            "next_build": [node, "node_modules/next/dist/bin/next", "build", "--webpack"],
        }
        for name, cmd in commands.items():
            t0 = time.monotonic()
            argv = wrap(cmd, cwd=site, home=home, node=node, timeout_s=STEP_TIMEOUT_S[name])
            try:
                proc = subprocess.run(argv, capture_output=True, text=True, timeout=STEP_TIMEOUT_S[name] + 30)
                code, log = proc.returncode, proc.stdout + proc.stderr
            except subprocess.TimeoutExpired as exc:
                code, log = 124, f"{exc}"
            steps.append({"name": name, "command": " ".join(cmd[1:]), "exit_status": code,
                          "duration_s": round(time.monotonic() - t0, 2), "log_tail": _tail(log)})
            if code == 124:
                return result("TIMED_OUT", iso.describe()), None
            if code != 0:
                return result("FAILED", iso.describe()), None

        out_dir = site / "out"
        missing = [r for r in routes if not (out_dir / (r.strip("/") + "/index.html" if r != "/" else "index.html")).is_file()]
        digest = output_digest(out_dir) if out_dir.is_dir() else ("", 0, 0)
        over = digest[2] > OUTPUT_QUOTA_BYTES
        steps.append({"name": "output_check", "command": "hash out/", "exit_status": 1 if (missing or over or not digest[1]) else 0,
                      "duration_s": 0, "log_tail": json.dumps({"missing_routes": missing, "files": digest[1],
                                                                "bytes": digest[2], "quota": OUTPUT_QUOTA_BYTES})})
        if missing or over or not digest[1]:
            return result("FAILED", iso.describe()), None
        keep = keep_output
        return result("PASSED", iso.describe(), digest), (out_dir if keep_output else None)
    finally:
        if not keep:
            cleanup(work)


__all__ = ["OUTPUT_QUOTA_BYTES", "build_site", "cleanup", "installed_versions", "output_digest"]
