#!/usr/bin/env python3
"""Collect exact-SHA release evidence from GitHub check runs (ACE v100).

Usage:
    python scripts/collect_release_evidence.py --sha <40-hex> --check-runs runs.json [--merged] [--out evidence.json]
    GITHUB_TOKEN=... python scripts/collect_release_evidence.py --sha <40-hex> --repo owner/name [--merged]

``runs.json`` is the body of ``GET /repos/{owner}/{repo}/commits/{sha}/check-runs`` (or its ``check_runs`` list).
The output is unsigned evidence plus a fail-closed status. It authorizes nothing:
release still needs a signed bundle from an externally held key, operational
evidence from the target environment and an authorized human approval.
Exit code 0 means the evidence was collected, not that a release is permitted.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.langgraph.agency.ace_evidence import gate_results_from_check_runs, production_status  # noqa: E402


def _fetch(repo: str, sha: str, token: str) -> list[dict]:
    runs: list[dict] = []
    page = 1
    while True:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/commits/{sha}/check-runs?per_page=100&page={page}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28"})
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed https host
            body = json.loads(resp.read().decode())
        runs += body.get("check_runs", [])
        if len(runs) >= int(body.get("total_count", 0)) or not body.get("check_runs"):
            return runs
        page += 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sha", required=True)
    ap.add_argument("--check-runs", type=Path, help="check-runs JSON; omit to fetch with GITHUB_TOKEN")
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "eyeszik/agent-mission-control-os"))
    ap.add_argument("--merged", action="store_true", help="the SHA is reachable from the default branch")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)

    if args.check_runs:
        data = json.loads(args.check_runs.read_text(encoding="utf-8"))
        runs = data["check_runs"] if isinstance(data, dict) else data
    else:
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            print("error: pass --check-runs or set GITHUB_TOKEN", file=sys.stderr)
            return 2
        runs = _fetch(args.repo, args.sha, token)

    collected = gate_results_from_check_runs(runs, sha=args.sha)
    now = datetime.now(timezone.utc)
    report = {
        "schema_version": "ace.release-evidence-draft.v1",
        "signed": False,
        "note": "Unsigned draft. Not a release authorization.",
        "commit_sha": args.sha,
        "collected_at": now.isoformat(),
        "gates": [g.model_dump(mode="json") for g in collected.gates],
        "check_run_problems": [p.model_dump(mode="json") for p in collected.problems],
        "status": production_status(collected=collected, merged_into_default=args.merged),
    }
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
