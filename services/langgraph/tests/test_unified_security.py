"""Regression tests for isolation, exact approvals and non-vacuous Python checks."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from services.langgraph.agency.execution_fabric.adapters import code_sandbox
from services.langgraph.agency.intake.release import artifact_release_verdict, open_artifact_approval
from services.langgraph.agency.project_os.storage import LocalStorageAdapter
from services.langgraph.agency.ucpo.sandbox import REPO_ROOT, probe_isolation, wrap
from services.langgraph.persistence.projects import create_project_artifact, create_project_workspace, revise_project_artifact
from services.langgraph.security.auth import Principal
from services.langgraph.tests._project_os_support import as_user, client, headers


def test_ucpo_chroot_hides_host_canaries_and_drops_capabilities(tmp_path):
    iso = probe_isolation()
    if not iso.available:
        pytest.skip(f"NOT_RUN: isolation unavailable: {iso.reasons}")
    host = tmp_path / "host-canary"
    host.write_text("synthetic host canary", encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    script = """
const fs = require('fs');
const status = fs.readFileSync('/proc/self/status', 'utf8');
const safe = p => { try { fs.readFileSync(p); return false; } catch { return true; } };
console.log(JSON.stringify({hidden: safe(process.argv[1]), repoHidden: safe(process.argv[2]),
  procHidden: safe('/proc/1/root' + process.argv[1]),
  caps: status.match(/^CapEff:\\s*(\\S+)/m)[1], nnp: status.match(/^NoNewPrivs:\\s*(\\S+)/m)[1]}));
