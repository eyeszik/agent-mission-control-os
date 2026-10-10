"""Generative Creative Foundry acceptance tests A01-A24.

Pure-model and persistence tests run everywhere. Tests that need local Chromium,
Blender or FFmpeg skip with an explicit NOT_RUN reason when those are absent;
a skip is never a pass.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from services.langgraph.agency.durable import governance
from services.langgraph.agency.foundry import compose, discovery, experience, motion, scene, variants
from services.langgraph.agency.foundry.capabilities import discover
from services.langgraph.agency.foundry.contracts import ProofState, UserBrief
from services.langgraph.agency.foundry.genome import compile_genome, contrast_report
from services.langgraph.agency.foundry.grammars import GRAMMARS, blend, normalise
from services.langgraph.agency.foundry.proof import proof_state
from services.langgraph.agency.foundry.routing import route_deliverable
from services.langgraph.agency.foundry.studio import Mission, observe, release_verdict, request_approval
from services.langgraph.agency.foundry.tokens import compile_tokens
from services.langgraph.agency.project_os.storage import LocalStorageAdapter
from services.langgraph.agency.visual.browser import probe_browser
from services.langgraph.agency.visual.verify import verify_media
from services.langgraph.persistence.agency_kernel import get_artifact
from services.langgraph.persistence.projects import create_project_workspace, list_project_artifacts
from services.langgraph.security.auth import Principal

from services.langgraph.tests._project_os_support import as_user, client, headers

ROOT = Path(__file__).resolve().parents[3]
FOUNDRY = ROOT / "services" / "langgraph" / "agency" / "foundry"
HAS_BROWSER = probe_browser()["available"]
HAS_BPY = importlib.util.find_spec("bpy") is not None
HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
NEEDS_BROWSER = pytest.mark.skipif(not HAS_BROWSER, reason="NOT_RUN: node, Chromium or @playwright/test missing")
BRIEF = UserBrief(organization="Halden & Fen", offering="Small-batch stoneware", business_objective="Made slowly, used daily",
                  desired_action="Join the studio list", visual_direction={"swiss_editorial": 0.7, "bauhaus_geometry": 0.3},
                  deliverable_types=("genome", "design_tokens", "logo_family", "poster"), seed=4242)


@pytest.fixture
def root(tmp_path, monkeypatch):
    export = tmp_path / "exports"
    monkeypatch.setenv("AMC_EXPORT_ROOT", str(export))
    monkeypatch.setenv("AMC_OBJECT_STORAGE_BACKEND", "local")
    return export


def _project(root: Path, tenant: str | None = None) -> tuple[str, str, Principal]:
    tenant = tenant or f"tenant-foundry-{uuid4().hex[:8]}"
    project = f"prj-{uuid4().hex[:12]}"
    create_project_workspace(tenant_id=tenant, project_id=project, actor="alice", display_name="Foundry", slug=f"f-{project[-6:]}",
                             export_root=root)
    return tenant, project, Principal(user_id="alice", tenant_id=tenant, role="admin", allowed_project_ids=frozenset({project}))


def _mission(root: Path, brief: UserBrief = BRIEF, tmp: Path | None = None, project=None) -> tuple[Mission, dict]:
    tenant, pid, principal = project or _project(root)
    m = Mission(principal, pid, brief, adapter=LocalStorageAdapter(root), work_dir=(tmp or root) / f"work-{uuid4().hex[:6]}")
    return m, m.run(counterfactual=False)


# ------------------------------------------------------------------ A01 / A02 canonical owners


def test_a01_no_second_artifact_store_or_scheduler():
    source = "\n".join(p.read_text() for p in FOUNDRY.glob("*.py"))
    for forbidden in ("CREATE TABLE", "sqlite3", "transaction(", "INSERT INTO", "scheduled_jobs"):
        assert forbidden not in source, forbidden
    assert "create_project_artifact" in source and "revise_project_artifact" in source


def test_a02_tokens_come_from_the_single_dtcg_compiler():
    source = (FOUNDRY / "tokens.py").read_text()
    assert "from services.langgraph.agency.design_tokens import compile_css" in source
    assert not re.search(r"def (normalize_value|compile_graph|generate_css)", "\n".join(p.read_text() for p in FOUNDRY.glob("*.py")))
    g = compile_genome(BRIEF, project_id="p")
    doc, css, src = compile_tokens(g)
    assert "amc-dtcg-compiler/v1" in css and "--amc-color-ink:" in css and len(src) == 64


# ------------------------------------------------------------------ A03 determinism


def test_a03_same_seed_and_configuration_gives_the_same_result():
    a, b = compile_genome(BRIEF, project_id="p"), compile_genome(BRIEF, project_id="p")
    assert a.content_hash == b.content_hash
    sa = compose.to_svg(compose.poster(a, headline="Made slowly"), a)
    sb = compose.to_svg(compose.poster(b, headline="Made slowly"), b)
    assert sa == sb
    other = compile_genome(BRIEF.model_copy(update={"seed": 7}), project_id="p")
    assert other.content_hash != a.content_hash
    assert compose.to_svg(compose.poster(a, headline="Made slowly", variant_seed=3), a) != sa
    ir = motion.logo_reveal(a)
    assert motion.frames(ir, a) == motion.frames(ir, b)
    caps = {c.capability_id: c for c in discover()}
    assert caps["raster.chromium"].deterministic == "declared_nondeterministic"
    assert caps["spatial.blender"].deterministic == "declared_nondeterministic"


def test_genome_records_assumptions_and_refuses_foreign_project_hint():
    g = compile_genome(UserBrief(organization="Acme"), project_id="p")
    fields = {a.field for a in g.assumptions}
    assert {"seed", "offering", "visual_direction", "brand_constraints.palette"} <= fields
    with pytest.raises(PermissionError):
        compile_genome(UserBrief(organization="Acme", existing_project_id="someone-else"), project_id="p")
    report = contrast_report(g.palette)
    assert report["ink/paper"] >= 7 and report["accent/paper"] >= 3
    assert g.novelty_constraints["max_candidates"] == 4 and g.novelty_constraints["max_generations"] == 2


def test_grammars_blend_deterministically_and_reject_unknowns():
    assert len(GRAMMARS) == 12 and all(g.anti_patterns and g.lineage_note for g in GRAMMARS.values())
    w = normalise({"art_deco": 2, "swiss_editorial": 2})
    assert w == {"art_deco": 0.5, "swiss_editorial": 0.5}
    assert blend(w) == blend(dict(reversed(list(w.items()))))
    with pytest.raises(ValueError):
        normalise({"vaporwave_copy_of_a_logo": 1})


# ------------------------------------------------------------------ A04 isolation


def test_a04_projects_and_tenants_stay_isolated(root):
    _, project_a, principal_a = _project(root)
    _, project_b, principal_b = _project(root)
    with pytest.raises(PermissionError):
        Mission(principal_b, project_a, BRIEF, adapter=LocalStorageAdapter(root))
    m, doc = _mission(root, BRIEF.model_copy(update={"deliverable_types": ("genome", "design_tokens")}),
                      project=(principal_a.tenant_id, project_a, principal_a))
    assert all(a["artifact_id"].startswith(f"{project_a}") or project_a in a["artifact_id"] for a in doc["artifacts"])
    assert [a for a in list_project_artifacts(project_b) if a.artifact_key.startswith("foundry-")] == []
    as_user(_mp := pytest.MonkeyPatch(), "bob", tenant=principal_b.tenant_id, projects=project_b)
    try:
        foreign = doc["artifacts"][0]["artifact_id"]
        r = client.get(f"/foundry/projects/{project_b}/artifacts/{foreign}/content")
        assert r.status_code in (403, 404)
        r = client.get(f"/foundry/projects/{project_a}/artifacts")
        assert r.status_code in (403, 404)
    finally:
        _mp.undo()


# ------------------------------------------------------------------ A05-A07 SVG/raster


def test_a05_generated_svg_parses_safely_and_stays_on_palette():
    g = compile_genome(BRIEF, project_id="p")
    for ir in (compose.poster(g, headline="A & B <test>"), compose.mark(g), compose.lockup(g), compose.lockup(g, on="ink")):
        svg = compose.to_svg(ir, g)
        v = verify_media(svg.encode(), mime_type="image/svg+xml", expect={"palette": sorted(set(g.palette.roles().values()))})
        assert v.status == "PASSED", v.findings
    for name in compose.ICON_PATHS:
        assert verify_media(compose.icon_svg(g, name).encode(), mime_type="image/svg+xml", expect={}).status == "PASSED"


@NEEDS_BROWSER
def test_a05_a06_a07_svg_renders_and_raster_has_real_pixels_at_the_specified_size(tmp_path):
    from services.langgraph.agency.visual.browser import rasterize_svg

    g = compile_genome(BRIEF, project_id="p")
    svg = compose.to_svg(compose.poster(g, headline="Made slowly, used daily", width=600, height=800), g)
    r = rasterize_svg(svg, width=600, height=800, out_dir=tmp_path)
    assert r["status"] == "PASSED" and r["result"]["blocked_requests"] == []
    v = verify_media(Path(r["capture"]).read_bytes(), mime_type="image/png", expect={"width": 600, "height": 800})
    assert v.status == "PASSED" and v.highest_passed.value == "Q4_RIGHTS"
    multi = verify_media(svg.encode(), mime_type="image/svg+xml", expect={"render_sizes": (64, 256)})
    assert any(c["check"] == "multi_size_render" and c["passed"] for c in multi.checks)


# ------------------------------------------------------------------ A08 / A10 variants


def test_a08_variants_preserve_lineage_and_respect_creative_caps():
    g = compile_genome(BRIEF, project_id="p")
    base = variants.generate_candidate(g)
    child = variants.mutate_candidate(g, base, dimensions=["composition", "grid"], seed=1)
    other = variants.mutate_candidate(g, base, dimensions=["typography"], seed=2)
    cross = variants.crossbreed_candidates(g, child, other, seed=3)
    assert child.parents == (base.candidate_id,) and {m["dimension"] for m in child.mutations} == {"composition", "grid"}
    assert cross.parents == (child.candidate_id, other.candidate_id) and cross.generation == 2
    with pytest.raises(variants.FoundryCapExceeded):
        variants.mutate_candidate(g, cross, dimensions=["grid"], seed=4)
    with pytest.raises(variants.FoundryCapExceeded):
        variants.check_population(g, 5)
    rendered = [variants.render_candidate(g, c, headline="H") for c in (base, child)]
    diff = variants.compare_candidates((rendered[0][0], rendered[0][1]), (rendered[1][0], rendered[1][1]))
    assert diff["kind"].startswith("COMPUTED_DIVERSITY") and diff["parameter_distance"] >= 0
    lin = variants.lineage([r[0] for r in rendered])
    assert lin[1]["parents"] == [base.candidate_id] and lin[1]["svg_sha256"]
    with pytest.raises(ValueError):
        variants.record_feedback(base.candidate_id, reviewer="", text="nice")
    fork = variants.fork_candidate(g, base, edits={"margin": 0.1})
    assert fork.mutations[0]["by"] == "human_edit"
    with pytest.raises(ValueError):
        variants.fork_candidate(g, base, edits={"palette": "#000000"})


def test_a10_approved_invariants_survive_every_mutation():
    locked = BRIEF.model_copy(update={"brand_constraints": {"palette": {"ink": "#1b1b1b", "paper": "#f7f4ee", "accent": "#a33a2a",
                                                                         "accent_2": "#2a5aa3", "muted": "#c9c3b8"}, "mark": "ring_dot"}})
    g = compile_genome(locked, project_id="p")
    assert {"brand_name", "geometry_rules.mark", "color_rules.palette"} <= set(g.invariants)
    allowed = set(g.palette.roles().values())
    base = variants.generate_candidate(g)
    for seed in range(4):
        c = variants.mutate_candidate(g, base, dimensions=list(variants.POSTER_DIMS), seed=seed)
        _, ir, svg = variants.render_candidate(g, c, headline="Made slowly")
        colours = set(re.findall(r"#[0-9a-f]{6}", svg))
        assert colours <= allowed, colours - allowed
        assert "Halden &amp; Fen" in svg
    assert compose.mark(g).primitives == compose.mark(g).primitives and g.geometry_rules["mark"] == "ring_dot"


# ------------------------------------------------------------------ A09 capability blocking


def test_a09_unsupported_capability_is_blocked_not_substituted():
    caps = {c.capability_id: c for c in discover()}
    missing = {k: v.model_copy(update={"status": "MISSING", "blockers": ("MISSING_DEPENDENCY:x",)}) for k, v in caps.items()}
    d = route_deliverable("product_scene", missing)
    assert d["status"] == "BLOCKED" and d["selected"] == "capability_gap"
    assert any(r["route"] == "hosted_generation" and r["reason"].startswith("FORBIDDEN") for r in d["rejected"])
    assert caps["spatial.r3f"].status in {"MISSING", "AVAILABLE"}
    blocked = scene.render_scene(scene.compile_scene(compile_genome(BRIEF, project_id="p"), scene="device_screen"),
                                 artwork_png=None, out_dir=Path("/nonexistent-never-written"))
    assert blocked == {"status": "BLOCKED", "reasons": ["SCENE_NOT_IMPLEMENTED:device_screen"]}
    for c in caps.values():
        if c.status == "AVAILABLE":
            assert not c.blockers


# ------------------------------------------------------------------ A11-A14 experience twin


@pytest.fixture(scope="module")
def twin(tmp_path_factory):
    if not HAS_BROWSER:
        pytest.skip("NOT_RUN: node, Chromium or @playwright/test missing")
    g = compile_genome(BRIEF, project_id="p")
    brief = BRIEF
    ir = experience.compile_experience(g, brief, headline="Made slowly, used daily", subhead="Stoneware", cta="See more")
    return g, ir, tmp_path_factory.mktemp("twin")


def test_a11_functional_interface_survives_visual_restyling(twin):
    g, ir, out = twin
    alt = compile_genome(BRIEF.model_copy(update={"visual_direction": {"synthetic_futurism": 1.0}, "seed": 99}), project_id="p")
    result = experience.counterfactual_skins(ir, g, alternate=alt, out_dir=out / "skins")
    for name in ("canonical", "unstyled", "alternate_dark"):
        assert result[name]["accepted"], (name, result[name])
        assert result[name]["passed_scenarios"] == result[name]["total"] == 12


def test_a12_a13_a14_keyboard_reduced_motion_and_font_fallback(twin):
    g, ir, out = twin
    missing_font = g.model_copy(update={"typography_rules": {**g.typography_rules, "stacks": {
        **g.typography_rules["stacks"], "display": ["AMC Missing Display", "DejaVu Sans", "sans-serif"]}}})
    ev = experience.evaluate(experience.render_html(ir, missing_font), out_dir=out / "a12", primary_font="AMC Missing Display")
    by_id = {s["id"]: s for s in ev["scenarios"]}
    assert ev["status"] == "PASSED", ev["findings"]
    assert by_id["keyboard_only"]["passed"] and by_id["invalid_input"]["passed"]
    assert by_id["reduced_motion"]["passed"]
    fallback = by_id["font_fallback"]["steps"][0]["detail"]
    assert "primary_available=false" in fallback and "width=" in fallback
    assert ev["blocked_requests"] == []


def test_a13_motion_has_a_reduced_motion_alternative():
    g = compile_genome(BRIEF, project_id="p")
    ir = motion.logo_reveal(g)
    assert ir.reduced_motion == "static_final_frame" and ir.frame_count == 60
    last = motion.sample(ir.layers[0], 1.0)
    assert last["opacity"] == 1 and last["scale"] == 1


# ------------------------------------------------------------------ A15 scene / A16 video


@pytest.mark.skipif(not HAS_BPY, reason="NOT_RUN: bpy (Blender as a Python module) is not installed")
def test_a15_missing_scene_asset_fails_recoverably(tmp_path):
    ir = scene.compile_scene(compile_genome(BRIEF, project_id="p"))
    r = scene.render_scene(ir, artwork_png=None, out_dir=tmp_path / "s")
    assert r.status == "FAILED" and r.exit_code == 3
    assert json.loads((tmp_path / "s" / "error.json").read_text())["error"] == "SCENE_INPUT"
    assert not list((tmp_path / "s").glob("frame_*.png"))


@pytest.mark.skipif(not (HAS_BROWSER and HAS_FFMPEG), reason="NOT_RUN: needs local Chromium and FFmpeg")
def test_a16_motion_file_has_decodable_frames(tmp_path):
    from services.langgraph.agency.visual.browser import render_svg_frames
    from services.langgraph.agency.visual.renderers import encode_video

    g = compile_genome(BRIEF, project_id="p")
    ir = motion.logo_reveal(g, width=320, height=180, fps=12, duration_s=1.0)
    fr = render_svg_frames(motion.frames(ir, g), width=ir.width, height=ir.height, out_dir=tmp_path)
    video = encode_video([Path(f) for f in fr["files"]], tmp_path / "m.mp4", fps=ir.fps)
    v = verify_media((tmp_path / "m.mp4").read_bytes(), mime_type="video/mp4",
                     expect={"width": 320, "height": 180, "fps": 12, "frames": ir.frame_count})
    assert video.status == "SUCCEEDED" and v.status == "PASSED", v.findings


# ------------------------------------------------------------------ A17-A19, A22-A23 mission persistence


def test_a17_interrupted_render_leaves_no_false_success(root, monkeypatch):
    from services.langgraph.agency.visual import browser

    calls = {"n": 0}

    def broken(*a, **k):
        calls["n"] += 1
        return {"status": "FAILED", "findings": ["BROWSER_EXIT:137"], "capture": None}

    monkeypatch.setattr(browser, "rasterize_svg", broken)
    m, doc = _mission(root)
    names = {a["name"] for a in doc["artifacts"]}
    assert "poster.svg" in names and "poster.png" not in names and "app-icon-512.png" not in names
    if m.caps["raster.chromium"].status == "AVAILABLE":
        assert calls["n"] >= 1 and any("BROWSER_EXIT:137" in g["blockers"] for g in doc["capability_gaps"])
    else:
        assert any(g["missing"] == ["raster.chromium"] for g in doc["capability_gaps"])
    for a in doc["artifacts"]:
        assert a["proof"]["state"] in {ProofState.VERIFIED.value, ProofState.OUTPUT_OBSERVED.value}


def test_a19_a22_a23_outputs_are_editable_sources_and_independently_verified(root):
    m, doc = _mission(root)
    adapter = LocalStorageAdapter(root)
    names = {a["name"]: a for a in doc["artifacts"]}
    for required in ("genome", "tokens.json", "tokens.css", "mark.svg", "lockup.svg", "icons.svg", "poster.svg", "manifest.json"):
        assert required in names, required
    for a in doc["artifacts"]:
        data, head = observe(a["artifact_id"], adapter)
        assert hashlib.sha256(data).hexdigest() == a["sha256"] == head["content_hash"]
        assert a["proof"]["validation_results"], a["name"]
        assert a["proof"]["output_sha256"] == a["sha256"]
    poster_svg, _ = observe(names["poster.svg"]["artifact_id"], adapter)
    assert b"<text" in poster_svg and b">Made slowly,</text>" in poster_svg and b">used daily</text>" in poster_svg  # live text, not outlines
    genome = json.loads(observe(names["genome"]["artifact_id"], adapter)[0])
    assert genome["schema_version"] == "amc-creative-genome/v1"
    assert names["mark.svg"]["proof"]["state"] in {"VERIFIED", "OUTPUT_OBSERVED"}
    assert all(a["proof"]["state"] == "VERIFIED" for a in doc["artifacts"] if a["name"] != "mark.svg")
    # tampering with stored bytes is caught on the next independent read
    from services.langgraph.agency.project_os.storage import StorageIntegrityError

    head = get_artifact(names["poster.svg"]["artifact_id"])
    store_path = adapter._path(*LocalStorageAdapter._parse(head["content_location"]))
    store_path.write_bytes(poster_svg.replace(b"Made slowly", b"Made quickly"))
    with pytest.raises(StorageIntegrityError):
        observe(names["poster.svg"]["artifact_id"], adapter)


def test_a18_genome_change_invalidates_dependents_and_stale_approval(root, monkeypatch):
    project = _project(root)
    m, doc = _mission(root, project=project)
    tenant, pid, principal = project
    poster = next(a for a in doc["artifacts"] if a["name"] == "poster.svg")
    approval = request_approval(principal, pid, poster["artifact_id"], adapter=LocalStorageAdapter(root), mission_id="fm-test")
    as_user(monkeypatch, "bob", tenant=tenant, projects=pid)
    decided = client.post(f"/approvals/{approval['approval_id']}/decide", json={"decision": "approve"}, headers=headers())
    assert decided.status_code == 200, decided.text
    ok = release_verdict(principal, pid, poster["artifact_id"], verified_version=poster["version"], verified_hash=poster["sha256"],
                         approval_id=approval["approval_id"])
    assert ok.allowed and ok.external_effects == "none"
    # change the genome: the genome is revised, every dependent is invalidated with a scoped edit request
    changed = BRIEF.model_copy(update={"visual_direction": {"art_deco": 1.0}})
    m2, doc2 = _mission(root, changed, project=project)
    genome_entry = next(a for a in doc2["artifacts"] if a["name"] == "genome")
    assert genome_entry["action"] == "revised" and poster["artifact_id"] in genome_entry["invalidated"]
    new_poster = next(a for a in doc2["artifacts"] if a["name"] == "poster.svg")
    assert new_poster["action"] == "revised" and new_poster["sha256"] != poster["sha256"]
    stale = release_verdict(principal, pid, poster["artifact_id"], verified_version=new_poster["version"],
                            verified_hash=new_poster["sha256"], approval_id=approval["approval_id"])
    assert not stale.allowed and "SUBJECT_HASH_MISMATCH" in stale.reasons
    from services.langgraph.persistence.projects import list_edit_requests

    assert any(r["artifact_id"] == poster["artifact_id"] for r in list_edit_requests(pid))


def test_proof_state_machine_needs_every_proof_in_order():
    base = dict(source_hash="s", compiled_ir_hash="c", executed=True, observed_sha256="h", recorded_sha256="h",
                validations=({"passed": True},), approval=None, release_allowed=False)
    assert proof_state(**base) == (ProofState.VERIFIED, "NO_APPROVAL_REQUESTED")
    assert proof_state(**{**base, "observed_sha256": None})[0] == ProofState.EXECUTED
    assert proof_state(**{**base, "recorded_sha256": "other"})[1] == "OUTPUT_NOT_OBSERVED_OR_HASH_MISMATCH"
    assert proof_state(**{**base, "validations": ({"passed": None},)})[1] == "VALIDATION_NOT_PASSED"
    assert proof_state(**{**base, "executed": False})[0] == ProofState.COMPILED
    approved = {"status": "resolved", "decision": "approve", "subject_hash": "h", "approval_id": "a"}
    assert proof_state(**{**base, "approval": approved}) == (ProofState.APPROVED, "RELEASE_GATE_REFUSED")
    assert proof_state(**{**base, "approval": {**approved, "subject_hash": "x"}})[0] == ProofState.APPROVAL_PENDING
    assert proof_state(**{**base, "approval": approved, "release_allowed": True}) == (ProofState.RELEASE_ELIGIBLE, None)


# ------------------------------------------------------------------ A20 / A21 effects and network


def test_a20_external_publication_and_discovery_stay_disabled(monkeypatch):
    assert not governance.decide("publish", authenticated=True, project_access=True, approval_current=True).allowed
    from services.langgraph.app.main import app

    paths = [p for p in app.openapi()["paths"] if p.startswith("/foundry")]
    assert paths and not any(w in p for p in paths for w in ("publish", "deploy", "order", "purchase", "send"))
    for a in discovery.inventory():
        assert a["status"] == "DISABLED"
        with pytest.raises(discovery.AdapterDisabled):
            discovery.search(a["adapter_id"], "ceramics")
    monkeypatch.setenv("AMC_DISCOVERY_OPENVERSE", "enabled")
    assert discovery.status("openverse") == "NOT_IMPLEMENTED"


@NEEDS_BROWSER
def test_a21_generated_pages_cannot_contact_remote_hosts(tmp_path):
    from services.langgraph.agency.visual.browser import run_experience

    html = ('<!doctype html><html><body><main><h1 id="t">x</h1><img src="https://example.com/pixel.png" alt="">'
            '<script>fetch("https://example.com/beacon").catch(function(){})</script></main></body></html>')
    run = run_experience(html, [{"id": "probe", "steps": [{"action": "wait", "value": 300}]}], out_dir=tmp_path)
    assert run["result"]["blocked_requests"] and "REMOTE_REQUEST_ATTEMPTED" in run["findings"]
    assert all(u.startswith("https://example.com") for u in run["result"]["blocked_requests"])


# ------------------------------------------------------------------ API


def test_api_capabilities_and_mission_route(root, monkeypatch):
    tenant, pid, _ = _project(root)
    as_user(monkeypatch, "alice", tenant=tenant, projects=pid)
    caps = client.get("/foundry/capabilities").json()
    assert caps["hosted_generation"] == "NONE" and len(caps["grammars"]) == 12
    body = {"brief": {"organization": "Halden & Fen", "deliverable_types": ["genome", "design_tokens"], "seed": 11}}
    assert client.post(f"/foundry/projects/{pid}/missions", json=body).status_code == 422  # Idempotency-Key required
    key = headers()
    r = client.post(f"/foundry/projects/{pid}/missions", json=body, headers=key)
    assert r.status_code == 201, r.text
    data = r.json()
    assert {a["name"] for a in data["artifacts"]} >= {"genome", "tokens.json", "tokens.css", "manifest.json"}
    assert data["external_effects"].startswith("none")
    again = client.post(f"/foundry/projects/{pid}/missions", json=body, headers=key)
    assert again.json() == data  # idempotent replay, no second mission
    listed = client.get(f"/foundry/projects/{pid}/artifacts").json()["artifacts"]
    assert len(listed) == len({a["artifact_id"] for a in data["artifacts"]})
    css = next(a for a in data["artifacts"] if a["name"] == "tokens.css")
    content = client.get(f"/foundry/projects/{pid}/artifacts/{css['artifact_id']}/content")
    assert content.status_code == 200 and hashlib.sha256(content.content).hexdigest() == css["sha256"]
    assert "sandbox" in content.headers["content-security-policy"]
    appr = client.post(f"/foundry/projects/{pid}/artifacts/{css['artifact_id']}/approval", json={"mission_id": data["mission_id"]})
    assert appr.status_code == 201 and appr.json()["approval"]["subject_hash"] == css["sha256"]
