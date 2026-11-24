#!/usr/bin/env python3
"""Run an isolated, fictional Northline brand-to-website demonstration locally.

Creates a NEW disposable SQLite database and storage root; never deploys, calls a
provider, or grants a real client's approval. Two synthetic local principals use
the existing approval endpoint. A real UCPO build tick is run for each revision;
browser QA remains blocked if the pinned Playwright Chromium is unavailable.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="NEW directory for the disposable database, editable source, exports and report")
    args = parser.parse_args()
    out = args.output_dir.expanduser().absolute()
    if out.exists():
        raise SystemExit(f"Refusing to overwrite an existing path: {out}")
    out.mkdir(parents=True)
    os.environ.update({"AMC_DATABASE_BACKEND": "sqlite", "AMC_DB_PATH": str(out / "northline.db"),
                       "AMC_EXPORT_ROOT": str(out / "objects"), "AMC_OBJECT_STORAGE_BACKEND": "local",
                       "AMC_AUTH_MODE": "local", "AMC_ENV": "local", "AMC_LOCAL_TENANT_ID": "tenant-northline-synthetic",
                       "AMC_LOCAL_PROJECT_IDS": "*", "AMC_MAX_RUNS_PER_TENANT_PER_HOUR": "0",
                       "AMC_MAX_ACTIVE_RUNS_PER_TENANT": "0"})
    os.environ.pop("AMC_ALLOW_SELF_APPROVAL", None)
    # Imports after environment setup are important: the SQLite path is read at import time.
    from fastapi.testclient import TestClient
    from services.langgraph.agency.project_os.storage import LocalStorageAdapter
    from services.langgraph.agency.ucpo import service as ucpo
    from services.langgraph.agency.vnexus.genome import document_from_flat
    from services.langgraph.app.main import app
    from services.langgraph.persistence.agency_kernel import get_artifact
    from services.langgraph.persistence.projects import create_project_artifact

    client = TestClient(app)
    tenant, project, brand, site = "tenant-northline-synthetic", "prj-northline-synthetic", "brand-northline-synthetic", "northline"
    values = json.loads((ROOT / "examples/northline/brand-values.json").read_text())["values"]
    mapping = json.loads((ROOT / "examples/northline/website-mapping.json").read_text())
    headers = {"Idempotency-Key": "northline-setup"}

    def identity(name: str, role: str) -> None:
        os.environ["AMC_LOCAL_USER_ID"] = name
        os.environ["AMC_LOCAL_ROLE"] = role

    def post(url: str, body: dict, key: str) -> dict:
        response = client.post(url, json=body, headers={"Idempotency-Key": key})
        if response.status_code not in {200, 201}:
            raise RuntimeError(f"{url}: HTTP {response.status_code}: {response.text[:500]}")
        return response.json()

    def approve_version(document: dict, label: str) -> dict:
        identity("alice-synthetic", "editor")
        payload = {"scope": "brand", "scope_ref": brand,
                   "document": document_from_flat(document).model_dump(mode="json")}
        version = post(f"/vnexus/brands/{brand}/versions", payload, f"{label}-draft")["version"]
        submitted = post(f"/vnexus/versions/{version['version_id']}/submit", {}, f"{label}-submit")["version"]
        identity("bob-synthetic", "reviewer")
        post(f"/approvals/{submitted['approval_id']}/decide", {"decision": "approve"}, f"{label}-decide")
        response = client.get(f"/vnexus/versions/{version['version_id']}", headers=headers)
        if response.status_code != 200:
            raise RuntimeError(f"settling synthetic approval failed: {response.status_code}")
        return response.json()["version"]

    def save_tree(directory: Path, files: dict[str, bytes]) -> None:
        directory.mkdir()
        for name, data in files.items():
            target = (directory / name).resolve()
            if directory.resolve() not in target.parents:
                raise ValueError("generated path escapes output directory")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

    def capture(label: str, compile_result: dict) -> tuple[dict, dict]:
        identity("alice-synthetic", "operator")
        build = post(f"/ucpo/projects/{project}/sites/{site}/build", {}, f"{label}-build")
        loaded = ucpo.load_stages(project, site, LocalStorageAdapter(out / "objects"))
        save_tree(out / f"{label}-editable-source", loaded["files"])
        if loaded["export"]:
            save_tree(out / f"{label}-static-export", {k: base64.b64decode(v) for k, v in loaded["export"].items()})
        b = loaded["build"]
        return {"job_id": compile_result["site"]["job_id"], "source_tree": compile_result["site"]["source_tree"],
                "source_files": compile_result["site"]["source_files"], "tick": build["tick"],
                "build_status": b.status if b else None, "build_output_hash": b.output_hash if b else None,
                "build_output_files": b.output_files if b else 0,
                "build_steps": [{k: s.get(k) for k in ("name", "exit_status", "duration_s")} for s in (b.steps if b else [])],
                "browser_qa_status": build["site"]["browser_qa"]["status"] if build["site"]["browser_qa"] else "NOT_RUN",
                "browser_qa_checks": build["site"]["browser_qa"]["checks"] if build["site"]["browser_qa"] else [],
                "coverage": build["site"]["coverage"], "release": build["site"]["release"],
                "approval": build["site"]["approval"]}, loaded

    identity("owner-synthetic", "owner")
    post("/projects", {"display_name": "Northline Workflow Studio (fictional)", "project_id": project, "slug": project}, "project")
    identity("alice-synthetic", "editor")
    post("/vnexus/brands", {"brand_id": brand, "display_name": "Northline Workflow Studio (fictional)",
                            "owner_project_id": project}, "brand")
    version1 = approve_version(values, "v1")
    adapter = LocalStorageAdapter(out / "objects")
    independent = create_project_artifact(tenant_id=tenant, project_id=project, actor="alice-synthetic",
        artifact_key="independent-notes", artifact_type="product_spec", adapter=adapter,
        content_text="Synthetic independent work; not a claim about a client.")
    before = get_artifact(independent.artifact_id)
    identity("alice-synthetic", "operator")
    first = post(f"/ucpo/projects/{project}/sites/from-brand", {"site_id": site, "brand_id": brand, "mapping": mapping}, "v1-compile")
    first_run, loaded1 = capture("v1", first)
    revised = {**values, "verbal.messaging.cta": "Discuss your workflow", "visual.color.accent": "#ffaa3d",
               "visual.color.accent_2": "#ff4c2f"}
    version2 = approve_version(revised, "v2")
    identity("alice-synthetic", "operator")
    stale = client.get(f"/ucpo/projects/{project}/sites/{site}", headers=headers)
    if stale.status_code != 200:
        raise RuntimeError(f"stale inspection failed: {stale.status_code}")
    second = post(f"/ucpo/projects/{project}/sites/from-brand", {"site_id": site, "brand_id": brand, "mapping": mapping}, "v2-compile")
    second_run, loaded2 = capture("v2", second)
    after = get_artifact(independent.artifact_id)
    same = sorted(k for k in loaded1["files"] if k in loaded2["files"] and loaded1["files"][k] == loaded2["files"][k])
    changed = sorted(k for k in loaded1["files"] if k in loaded2["files"] and loaded1["files"][k] != loaded2["files"][k])
    report = {"label": "FICTIONAL / SYNTHETIC LOCAL DEMO; approvals are not real client approvals",
        "tenant": tenant, "project": project, "brand": brand, "site": site, "external_effects": "none",
        "browser_note": "Pinned Playwright Chromium is required for canonical QA; missing/blocked is not a pass.",
        "v1": {**first_run, "brand_version": version1["version_id"], "primary_accent": first["brand"]["primary_accent"],
               "cta": loaded1["brief"].cta_label, "pages": [p.slug for p in loaded1["brief"].pages]},
        "after_brand_change_before_recompile": stale.json()["release"],
        "v2": {**second_run, "brand_version": version2["version_id"], "primary_accent": second["brand"]["primary_accent"],
               "cta": loaded2["brief"].cta_label, "pages": [p.slug for p in loaded2["brief"].pages]},
        "revision": {"changed_files": changed, "unchanged_files": same,
                     "independent_artifact_id": independent.artifact_id, "independent_artifact_unchanged": before == after},
        "missing": ["six completed social assets", "30-second film", "two 15-second cutdowns", "captions",
                    "thumbnails", "production rights and editable media handoff", "real client review", "release authorization"]}
    report_bytes = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
    (out / "northline-report.json").write_bytes(report_bytes)
    print(json.dumps({"report": str(out / "northline-report.json"), "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
                      "v1_build": first_run["build_status"], "v1_qa": first_run["browser_qa_status"],
                      "v2_build": second_run["build_status"], "v2_qa": second_run["browser_qa_status"],
                      "independent_artifact_unchanged": before == after, "release": "NOT_AUTHORIZED"}, indent=2))
    return 0


if __name__ == "__main__":
    main()
