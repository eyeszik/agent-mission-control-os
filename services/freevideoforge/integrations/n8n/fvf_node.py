#!/usr/bin/env python3
"""stdin/stdout JSON bridge for n8n's Execute Command node.

Reads one JSON request on stdin, runs the local FreeVideoForge pipeline, writes
one JSON response on stdout. No n8n SDK, no network service, no credentials.

This exists to prove the point that FreeVideoForge's programmatic interface is
usable by an external automation system without the pipeline knowing anything
about that system. n8n is an optional consumer, never a dependency.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow running straight from a checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from freevideoforge import api, doctor  # noqa: E402
from freevideoforge.errors import ForgeError  # noqa: E402
from freevideoforge.models import GenerateRequest, to_jsonable  # noqa: E402

MAX_INPUT_BYTES = 256 * 1024


def _fail(message: str, **extra) -> int:
    json.dump({"ok": False, "error": message, **extra}, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 1


def handle(payload: dict) -> tuple[int, dict]:
    action = str(payload.get("action", "generate"))
    workspace = payload.get("workspace")

    if action == "generate":
        request = GenerateRequest.from_dict(payload.get("request") or {})
        request.validate()
        result = api.generate(request, workspace=workspace)
        body = to_jsonable(result)
        body["ok"] = result.ok
        return (0 if result.ok else 1), body

    if action == "resume":
        run_id = payload.get("run_id")
        if not run_id:
            raise ForgeError("resume requires run_id")
        result = api.resume(str(run_id), workspace=workspace)
        body = to_jsonable(result)
        body["ok"] = result.ok
        return (0 if result.ok else 1), body

    if action == "status":
        run_id = payload.get("run_id")
        if not run_id:
            raise ForgeError("status requires run_id")
        return 0, {"ok": True, **to_jsonable(api.run_status(str(run_id), workspace))}

    if action == "runs":
        limit = int(payload.get("limit", 25))
        return 0, {"ok": True, "runs": api.list_runs(workspace, limit=limit)}

    if action == "doctor":
        return 0, {"ok": True, **doctor.collect(workspace)}

    raise ForgeError(
        f"Unknown action {action!r}. "
        "Use generate, resume, status, runs or doctor."
    )


def main() -> int:
    raw = sys.stdin.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        return _fail(f"request exceeds {MAX_INPUT_BYTES} bytes")
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        return _fail(f"invalid JSON on stdin: {exc}")
    if not isinstance(payload, dict):
        return _fail("request must be a JSON object")

    try:
        code, body = handle(payload)
    except ForgeError as exc:
        return _fail(str(exc), error_class=type(exc).__name__)
    except Exception as exc:  # a bridge must always answer in JSON
        return _fail(f"{type(exc).__name__}: {exc}")

    json.dump(body, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
