"""Measure the VNEXUS brand book build: cold, warm identical, one-page copy edit, global palette edit, interrupted and
resumed, and two concurrent brands (isolation). Real routes, real local storage, real Chromium when available.

Writes runtime/brandbook/benchmark.json (or --out). Every number is measured on this host; nothing is projected.

    python scripts/bench_brandbook.py --samples 3 --label after
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import tempfile
import threading
import time
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _env(tmp: Path) -> None:
    os.environ.update({"AMC_ENV": "local", "AMC_AUTH_MODE": "local", "AMC_DATABASE_BACKEND": "sqlite",
                       "AMC_DB_PATH": str(tmp / "bench.db"), "AMC_EXPORT_ROOT": str(tmp / "exports"),
                       "AMC_OBJECT_STORAGE_BACKEND": "local"})
    for k in ("AMC_LLM_PROVIDER", "AMC_GEMINI_MODEL", "GEMINI_API_KEY", "ANTHROPIC_BASE_URL"):
        os.environ.pop(k, None)


def _user(user: str, role: str, tenant: str) -> None:
    os.environ.update({"AMC_LOCAL_USER_ID": user, "AMC_LOCAL_ROLE": role, "AMC_LOCAL_TENANT_ID": tenant, "AMC_LOCAL_PROJECT_IDS": "*"})


def _summary(values: list[float]) -> dict:
    if not values:
        return {}
    out = {"n": len(values), "median": round(statistics.median(values), 1), "min": round(min(values), 1), "max": round(max(values), 1)}
    if len(values) >= 20:  # percentiles only with enough samples
        out["p95"] = round(sorted(values)[int(len(values) * 0.95) - 1], 1)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=3)
    ap.add_argument("--label", default="run")
    ap.add_argument("--out", default=str(ROOT / "runtime" / "brandbook" / "benchmark.json"))
    args = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="amc-bench-brandbook-"))
    _env(tmp)
    from fastapi.testclient import TestClient

    from services.langgraph.agency.vnexus.brandbook import service as book
    from services.langgraph.agency.vnexus.brandbook.manifest import Mode
    from services.langgraph.agency.vnexus.genome import Scope, document_from_flat
    from services.langgraph.agency.visual.browser import probe_browser
    from services.langgraph.app.main import app
    from services.langgraph.security.auth import Principal
    from services.langgraph.tests._vnexus_support import FULL_DOC
    from services.langgraph.tests.test_vnexus_brandbook import DECIDED

    client = TestClient(app)
    hdr = lambda: {"Idempotency-Key": str(uuid4())}  # noqa: E731

    def world():
        tenant = f"tenant-bench-{uuid4().hex[:8]}"
        owner = f"prj-bench-{uuid4().hex[:8]}"
        _user("olivia", "owner", tenant)
        assert client.post("/projects", json={"display_name": owner, "project_id": owner, "slug": owner}, headers=hdr()).status_code == 201
        _user("alice", "editor", tenant)
        brand = f"brand-{uuid4().hex[:8]}"
        assert client.post("/vnexus/brands", json={"brand_id": brand, "display_name": f"Bench {brand[-4:]} (fictional)",
                                                    "owner_project_id": owner}, headers=hdr()).status_code == 201
        return tenant, owner, brand

    def approve(tenant, brand, doc):
        _user("alice", "editor", tenant)
        v = client.post(f"/vnexus/brands/{brand}/versions", json={"scope": "brand", "scope_ref": brand,
                        "document": doc.model_dump(mode="json")}, headers=hdr()).json()["version"]
        aid = client.post(f"/vnexus/versions/{v['version_id']}/submit", headers=hdr()).json()["version"]["approval_id"]
        _user("bob", "reviewer", tenant)
        assert client.post(f"/approvals/{aid}/decide", json={"decision": "approve"}, headers=hdr()).status_code == 200
        client.get(f"/vnexus/versions/{v['version_id']}")
        _user("alice", "editor", tenant)

    def build(owner, brand):
        r = client.post(f"/vnexus/brands/{brand}/brandbook/builds", json={"scope": "brand", "scope_ref": brand, "project_id": owner,
                        "mode": "PREVIEW"}, headers=hdr())
        assert r.status_code == 201, r.text
        return r.json()["telemetry"]

    base_doc = document_from_flat({**FULL_DOC.flatten(), **DECIDED}, constraints=list(FULL_DOC.constraints))
    runs: dict[str, list[dict]] = {k: [] for k in ("cold", "warm", "copy_edit", "palette_edit", "resume_after_interrupt")}
    for _ in range(args.samples):
        book.clear_cache()
        tenant, owner, brand = world()
        approve(tenant, brand, base_doc)
        runs["cold"].append(build(owner, brand))
        runs["warm"].append(build(owner, brand))
        doc2 = document_from_flat({**base_doc.flatten(), "verbal.voice.tone": ["plain", "precise"]}, constraints=list(base_doc.constraints))
        approve(tenant, brand, doc2)
        runs["copy_edit"].append(build(owner, brand))
        doc3 = document_from_flat({**doc2.flatten(), "visual.color.accent": "#9a3412"}, constraints=list(base_doc.constraints))
        approve(tenant, brand, doc3)
        runs["palette_edit"].append(build(owner, brand))
        alice = Principal(user_id="alice", tenant_id=tenant, role="editor", allowed_project_ids=frozenset({"*"}))
        doc4 = document_from_flat({**doc3.flatten(), "visual.color.accent": "#1d4ed8"}, constraints=list(base_doc.constraints))
        approve(tenant, brand, doc4)
        try:
            book.build(alice, brand, scope=Scope.BRAND, scope_ref=brand, project_id=owner, mode=Mode.PREVIEW, interrupt_after=8)
        except RuntimeError:
            pass
        book.clear_cache()
        runs["resume_after_interrupt"].append(
            book.build(alice, brand, scope=Scope.BRAND, scope_ref=brand, project_id=owner, mode=Mode.PREVIEW)["telemetry"])

    # Concurrent isolation: two brands in two tenants, built at the same time in two threads.
    pairs = [world() for _ in range(2)]
    for tenant, _owner, brand in pairs:
        approve(tenant, brand, base_doc)
    results: dict[str, dict] = {}

    def worker(tenant, owner, brand):
        p = Principal(user_id="alice", tenant_id=tenant, role="editor", allowed_project_ids=frozenset({"*"}))
        t = time.perf_counter()
        rec = book.build(p, brand, scope=Scope.BRAND, scope_ref=brand, project_id=owner, mode=Mode.PREVIEW)
        html, _ = book.read_output(p, brand, scope=Scope.BRAND, scope_ref=brand, project_id=owner, mode=Mode.PREVIEW, kind="book")
        results[brand] = {"wall_ms": round((time.perf_counter() - t) * 1000, 1), "html": html.decode(), "status": rec["status"]}

    threads = [threading.Thread(target=worker, args=pair) for pair in pairs]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    (b1, b2) = [p[2] for p in pairs]
    isolation = {"wall_ms": [results[b]["wall_ms"] for b in (b1, b2)],
                 "own_name_present": all(f"Bench {b[-4:]}" in results[b]["html"] for b in (b1, b2)),
                 "other_name_absent": f"Bench {b2[-4:]}" not in results[b1]["html"] and f"Bench {b1[-4:]}" not in results[b2]["html"]}

    report = {"label": args.label, "samples": args.samples, "fixture": "FULL_DOC + DECIDED (fictional), PREVIEW mode, 24 pages",
              "environment": {"python": platform.python_version(), "platform": platform.platform(), "cpu_count": os.cpu_count(),
                              "chromium": probe_browser().get("available", False), "storage": "local filesystem + SQLite"},
              "scenarios": {}, "concurrent_isolation": isolation}
    for name, items in runs.items():
        report["scenarios"][name] = {
            "total_ms": _summary([i["total_ms"] for i in items]),
            "stage_ms_median": {k: round(statistics.median([i["stage_ms"].get(k, 0) for i in items]), 1)
                                for k in sorted({k for i in items for k in i["stage_ms"]})},
            "pages_rendered": [i["pages_rendered"] for i in items], "pages_reused": [i["pages_reused"] for i in items],
            "browser_runs": [i["browser_runs"] for i in items], "cache_hits": [i["cache_hits"] for i in items],
            "model_calls": sum(i["model_calls"] for i in items), "peak_rss_kb": max(i["peak_rss_kb"] for i in items)}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    existing = json.loads(out.read_text()) if out.exists() else {}
    existing[args.label] = report
    out.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: v["total_ms"] | {"rendered": v["pages_rendered"], "browser_runs": v["browser_runs"]}
                      for k, v in report["scenarios"].items()}, indent=1))
    print("isolation", isolation)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
