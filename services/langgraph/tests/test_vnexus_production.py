"""VNEXUS production: media fabric lifecycle, identity, experience, art direction and video from an approved genome.

Local renders really run (Chromium, Pillow, FFmpeg) when the host has them;
a check that could not run is asserted as NOT_RUN, never as a pass.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from uuid import uuid4

import pytest

from services.langgraph.agency.vnexus import media_fabric
from services.langgraph.agency.vnexus.genome import document_from_flat
from services.langgraph.agency.visual.browser import probe_browser
from services.langgraph.tests._project_os_support import as_user, client, headers
from services.langgraph.tests._vnexus_support import FULL_DOC, _approve, _c, _draft, make_world

BROWSER = probe_browser().get("available", False)
needs_browser = pytest.mark.skipif(not BROWSER, reason="NOT_RUN: local Chromium unavailable")
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None or not BROWSER, reason="NOT_RUN: ffmpeg or Chromium unavailable")


@pytest.fixture
def world(monkeypatch, tmp_path):
    return make_world(monkeypatch, tmp_path)


@pytest.fixture
def approved(world):
    v = _approve(world, _draft(world, "brand", world["brand"], FULL_DOC))
    return {**world, "version": v}


def _job(w, provider: str, request: dict, *, key: str | None = None, budget: int = 0, run: bool = True):
    return client.post(f"/vnexus/projects/{w['owner']}/media-jobs", json={"provider_id": provider, "request": request,
                                                                         "budget_ceiling_minor": budget, "run": run},
                       headers={"Idempotency-Key": key or str(uuid4())})


SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64"><title>t</title><rect width="64" height="64" fill="#14161a"/><circle cx="32" cy="32" r="12" fill="#f7f4ee"/></svg>'


# --------------------------------------------------------------------------- fabric


def test_discovery_is_truthful():
    found = {p["provider_id"]: p for p in media_fabric.discover()}
    for hosted in ("hosted.text_to_image", "hosted.text_to_video", "hosted.image_to_video"):
        assert found[hosted]["status"] == "DISABLED" and "PAID_CALLS_NOT_AUTHORIZED" in found[hosted]["blockers"]
    assert found["local.svg"]["status"] == "AVAILABLE"
    assert found["mock.simulated"]["status"] == "DISABLED"  # off unless explicitly enabled
    assert media_fabric.select_provider(media_fabric.Capability.TEXT_TO_IMAGE) is None
    assert not media_fabric.can_claim_generated("QC_PASSED", {"sha256": "a" * 64, "simulated": True})
    assert not media_fabric.can_claim_generated("ARTIFACT_RECEIVED", {"sha256": "a" * 64, "simulated": False})
    assert media_fabric.can_claim_generated("QC_PASSED", {"sha256": "a" * 64, "simulated": False})


def test_local_svg_job_lifecycle_idempotency_and_integrity(world):
    w = world
    key = str(uuid4())
    r = _job(w, "local.svg", {"capability": "VECTOR_SVG", "spec": {"svg": SVG}, "width": 64, "height": 64}, key=key)
    assert r.status_code == 201, r.text
    job = r.json()["job"]
    assert job["state"] == "QC_PASSED" and job["claimable_as_generated"] and not job["simulated"]
    assert job["authorized_by"] == "alice" and job["estimate"]["amount_minor"] == 0
    assert job["artifact"]["sha256"] == hashlib.sha256(SVG.encode()).hexdigest() == job["artifact"]["readback_sha256"]
    replay = _job(w, "local.svg", {"capability": "VECTOR_SVG", "spec": {"svg": SVG}, "width": 64, "height": 64}, key=key)
    assert replay.json()["job"]["job_id"] == job["job_id"]
    clash = _job(w, "local.svg", {"capability": "VECTOR_SVG", "spec": {"svg": SVG.replace("12", "13")}}, key=key)
    assert clash.status_code == 409
    detail = client.get(f"/vnexus/media-jobs/{job['job_id']}").json()["job"]
    assert [t["to_state"] for t in detail["transitions"]] == ["PLANNED", "VALIDATED", "AUTHORIZED", "QUEUED", "RUNNING",
                                                               "ARTIFACT_RECEIVED", "QC_PASSED"]
    stored = client.get(f"/projects/{w['owner']}/artifacts/{job['artifact']['artifact_id']}")
    assert stored.status_code in (200, 404)  # project artifact routes vary; the job record carries the read-back proof


def test_rejections_are_failures_not_outputs(world):
    w = world
    unsafe = _job(w, "local.svg", {"capability": "VECTOR_SVG", "spec": {"svg": "<svg xmlns='http://www.w3.org/2000/svg'><script>x</script></svg>"}})
    assert unsafe.json()["job"]["state"] == "FAILED" and "SVG_UNSAFE" in unsafe.json()["job"]["error"]
    hosted = _job(w, "hosted.text_to_image", {"capability": "TEXT_TO_IMAGE", "spec": {"prompt": "a vase"}, "width": 512, "height": 512})
    body = hosted.json()["job"]
    assert body["state"] == "FAILED" and "PROVIDER_DISABLED" in body["error"] and not body["artifact"]
    wrong = _job(w, "local.svg", {"capability": "RASTER_PNG", "spec": {"svg": SVG}})
    assert "CAPABILITY_UNSUPPORTED" in wrong.json()["job"]["error"]
    assert _job(w, "nope.provider", {"capability": "VECTOR_SVG", "spec": {"svg": SVG}}).status_code == 404


def test_mock_provider_retry_corruption_budget_rate_limit_and_spend_approval(world, monkeypatch):
    w = world
    monkeypatch.setenv("AMC_VNEXUS_MOCK_PROVIDERS", "1")
    req = {"capability": "TEXT_TO_IMAGE", "width": 32, "height": 32}
    once = _job(w, "mock.simulated", {**req, "spec": {"mock": "transient_once", "mock_key": str(uuid4())}}).json()["job"]
    assert once["state"] == "QC_PASSED" and once["attempts"] == 2 and once["simulated"] and not once["claimable_as_generated"]
    assert once["artifact"]["artifact_id"] is None and once["qc"]["verdict"] == "SIMULATED_ONLY"
    always = _job(w, "mock.simulated", {**req, "spec": {"mock": "transient"}}).json()["job"]
    assert always["state"] == "FAILED" and always["attempts"] == 2 and always["error"].startswith("TRANSIENT")
    perm = _job(w, "mock.simulated", {**req, "spec": {"mock": "permanent"}}).json()["job"]
    assert perm["state"] == "FAILED" and perm["attempts"] == 1 and perm["error"].startswith("PERMANENT")
    bad = _job(w, "mock.simulated", {**req, "spec": {"mock": "corrupt"}}).json()["job"]
    assert bad["state"] == "FAILED" and bad["error"].startswith("INTEGRITY")
    assert client.post(f"/vnexus/media-jobs/{perm['job_id']}/retry").status_code == 409

    monkeypatch.setenv("AMC_VNEXUS_MOCK_COST_MINOR", "250")
    over = _job(w, "mock.simulated", {**req, "spec": {}}, budget=100).json()["job"]
    assert over["state"] == "FAILED" and "BUDGET_EXCEEDED" in over["error"]
    paid = _job(w, "mock.simulated", {**req, "spec": {}}, budget=500).json()["job"]
    assert paid["state"] == "VALIDATED" and paid["estimate"]["approval_id"]
    assert client.post(f"/vnexus/media-jobs/{paid['job_id']}/run").json()["job"]["state"] == "VALIDATED"  # cannot run unauthorized
    own = client.post(f"/approvals/{paid['estimate']['approval_id']}/decide", json={"decision": "approve"}, headers=headers())
    assert own.status_code == 403  # the requester cannot authorize their own spend
    as_user(w["mp"], "bob", role="approver", tenant=w["tenant"])
    assert client.post(f"/approvals/{paid['estimate']['approval_id']}/decide", json={"decision": "approve"}, headers=headers()).status_code == 200
    as_user(w["mp"], "alice", role="editor", tenant=w["tenant"])
    authorized = client.post(f"/vnexus/media-jobs/{paid['job_id']}/authorize").json()["job"]
    assert authorized["state"] == "AUTHORIZED" and authorized["authorized_by"] == "bob"
    ran = client.post(f"/vnexus/media-jobs/{paid['job_id']}/run").json()["job"]
    assert ran["state"] == "QC_PASSED" and ran["simulated"] and not ran["claimable_as_generated"]

    monkeypatch.setenv("AMC_VNEXUS_MOCK_COST_MINOR", "0")
    monkeypatch.setenv("AMC_VNEXUS_MOCK_RATE_LIMIT", "1")
    limited = _job(w, "mock.simulated", {**req, "spec": {}})
    assert limited.status_code == 429
    queued = client.get(f"/vnexus/projects/{w['owner']}/media-jobs").json()["jobs"]
    stuck = [j for j in queued if j["state"] == "QUEUED"]
    assert stuck and client.post(f"/vnexus/media-jobs/{stuck[0]['job_id']}/cancel").json()["job"]["state"] == "CANCELED"


def test_media_jobs_are_tenant_isolated(world, monkeypatch):
    w = world
    job = _job(w, "local.svg", {"capability": "VECTOR_SVG", "spec": {"svg": SVG}}).json()["job"]
    as_user(monkeypatch, "mallory", role="admin", tenant=f"tenant-other-{uuid4().hex[:6]}")
    assert client.get(f"/vnexus/media-jobs/{job['job_id']}").status_code == 404
    assert client.post(f"/vnexus/media-jobs/{job['job_id']}/cancel").status_code == 404
    as_user(monkeypatch, "victor", role="viewer", tenant=w["tenant"])
    assert _job(w, "local.svg", {"capability": "VECTOR_SVG", "spec": {"svg": SVG}}).status_code == 403


# --------------------------------------------------------------------------- production


def _produce(w, kind: str, body: dict, key: str | None = None):
    return client.post(f"/vnexus/brands/{w['brand']}/production/{kind}",
                       json={"scope": "brand", "scope_ref": w["brand"], "project_id": w["owner"], **body},
                       headers={"Idempotency-Key": key or str(uuid4())})


def test_production_requires_an_approved_genome(world):
    w = world
    _draft(w, "brand", w["brand"], FULL_DOC)  # a draft only
    r = _produce(w, "identity", {"deliverables": ["logo_mark"]})
    assert r.status_code == 409 and "no approved genome" in r.text
    # Blocking findings on the approved genome also stop production.
    weak = document_from_flat({"visual.color.ink": "#cccccc", "visual.color.paper": "#ffffff"},
                              constraints=[_c("c", "visual.color.ink", "MIN_CONTRAST", against="visual.color.paper", ratio=4.5)])
    v = _draft(w, "brand", w["brand"], weak)
    assert client.post(f"/vnexus/versions/{v['version_id']}/submit", headers=headers()).status_code == 409


@needs_browser
def test_identity_production_end_to_end(approved):
    w = approved
    r = _produce(w, "identity", {"deliverables": ["logo_mark", "logo_lockup", "monogram", "icon_family", "color_system",
                                                  "typography_specimen", "poster", "social_graphics", "brand_guidelines"],
                                 "copy_text": {"headline": "Made slowly, used daily", "cta": "Join the studio list"}})
    assert r.status_code == 200, r.text
    rep = r.json()
    states = {o["name"]: o["state"] for o in rep["outputs"]}
    assert all(s == "QC_PASSED" for s in states.values()), {k: v for k, v in states.items() if v != "QC_PASSED"}
    assert {"logo-mark.svg", "logo-mark-transparent.png", "logo-lockup.pdf", "social-square.webp", "brand-guidelines.pdf"} <= set(states)
    assert all(o["claimable_as_generated"] and o["graph_node"] for o in rep["outputs"])
    checks = {(v["output"], v["check"]): v for v in rep["validations"]}
    assert checks[("logo-mark-transparent.png", "transparency")]["status"] == "PASSED"
    assert checks[("logo_mark", "min_reproduction")]["status"] == "PASSED"
    assert checks[("icon_family", "stroke_consistency")]["status"] == "PASSED"
    assert checks[("poster", "text_contrast")]["status"] == "PASSED"
    assert all(v["status"] == "PASSED" for v in rep["validations"] if v["check"] == "palette_conformance")
    assert rep["status"] == "VERIFIED" and "visual coherence" in rep["human_review_required"]
    graph = client.get(f"/vnexus/brands/{w['brand']}/graph").json()
    gv = next(n for n in graph["nodes"] if n["kind"] == "GenomeVersion")
    impact = client.post(f"/vnexus/brands/{w['brand']}/graph/impact", json={"node_ids": [gv["node_id"]]}).json()
    assert len(impact["affected"]) == len(rep["outputs"])  # a genome change reaches every produced asset


@needs_browser
def test_experience_production_and_spec_only_targets(approved):
    w = approved
    r = _produce(w, "experience", {"request": {"target": "LANDING_PAGE", "objective": "Grow the studio list",
                                               "primary_action": "Join the studio list",
                                               "content": [{"title": "Plates", "body": "Stoneware for every day."}]}})
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["verification"]["status"] == "PASSED" and rep["status"] == "VERIFIED"
    assert rep["verification"]["network_isolated"] is True and len(rep["verification"]["scenarios"]) == 12
    stages = [s["stage"] for s in rep["package"]["stages"]]
    assert stages[0] == "genome_context" and stages[-1] == "implementation_artifacts" and len(stages) == 9  # + stored verification report
    assert {"package", "html", "tokens_css", "verification"} <= set(rep["stored"])
    dash = _produce(w, "experience", {"request": {"target": "SAAS_DASHBOARD", "objective": "Track orders"}}).json()
    assert dash["status"] == "SPEC_ONLY" and dash["verification"]["status"] == "NOT_APPLICABLE"
    assert dash["package"]["stages"][-1]["payload"]["status"] == "SPEC_ONLY"


def test_art_direction_labels_every_claim(approved):
    w = approved
    r = _produce(w, "art-direction", {"request": {"objective": "Launch poster", "medium": "POSTER", "platform": "print.poster_a_ratio",
                                                  "references": [{"ref": "artifact:owned-1", "rights": "OWNED"},
                                                                 {"ref": "https://example.org/moodboard", "rights": "UNKNOWN"}],
                                                  "exploration": True}})
    assert r.status_code == 200, r.text
    brief = r.json()["brief"]
    classes = {c["claim_class"] for c in brief["claims"]}
    assert classes == {"VERIFIED_REQUIREMENT", "INFERRED_DECISION", "EXPERIMENTAL_SUGGESTION"}
    preset = next(c for c in brief["claims"] if c["section"] == "production_constraints")
    assert preset["claim_class"] == "INFERRED_DECISION" and "confirm" in preset["rationale"]
    assert brief["excluded_references"] == ["https://example.org/moodboard"]
    assert {r["method"] for r in brief["rubric"]} == {"MEASURED", "HUMAN_REQUIRED"}


@needs_ffmpeg
def test_video_production_procedural_master_captions_and_blocked_ai_shot(approved, tmp_path):
    w = approved
    r = _produce(w, "video", {"brief": {"objective": "Introduce the studio", "headline": "Made slowly, used daily",
                                        "points": ["Small batches", "Repairable"], "cta": "Join the studio list", "width": 480,
                                        "height": 270, "fps": 12, "max_duration_s": 10, "include_shots": ["LIVE_ACTION"]}})
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["status"] == "MASTER_READY"
    master = rep["stages"]["master"]
    assert {"master_silent", "captions", "reduced_motion_still"} <= set(master["deliverables"])
    assert master["procedural_only"] is True and master["blocked_shots"] == ["x1"]
    blocked = rep["stages"]["render_jobs"]["blocked_shots"][0]
    assert blocked["state"] == "FAILED" and "PROVIDER_DISABLED" in blocked["error"]
    assert rep["stages"]["audio"]["status"] == "SILENT"
    qc = {c["check"]: c["passed"] for c in rep["stages"]["quality_control"]["checks"]}
    assert all(qc.values()), qc
    assert rep["stages"]["script"]["placeholders"] == []
    assert "not filmed footage" in rep["label"]


@needs_ffmpeg
def test_video_audio_requires_licence_and_muxes_real_audio(approved, tmp_path):
    w = approved
    tone = tmp_path / "tone.m4a"
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=8",
                    "-c:a", "aac", str(tone)], check=True)
    from services.langgraph.agency.foundry.studio import store
    from services.langgraph.api.routes._project_common import storage_adapter
    from services.langgraph.security.auth import Principal

    alice = Principal(user_id="alice", tenant_id=w["tenant"], role="editor", allowed_project_ids=frozenset({w["owner"]}))
    audio = store(alice, w["owner"], "tone.m4a", tone.read_bytes(), mime="audio/mp4", artifact_type="media_asset", subtype="audio",
                  adapter=storage_adapter())
    base = {"objective": "x", "headline": "Hello", "cta": "Go", "width": 320, "height": 180, "fps": 8, "max_duration_s": 6,
            "audio_artifact_id": audio["artifact_id"]}
    refused = _produce(w, "video", {"brief": base}).json()
    assert refused["stages"]["audio"]["status"] == "REFUSED"
    muxed = _produce(w, "video", {"brief": {**base, "audio_licence": "test tone generated locally by ffmpeg lavfi; no third-party rights"}}).json()
    assert muxed["stages"]["audio"]["status"] == "MUXED" and muxed["stages"]["audio"]["streams"] == ["audio", "video"]
    assert "master_with_audio" in muxed["stages"]["master"]["deliverables"]
