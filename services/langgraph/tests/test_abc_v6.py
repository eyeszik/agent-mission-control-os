"""ABC-v6 acceptance matrix T01-T20 and the seven adversarial families.

Durable-runtime tests drive the real tick engine against real Project OS rows
and storage. They use the R4 vector route because it needs no optional host
software; tests of R1 Blender, R5 video and the real-browser harness run only
where those are installed and skip with the reason otherwise (a skip is
NOT_RUN, never PASSED).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from services.langgraph.agency.durable import build_dag as dag
from services.langgraph.agency.durable import governance
from services.langgraph.agency.durable.fsm import TRANSITIONS, IllegalTransition, RunState, reachable
from services.langgraph.agency.durable.genome import Constraint, Predicate, SourceEvidence, Unknown, compile_genome, proof_debt
from services.langgraph.agency.durable.observability import metrics, project_metrics, spans
from services.langgraph.agency.durable.proofs import (
    EvidenceRecord,
    capability_registry,
    evidence_valid,
    invalidated_by,
    minimal_proof_set,
    proof_graph,
)
from services.langgraph.agency.durable.ticks import idempotency_key, run_tick
from services.langgraph.agency.durable.visual_job import HANDLERS, settle_waiting_approval, submit_visual_job
from services.langgraph.agency.execution_fabric.adapters.code_sandbox import network_namespace_available
from services.langgraph.agency.intake.release import artifact_release_verdict
from services.langgraph.agency.project_os.storage import LocalStorageAdapter
from services.langgraph.agency.visual import capabilities as caps_mod
from services.langgraph.agency.visual import engine
from services.langgraph.agency.visual.browser import probe_browser, three_renderer_for
from services.langgraph.agency.visual.contracts import (
    Capability,
    CapabilityStatus,
    QualityLevel,
    Route,
    SourceAsset,
    VisualIntent,
)
from services.langgraph.agency.visual.router import route
from services.langgraph.agency.visual.verify import HUMAN_LEVELS, verify_media
from services.langgraph.persistence import durable_runs as store
from services.langgraph.persistence.agency_kernel import get_artifact
from services.langgraph.persistence.approvals import get_approval
from services.langgraph.persistence.projects import create_project_workspace, revise_project_artifact
from services.langgraph.security.auth import Principal

from services.langgraph.tests._project_os_support import as_user, client, headers

ROOT = Path(__file__).resolve().parents[3]
PALETTE = {"primary": "#5b1a22", "secondary": "#665d52", "surface": "#ece6da", "text": "#121212"}
HAS_BPY = importlib.util.find_spec("bpy") is not None
HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
HAS_BROWSER = probe_browser()["available"]
HAS_PIL = importlib.util.find_spec("PIL") is not None


@pytest.fixture
def root(tmp_path, monkeypatch):
    export = tmp_path / "exports"
    monkeypatch.setenv("AMC_EXPORT_ROOT", str(export))
    monkeypatch.setenv("AMC_OBJECT_STORAGE_BACKEND", "local")
    # Durable-runtime tests verify SVG structure, safety and palette; the real multi-size browser
    # render is exercised by its own test so each tick does not launch Chromium.
    monkeypatch.setattr(engine, "SVG_RENDER_SIZES", ())
    return export


def _tenant() -> str:
    return f"tenant-abc-{uuid4().hex[:8]}"


def _project(tenant: str, root: Path, name: str = "Velune") -> str:
    project_id = f"prj-{uuid4().hex[:12]}"
    create_project_workspace(tenant_id=tenant, project_id=project_id, actor="alice", display_name=name,
                             slug=f"{name.lower()}-{project_id[-6:]}", brand_name=name, export_root=root)
    return project_id


def _principal(tenant: str, *projects: str, user: str = "alice") -> Principal:
    return Principal(user_id=user, tenant_id=tenant, role="admin", allowed_project_ids=frozenset(projects or ("*",)))


def _mark(**kw) -> VisualIntent:
    return VisualIntent(category="brand_mark", output="svg", subject="Maison Velune", palette=PALETTE, **kw)


def _job(root: Path, *, intent: VisualIntent | None = None, key: str = "mark", approval: bool = True):
    tenant = _tenant()
    project = _project(tenant, root)
    principal = _principal(tenant, project)
    job = submit_visual_job(principal, project, intent or _mark(), artifact_key=key, mission_id=f"m-{uuid4().hex[:6]}",
                            export_root=root, requires_approval=approval,
                            due_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    return tenant, project, principal, job


def _states(job_id: str) -> list[tuple[str, str]]:
    return [(t["from_state"], t["to_state"]) for t in store.list_transitions(job_id)]


HAPPY_PATH = [("DORMANT", "SCHEDULED"), ("SCHEDULED", "LEASED"), ("LEASED", "PRECHECK"), ("PRECHECK", "READY"),
              ("READY", "RUNNING"), ("RUNNING", "OBSERVING"), ("OBSERVING", "VERIFYING"), ("VERIFYING", "COMMITTING"),
              ("COMMITTING", "WAITING_APPROVAL")]


# ------------------------------------------------------------------ T01 build DAG


def test_t01_build_dag_is_acyclic_dependency_complete_and_schema_valid():
    order = dag.toposort()
    assert len(order) == len(dag.BUILD_DAG) == 12 and order[0] == "A00_DISCOVER" and order[-1] == "A11_SEAL"
    position = {n: i for i, n in enumerate(order)}
    for node in dag.BUILD_DAG:
        assert all(position[d] < position[node.name] for d in node.deps)
        assert node.timeout_s > 0 and 0 <= node.retries <= 3 and node.verification and node.rollback
        assert set(node.edge_types) == set(node.deps) and all(v in {"artifact", "dependency"} for v in node.edge_types.values())
    ids = [n.node_id for n in dag.BUILD_DAG]
    assert len(set(ids)) == len(ids) and ids == [n.node_id for n in dag.BUILD_DAG]  # deterministic identities
    path, budget = dag.critical_path()
    assert budget == sum(dag.by_name()[n].timeout_s for n in path)
    for wave_index, wave in enumerate(dag.waves(max_parallel=2)):
        assert len(wave) <= 2
        earlier = {n for w in dag.waves(max_parallel=2)[:wave_index] for n in w}
        assert all(set(dag.by_name()[n].deps) <= earlier for n in wave)
    assert dag.dependency_closure("A11_SEAL") == set(order) - {"A11_SEAL"}


def test_t01_cycles_and_dangling_dependencies_are_rejected():
    a = dag._n("X", ("Y",), "o", "a", (), ("cmd:x",))
    b = dag._n("Y", ("X",), "o", "a", (), ("cmd:y",))
    with pytest.raises(dag.DagError, match="cycle"):
        dag.toposort((a, b))
    with pytest.raises(dag.DagError, match="missing node"):
        dag.toposort((dag._n("Z", ("NOPE",), "o", "a", (), ("cmd:z",)),))


def test_three_predicates_are_never_conflated_and_not_run_never_passes():
    node = dag.by_name()["A09_TEST"]
    assert dag.node_status(node, {}) == "NOT_RUN"
    assert dag.node_status(node, {"cmd:pytest_full": "PASSED"}) == "NOT_RUN"
    assert dag.node_status(node, {v: "PASSED" for v in node.verification}) == "PASSED"
    assert dag.node_status(node, {"cmd:pytest_full": "FAILED", "cmd:ruff": "PASSED", "cmd:compileall": "PASSED"}) == "FAILED"
    built = dag.build_complete(artifacts_exist=True, hashes_match=True, checks_pass=True, critical_unresolved=0)
    assert built
    assert not dag.release_eligible(build_ok=built, review_passed=False, authorization_valid=True, approval_current=True,
                                    simulation_free=True)
    assert not dag.runtime_active(scheduler_configured=True, worker_operational=False, durable_state=True,
                                  activation_authorized=False)


# ------------------------------------------------------------------ T02 FSM


def test_t02_fsm_is_closed_and_every_state_is_reachable():
    assert set(TRANSITIONS) == set(RunState) and len(RunState) == 20
    assert reachable() == set(RunState)
    assert TRANSITIONS[RunState.STOPPED] == frozenset()


def test_t02_tick_transitions_are_legal_and_persisted(root):
    _, project, _, job = _job(root)
    report = run_tick(worker_id="w1", handlers=HANDLERS, job_id=job["job_id"])
    assert report.outcome == "COMMITTED" and report.final_state == "WAITING_APPROVAL", report.reasons
    states = _states(job["job_id"])
    assert states == HAPPY_PATH
    assert all(RunState(b) in TRANSITIONS[RunState(a)] for a, b in states)
    tokens = {t["fencing_token"] for t in store.list_transitions(job["job_id"])[1:]}
    assert tokens == {1}


def test_t02_illegal_transition_is_refused_and_not_logged(root):
    _, _, _, job = _job(root)
    before = len(store.list_transitions(job["job_id"]))
    with pytest.raises(IllegalTransition):
        store.transition(job, RunState.RUNNING, fencing_token=0, now=datetime.now(timezone.utc))
    with pytest.raises(ValueError, match="cannot set"):
        store.transition(job, RunState.PAUSED, fencing_token=0, now=datetime.now(timezone.utc), state="RUNNING")
    assert len(store.list_transitions(job["job_id"])) == before and store.get_job(job["job_id"])["state"] == "SCHEDULED"


# ------------------------------------------------------------------ T03 duplicates / races (AUTONOMY)


def test_t03_duplicate_ticks_and_resubmission_do_not_duplicate_effects(root):
    _, project, principal, job = _job(root)
    first = run_tick(worker_id="w1", handlers=HANDLERS, job_id=job["job_id"])
    second = run_tick(worker_id="w2", handlers=HANDLERS, job_id=job["job_id"])
    assert first.outcome == "COMMITTED" and second.outcome == "NO_WORK"
    intents = store.list_intents(job["job_id"])
    assert [i["status"] for i in intents] == ["COMMITTED"]
    head = get_artifact(HANDLERS["visual_render"].target(job))
    assert head["version"] == 1 and head["content_hash"] == first.telemetry["artifact_hash"]
    # Resubmitting the same mission/key returns the same job; changing the spec under that key is refused.
    again = submit_visual_job(principal, project, _mark(), artifact_key="mark", mission_id=job["spec"]["mission_id"],
                              export_root=root)
    assert again["job_id"] == job["job_id"] and again["state"] == "WAITING_APPROVAL"
    with pytest.raises(ValueError, match="different spec"):
        submit_visual_job(principal, project, _mark(seed=9), artifact_key="mark", mission_id=job["spec"]["mission_id"],
                          export_root=root)


def test_t03_concurrent_claim_loses_and_stale_fence_cannot_write(root):
    _, _, _, job = _job(root)
    now = datetime.now(timezone.utc)
    a, _ = store.claim_due_job(worker_id="A", now=now, lease_seconds=60, job_id=job["job_id"])
    assert store.claim_due_job(worker_id="B", now=now, lease_seconds=60, job_id=job["job_id"]) is None
    later = now + timedelta(seconds=120)  # A's lease expired: B may claim, but only into RECONCILING
    b, entered = store.claim_due_job(worker_id="B", now=later, lease_seconds=60, job_id=job["job_id"])
    assert entered is RunState.RECONCILING and b["lease_token"] == a["lease_token"] + 1
    with pytest.raises(store.StaleFence):
        store.transition(a, RunState.PRECHECK, fencing_token=a["lease_token"], now=later)
    with pytest.raises(store.StaleFence):
        store.commit_intent(key="nope", receipt={}, fencing_token=a["lease_token"], job_id=job["job_id"], now=later)


def test_idempotency_key_is_stable_and_scope_sensitive():
    base = dict(tenant="t", project="p", job="j", logical_tick=1, operation="visual.render", target="a", input_hash="h",
                contract_version="v1")
    assert idempotency_key(**base) == idempotency_key(**base)
    for field, value in (("tenant", "t2"), ("project", "p2"), ("logical_tick", 2), ("input_hash", "h2"),
                         ("contract_version", "v2")):
        assert idempotency_key(**{**base, field: value}) != idempotency_key(**base)


# ------------------------------------------------------------------ T04 isolation (CONTEXT)


def test_t04_cross_tenant_and_cross_project_blocked(root):
    tenant_a, tenant_b = _tenant(), _tenant()
    project_a, project_b = _project(tenant_a, root, "Alpha"), _project(tenant_b, root, "Beta")
    with pytest.raises(PermissionError):
        submit_visual_job(_principal(tenant_b, project_a), project_a, _mark(), artifact_key="m", mission_id="x", export_root=root)
    with pytest.raises(PermissionError):
        submit_visual_job(_principal(tenant_a, project_b), project_a, _mark(), artifact_key="m", mission_id="x", export_root=root)
    job = submit_visual_job(_principal(tenant_a, project_a), project_a, _mark(), artifact_key="m", mission_id="x",
                            export_root=root, due_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    # A tick scoped to project B never touches A's job; telemetry stays per project.
    assert run_tick(worker_id="w", handlers=HANDLERS, project_id=project_b).outcome == "NO_WORK"
    assert run_tick(worker_id="w", handlers=HANDLERS, job_id=job["job_id"]).outcome == "COMMITTED"
    assert store.list_project_ticks(project_b) == []
    assert {t["project_id"] for t in store.list_project_ticks(project_a)} == {project_a}
    # An artifact from project A cannot be released under project B.
    target = HANDLERS["visual_render"].target(job)
    head = get_artifact(target)
    verdict = artifact_release_verdict(simulated=False, verification_passed=True, artifact_id=target,
                                       verified_version=head["version"], verified_hash=head["content_hash"],
                                       approval_id=None, tenant_id=tenant_b, project_id=project_b)
    assert not verdict.allowed and "CROSS_PROJECT_ARTIFACT" in verdict.reasons


def test_t04_principal_losing_access_blocks_at_precheck(root):
    tenant = _tenant()
    project = _project(tenant, root)
    job = submit_visual_job(_principal(tenant, project), project, _mark(), artifact_key="m", mission_id="x",
                            export_root=root, due_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    from services.langgraph.persistence.database import transaction, table

    narrowed = {**job["spec"], "principal": {**job["spec"]["principal"], "allowed_project_ids": ["prj-elsewhere"]}}
    with transaction(write=True) as db:
        db.execute(f"UPDATE {table('durable_jobs')} SET spec = ? WHERE job_id = ?", (json.dumps(narrowed), job["job_id"]))
    report = run_tick(worker_id="w", handlers=HANDLERS, job_id=job["job_id"])
    assert report.final_state == "BLOCKED_AUTHORITY" and "PRINCIPAL_LOST_PROJECT_ACCESS" in report.reasons
    assert store.list_intents(job["job_id"]) == [] and get_artifact(HANDLERS["visual_render"].target(job)) is None


# ------------------------------------------------------------------ T05 simulation


def test_t05_simulation_cannot_release(root):
    _, project, principal, job = _job(root)
    run_tick(worker_id="w", handlers=HANDLERS, job_id=job["job_id"])
    head = get_artifact(HANDLERS["visual_render"].target(job))
    verdict = artifact_release_verdict(simulated=True, verification_passed=True, artifact_id=head["artifact_id"],
                                       verified_version=head["version"], verified_hash=head["content_hash"],
                                       approval_id=store.get_job(job["job_id"])["result"]["approval_id"],
                                       tenant_id=principal.tenant_id, project_id=project)
    assert not verdict.allowed and "SIMULATION_NOT_RELEASABLE" in verdict.reasons
    sim = governance.decide("release.internal", authenticated=True, project_access=True, simulation=True,
                            approval_current=True)
    assert not sim.allowed and "SIMULATION_HAS_NO_EFFECTS" in sim.reasons


# ------------------------------------------------------------------ T06 missing providers (FAILURE)


def test_t06_missing_provider_is_a_truthful_blocker(root, monkeypatch, tmp_path):
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "model_index.json").write_text("{}")
    monkeypatch.setenv(caps_mod.DIFFUSION_MODEL_DIR_ENV, str(model_dir))
    diffusion = caps_mod.probe_diffusion()
    assert diffusion.status is CapabilityStatus.BLOCKED_LOCAL_MODEL
    assert any(b.startswith("NO_LICENSE_RECORD") for b in diffusion.blockers)
    concept = VisualIntent(category="concept_image", exactness="approximate", palette=PALETTE)
    decision = route(concept, {**caps_mod.probe_all(), Route.OFFLINE_DIFFUSION: diffusion})
    assert decision.status == "BLOCKED" and decision.route is None
    assert all(r.startswith("R2_OFFLINE_DIFFUSION:") for r in decision.reasons)
    # No substitution: a different route is not picked, and nothing is persisted.
    tenant = _tenant()
    project = _project(tenant, root)
    result = engine.produce(_principal(tenant, project), project, concept, work_dir=root / "w", artifact_key="c",
                            export_root=root, capabilities={Route.OFFLINE_DIFFUSION: diffusion})
    assert result.status == "BLOCKED" and result.artifact_id is None
    # Through the durable runtime the same gap is a BLOCKED_PROVIDER state with no write intent.
    job = submit_visual_job(_principal(tenant, project), project, concept, artifact_key="c", mission_id="x",
                            export_root=root, due_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    report = run_tick(worker_id="w", handlers=HANDLERS, job_id=job["job_id"])
    assert report.final_state == "BLOCKED_PROVIDER" and store.list_intents(job["job_id"]) == []


def test_t06_three_js_route_reports_its_real_dependency_state():
    three = caps_mod.probe_three()
    installed = (ROOT / "apps" / "web" / "node_modules" / "three" / "package.json").is_file()
    assert three.available is installed
    if not installed:
        assert three.status is CapabilityStatus.MISSING_DEPENDENCIES
        decision = route(VisualIntent(category="interactive_scene", interactivity=True, palette=PALETTE),
                         {Route.THREE_JS: three})
        assert decision.status == "BLOCKED"


# ------------------------------------------------------------------ T07/T09/T12 real local renders


@pytest.mark.skipif(not HAS_BPY, reason="NOT_RUN: bpy (Blender as a Python module) is not installed on this host")
def test_t07_t09_local_cycles_render_is_persisted_and_passes_technical_checks(root):
    tenant = _tenant()
    project = _project(tenant, root)
    intent = VisualIntent(category="product_still", width=160, height=200, samples=8, palette=PALETTE)
    result = engine.produce(_principal(tenant, project), project, intent, work_dir=root / "w", artifact_key="still",
                            export_root=root)
    assert result.status == "PRODUCED", result.reasons
    receipt = result.receipts[0]
    assert receipt.route is Route.BLENDER_CYCLES and receipt.exit_code == 0 and receipt.genome.renderer == "blender_cycles"
    v = result.verification
    assert v.status == "PASSED" and v.highest_passed is QualityLevel.Q4_RIGHTS and v.mime_type == "image/png"
    stored = LocalStorageAdapter(root).get_bytes(get_artifact(result.artifact_id)["content_location"])
    assert hashlib.sha256(stored).hexdigest() == result.content_hash == v.content_hash


@pytest.mark.skipif(not (HAS_BPY and HAS_FFMPEG), reason="NOT_RUN: needs bpy and ffmpeg/ffprobe")
def test_t12_video_contains_actual_probed_frames(root):
    tenant = _tenant()
    project = _project(tenant, root)
    intent = VisualIntent(category="product_turntable", output="video", width=96, height=96, frames=4, fps=12, samples=4,
                          palette=PALETTE)
    result = engine.produce(_principal(tenant, project), project, intent, work_dir=root / "w", artifact_key="spin",
                            export_root=root)
    assert result.status == "PRODUCED", result.reasons
    probe = {c["check"]: c for c in result.verification.checks}
    assert probe["dims_fps_frames_codec"]["passed"] and "4f h264 vs" in probe["dims_fps_frames_codec"]["detail"]
    assert [r.route for r in result.receipts] == [Route.BLENDER_CYCLES, Route.LOCAL_VIDEO]


# ------------------------------------------------------------------ T08 offline


@pytest.mark.skipif(not network_namespace_available(), reason="NOT_RUN: unshare -rn is unavailable on this host")
def test_t08_isolated_renderer_process_cannot_reach_the_network():
    from services.langgraph.agency.visual.renderers import _env, _isolated

    code = ("import socket,sys\ns=socket.socket()\ns.settimeout(3)\n"
            "try:\n s.connect(('1.1.1.1',443)); print('CONNECTED')\nexcept OSError as e:\n print('BLOCKED', e.errno)")
    cmd, isolated = _isolated([sys.executable, "-I", "-c", code])
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=_env())
    assert isolated and out.stdout.startswith("BLOCKED"), out.stdout + out.stderr
    env = _env({})
    assert not any(k.lower().endswith("_proxy") and k.lower() != "no_proxy" for k in env)
    assert env["HF_HUB_OFFLINE"] == "1"


# ------------------------------------------------------------------ T10/T11 Three.js architecture and browser


def test_t10_three_renderer_chosen_by_actual_shader_architecture():
    assert three_renderer_for({"tsl", "node_material"})["renderer"] == "WebGPURenderer"
    assert three_renderer_for({"shader_material", "effect_composer"})["renderer"] == "WebGLRenderer"
    assert three_renderer_for({"standard_material"})["renderer"] == "WebGLRenderer"
    mixed = three_renderer_for({"tsl", "on_before_compile"})
    assert mixed["status"] == "BLOCKED" and "MIXED_SHADER_ARCHITECTURE" in mixed["reasons"][0]
    assert three_renderer_for({"mystery"})["status"] == "BLOCKED"


@pytest.mark.skipif(not HAS_BROWSER, reason="NOT_RUN: node, Chromium or @playwright/test missing")
def test_t11_browser_executes_shaders_handles_context_loss_and_renders_svg_sizes(tmp_path):
    from services.langgraph.agency.visual.browser import capture_svg_sizes, capture_webgl
    from services.langgraph.agency.assets import render_logo_svg

    good = capture_webgl(
        vertex="attribute vec2 position; void main(){ gl_Position = vec4(position,0.0,1.0); }",
        fragment=("precision mediump float; uniform vec2 resolution; uniform vec3 primary;"
                  "void main(){ vec2 uv = gl_FragCoord.xy/resolution; gl_FragColor = vec4(primary*uv.x + uv.y*0.5, 1.0); }"),
        width=96, height=64, uniforms={"primary": [0.36, 0.1, 0.13]}, out_dir=tmp_path / "gl")
    assert good["status"] == "PASSED", good["findings"]
    assert Path(good["capture"]).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" and good["result"]["blocked_requests"] == []
    broken = capture_webgl(vertex="attribute vec2 position; void main(){ gl_Position = vec4(position,0.0,1.0); }",
                           fragment="precision mediump float; void main(){ gl_FragColor = undefined_symbol; }",
                           width=32, height=32, out_dir=tmp_path / "bad")
    assert broken["status"] == "FAILED" and "SHADER_COMPILE_FAILED" in broken["findings"]
    svg = render_logo_svg(brand_name="Maison Velune", primary=PALETTE["primary"], secondary=PALETTE["secondary"],
                          surface=PALETTE["surface"])
    sizes = capture_svg_sizes(svg, sizes=(32, 256), out_dir=tmp_path / "svg")
    assert sizes["status"] == "PASSED" and len(sizes["captures"]) == 2
    verdict = verify_media(svg.encode(), mime_type="image/svg+xml",
                           expect={"palette": list(PALETTE.values()), "render_sizes": (48,)})
    assert verdict.status == "PASSED" and any(c["check"] == "multi_size_render" and c["passed"] for c in verdict.checks)


def test_multi_size_check_that_cannot_run_is_inconclusive_not_passed(monkeypatch):
    from services.langgraph.agency.visual import browser
    from services.langgraph.agency.assets import render_logo_svg

    monkeypatch.setattr(browser, "probe_browser", lambda: {"available": False, "blockers": ["MISSING_DEPENDENCY:chromium"]})
    svg = render_logo_svg(brand_name="V", primary=PALETTE["primary"], secondary=PALETTE["secondary"], surface=PALETTE["surface"])
    v = verify_media(svg.encode(), mime_type="image/svg+xml", expect={"palette": list(PALETTE.values()), "render_sizes": (32,)})
    assert v.status == "INCONCLUSIVE" and "MULTI_SIZE_RENDER_NOT_RUN" in v.findings


# ------------------------------------------------------------------ T13/T14 proof (PROOF)


def test_t13_corrupt_or_stale_bytes_invalidate_verification(root):
    _, project, principal, job = _job(root)
    run_tick(worker_id="w", handlers=HANDLERS, job_id=job["job_id"])
    head = get_artifact(HANDLERS["visual_render"].target(job))
    adapter = LocalStorageAdapter(root)
    data = adapter.get_bytes(head["content_location"])
    tampered = verify_media(data.replace(b"<rect", b"<script/><rect", 1), mime_type="image/svg+xml",
                            expect={"palette": list(PALETTE.values())}, recorded_hash=head["content_hash"])
    assert tampered.status == "FAILED" and "CONTENT_HASH_MISMATCH" in tampered.findings
    garbage = verify_media(b"\x89PNG\r\n\x1a\nnot really", mime_type="image/png", expect={"width": 64, "height": 64})
    if HAS_PIL:
        blank_png = verify_media(_flat_png(), mime_type="image/png", expect={"width": 64, "height": 64})
        assert blank_png.status == "FAILED" and blank_png.highest_passed is QualityLevel.Q2_DIMENSIONS_FORMAT
        assert garbage.status == "FAILED" and garbage.highest_passed is QualityLevel.Q0_VALID_FILE
    else:  # without a decoder the PNG cannot be judged either way, and is never PASSED
        assert garbage.status == "INCONCLUSIVE" and "PNG_DECODE_NOT_RUN" in garbage.findings
    unknown = verify_media(b"%PDF-1.7", mime_type="application/pdf", expect={})
    assert unknown.status == "INCONCLUSIVE"
    off_palette = verify_media(data.replace(PALETTE["primary"].encode(), b"#00ff00"), mime_type="image/svg+xml",
                               expect={"palette": list(PALETTE.values())})
    assert off_palette.status == "FAILED"
    # A verification of the old head is stale once the head moves.
    revise_project_artifact(project_id=project, artifact_id=head["artifact_id"], actor="mallory", adapter=adapter,
                            expected_version=head["version"], content_text="<svg xmlns='http://www.w3.org/2000/svg'/>")
    verdict = artifact_release_verdict(simulated=False, verification_passed=True, artifact_id=head["artifact_id"],
                                       verified_version=head["version"], verified_hash=head["content_hash"],
                                       approval_id=store.get_job(job["job_id"])["result"]["approval_id"],
                                       tenant_id=principal.tenant_id, project_id=project)
    assert not verdict.allowed and any(r.startswith("VERIFICATION_STALE") for r in verdict.reasons)


def _flat_png() -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (236, 230, 218)).save(buf, format="PNG")
    return buf.getvalue()


def test_t14_modified_artifact_invalidates_old_approval_and_release_needs_another_human(root, monkeypatch):
    tenant, project, principal, job = _job(root)
    run_tick(worker_id="w", handlers=HANDLERS, job_id=job["job_id"])
    committed = store.get_job(job["job_id"])
    approval_id = committed["result"]["approval_id"]
    head = get_artifact(HANDLERS["visual_render"].target(job))
    assert get_approval(approval_id)["subject_hash"] == head["content_hash"]

    def verdict(h=head):
        return artifact_release_verdict(simulated=False, verification_passed=True, artifact_id=h["artifact_id"],
                                        verified_version=h["version"], verified_hash=h["content_hash"],
                                        approval_id=approval_id, tenant_id=tenant, project_id=project)

    assert "APPROVAL_PENDING" in verdict().reasons
    as_user(monkeypatch, "alice", tenant=tenant, projects=project)  # the initiator cannot approve
    assert client.post(f"/approvals/{approval_id}/decide", json={"decision": "approve"}, headers=headers()).status_code == 403
    as_user(monkeypatch, "bob", tenant=tenant, projects=project)
    assert client.post(f"/approvals/{approval_id}/decide", json={"decision": "approve"}, headers=headers()).status_code == 200
    assert verdict().allowed and verdict().external_effects == "none"
    settled = settle_waiting_approval(job["job_id"])
    assert settled["state"] == "DORMANT" and settled["approval_outcome"] == "approve"

    # New bytes: the old approval no longer releases the new head, and the old verification is stale.
    adapter = LocalStorageAdapter(root)
    revise_project_artifact(project_id=project, artifact_id=head["artifact_id"], actor="alice", adapter=adapter,
                            expected_version=head["version"], content_text=adapter.get_bytes(head["content_location"]).decode()
                            .replace(PALETTE["secondary"], PALETTE["primary"]))
    new_head = get_artifact(head["artifact_id"])
    after = verdict(new_head)
    assert not after.allowed and "SUBJECT_HASH_MISMATCH" in after.reasons


# ------------------------------------------------------------------ T15 external effects (CONFLICT/FAILURE)


def test_t15_publish_spend_send_never_dispatched():
    for action in ("publish", "send", "deploy", "spend", "purchase", "delete.production", "unlisted.thing"):
        d = governance.decide(action, authenticated=True, project_access=True, approval_current=True)
        assert not d.allowed and not d.dispatched and d.level in {governance.Level.G3, governance.Level.G4}
    assert governance.level_of("unlisted.thing") is governance.Level.G4
    from services.langgraph.integrations.paid_media import spend_execution_available

    assert spend_execution_available() is False
    assert all(governance.resolve_enforcers().values())
    assert governance.decide("render.local", authenticated=True, project_access=True).allowed
    assert not governance.decide("render.local", authenticated=True, project_access=False).allowed


# ------------------------------------------------------------------ T16 crash recovery (AUTONOMY)


def test_t16_crash_after_dispatch_is_reconciled_by_adoption_not_redispatch(root):
    _, _, _, job = _job(root)

    def crash(point):
        if point == "after_dispatch":
            raise RuntimeError("worker killed after the render was persisted")

    with pytest.raises(RuntimeError):
        run_tick(worker_id="A", handlers=HANDLERS, job_id=job["job_id"], hook=crash, lease_seconds=60)
    crashed = store.get_job(job["job_id"])
    assert crashed["state"] == "RUNNING" and [i["status"] for i in store.list_intents(job["job_id"])] == ["INTENT"]
    target = HANDLERS["visual_render"].target(job)
    assert get_artifact(target)["version"] == 1

    later = datetime.now(timezone.utc) + timedelta(seconds=120)
    report = run_tick(worker_id="B", handlers=HANDLERS, job_id=job["job_id"], now=later)
    assert report.adopted and not report.dispatched and report.final_state == "WAITING_APPROVAL", report.reasons
    assert get_artifact(target)["version"] == 1  # adopted, not rendered again
    assert [i["status"] for i in store.list_intents(job["job_id"])] == ["COMMITTED"]
    assert ("RUNNING", "RECONCILING") in _states(job["job_id"]) and ("RECONCILING", "OBSERVING") in _states(job["job_id"])


def test_t16_crash_before_any_effect_redoes_under_the_same_intent(root):
    _, _, _, job = _job(root)

    def crash(point):
        if point == "after_intent":
            raise RuntimeError("worker killed before dispatch")

    with pytest.raises(RuntimeError):
        run_tick(worker_id="A", handlers=HANDLERS, job_id=job["job_id"], hook=crash, lease_seconds=60)
    target = HANDLERS["visual_render"].target(job)
    assert get_artifact(target) is None
    report = run_tick(worker_id="B", handlers=HANDLERS, job_id=job["job_id"],
                      now=datetime.now(timezone.utc) + timedelta(seconds=120))
    assert report.dispatched and not report.adopted and report.final_state == "WAITING_APPROVAL"
    assert len(store.list_intents(job["job_id"])) == 1 and get_artifact(target)["version"] == 1


def test_repeated_identical_failure_dead_letters_via_negative_knowledge(root, monkeypatch):
    _, _, _, job = _job(root)
    handler = HANDLERS["visual_render"]
    monkeypatch.setattr(type(handler), "dispatch", lambda self, j: (_ for _ in ()).throw(OSError("disk full")))
    first = run_tick(worker_id="w", handlers=HANDLERS, job_id=job["job_id"])
    assert first.final_state == "RETRY_PENDING"
    second = run_tick(worker_id="w", handlers=HANDLERS, job_id=job["job_id"],
                      now=datetime.now(timezone.utc) + timedelta(seconds=60))
    assert second.final_state == "DEAD_LETTER" and any("NEGATIVE_KNOWLEDGE" in r for r in second.reasons)
    registry = capability_registry(caps_mod.probe_all(), store.jobs_for_project(job["project_id"]))
    assert registry["job_kinds"]["visual_render"]["circuit"] == "OPEN"
    # The operator path back out is explicit and logged; a dead letter cannot jump straight to running.
    with pytest.raises(IllegalTransition):
        store.operator_move(job["job_id"], RunState.SCHEDULED, actor="ops", reason="fixed disk")
    store.operator_move(job["job_id"], RunState.PAUSED, actor="ops", reason="investigating")
    resumed = store.operator_move(job["job_id"], RunState.SCHEDULED, actor="ops", reason="fixed disk")
    assert resumed["state"] == "SCHEDULED" and _states(job["job_id"])[-1] == ("PAUSED", "SCHEDULED")


# ------------------------------------------------------------------ T17 rights


def test_t17_unknown_rights_block_production(root):
    tenant = _tenant()
    project = _project(tenant, root)
    asset = SourceAsset(ref="textures/linen.jpg", sha256="a" * 64)
    intent = VisualIntent(category="product_still", palette=PALETTE, source_assets=(asset,))
    decision = route(intent, caps_mod.probe_all())
    assert decision.status == "BLOCKED" and decision.reasons == ("RIGHTS_UNVERIFIED:textures/linen.jpg",)
    job = submit_visual_job(_principal(tenant, project), project, intent, artifact_key="still", mission_id="x",
                            export_root=root, due_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    report = run_tick(worker_id="w", handlers=HANDLERS, job_id=job["job_id"])
    assert report.final_state == "BLOCKED_AUTHORITY" and store.list_intents(job["job_id"]) == []
    svg = b"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10'><rect width='10' height='10' fill='#5b1a22'/></svg>"
    unlicensed = verify_media(svg, mime_type="image/svg+xml", expect={}, source_assets=(asset,))
    assert unlicensed.status == "FAILED" and "RIGHTS_UNVERIFIED:textures/linen.jpg" in unlicensed.findings
    licensed = SourceAsset(ref="textures/linen.jpg", sha256="a" * 64, license="CC0-1.0")
    assert verify_media(svg, mime_type="image/svg+xml", expect={}, source_assets=(licensed,)).highest_passed is QualityLevel.Q4_RIGHTS


def test_q5_to_q7_are_never_machine_passed(root):
    _, _, _, job = _job(root)
    run_tick(worker_id="w", handlers=HANDLERS, job_id=job["job_id"])
    receipt = store.list_intents(job["job_id"])[0]["receipt"]
    verification = receipt["observation"]["verification"]
    assert set(verification["human_required"]) == {q.value for q in HUMAN_LEVELS}
    assert verification["highest_passed"] == QualityLevel.Q4_RIGHTS.value
    assert not any(c["level"] in {q.value for q in HUMAN_LEVELS} for c in verification["checks"])


# ------------------------------------------------------------------ T18 observability


def test_t18_telemetry_matches_actual_operations(root):
    _, project, _, job = _job(root)
    report = run_tick(worker_id="w", handlers=HANDLERS, job_id=job["job_id"])
    ticks = store.list_ticks(job["job_id"])
    assert len(ticks) == 1 and ticks[0]["trace_id"] == report.trace_id
    tel = ticks[0]["telemetry"]
    head = get_artifact(HANDLERS["visual_render"].target(job))
    assert tel["artifact_hash"] == head["content_hash"] and tel["verification_state"] == "PASSED"
    assert tel["final_state"] == store.get_job(job["job_id"])["state"] and tel["checkpoint_version"] == store.get_job(job["job_id"])["version"]
    assert tel["observed_cost"] == "NOT_MEASURED" and tel["resource_usage"]["gpu_memory"] == "NOT_MEASURED"
    traced = [t for t in store.list_transitions(job["job_id"]) if t["trace_id"] == report.trace_id]
    assert len(traced) == len(HAPPY_PATH) - 2  # every move after the claim carries the tick's trace id
    m = project_metrics(project)
    assert m["working_ticks"] == 1 and m["intents"] == {"committed": 1, "open": 0} and m["verification"]["passed"] == 1
    assert m["percentile_comparison"] == "BASELINE_UNKNOWN" and m["cost_per_verified_artifact"] == "NOT_MEASURED"
    docs = spans(ticks)
    assert docs[0]["attributes"]["artifact_hash"] == head["content_hash"]
    forbidden = {"spec", "prompt", "principal", "palette"}
    assert not forbidden & set(docs[0]["attributes"])
    assert metrics(ticks=[], transitions=[], intents=[])["retry_rate"] is None


# ------------------------------------------------------------------ T19/T20 repository and seal


def test_t19_domain_stages_preserved():
    from services.langgraph.agency.delivery.workflow import LEGACY_WORKFLOW, topology

    assert topology(LEGACY_WORKFLOW)["node_ids"] == [
        "brief_intake", "brand_strategy", "creative_concepting", "copywriting", "design_brief", "campaign_assembly",
        "brand_safety_qa", "hitl_gate", "delivery"]


def test_t19_abc_manifests_match_code():
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "compile_abc_manifests.py"), "--check"],
                         capture_output=True, text=True, cwd=ROOT)
    assert out.returncode == 0, out.stderr


def test_t20_seal_never_counts_not_run_as_passed(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import seal_abc_build as seal
    finally:
        sys.path.pop(0)
    results = {"cmd:pytest_abc": {"verdict": "PASSED", "exit_code": 0}, "cmd:ruff": {"verdict": "FAILED", "exit_code": 1}}
    evidence = seal.evidence_states(results, files={})
    assert evidence["cmd:pytest_full"] == "NOT_RUN" and evidence["cmd:ruff"] == "FAILED"
    statuses = seal.node_statuses(evidence)
    assert statuses["A09_TEST"] == "FAILED" and statuses["A00_DISCOVER"] == "NOT_RUN"
    doc = seal.compose(commit="0" * 40, command_results=results, evidence=evidence, blockers=["x"], sample_hashes={})
    assert doc["final_status"] != "IMPLEMENTED_VERIFIED"
    assert doc["predicates"]["ReleaseEligible"] is False and doc["predicates"]["RuntimeActive"] is False
    assert doc["signature_status"] == "UNSIGNED"


# ------------------------------------------------------------------ genome (CONTEXT / CONFLICT / REUSE)


def _genome(**kw):
    base = dict(mission_id="m", tenant_id="t", project_resolution={"status": "BOUND", "project_id": "p"}, objective="o",
                audience="a", deliverables=({"id": "still", "capability": "R1"},),
                predicates=(Predicate(predicate_id="P1", description="readback", verifier="media.readback"),),
                capabilities={"R1": "VERIFIED_AVAILABLE"}, now=datetime(2026, 10, 9, tzinfo=timezone.utc))
    return compile_genome(**{**base, **kw})


def test_genome_admission_rules():
    assert _genome().status == "READY"
    assert _genome(project_resolution={"status": "AMBIGUOUS"}).status == "PROJECT_AMBIGUOUS"
    assert _genome(project_resolution={"status": "AMBIGUOUS"}).project_id is None
    g = _genome(unknowns=(Unknown(key="audience_age", critical=True), Unknown(key="tone", critical=False, default="calm")))
    assert g.status == "HUMAN_INPUT_REQUIRED" and g.blockers == ("CRITICAL_UNKNOWN:audience_age",)
    assert _genome(unknowns=(Unknown(key="tone", critical=False, default="calm"),)).assumptions == (
        {"key": "tone", "value": "calm", "type": "ASSUMED"},)
    conflict = _genome(constraints=(Constraint(key="width", op="min", value=2000), Constraint(key="width", op="max", value=1200)))
    assert conflict.status == "CONFLICT_BLOCKED" and "min 2000 exceeds max 1200" in conflict.conflicts[0]
    assert _genome(constraints=(Constraint(key="logo", op="requires", value="wordmark"),
                                Constraint(key="logo", op="forbids", value="wordmark"))).status == "CONFLICT_BLOCKED"
    stale = _genome(sources=(SourceEvidence(ref="brief.pdf", retrieved_at="2026-01-01T00:00:00+00:00",
                                            fresh_until="2026-02-01T00:00:00+00:00"),))
    assert stale.status == "REFRESH_REQUIRED"
    assert _genome(capabilities={"R1": "BLOCKED_ENVIRONMENT"}).status == "CAPABILITY_BLOCKED"
    with pytest.raises(ValueError, match="no registered verifier"):
        _genome(predicates=(Predicate(predicate_id="P", description="trust me", verifier="self_report"),))
    assert _genome().genome_hash == _genome().genome_hash


def test_proof_debt_and_minimal_proof_set():
    preds = (Predicate(predicate_id="A", description="", verifier="media.readback"),
             Predicate(predicate_id="B", description="", verifier="human.review", depends_on=("A",)),
             Predicate(predicate_id="C", description="", verifier="tests.pytest", severity="minor"))
    debt = proof_debt(preds, {"C": "VERIFIED"})
    assert [d["predicate_id"] for d in debt] == ["A", "B"] and debt[0]["blocks"] == 1
    records = [EvidenceRecord("e1", "media.readback", "h", frozenset({"A"}), {"intent": "1"}),
               EvidenceRecord("e2", "human.review", "h", frozenset({"B"})),
               EvidenceRecord("e3", "bundle", "h", frozenset({"A", "B"}), {"intent": "1"}),
               EvidenceRecord("e4", "never", "h", frozenset({"C"}), state="NOT_RUN")]
    best = minimal_proof_set({"A", "B"}, records)
    assert best == {"complete": True, "evidence": ["e3"], "missing": [], "method": "exact"}
    assert minimal_proof_set({"C"}, records)["complete"] is False
    ok, why = evidence_valid(records[0], current_subject_hash="h", current_versions={"intent": "2"})
    assert not ok and why == ["DEPENDENCY_CHANGED:intent"]
    assert evidence_valid(records[0], current_subject_hash="h2", current_versions={"intent": "1"})[1] == ["SUBJECT_HASH_CHANGED"]
    assert invalidated_by(records, {"intent"}) == ["e1", "e3"]
    graph = proof_graph(requirement="R", execution={"x": 1}, artifact={"a": 1}, readback=None, verification={"v": 1},
                        approval=None, release=None)
    assert [g["present"] for g in graph] == [True, True, True, False, False, False, False]


def test_capability_registry_reflects_probed_versions():
    reg = capability_registry({Route.VECTOR: Capability(route=Route.VECTOR, status=CapabilityStatus.VERIFIED_AVAILABLE,
                                                         version="x", detail="d")}, [])
    assert reg["adapters"]["R4_VECTOR"]["status"] == "VERIFIED_AVAILABLE" and reg["baseline"].startswith("BASELINE_UNKNOWN")
