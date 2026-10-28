"""Run the creative-direction pipeline for a FICTIONAL brand into runtime/directions/demo/ (real API, scratch SQLite DB).

    python scripts/render_directions_demo.py

Brief -> intent (existing prompt compiler) -> refused hosted route with a manual-handoff offer -> two synthetic imports
(USER_REPORTED) + three local compositions -> COMPARE review (named reviewer scores) -> human selection through the
approval route (a second fictional reviewer) -> vector reconstruction measured in local Chromium -> RELEASE review ->
genome draft pinning the master -> genome approval -> brand book mark resolved by hash. No hosted provider is called.
The images are synthetic shapes drawn by this script; nothing here is a real brand, client, person or claim.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "runtime" / "directions" / "demo"


class _Env:
    """The tiny part of pytest's monkeypatch that the shared fixtures use."""

    def setenv(self, k: str, v: str) -> None:
        os.environ[k] = v

    def delenv(self, k: str, raising: bool = True) -> None:
        os.environ.pop(k, None)


def main() -> int:
    scratch = Path(tempfile.mkdtemp(prefix="amc-directions-demo-"))
    os.environ.update({"AMC_ENV": "local", "AMC_AUTH_MODE": "local", "AMC_DATABASE_BACKEND": "sqlite",
                       "AMC_DB_PATH": str(scratch / "demo.db")})
    for k in ("AMC_LLM_PROVIDER", "GEMINI_API_KEY", "AMC_VNEXUS_MOCK_PROVIDERS"):
        os.environ.pop(k, None)
    from services.langgraph.agency.visual.browser import probe_browser
    from services.langgraph.agency.vnexus.directions.review import LENSES
    from services.langgraph.tests._project_os_support import as_user, client, headers
    from services.langgraph.tests._vnexus_support import FULL_DOC, _approve, _draft, make_world
    from services.langgraph.tests.test_vnexus_directions import ACCENT, PAPER, b64, disc_png

    if not probe_browser().get("available"):
        print("NOT_RUN: local Chromium unavailable; the reconstruction fidelity cannot be measured", file=sys.stderr)
        return 2
    env = _Env()
    w = make_world(env, scratch)
    _approve(w, _draft(w, "brand", w["brand"], FULL_DOC))
    p = {"project_id": w["owner"]}
    intent = client.post(f"/vnexus/brands/{w['brand']}/directions/intents", headers=headers(), json={
        "scope": "brand", "scope_ref": w["brand"], **p,
        "brief": {"asset_role": "LOGO_MARK", "objective": "A mark for a small stoneware studio (fictional)", "exact_text": "@none",
                  "applications": ["favicon 32px", "A4 letterhead"], "category": "ceramics (fictional)"}}).json()["intent"]
    base = f"/vnexus/brands/{w['brand']}/directions/intents/{intent['intent_id']}"
    refused = client.post(base + "/generate", json={**p, "route_id": "cloudflare.workers_ai.text_to_image"}, headers=headers()).json()
    composed = client.post(base + "/generate", json={**p, "route_id": "local.foundry_compose"}, headers=headers()).json()
    images = {"candidate-a.png": disc_png(size=192, ring=(0.18, 0.24, PAPER)), "candidate-b.png": disc_png(size=192, fg=ACCENT, radius=0.25)}
    imported = [client.post(base + "/candidates", json={**p, "slot": i + 1, "mime": "image/png", "data_base64": b64(data),
                                                          "reported": {"provider": "operator (fictional)", "rights_basis": "operator-owned (fictional)"}},
                            headers=headers()).json()["candidate"] for i, data in enumerate(images.values())]
    a, b = (c["candidate_id"] for c in imported)
    probe = client.post(base + "/reviews", json={**p, "mode": "COMPARE", "candidate_ids": [a, b]}, headers=headers()).json()["session"]
    lab = {cid: label for label, cid in probe["labels"].items()}

    def board(cid: str, value: int) -> list[dict]:
        rows = [{"candidate": lab[cid], "seat": "13", "criterion": "safety_privacy_rights", "evidence_class": "OBSERVED",
                 "observation": "no third-party marks, likeness or personal data visible", "gate": "SAFETY_PRIVACY_RIGHTS", "gate_status": "PASS"},
                {"candidate": lab[cid], "seat": "09", "criterion": "intended_vs_apparent", "evidence_class": "INFERRED",
                 "observation": "reads calm and plain", "trait": "plain", "cue": "single closed form, no ornament"}]
        rows += [{"candidate": lab[cid], "seat": s, "criterion": c, "evidence_class": "INFERRED",
                  "observation": f"{c}: fictional reviewer judgment", "score": value} for s in ("01", "02", "03", "05", "10")
                 for c in LENSES[s]["criteria"]]
        return rows
    compare = client.post(base + "/reviews", json={**p, "mode": "COMPARE", "candidate_ids": [a, b],
                                                   "findings": board(a, 8) + board(b, 6)}, headers=headers()).json()["session"]
    selection = client.post(base + "/selection", json={**p, "candidate_id": compare["recommendation"]["candidate_id"],
                                                       "session_id": compare["session_id"]}, headers=headers()).json()
    as_user(env, "bob", role="reviewer", tenant=w["tenant"])
    client.post(f"/approvals/{selection['approval_id']}/decide", json={"decision": "approve"}, headers=headers())
    as_user(env, "alice", role="editor", tenant=w["tenant"])
    rec = client.post(base + "/reconstructions", json={**p, "candidate_id": compare["recommendation"]["candidate_id"],
                                                       "method": "controlled_trace"}, headers=headers()).json()
    vec = rec["candidate"]["candidate_id"]
    release = client.post(base + "/reviews", json={**p, "mode": "RELEASE", "candidate_ids": [vec], "findings": [
        {"candidate": vec, "seat": "13", "criterion": "safety_privacy_rights", "evidence_class": "OBSERVED",
         "observation": "traced locally from the approved selection", "gate": "SAFETY_PRIVACY_RIGHTS", "gate_status": "PASS"},
        {"candidate": vec, "seat": "12", "criterion": "channel_fit", "evidence_class": "OBSERVED",
         "observation": "reads at favicon size in a browser tab (fictional check)", "score": 7}]}, headers=headers()).json()["session"]
    freeze = client.post(base + "/freeze", json={**p, "master_candidate_id": vec, "session_id": release["session_id"]},
                         headers=headers()).json()
    as_user(env, "bob", role="reviewer", tenant=w["tenant"])
    client.post(f"/approvals/{freeze['approval_id']}/decide", json={"decision": "approve"}, headers=headers())
    client.get(f"/vnexus/versions/{freeze['genome_version_id']}")
    as_user(env, "alice", role="editor", tenant=w["tenant"])
    gaps = client.get(f"/vnexus/brands/{w['brand']}/brandbook/gaps",
                      params={"scope": "brand", "scope_ref": w["brand"], "project_id": w["owner"], "mode": "PREVIEW"}).json()
    master_svg = client.get(base + f"/candidates/{vec}/content", params=p).content

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    for name, data in images.items():
        (OUT / name).write_bytes(data)
    (OUT / "master.svg").write_bytes(master_svg)
    redact = lambda d: json.loads(json.dumps(d).replace(str(scratch), "<scratch>"))  # noqa: E731
    for name, doc in {"intent.json": intent, "generate-refused.json": refused, "generate-local.json": composed,
                      "review-compare.json": compare, "selection.json": selection, "reconstruction.json": rec,
                      "review-release.json": release, "freeze.json": freeze}.items():
        (OUT / name).write_text(json.dumps(redact(doc), indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = {
        "brand": "Halden & Fen (fictional)", "hosted_route": refused["status"], "hosted_offer": refused["decision"]["offer"],
        "local_compositions": len([c for c in composed["candidates"] if c["status"] == "COMPLETE"]),
        "compare_verdict": compare["recommendation"]["verdict"], "compare_means": compare["recommendation"]["aggregate"]["means"],
        "reconstruction_status": rec["reconstruction"]["status"], "fidelity": rec["reconstruction"]["fidelity"].get("measured"),
        "release_verdict": release["recommendation"]["verdict"], "freeze": freeze["status"],
        "brand_book_mark": {"kind": gaps["mark"]["kind"], "sha256_matches_master": gaps["mark"]["sha256"] == rec["candidate"]["observed"]["sha256"]},
        "measured_recall": compare["brand_memory"]["measured_recall"], "provider_calls": 0,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    shutil.rmtree(scratch, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
