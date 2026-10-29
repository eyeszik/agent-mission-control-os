#!/usr/bin/env python3
"""Offline fictional creative cases; measures compilation, never rendered quality.

Run this same script with --repo pointing to separate baseline/candidate checkouts.
Imports and request construction are outside the timed region. No model calls.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path


CASES = (
    ("graphic", "IMAGE", "Editorial poster", "Create a visually distinct editorial poster with a clear focal hierarchy."),
    ("ui_ux", "UI_UX", "Product onboarding", "Design an accessible product onboarding flow with clear next actions."),
    ("storytelling", "STORYBOARD", "Brand narrative", "Develop a visual narrative with setup, tension and a meaningful resolution."),
    ("branding", "PRESENTATION", "Identity presentation", "Present a coherent brand identity using the supplied fictional brand foundation."),
    ("marketing", "COPY", "Landing page", "Write a truthful landing page with a specific audience and one primary call to action."),
)


def requests(repo: Path, compiler):
    original = compiler.load_request(str(repo / "sample_prompt_request.json"))
    result = []
    for label, family, asset_type, objective in CASES:
        raw = original.model_dump(mode="json")
        raw["providers"] = []
        asset = raw["asset_requirements"][0]
        asset.update(asset_id=f"fixture-{label}", family=family, asset_type=asset_type,
                     objective=objective, required_capabilities=[])
        result.append((label, compiler.PromptCompilerRequest.model_validate(raw)))
    return result


def measure(compiler, request, iterations: int) -> dict:
    started = time.perf_counter_ns()
    result = compiler.compile_prompt_packages(request)
    first_ms = (time.perf_counter_ns() - started) / 1e6
    samples = []
    for _ in range(iterations):
        started = time.perf_counter_ns()
        result = compiler.compile_prompt_packages(request)
        samples.append((time.perf_counter_ns() - started) / 1e6)
    return {"first_call_ms": first_ms, "samples_ms": samples, "median_ms": statistics.median(samples),
            "max_ms": max(samples), "state": result.final_state.value,
            "result_sha256": hashlib.sha256(result.model_dump_json().encode()).hexdigest(),
            "prompt_hashes": [p.prompt_hash for p in result.prompt_packages]}


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--iterations", type=int, default=25)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 5 <= args.iterations <= 200:
        parser.error("iterations must be between 5 and 200")
    return args


def main() -> None:
    args = arguments()
    repo = args.repo.resolve()
    sys.path.insert(0, str(repo))
    from services.langgraph.agency import prompt_compiler as compiler

    if not Path(compiler.__file__).resolve().is_relative_to(repo):
        raise SystemExit("compiler import did not resolve to the requested checkout")
    report = {"schema": "amc-prompt-benchmark/v1", "fixture_only": True,
              "revision": subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip(),
              "registry_source_sha256": hashlib.sha256((repo / "services/langgraph/agency/guidance/registry.py").read_bytes()).hexdigest(),
              "worktree_dirty": bool(subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain"], text=True)),
              "python": platform.python_version(), "platform": platform.platform(),
              "iterations": args.iterations, "timing_scope": "compile_prompt_packages only; no provider or rendering",
              "cases": {label: measure(compiler, request, args.iterations) for label, request in requests(repo, compiler)}}
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    for label, case in report["cases"].items():
        print(f"{label}: {case['median_ms']:.3f} ms median, {case['state']}")


if __name__ == "__main__":
    main()
