#!/usr/bin/env python3
"""Run the ABC-v6 build checks and write runtime/abc/verification-seal.json from their real results.

    python scripts/seal_abc_build.py            # every command except the full suite
    python scripts/seal_abc_build.py --full     # also the full backend suite (A09)

Every command records argv, exit code, environment, start time, duration, an
output tail and the SHA-256 of the full output. Node and predicate states are
computed from that evidence: a command that was not run is NOT_RUN, and
NOT_RUN is never PASSED.

The seal is unsigned. A SHA-256 binds bytes to this record; it is not proof of
who produced them. ReleaseEligible needs human review and a current approval,
and RuntimeActive needs a deployed worker; this script cannot supply either and
says so instead.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SEAL = ROOT / "runtime" / "abc" / "verification-seal.json"
SEAL_VERSION = "amc-verification-seal/v1"
TESTS = ROOT / "services" / "langgraph" / "tests"
CHANGED_PATHS = ["services/langgraph/agency/visual", "services/langgraph/agency/durable",
                 "services/langgraph/agency/intake", "services/langgraph/persistence/durable_runs.py",
                 "services/langgraph/tests/test_abc_v6.py", "scripts/compile_abc_manifests.py", "scripts/seal_abc_build.py"]
GATES = ["verify_repository_invariants.py", "verify_production_readiness.py", "verify_auth_bindings.py",
         "verify_ontology_parity.py", "verify_design_tokens.py", "verify_manifest.py", "verify_guidance_registry.py"]
FILES = ("docs/abc-v6-traceability.md", "runtime/abc/samples/provenance.json")
PY = sys.executable


def commands(full: bool) -> dict[str, list[list[str]]]:
    probe = ("import json; from services.langgraph.agency.visual.capabilities import probe_all; "
             "print(json.dumps({r.value: [c.status.value, c.version, list(c.blockers)] for r, c in probe_all().items()}))")
    cmds = {
        "cmd:environment_snapshot": [[PY, "-c", probe], ["git", "status", "--short"]],
        "cmd:pytest_abc": [[PY, "-m", "pytest", str(TESTS / "test_abc_v6.py"), "-q", "-rs"]],
        "cmd:pytest_intake": [[PY, "-m", "pytest", str(TESTS / "test_intake_mission.py"), "-q"]],
        "cmd:ruff": [["ruff", "check", *CHANGED_PATHS]],
        "cmd:compileall": [[PY, "-m", "compileall", "-q", "services/langgraph", "scripts"]],
        "cmd:abc_manifests_check": [[PY, "scripts/compile_abc_manifests.py", "--check"]],
        "cmd:gates": [[PY, f"scripts/{g}"] for g in GATES],
    }
    if full:
        cmds["cmd:pytest_full"] = [[PY, "-m", "pytest", str(TESTS), "-q", "-p", "no:cacheprovider"]]
    return cmds


def environment() -> dict:
    return {"python": platform.python_version(), "platform": platform.platform(),
            "database_backend": os.environ.get("AMC_DATABASE_BACKEND", "sqlite"),
            "db_path_set": bool(os.environ.get("AMC_DB_PATH")), "cwd": str(ROOT)}


def run(cid: str, argvs: list[list[str]]) -> dict:
    steps, start = [], time.monotonic()
    started = datetime.now(timezone.utc).isoformat()
    for argv in argvs:
        t0 = time.monotonic()
        try:
            proc = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=3600)
            code, output = proc.returncode, proc.stdout + proc.stderr
        except FileNotFoundError as exc:
            code, output = 127, f"not found: {exc}"
        except subprocess.TimeoutExpired:
            code, output = 124, "timed out after 3600s"
        steps.append({"command": argv, "exit_code": code, "duration_s": round(time.monotonic() - t0, 2),
                      "output_sha256": hashlib.sha256(output.encode()).hexdigest(), "output_tail": output[-1500:]})
    exit_code = next((s["exit_code"] for s in steps if s["exit_code"] != 0), 0)
    return {"id": cid, "started_at": started, "duration_s": round(time.monotonic() - start, 2), "exit_code": exit_code,
            "verdict": "PASSED" if exit_code == 0 else "FAILED", "environment": environment(), "steps": steps}


def evidence_states(command_results: dict, *, files: dict) -> dict:
    from services.langgraph.agency.durable.build_dag import BUILD_DAG

    states: dict[str, str] = {}
    for node in BUILD_DAG:
        for ev in node.verification:
            if ev.startswith("cmd:"):
                states[ev] = command_results.get(ev, {}).get("verdict", "NOT_RUN")
            elif ev.startswith("file:"):
                states[ev] = "PASSED" if files.get(ev[5:]) else "NOT_RUN"
            elif ev == "self:seal_composed":
                states[ev] = "PASSED"  # this document is that evidence
    return states


def node_statuses(evidence: dict) -> dict:
    from services.langgraph.agency.durable.build_dag import BUILD_DAG, node_status

    return {n.name: node_status(n, evidence) for n in BUILD_DAG}


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=30).stdout.strip()
    except OSError:
        return ""


def sample_hashes() -> tuple[dict, bool]:
    prov = ROOT / "runtime" / "abc" / "samples" / "provenance.json"
    if not prov.is_file():
        return {}, False
    doc = json.loads(prov.read_text())
    out, ok = {}, True
    for s in doc.get("samples", []):
        path = ROOT / "runtime" / "abc" / "samples" / s["file"]
        actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        out[f"runtime/abc/samples/{s['file']}"] = actual
        ok = ok and actual is not None and actual == s["sha256"]
    return out, ok and bool(out)


def compose(*, commit: str, command_results: dict, evidence: dict, blockers: list, sample_hashes: dict,
            samples_match: bool = False, dirty: list | None = None) -> dict:
    from services.langgraph.agency.durable.build_dag import as_document, build_complete, release_eligible, runtime_active
    from services.langgraph.agency.durable.fsm import RUN_FSM_VERSION
    from services.langgraph.agency.execution.canonical import canonical_hash

    sys.path.insert(0, str(ROOT / "scripts"))
    import compile_abc_manifests as manifests  # noqa: E402

    nodes = node_statuses(evidence)
    manifest_hashes = {f"runtime/abc/{name}": hashlib.sha256(manifests.render(builder).encode()).hexdigest()
                       for name, builder in manifests.FILES.items()}
    on_disk = {k: (hashlib.sha256((ROOT / k).read_bytes()).hexdigest() if (ROOT / k).is_file() else None) for k in manifest_hashes}
    built = build_complete(artifacts_exist=all(on_disk.values()) and bool(sample_hashes),
                           hashes_match=on_disk == manifest_hashes and samples_match,
                           checks_pass=all(s == "PASSED" for s in nodes.values()),
                           critical_unresolved=sum(1 for s in nodes.values() if s != "PASSED"))
    release = release_eligible(build_ok=built, review_passed=False, authorization_valid=False, approval_current=False,
                               simulation_free=True)
    active = runtime_active(scheduler_configured=False, worker_operational=False, durable_state=True,
                            activation_authorized=False)
    predicates = {"BuildComplete": built, "ReleaseEligible": release, "RuntimeActive": active}
    if built and not blockers:
        final = "IMPLEMENTED_VERIFIED"
    elif any(s == "PASSED" for s in nodes.values()):
        final = "IMPLEMENTED_PARTIALLY_VERIFIED"
    else:
        final = "NOT_IMPLEMENTED"
    return {
        "schema_version": SEAL_VERSION,
        "commit": commit,
        "working_tree_changes_other_than_seal": dirty or [],
        "sealed_at": datetime.now(timezone.utc).isoformat(),
        "schema_versions": json.loads(manifests.render(manifests.system_genome).split("\n", 1)[1])["schema_versions"],
        "artifact_hashes": {**on_disk, **sample_hashes},
        "build_dag_hash": canonical_hash(as_document()),
        "run_fsm_hash": canonical_hash(manifests.run_fsm()),
        "run_fsm_version": RUN_FSM_VERSION,
        "node_status": nodes,
        "predicates": predicates,
        "predicate_notes": {
            "ReleaseEligible": "false: no human visual/brand/realism review or current approval exists for the samples",
            "RuntimeActive": "false: no persistent scheduler/worker is deployed or authorized; ticks are invoked explicitly",
        },
        "passed_predicates": sorted(k for k, v in predicates.items() if v),
        "failed_predicates": sorted(k for k, v in predicates.items() if not v),
        "command_results": command_results,
        "evidence_refs": evidence,
        "authorization_refs": [],
        "authorization_note": "No G3/G4 action was authorized or performed. Merge requires the repository owner.",
        "blockers": blockers,
        "signature_status": "UNSIGNED",
        "signature_note": "SHA-256 binds bytes to this record; it is not cryptographic authenticity.",
        "final_status": final,
    }


def blockers() -> list[str]:
    from services.langgraph.agency.durable.observability import exporter_status
    from services.langgraph.agency.visual.capabilities import probe_all

    out = [f"{r.value}:{c.status.value}:{'; '.join(c.blockers)}" for r, c in probe_all().items() if not c.available]
    out.append(f"OPENTELEMETRY:{exporter_status()['opentelemetry']}")
    out.append("PERSISTENT_WORKER:NOT_DEPLOYED (RuntimeActive requires an authorized deployment)")
    out.append("Q5_Q7:HUMAN_REQUIRED (visual constraints, realism/brand assessment and approval are human decisions)")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--full", action="store_true", help="also run the full backend suite")
    args = parser.parse_args(argv)
    results = {}
    for cid, argvs in commands(args.full).items():
        print(f"running {cid} ...", flush=True)
        results[cid] = run(cid, argvs)
        print(f"  {results[cid]['verdict']} (exit {results[cid]['exit_code']}, {results[cid]['duration_s']}s)", flush=True)
    files = {f: (ROOT / f).is_file() for f in FILES}
    evidence = evidence_states(results, files={k: v for k, v in files.items()})
    hashes, match = sample_hashes()
    dirty = [line for line in _git("status", "--porcelain").splitlines() if not line.endswith("verification-seal.json")]
    doc = compose(commit=_git("rev-parse", "HEAD"), command_results=results, evidence=evidence, blockers=blockers(),
                  sample_hashes=hashes, samples_match=match, dirty=dirty)
    SEAL.parent.mkdir(parents=True, exist_ok=True)
    SEAL.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"final_status": doc["final_status"], "predicates": doc["predicates"], "node_status": doc["node_status"]},
                     indent=2))
    return 0 if all(r["verdict"] == "PASSED" for r in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
