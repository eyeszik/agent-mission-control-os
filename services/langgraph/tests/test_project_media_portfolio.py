"""Video bridge, DAM ingest, brand drift, paid media, workstreams, portfolio, runs."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from _project_os_support import TENANT, as_user, client, export_root, headers, new_project  # noqa: F401
from services.langgraph.agency.project_os.video import freevideoforge_capability

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _env(monkeypatch, export_root):  # noqa: F811
    as_user(monkeypatch, "producer-1")


def _fvf_run(base: Path, *, run_id: str = "fvf-run-1", zero_paid: bool = True, failed_check: bool = False) -> Path:
    """A run directory shaped exactly like FreeVideoForge's documented output
    contract (seven files). Test fixture; it is not a rendered video."""
    out = base / run_id
    out.mkdir(parents=True)
    (out / "final.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64)
    (out / "thumbnail.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 32)
    (out / "script.json").write_text(json.dumps({"narration": "Why the moon changes shape"}))
    (out / "storyboard.json").write_text(json.dumps({"scenes": [{"id": "s1"}, {"id": "s2"}]}))
    (out / "captions.srt").write_text("1\n00:00:00,000 --> 00:00:02,000\nHello\n")
    (out / "manifest.json").write_text(json.dumps({
        "run_id": run_id, "version": "1.0.0", "created_at": 0, "completed_at": 1, "config_hash": "c" * 64,
        "project": {"render": {"duration": 30.0, "aspect": "9:16"}}, "providers": {"script": "template", "speech": "silence"},
        "assets": [{"kind": "frame", "seed": 7}], "outputs": {}, "environment": {"python": "3.11"},
        "zero_paid_api_spend": zero_paid, "credentials_used": [],
    }))
    (out / "quality-report.json").write_text(json.dumps({"checks": [{"name": "duration", "status": "FAIL" if failed_check else "PASS"}]}))
    return out


def test_video_plan_bridges_cinematic_shots_to_freevideoforge():
    pid = new_project()["project_id"]
    request = json.loads((ROOT / "sample_cinematic_request.json").read_text())
    plan = client.post(f"/projects/{pid}/video/plan", json={"cinematic_request": request, "aspect": "16:9", "seed": 11}).json()
    assert plan["title"] == "Atelier — Movement"
    assert plan["generation_firewall"] == "PROMPT_PACKAGE_READY"
    assert plan["freevideoforge_request"]["aspect"] == "16:9" and plan["freevideoforge_request"]["allow_paid"] is False
    assert plan["shots"] and {"shot_id", "camera", "lens", "lighting", "continuity_refs"} <= set(plan["shots"][0])
    stages = {s["stage"]: s["status"] for s in plan["stages"]}
    assert stages["SHOT_IR"] == "COMPLETE"
    capability = freevideoforge_capability()
    expected = "PENDING_LOCAL_RENDER" if capability["can_render"] else "BLOCKED_NO_LOCAL_RENDERER"
    assert stages["GENERATION"] == expected, "the plan must reflect what this machine can actually do"


def test_video_ingest_registers_lineage_and_reproducibility(monkeypatch, tmp_path):
    pid = new_project()["project_id"]
    ingest_root = tmp_path / "fvf"
    monkeypatch.setenv("AMC_VIDEO_INGEST_ROOT", str(ingest_root))
    out = _fvf_run(ingest_root)
    result = client.post(f"/projects/{pid}/video/ingest", json={"output_dir": str(out)})
    assert result.status_code == 201, result.text
    body = result.json()
    assert body["reproducibility"]["provider"] == "freevideoforge" and body["reproducibility"]["seed"] == 7
    assert body["reproducibility"]["guarantee"] == "SEEDED_BEST_EFFORT"
    videos = client.get(f"/projects/{pid}/artifacts", params={"media_type": "video"}).json()["artifacts"]
    master = videos[0]
    assert master["artifact_type"] == "media_asset" and master["duration_seconds"] == 30.0
    assert len(master["dependency_refs"]) == 2  # script + storyboard
    thumb = client.get(f"/projects/{pid}/artifacts", params={"media_type": "image"}).json()["artifacts"][0]
    assert thumb["master_artifact_id"] == master["artifact_id"]
    events = [e["event_type"] for e in client.get(f"/projects/{pid}/events").json()["events"]]
    assert "PREVIEW_READY" in events and "QA_BLOCKED" not in events


def test_video_ingest_refuses_paths_outside_root_and_paid_runs(monkeypatch, tmp_path):
    pid = new_project()["project_id"]
    ingest_root = tmp_path / "fvf"
    monkeypatch.setenv("AMC_VIDEO_INGEST_ROOT", str(ingest_root))
    outside = _fvf_run(tmp_path / "elsewhere")
    assert client.post(f"/projects/{pid}/video/ingest", json={"output_dir": str(outside)}).status_code == 400
    assert client.post(f"/projects/{pid}/video/ingest", json={"output_dir": str(ingest_root / ".." / "elsewhere" / "fvf-run-1")}).status_code == 400
    paid = _fvf_run(ingest_root, run_id="paid-run", zero_paid=False)
    assert client.post(f"/projects/{pid}/video/ingest", json={"output_dir": str(paid)}).status_code == 422


def test_failed_video_qc_surfaces_as_qa_blocked(monkeypatch, tmp_path):
    pid = new_project()["project_id"]
    monkeypatch.setenv("AMC_VIDEO_INGEST_ROOT", str(tmp_path / "fvf"))
    out = _fvf_run(tmp_path / "fvf", failed_check=True)
    body = client.post(f"/projects/{pid}/video/ingest", json={"output_dir": str(out)}).json()
    assert body["qc"]["status"] == "FAIL"
    assert "QA_BLOCKED" in [e["event_type"] for e in client.get(f"/projects/{pid}/events").json()["events"]]


def test_brand_drift_reports_findings_and_never_overwrites():
    pid = new_project()["project_id"]
    for key, text in (("a", "Try OldName for $49.00 in #ff0000"), ("b", "Try OldName for $49.00 in #ff0000")):
        client.post(f"/projects/{pid}/artifacts", json={"artifact_key": key, "artifact_type": "copy_variant", "content_text": text})
    report = client.post(f"/projects/{pid}/brand-drift", json={"palette": ["#1f2937"], "deprecated_names": {"OldName": "NewName"},
                                                              "current_prices": ["$59.00"], "banned_terms": []}).json()["report"]
    categories = {f["category"] for f in report["findings"]}
    assert {"colors", "naming", "old_pricing", "duplicate_content"} <= categories
    assert report["autonomous_overwrites"] == 0
    assert "logo_misuse" in report["not_evaluated"] and "voice" in report["not_evaluated"]
    history = client.get(f"/projects/{pid}/artifacts/art-{pid}-a/history").json()["versions"]
    assert len(history) == 1, "drift analysis must not revise artifacts"


def test_paid_media_plan_never_grants_spend_authority(monkeypatch):
    pid = new_project()["project_id"]
    monkeypatch.setenv("AMC_PAID_MEDIA_MODE", "disabled")
    plan = client.post(f"/projects/{pid}/paid-media/plan", json={"objective": "signups", "offer": "trial", "audiences": ["founders", "ops"],
                                                                "channels": ["meta", "google_search"], "budget_minor": 100000, "currency": "usd",
                                                                "flight_days": 10, "creative_refs": ["c1", "c2"], "keywords": ["coffee subscription"]}).json()["plan"]
    assert plan["spend_authority_granted"] is False and plan["execution_available"] is False
    assert len(plan["campaign_architecture"]["ad_groups"]) == 4 and len(plan["creative_matrix"]) == 8
    steps = {s["step"]: s["status"] for s in plan["mutation_sequence"]}
    assert steps["PLAN"] == "COMPLETE" and steps["IDEMPOTENT_PROVIDER_WRITE"] == "NOT_AVAILABLE"
    assert plan["budget"]["daily_minor"] == 10000


def test_workstream_readiness_tracks_project_artifacts():
    pid = new_project()["project_id"]
    plan = client.get(f"/projects/{pid}/workstreams/search").json()
    assert plan["stages"][0]["readiness"] == "READY" and plan["stages"][1]["readiness"] == "WAITING"
    assert all(stage["producing_roles"] for stage in plan["stages"])
    client.post(f"/projects/{pid}/artifacts", json={"artifact_key": "seo-audit", "artifact_type": "research_brief", "subtype": "seo_audit", "content_text": "audit"})
    after = client.get(f"/projects/{pid}/workstreams/search").json()
    assert after["stages"][0]["readiness"] == "IN_PROGRESS"
    assert client.get(f"/projects/{pid}/workstreams/not-a-workstream").status_code == 404


def test_portfolio_aggregates_only_accessible_projects(monkeypatch):
    a = new_project("Portfolio A")["project_id"]
    b = new_project("Portfolio B")["project_id"]
    view = client.get("/portfolio").json()
    ids = {p["project_id"] for p in view["projects"]}
    assert {a, b} <= ids
    row = next(p for p in view["projects"] if p["project_id"] == a)
    assert row["performance"] == "UNKNOWN_NO_OBSERVED_METRICS" and row["brand_health"] == "OK"
    assert "workstream_templates" in view["shared_resources"]
    as_user(monkeypatch, "client-a", projects=a)
    scoped = client.get("/portfolio").json()
    assert [p["project_id"] for p in scoped["projects"]] == [a]
    as_user(monkeypatch, "other-tenant", tenant="tenant-portfolio-other")
    assert all(p["project_id"] not in {a, b} for p in client.get("/portfolio").json()["projects"])


def test_agency_run_becomes_project_history_and_mirrors_export(export_root):  # noqa: F811
    project_id = f"proj-run-{uuid4().hex[:8]}"
    response = client.post(
        "/agency/runs",
        json={"project_id": project_id, "tenant_id": TENANT, "brief": {
            "brand_name": "Mirror Co", "business_idea": "Subscription coffee for remote teams",
            "target_audience": "Remote-first startups", "goals": ["awareness"], "channels": ["linkedin"],
        }},
        headers=headers(),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    # Legacy fields are unchanged; the project mirror is additive.
    assert set(body["workspace_export"]) >= {"root_folder", "business_folder", "branding_folder", "files_written"}
    assert body["artifact_bindings"]
    assert body["project_workspace"]["ok"] is True and body["project_workspace"]["hashes_verified"] is True
    assert body["project_workspace"]["run_root"].endswith(f".amc/runs/{body['run_id']}")
    events = [e["event_type"] for e in client.get(f"/projects/{project_id}/events").json()["events"]]
    assert events[:2] == ["PROJECT_CREATED", "WORK_STARTED"]
    assert "APPROVAL_REQUIRED" in events
    snapshot = client.get(f"/projects/{project_id}").json()["snapshot"]
    assert body["run_id"] in snapshot["run_ids"]
