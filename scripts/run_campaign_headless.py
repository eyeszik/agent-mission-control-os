#!/usr/bin/env python3
"""Run a campaign on a private loopback API; never approve or publish it."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def runtime_env(output: Path, mode: str) -> dict[str, str]:
    # Do not inherit production database, auth, telemetry, or provider redirects.
    env = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "LANG") if k in os.environ}
    env.update(AMC_ENV="local", AMC_AUTH_MODE="local", AMC_DATABASE_BACKEND="sqlite",
               AMC_LOCAL_USER_ID="headless-operator", AMC_LOCAL_TENANT_ID="campaign-sandbox",
               AMC_LOCAL_PROJECT_IDS="black-feather-ceremony", AMC_LOCAL_ROLE="operator",
               AMC_DB_PATH=str(output / "state.db"), AMC_EXPORT_ROOT=str(output / "exports"),
               AMC_PUBLICATION_MODE="disabled", AMC_PAID_MEDIA_MODE="disabled",
               PYTHONPATH=str(ROOT), PYTHONUNBUFFERED="1")
    if mode == "live":
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not key:
            raise ValueError("Live generation requires OPENAI_API_KEY in the execution environment")
        env["OPENAI_API_KEY"] = key
        env["AMC_OPENAI_MODEL"] = os.environ.get("AMC_OPENAI_MODEL", "gpt-4o-mini")
    return env


def classify(result: dict, mode: str) -> str:
    if result.get("status") != "needs_approval":
        raise ValueError("Campaign did not stop at the expected human approval gate")
    if mode == "dry-run":
        if not result.get("degraded"):
            raise ValueError("Dry run must identify degraded generation")
        return "DEGRADED_DRY_RUN_NOT_DELIVERABLE"
    provenance = result.get("generation_provenance", [])
    if result.get("degraded") or not provenance or any(p.get("mode") != "PROVIDER_SUCCESS" for p in provenance):
        raise ValueError("Live generation was degraded or lacks provider-success evidence")
    return "GENERATED_AWAITING_HUMAN_REVIEW"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brief", type=Path, default=ROOT / "examples/campaigns/black-feather-ceremony.json")
    parser.add_argument("--output", type=Path, required=True, help="New private directory; never reuse an uncertain run")
    parser.add_argument("--mode", choices=("dry-run", "live"), default="dry-run")
    args = parser.parse_args()
    payload = json.loads(args.brief.read_text())
    if payload.get("project_id") != "black-feather-ceremony" or "tenant_id" in payload:
        parser.error("Brief must use black-feather-ceremony project and server-derived tenant")
    output = args.output.resolve()
    env = runtime_env(output, args.mode)
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    request_bytes = json.dumps(payload, sort_keys=True).encode()
    digest = hashlib.sha256(request_bytes).hexdigest()
    def save(name, value):
        (output / name).write_text(json.dumps(value, indent=2) + "\n")
    save("request.json", payload)
    save("execution.json", {"state": "STARTING", "mode": args.mode, "request_sha256": digest})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with socket.socket() as listener, (output / "backend.log").open("w") as log:
        listener.bind(("127.0.0.1", 0)); listener.listen(128)
        port = listener.getsockname()[1]
        proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "services.langgraph.app.main:app",
                                 "--fd", str(listener.fileno())], cwd=ROOT, env=env,
                                pass_fds=(listener.fileno(),), stdout=log, stderr=log)
        base = f"http://127.0.0.1:{port}"
        def request(path, data=None):
            headers = {"Content-Type": "application/json", "Idempotency-Key": digest}
            req = urllib.request.Request(base + path, data=data, headers=headers)
            with opener.open(req, timeout=600 if data else 2) as response:
                return json.load(response)
        submitted = False
        try:
            ready = None
            for _ in range(60):
                if proc.poll() is not None:
                    raise RuntimeError("Backend exited; inspect local backend.log")
                try:
                    ready = request("/ready")
                    if ready.get("ready"):
                        break
                except (OSError, urllib.error.URLError):
                    pass
                time.sleep(0.5)
            if not ready or not ready.get("ready"):
                raise RuntimeError("Backend readiness failed")
            save("readiness.json", ready)
            save("execution.json", {"state": "IN_DOUBT", "request_sha256": digest,
                                    "note": "POST may execute; never automatically resubmit after timeout"})
            submitted = True
            created = request("/agency/runs", request_bytes)
            save("create-response.json", created)
            run_id = created["run_id"]
            result = request("/agency/runs/" + run_id)
            save("campaign.json", result)
            status = classify(result, args.mode)
            receipt = {"state": status, "run_id": run_id, "mode": args.mode,
                       "request_sha256": digest, "approval_submitted": False,
                       "publication": "disabled", "paid_media": "disabled"}
            save("execution.json", receipt)
            print(json.dumps(receipt, indent=2))
            return 0
        except Exception as exc:
            save("failure.json", {"state": "IN_DOUBT" if submitted else "FAILED_BEFORE_SUBMISSION",
                                  "error_class": type(exc).__name__,
                                  "recovery": "Inspect existing state and receipts; do not automatically resubmit"})
            print(f"Campaign failed ({type(exc).__name__}); inspect {output}", file=sys.stderr)
            return 1
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill(); proc.wait()


if __name__ == "__main__":
    raise SystemExit(main())