"""
    argv = wrap([iso.node, "-e", script, str(host), str(REPO_ROOT / "README.md")],
                cwd=work, home=work, node=iso.node, timeout_s=15)
    result = subprocess.run(argv, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    assert observed == {"hidden": True, "repoHidden": True, "procHidden": True,
                        "caps": "0000000000000000", "nnp": "1"}
    assert iso.facts["network_probe_exit"] == 3
    assert host.read_text() == "synthetic host canary"


def test_sandbox_refuses_network_opt_in(tmp_path):
    with pytest.raises(ValueError, match="network-enabled"):
        wrap(["true"], cwd=tmp_path, home=tmp_path, node="/usr/local/bin/node", timeout_s=1, network=True)


def test_python_validator_refuses_empty_noop_or_unchecked_patches():
    if not code_sandbox.network_namespace_available() or not code_sandbox.mount_namespace_available():
        pytest.skip("NOT_RUN: validator namespaces unavailable")
    cases = [
        ({"a.py": "x=1\n"}, {}, [["py_compile", "a.py"]], "EMPTY_PATCH"),
        ({"a.py": "x=1\n"}, {"a.py": "x=1\n"}, [["py_compile", "a.py"]], "EMPTY_PATCH"),
        ({}, {"a.py": "x=2\n"}, [], "EMPTY_CHECKS"),
        ({}, {"a.py": "x=2\n", "b.py": "y=3\n"}, [["py_compile", "a.py"]], "UNCHECKED_PATCH"),
    ]
    for base, patch, checks, code in cases:
        with pytest.raises(code_sandbox.SandboxViolation) as exc:
            code_sandbox.run_patch(base, patch, checks)
        assert exc.value.code == code


def test_same_bytes_do_not_transfer_approval_between_artifacts_or_versions(tmp_path, monkeypatch):
    tenant, project = "tenant-security-" + uuid4().hex[:8], "prj-security-" + uuid4().hex[:8]
    adapter = LocalStorageAdapter(tmp_path)
    create_project_workspace(tenant_id=tenant, project_id=project, actor="alice", display_name="security fixture", export_root=tmp_path)
    alice = Principal("alice", tenant, "admin", frozenset({project}))
    items = [create_project_artifact(tenant_id=tenant, project_id=project, actor="alice", artifact_key=key,
                                     artifact_type="product_spec", adapter=adapter, content_text="same bytes")
             for key in ("first", "second")]
    def open_for(item):
        return open_artifact_approval(alice, tenant_id=tenant, project_id=project, mission_id=project + ":same-mission",
            contract_hash="contract", artifact_id=item.artifact_id, version=item.version, content_hash=item.content_hash,
            run_pipeline="test", policy_version="test-policy", subject_type="TEST_ARTIFACT", reason="Review this exact artifact")
    first, second = map(open_for, items)
    assert first["approval_id"] != second["approval_id"]
    as_user(monkeypatch, "bob", tenant=tenant, projects=project)
    decision = client.post(f"/approvals/{first['approval_id']}/decide", json={"decision": "approve"}, headers=headers())
    assert decision.status_code == 200, decision.text
    def verdict(item, approval):
        return artifact_release_verdict(simulated=False, verification_passed=True, artifact_id=item.artifact_id,
            verified_version=item.version, verified_hash=item.content_hash, approval_id=approval,
            tenant_id=tenant, project_id=project)
    assert verdict(items[0], first["approval_id"]).allowed
    forged = verdict(items[1], first["approval_id"])
    assert not forged.allowed and "SUBJECT_REF_MISMATCH" in forged.reasons
    revised = revise_project_artifact(project_id=project, artifact_id=items[0].artifact_id, actor="alice", adapter=adapter,
                                      expected_version=items[0].version, content_text="same bytes")
    after = revised["artifact"]
    result = artifact_release_verdict(simulated=False, verification_passed=True, artifact_id=after.artifact_id,
        verified_version=after.version, verified_hash=after.content_hash, approval_id=first["approval_id"],
        tenant_id=tenant, project_id=project)
    assert not result.allowed and "SUBJECT_VERSION_MISMATCH" in result.reasons


def test_generic_release_rejects_ineligible_website_proof_and_wrong_approval_purpose(tmp_path, monkeypatch):
    """Synthetic approval cannot turn an incomplete proof into website release eligibility."""
    from services.langgraph.agency.ucpo.release import seal_proof

    tenant, project = "tenant-proof-" + uuid4().hex[:8], "prj-proof-" + uuid4().hex[:8]
    monkeypatch.setenv("AMC_EXPORT_ROOT", str(tmp_path))
    monkeypatch.setenv("AMC_OBJECT_STORAGE_BACKEND", "local")
    adapter = LocalStorageAdapter(tmp_path)
    create_project_workspace(tenant_id=tenant, project_id=project, actor="alice", display_name="proof fixture", export_root=tmp_path)
    alice = Principal("alice", tenant, "admin", frozenset({project}))
    proof = seal_proof(project_ref=project, site_id="fixture", revisions={}, artifact_refs={}, build=None, qa=None, coverage=None)
    artifact = create_project_artifact(tenant_id=tenant, project_id=project, actor="alice", artifact_key="foundry-ucpo-fixture-release_proof",
        artifact_type="release_record", subtype="ucpo.release_proof", adapter=adapter,
        content_text=proof.model_dump_json())
    approval = open_artifact_approval(alice, tenant_id=tenant, project_id=project, mission_id=f"{project}:wrong-purpose",
        contract_hash="test", artifact_id=artifact.artifact_id, version=artifact.version, content_hash=artifact.content_hash,
        run_pipeline="test", policy_version="unrelated-policy", subject_type="UNRELATED_SUBJECT", reason="Synthetic test")
    as_user(monkeypatch, "bob", role="reviewer", tenant=tenant, projects=project)
    decision = client.post(f"/approvals/{approval['approval_id']}/decide", json={"decision": "approve"}, headers=headers())
    assert decision.status_code == 200, decision.text
    verdict = artifact_release_verdict(simulated=False, verification_passed=True, artifact_id=artifact.artifact_id,
        verified_version=artifact.version, verified_hash=artifact.content_hash, approval_id=approval["approval_id"],
        tenant_id=tenant, project_id=project)
    assert not verdict.allowed
    assert "PROOF_NOT_ELIGIBLE" in verdict.reasons
    assert any("PROOF_INCOMPLETE" in r for r in verdict.reasons)
    assert "APPROVAL_PURPOSE_MISMATCH" in verdict.reasons


def test_motion_provider_checks_every_frame_and_bounds_work():
    from services.langgraph.agency.vnexus.media_fabric import Capability, LocalMotion, MediaRequest

    good = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="2" height="2"/></svg>'
    unsafe = '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    provider = LocalMotion()
    def issues(frames, width=640, height=360, fps=30):
        request = MediaRequest(capability=Capability.MOTION_MP4, spec={"frames": frames, "fps": fps}, width=width, height=height)
        return provider._validate_spec(request)
    assert not issues([good, good, good])
    assert "SVG_FRAME_INVALID" in issues([good, unsafe, good])
    assert any("every frame must be text" in error for error in issues([good, 7, good]))
    assert "SVG_FRAME_BUDGET_EXCEEDED" in issues([good, good + " " * 128_001])
    assert "FRAME_PIXEL_BUDGET_EXCEEDED" in issues([good] * 900, 1920, 1080)
    assert any("fps" in error for error in issues([good, good], fps=True))


def test_visual_browser_blocks_when_isolation_unavailable(tmp_path, monkeypatch):
    from services.langgraph.agency.ucpo import sandbox
    from services.langgraph.agency.visual import browser

    monkeypatch.setattr(sandbox, "probe_isolation", lambda: sandbox.Isolation(False, ("synthetic unavailable boundary",)))
    monkeypatch.setattr(browser, "chromium_path", lambda: Path("/unused/chromium"))
    def forbidden(*args, **kwargs):
        raise AssertionError("untrusted browser process must not start")
    monkeypatch.setattr(browser.subprocess, "run", forbidden)
    result = browser.rasterize_svg("<svg/>", width=16, height=16, out_dir=tmp_path)
    assert result["status"] == "FAILED"
    assert result["network_isolated"] is False
    assert "synthetic unavailable boundary" in result["stderr_tail"]


def test_visual_browser_never_counts_stale_outputs_as_evidence(tmp_path, monkeypatch):
    from services.langgraph.agency.visual import browser

    (tmp_path / "webgl.png").write_bytes(b"old png")
    (tmp_path / "document.pdf").write_bytes(b"%PDF-old")
    fake = {"exit_code": 0, "wall_ms": 0, "network_isolated": True, "stderr_tail": "",
            "result": {}, "command": [], "output_files": []}
    monkeypatch.setattr(browser, "_run", lambda *args, **kwargs: fake)
    webgl = browser.capture_webgl(vertex="", fragment="", width=1, height=1, out_dir=tmp_path)
    pdf = browser.render_pdf("", width_px=1, height_px=1, out_dir=tmp_path)
    sizes = browser.capture_svg_sizes("<svg/>", sizes=iter([32]), out_dir=tmp_path)
    assert webgl["status"] == "FAILED" and "MISSING_CAPTURE" in webgl["findings"]
    assert pdf["status"] == "FAILED" and "PDF_NOT_WRITTEN" in pdf["findings"]
    assert sizes["status"] == "FAILED" and "MISSING_SIZE_OBSERVATION" in sizes["findings"]
    assert browser._expected_outputs({"mode": "layout", "capture": True},
                                     {"captures": {"bad": "../../elsewhere.png", "ok": "page-ok.png"}}) == {"page-ok.png"}


def test_visual_browser_isolates_client_output_and_blocks_network(tmp_path):
    from services.langgraph.agency.visual import browser

    probe = browser.probe_browser()
    if not probe["available"]:
        pytest.skip(f"NOT_RUN: browser/isolation unavailable: {probe['blockers']}")
    out = tmp_path / "output"
    out.mkdir()
    canary = out / "other-client-canary"
    canary.write_text("synthetic host-only data", encoding="utf-8")
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"><rect width="16" height="16" fill="navy"/></svg>'
    result = browser.rasterize_svg(svg, width=16, height=16, out_dir=out)
    assert result["status"] == "PASSED" and result["network_isolated"]
    assert str(out) not in " ".join(result["command"])
    assert canary.read_text(encoding="utf-8") == "synthetic host-only data"
    html = '<html><body><img src="https://example.com/test.png" alt=""></body></html>'
    remote = browser.run_experience(html, [{"id": "probe", "steps": [{"action": "wait", "value": 200}]}], out_dir=out)
    assert remote["status"] == "FAILED" and "REMOTE_REQUEST_ATTEMPTED" in remote["findings"]


def test_composer_refuses_copy_it_would_silently_truncate():
    from services.langgraph.agency.foundry.compose import _wrap

    copy = "Make the invisible work visible"
    assert " ".join(_wrap(copy, size=30, max_width=180)) == copy
    with pytest.raises(ValueError, match="COPY_EXCEEDS_LAYOUT"):
        _wrap("Many important words must never simply disappear " * 30, size=40, max_width=180)
    with pytest.raises(ValueError, match="COPY_EXCEEDS_LAYOUT"):
        _wrap("extraordinarilylongunbrokenword", size=40, max_width=180)


def test_video_tools_fail_closed_without_isolation_or_verifier(tmp_path, monkeypatch):
    from services.langgraph.agency.ucpo import sandbox
    from services.langgraph.agency.visual import renderers, verify

    monkeypatch.setattr(renderers.shutil, "which", lambda name: "/usr/bin/true" if name == "ffmpeg" else None)
    monkeypatch.setattr(sandbox, "probe_isolation", lambda: sandbox.Isolation(False, ("no boundary",)))
    r = renderers.encode_video([tmp_path / "untrusted.png"], tmp_path / "out.mp4", fps=30)
    assert r.status == "FAILED" and r.reasons[0].startswith("BLOCKED_ISOLATION:")
    assert not (tmp_path / "out.mp4").exists()
    def unavailable(path):
        raise verify.VideoProbeUnavailable("no safe verifier")
    monkeypatch.setattr(verify, "_probe_video", unavailable)
    verdict = verify.verify_media(b"\x00\x00\x00\x18ftypmp42fake", mime_type="video/mp4",
                                  expect={"width": 16, "height": 16, "fps": 1, "frames": 1})
    assert verdict.status == "INCONCLUSIVE" and "FFPROBE_NOT_RUN" in verdict.findings
    assert any(c["check"] == "ffprobe" and c["passed"] is None for c in verdict.checks)


def test_video_encoder_rejects_invalid_and_mismatched_frames(tmp_path, monkeypatch):
    import struct
    from services.langgraph.agency.ucpo import sandbox
    from services.langgraph.agency.visual import renderers

    monkeypatch.setattr(renderers.shutil, "which", lambda name: "/usr/bin/true" if name == "ffmpeg" else None)
    monkeypatch.setattr(sandbox, "probe_isolation", lambda: sandbox.Isolation(True, (), node="/usr/local/bin/node"))
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not a png")
    assert renderers.encode_video([bad], tmp_path / "bad.mp4", fps=30).reasons == ("FRAME_NOT_PNG",)
    def header(width, height):
        return b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR" + struct.pack(">II", width, height)
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    a.write_bytes(header(16, 16)); b.write_bytes(header(32, 16))
    assert renderers.encode_video([a, b], tmp_path / "bad.mp4", fps=30).reasons == ("FRAME_DIMENSIONS_MISMATCH",)
    assert renderers.encode_video([a], tmp_path / "bad.mp4", fps=True).reasons == ("FRAME_OR_FPS_BUDGET_EXCEEDED",)
    assert not (tmp_path / "bad.mp4").exists()


def test_video_encoder_and_probe_use_isolated_scratch(tmp_path):
    import shutil
    from services.langgraph.agency.ucpo.sandbox import probe_isolation
    from services.langgraph.agency.visual.renderers import encode_video
    from services.langgraph.agency.visual.verify import verify_media

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe") or not probe_isolation().available:
        pytest.skip("NOT_RUN: ffmpeg, ffprobe or sandbox unavailable")
    Image = pytest.importorskip("PIL.Image")
    ImageDraw = pytest.importorskip("PIL.ImageDraw")
    frames = []
    for i in range(5):
        image = Image.new("RGB", (32, 32), (20 + i * 20, 30, 100))
        ImageDraw.Draw(image).rectangle((8, 8, 24, 24), fill=(245, 235, 200))
        p = tmp_path / f"original-{i}.png"
        image.save(p)
        frames.append(p)
    out = tmp_path / "video.mp4"
    encoded = encode_video(frames, out, fps=5)
    assert encoded.status == "SUCCEEDED" and encoded.network_isolated is True, encoded.reasons
    assert str(tmp_path) not in " ".join(encoded.command)
    verdict = verify_media(out.read_bytes(), mime_type="video/mp4", expect={"width": 32, "height": 32, "fps": 5, "frames": 5})
    assert verdict.status == "PASSED", verdict.findings
    assert any(c["check"] == "dims_fps_frames_codec" and c["passed"] for c in verdict.checks)


def test_mux_refuses_short_audio_that_would_truncate_video(tmp_path):
    import shutil
    from services.langgraph.agency.ucpo.sandbox import probe_isolation
    from services.langgraph.agency.visual.renderers import encode_video
    from services.langgraph.agency.vnexus.video import mux_audio

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe") or not probe_isolation().available:
        pytest.skip("NOT_RUN: ffmpeg, ffprobe or sandbox unavailable")
    Image = pytest.importorskip("PIL.Image")
    frames = []
    for i in range(10):
        p = tmp_path / f"frame-{i}.png"
        Image.new("RGB", (64, 64), (20 + i * 20, 30, 100)).save(p)
        frames.append(p)
    original = tmp_path / "original.mp4"
    assert encode_video(frames, original, fps=5).status == "SUCCEEDED"
    for duration, expected in ((3, "SUCCEEDED"), (0.4, "FAILED")):
        audio, output = tmp_path / f"tone-{duration}.m4a", tmp_path / f"muxed-{duration}.mp4"
        # Trusted synthetic test tone, not external user input.
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        f"sine=frequency=440:duration={duration}", "-c:a", "aac", str(audio)], check=True)
        result = mux_audio(original, audio, output)
        assert result["status"] == expected, result
        assert output.exists() == (expected == "SUCCEEDED")


def test_social_poster_cta_uses_a_legible_foreground():
    from services.langgraph.agency.foundry import compose
    from services.langgraph.agency.foundry.contracts import UserBrief
    from services.langgraph.agency.foundry.genome import compile_genome
    from services.langgraph.agency.vnexus.identity import text_contrast

    brief = UserBrief(organization="Fictional studio", offering="Workflow planning", business_objective="Clarity",
                      desired_action="Discuss your workflow", deliverable_types=("genome",),
                      brand_constraints={"palette": {"ink": "#171719", "paper": "#f0eee9", "accent": "#ffaa3d",
                                                     "accent_2": "#ff4c2f", "muted": "#838185"}})
    genome = compile_genome(brief, project_id="synthetic")
    ir = compose.poster(genome, headline="See your workflow clearly", cta="Discuss your workflow", width=1080, height=1080)
    assert text_contrast(ir, genome)["status"] == "PASSED"
    cta = next(t for t in ir.text if t.role == "cta")
    assert cta.fill == ("paper" if ir.background == "ink" else "ink")


def test_poster_fits_headline_above_footer_and_detects_estimated_collisions():
    from services.langgraph.agency.foundry import compose
    from services.langgraph.agency.foundry.contracts import UserBrief
    from services.langgraph.agency.foundry.genome import compile_genome
    from services.langgraph.agency.vnexus.identity import text_overlap

    genome = compile_genome(UserBrief(organization="Northline Workflow Studio"), project_id="synthetic")
    ir = compose.poster(genome, headline="See your workflow clearly", cta="Discuss your workflow", width=1080, height=1080)
    assert text_overlap(ir)["status"] == "PASSED"
    wordmark = next(t for t in ir.text if t.role == "wordmark")
    headline = next(t for t in ir.text if t.role == "headline")
    collided = headline.model_copy(update={"y": wordmark.y, "size": wordmark.size})
    broken = ir.model_copy(update={"text": (collided, wordmark)})
    assert text_overlap(broken)["status"] == "FAILED"
    # Content cannot be silently clipped just because reducing the font is possible.
    with pytest.raises(ValueError, match="COPY_EXCEEDS_LAYOUT"):
        compose.poster(genome, headline="verylongword" * 300, width=1080, height=1080)


def test_rendered_text_check_detects_collisions_and_blocks_missing_browser(tmp_path, monkeypatch):
    from services.langgraph.agency.foundry import compose
    from services.langgraph.agency.foundry.contracts import UserBrief
    from services.langgraph.agency.foundry.genome import compile_genome
    from services.langgraph.agency.visual import browser
    from services.langgraph.agency.vnexus.identity import rendered_text_layout

    genome = compile_genome(UserBrief(organization="Northline Workflow Studio"), project_id="synthetic")
    ir = compose.poster(genome, headline="See your workflow clearly", cta="Discuss your workflow", width=1080, height=1080)
    executable = Path("/home/user/.local/amc-tools/chromium/test-run/chromium")
    if executable.is_file() and probe_isolation().available:
        monkeypatch.setattr(browser, "chromium_path", lambda: executable)
        assert rendered_text_layout(ir, genome, margin=0.06, work=tmp_path / "ok")["status"] == "PASSED"
        wordmark = next(t for t in ir.text if t.role == "wordmark")
        headline = next(t for t in ir.text if t.role == "headline")
        broken = ir.model_copy(update={"text": (headline.model_copy(update={"y": wordmark.y, "size": wordmark.size}), wordmark)})
        assert rendered_text_layout(broken, genome, margin=0.06, work=tmp_path / "bad")["status"] == "FAILED"
    monkeypatch.setattr(browser, "_run", lambda *args, **kwargs: {"exit_code": None, "result": {}})
    assert rendered_text_layout(ir, genome, margin=0.06, work=tmp_path / "missing")["status"] == "NOT_RUN"


def test_media_staging_rejects_symlinks_fifos_and_oversized_files_without_overwriting(tmp_path):
    import os
    from services.langgraph.agency.visual.file_staging import UnsafeInput, copy_regular_bounded

    source, dest = tmp_path / "input.bin", tmp_path / "staged.bin"
    source.write_bytes(b"0123456789")
    with pytest.raises(UnsafeInput):
        copy_regular_bounded(source, dest, max_bytes=9)
    assert not dest.exists()
    link = tmp_path / "link.bin"
    link.symlink_to(source)
    with pytest.raises(UnsafeInput):
        copy_regular_bounded(link, dest, max_bytes=100)
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)
    with pytest.raises(UnsafeInput):
        copy_regular_bounded(fifo, dest, max_bytes=100)
    assert copy_regular_bounded(source, dest, max_bytes=10) == 10
    with pytest.raises(FileExistsError):
        copy_regular_bounded(source, dest, max_bytes=10)
    assert dest.read_bytes() == b"0123456789"


def test_video_nonblank_check_is_inconclusive_when_pixel_sampling_unavailable(monkeypatch):
    from services.langgraph.agency.visual import verify

    monkeypatch.setattr(verify, "_probe_video", lambda path: {"codec": "h264", "width": 16, "height": 16,
                                                              "fps": 1.0, "frames": 1, "duration": 1.0})
    def unavailable(path, frames):
        raise verify.VideoProbeUnavailable("no safe decoder")
    monkeypatch.setattr(verify, "_sample_video_pixels", unavailable)
    verdict = verify.verify_media(b"\x00\x00\x00\x18ftypmp42fake", mime_type="video/mp4",
                                  expect={"width": 16, "height": 16, "fps": 1, "frames": 1})
    assert verdict.status == "INCONCLUSIVE"
    assert "VIDEO_PIXEL_SAMPLING_NOT_RUN" in verdict.findings
    assert not any(c["check"] == "source_rights" for c in verdict.checks)


def test_a_nonzero_duration_black_video_does_not_pass_nonblank_qc(tmp_path):
    import shutil
    from services.langgraph.agency.visual.renderers import encode_video
    from services.langgraph.agency.visual.verify import verify_media

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe") or not probe_isolation().available:
        pytest.skip("NOT_RUN: ffmpeg, ffprobe or isolation unavailable")
    Image = pytest.importorskip("PIL.Image")
    frames = []
    for i in range(5):
        p = tmp_path / f"black-{i}.png"
        Image.new("RGB", (32, 32), (0, 0, 0)).save(p)
        frames.append(p)
    out = tmp_path / "black.mp4"
    assert encode_video(frames, out, fps=5).status == "SUCCEEDED"
    result = verify_media(out.read_bytes(), mime_type="video/mp4", expect={"width": 32, "height": 32, "fps": 5, "frames": 5})
    assert result.status == "FAILED"
    assert any(c["check"] == "sampled_pixel_variation" and c["passed"] is False for c in result.checks)


def test_video_sampling_allows_one_fade_frame_but_rejects_a_flat_sampled_region(tmp_path):
    import shutil
    from services.langgraph.agency.visual.renderers import encode_video
    from services.langgraph.agency.visual.verify import verify_media

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe") or not probe_isolation().available:
        pytest.skip("NOT_RUN: ffmpeg, ffprobe or isolation unavailable")
    Image = pytest.importorskip("PIL.Image")
    Draw = pytest.importorskip("PIL.ImageDraw")

    def make_video(name, dark_indexes):
        paths = []
        for i in range(30):
            image = Image.new("RGB", (32, 32), (0, 0, 0))
            if i not in dark_indexes:
                Draw.Draw(image).rectangle((6, 6, 25, 25), fill=(230, 230, 230))
            p = tmp_path / f"{name}-{i}.png"
            image.save(p)
            paths.append(p)
        output = tmp_path / f"{name}.mp4"
        assert encode_video(paths, output, fps=10).status == "SUCCEEDED"
        return verify_media(output.read_bytes(), mime_type="video/mp4",
                            expect={"width": 32, "height": 32, "fps": 10, "frames": 30})

    fade = make_video("fade", {15})
    assert fade.status == "PASSED", fade.findings
    sample = next(c for c in fade.checks if c["check"] == "sampled_pixel_variation")
    assert "low-variation samples [15]" in sample["detail"]
    flat_region = make_video("flat-region", {15, 16})
    assert flat_region.status == "FAILED"
    assert any(c["check"] == "sampled_pixel_variation" and c["passed"] is False for c in flat_region.checks)
