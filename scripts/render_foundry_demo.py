#!/usr/bin/env python3
"""Render the Creative Foundry demonstration for a FICTIONAL brand and write it to runtime/foundry/demo/.

    python scripts/render_foundry_demo.py [--out runtime/foundry/demo] [--quality draft|standard]

"Halden & Fen" and everything said about it is invented for this demonstration:
there is no such company, no customers, no research and no sales data. The run
uses a throwaway SQLite database and export root, goes through the real
foundry mission (Project OS persistence, independent readback, proofs), copies
the stored bytes out by artifact name, re-hashes them, and writes a provenance
manifest and a static preview index. Nothing is published and no approval is
decided here.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DISCLAIMER = ("FICTIONAL DEMONSTRATION BRAND. 'Halden & Fen', its offering, audience and copy are invented for this "
              "demo. No real company, customer research, participants, sales or performance data exist or are implied.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(ROOT / "runtime" / "foundry" / "demo"))
    parser.add_argument("--quality", choices=("draft", "standard"), default="standard")
    args = parser.parse_args(argv)
    work = Path(tempfile.mkdtemp(prefix="amc-foundry-demo-"))
    os.environ.update({"AMC_DB_PATH": str(work / "demo.db"), "AMC_EXPORT_ROOT": str(work / "exports"),
                       "AMC_OBJECT_STORAGE_BACKEND": "local", "AMC_DATABASE_BACKEND": "sqlite"})

    from services.langgraph.agency.foundry.contracts import UserBrief
    from services.langgraph.agency.foundry.studio import Mission, observe
    from services.langgraph.agency.project_os.storage import LocalStorageAdapter
    from services.langgraph.persistence.projects import create_project_workspace
    from services.langgraph.security.auth import Principal

    export = Path(os.environ["AMC_EXPORT_ROOT"])
    tenant, project = "tenant-foundry-demo", "prj-foundry-demo"
    create_project_workspace(tenant_id=tenant, project_id=project, actor="demo-operator", display_name="Halden & Fen (fictional)",
                             slug="halden-fen-demo", brand_name="Halden & Fen", export_root=export)
    principal = Principal(user_id="demo-operator", tenant_id=tenant, role="admin", allowed_project_ids=frozenset({project}))
    brief = UserBrief(
        organization="Halden & Fen", offering="Small-batch stoneware for everyday tables (fictional)",
        business_objective="Made slowly, used daily", target_audience="People furnishing a first home (invented persona)",
        audience_needs="Durable, repairable tableware (assumed, not researched)", desired_action="Join the studio list",
        deliverable_types=("genome", "design_tokens", "logo_family", "poster", "variants", "website_section", "product_scene",
                           "motion"),
        visual_direction={"swiss_editorial": 0.65, "bauhaus_geometry": 0.35}, render_quality=args.quality, seed=4242,
    )
    mission = Mission(principal, project, brief, adapter=LocalStorageAdapter(export), work_dir=work / "mission",
                      copy={"headline": "Made slowly, used daily", "subhead": "Stoneware for the everyday table",
                            "cta": "Join the studio list", "meta": "FICTIONAL BRAND / DEMO"})
    started = datetime.now(timezone.utc)
    doc = mission.run(counterfactual=True, quality=args.quality)
    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    adapter = LocalStorageAdapter(export)
    files = []
    for a in doc["artifacts"]:
        data, head = observe(a["artifact_id"], adapter)
        name = "genome.json" if a["name"] == "genome" else a["name"]
        (out / name).write_bytes(data)
        sha = hashlib.sha256((out / name).read_bytes()).hexdigest()
        files.append({"file": name, "deliverable": a["deliverable"], "mime_type": a["mime_type"], "bytes": len(data),
                      "sha256": sha, "matches_stored_hash": sha == head["content_hash"] == a["sha256"],
                      "artifact_id": a["artifact_id"], "version": a["version"], "proof_state": a["proof"]["state"],
                      "next_proof": a["proof"]["blocked_at"], "renderer": a["proof"]["renderer_id"],
                      "renderer_version": a["proof"]["renderer_version"], "compiled_ir_hash": a["proof"]["compiled_ir_hash"],
                      "validations": a["proof"]["validation_results"], "elapsed_ms": a["elapsed_ms"]})
    provenance = {"schema_version": "amc-foundry-demo/v1", "disclaimer": DISCLAIMER, "generated_at": started.isoformat(),
                  "quality": args.quality, "genome_hash": doc["genome_hash"], "files": files, "routes": doc["routes"],
                  "capability_gaps": doc["capability_gaps"], "assumptions": doc["assumptions"],
                  "capabilities": [{k: c[k] for k in ("capability_id", "status", "installed_version", "blockers")}
                                   for c in doc["capabilities"]],
                  "approval_status": "NONE REQUESTED: every artifact stops at VERIFIED until a human reviewer decides",
                  "external_effects": doc["external_effects"]}
    (out / "provenance.json").write_text(json.dumps(provenance, indent=2, sort_keys=True, default=str) + "\n")
    tiles = []
    for f in files:
        label = html.escape(f"{f['file']} ({f['proof_state']})")
        if f["mime_type"].startswith("image/"):
            body = f'<img src="{html.escape(f["file"])}" alt="{html.escape(f["file"])}" loading="lazy">'
        elif f["mime_type"] == "video/mp4":
            body = f'<video src="{html.escape(f["file"])}" controls muted playsinline></video>'
        else:
            body = f'<a href="{html.escape(f["file"])}">Open {html.escape(f["file"])}</a>'
        tiles.append(f'<figure>{body}<figcaption>{label}<br><code>{f["sha256"][:16]}…</code></figcaption></figure>')
    index = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Creative Foundry demo: Halden &amp; Fen (fictional)</title>
<style>body{{font-family:system-ui,sans-serif;margin:2rem;max-width:80rem;color:#1c1c1c;background:#fafafa}}
.grid{{display:grid;gap:1rem;grid-template-columns:repeat(auto-fill,minmax(14rem,1fr))}}
figure{{margin:0;padding:.75rem;background:#fff;border:1px solid #ccc;border-radius:8px}}
img,video{{width:100%;height:auto;background:#eee}} code{{font-size:.8em}} .note{{padding:1rem;border:2px solid #1c1c1c}}</style></head>
<body><h1>Creative Foundry demo</h1><p class="note">{html.escape(DISCLAIMER)}</p>
<p>Every file below was rendered locally and re-read from Project OS storage; hashes and checks are in
<a href="provenance.json">provenance.json</a>. The 3D scene is a synthetic render, not a photograph of a product.
The website section is a working page: <a href="section.html">open section.html</a>.</p>
<div class="grid">{''.join(tiles)}</div></body></html>
"""
    (out / "index.html").write_text(index)
    shutil.rmtree(work, ignore_errors=True)
    print(json.dumps({f["file"]: [f["proof_state"], f["bytes"]] for f in files}, indent=2))
    print("gaps:", doc["capability_gaps"])
    return 0 if all(f["matches_stored_hash"] for f in files) else 1


if __name__ == "__main__":
    raise SystemExit(main())
