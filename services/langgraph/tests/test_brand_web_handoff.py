"""Northline is fictional; local test approvals are not real client approvals."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest

from services.langgraph.agency.project_os.storage import LocalStorageAdapter
from services.langgraph.agency.ucpo import service
from services.langgraph.agency.ucpo.brand_web import current_brand, map_brief
from services.langgraph.agency.ucpo.brand_web_contracts import BrandSiteRequest, BrandWebsiteMapping
from services.langgraph.agency.vnexus.genome import document_from_flat
from services.langgraph.persistence.agency_kernel import get_artifact
from services.langgraph.persistence.approvals import mark_approval_stale
from services.langgraph.persistence.projects import create_project_artifact
from services.langgraph.security.auth import Principal
from services.langgraph.tests._project_os_support import as_user, client, headers
from services.langgraph.tests._vnexus_support import _approve, _draft, make_world
from services.langgraph.tests.test_vnexus_contracts import _shape_matches, structure

ROOT = Path(__file__).resolve().parents[3]
VALUES = json.loads((ROOT / "examples/northline/brand-values.json").read_text())["values"]
MAPPING = json.loads((ROOT / "examples/northline/website-mapping.json").read_text())
FIXTURE = ROOT / "packages/shared/tests/fixtures/brand-web.json"


@pytest.fixture
def world(monkeypatch, tmp_path):
    return make_world(monkeypatch, tmp_path)


def request(w, *, site="northline", brand=None, mapping=None, key=None):
    as_user(w["mp"], "alice", role="operator", tenant=w["tenant"])
    return client.post(f"/ucpo/projects/{w['owner']}/sites/from-brand",
        json={"site_id": site, "brand_id": brand or w["brand"], "mapping": mapping or MAPPING},
        headers={"Idempotency-Key": key} if key else headers())


def test_northline_brand_to_web_revision_and_selective_preservation(world):
    w = world
    first_version = _approve(w, _draft(w, "brand", w["brand"], document_from_flat(VALUES)))
    root = Path(os.environ["AMC_EXPORT_ROOT"])
    adapter = LocalStorageAdapter(root)
    untouched = create_project_artifact(tenant_id=w["tenant"], project_id=w["owner"], actor="alice",
        artifact_key="independent-notes", artifact_type="product_spec", adapter=adapter, content_text="independent work")
    first = request(w, key="northline-first")
    assert first.status_code == 201, first.text
    result1 = first.json()
    assert request(w, key="northline-first").json() == result1
    assert result1["brand"]["layers"][0]["version_id"] == first_version["version_id"]
    assert result1["brand"]["primary_accent"] == "signal_red"
    assert "verbal.voice.tone" in result1["brand"]["unmapped_keys"]
    one = service.load_stages(w["owner"], "northline", adapter)
    assert len(one["brief"].pages) == 7
    assert one["brief"].organization == VALUES["verbal.messaging.organization"]
    assert one["brief"].cta_label == VALUES["verbal.messaging.cta"]
    assert one["ir"].pages[0].sections[0].accent == "signal_red"
    assert one["ir"].pages[0].sections[0].cta["href"] == "/contact/#connect"
    assert set(one["files"]) >= {"app/page.tsx", "app/services/page.tsx", "app/process/page.tsx", "app/about/page.tsx",
                                  "app/contact/page.tsx", "app/workflow-diagnostic/page.tsx",
                                  "app/implementation-planning/page.tsx", "public/assets/workflow-plate.svg"}
    before_unrelated = get_artifact(untouched.artifact_id)
    # A direct hand-entered brief must not detach the approved-brand binding.
    direct = client.post(f"/ucpo/projects/{w['owner']}/sites", headers=headers(),
                         json={"site_id": "northline", "brief": one["brief"].model_dump(mode="json")})
    assert direct.status_code == 422 and "BRAND_BOUND_SITE" in direct.text

    revised_values = {**VALUES, "verbal.messaging.cta": "Discuss your workflow",
                      "visual.color.accent": "#ffaa3d", "visual.color.accent_2": "#ff4c2f"}
    second_version = _approve(w, _draft(w, "brand", w["brand"], document_from_flat(revised_values)))
    assert second_version["version_id"] != first_version["version_id"]
    as_user(w["mp"], "alice", role="operator", tenant=w["tenant"])
    stale_view = client.get(f"/ucpo/projects/{w['owner']}/sites/northline").json()
    assert stale_view["release"]["allowed"] is False
    assert any("BRAND_HANDOFF_STALE" in r for r in stale_view["release"]["reasons"])
    old_tick = service.run_build_tick(result1["site"]["job_id"])
    assert old_tick.final_state == "BLOCKED_ENVIRONMENT" and any("BRAND_HANDOFF_STALE" in r for r in old_tick.reasons)
    second = request(w, key="northline-second")
    assert second.status_code == 201, second.text
    result2 = second.json()
    two = service.load_stages(w["owner"], "northline", adapter)
    assert result2["site"]["job_id"] != result1["site"]["job_id"]
    assert two["brief"].cta_label == "Discuss your workflow"
    assert two["ir"].pages[0].sections[0].accent == "amber"
    assert two["ir"].pages[0].sections[0].cta["label"] == "Discuss your workflow"
    assert one["files"]["content/site.json"] != two["files"]["content/site.json"]
    assert one["files"]["app/about/page.tsx"] == two["files"]["app/about/page.tsx"]
    assert get_artifact(untouched.artifact_id) == before_unrelated
    assert get_artifact(one["entries"]["brief"]["artifact_id"])["version"] > one["entries"]["brief"]["version"]
    assert client.get(f"/ucpo/projects/{w['owner']}/sites/northline").json()["release"]["allowed"] is False


def test_missing_copy_unsupported_palette_and_invalid_mapping_fail_before_write(world):
    w = world
    missing = dict(VALUES)
    del missing["verbal.messaging.index_heading"]
    _approve(w, _draft(w, "brand", w["brand"], document_from_flat(missing)))
    response = request(w)
    assert response.status_code == 422 and "MISSING_APPROVED_COPY" in response.text
    assert not service.list_sites(w["owner"])
    with pytest.raises(ValueError, match="UNSUPPORTED_BRAND_PALETTE"):
        map_brief({**VALUES, "visual.color.accent": "#123456"}, BrandWebsiteMapping.model_validate(MAPPING))
    broken = copy.deepcopy(MAPPING)
    broken["pages"][0]["sections"][0]["heading_key"] = "visual.color.accent"
    assert request(w, mapping=broken).status_code == 422


def test_unapproved_stale_and_cross_tenant_brands_are_denied(world):
    w = world
    draft = _draft(w, "brand", w["brand"], document_from_flat(VALUES))
    assert request(w).status_code == 422
    approved = _approve(w, draft)
    principal = Principal("alice", w["tenant"], "operator", frozenset({w["owner"]}))
    assert current_brand(principal, w["owner"], w["brand"])[1][0]["version_id"] == approved["version_id"]
    mark_approval_stale(approved["approval_id"], "synthetic revocation test")
    assert request(w).status_code == 422
    as_user(w["mp"], "mallory", tenant="other-tenant", projects=w["owner"])
    denied = client.post(f"/ucpo/projects/{w['owner']}/sites/from-brand", headers=headers(),
        json={"site_id":"northline", "brand_id":w["brand"], "mapping":MAPPING})
    assert denied.status_code in {403, 404}


def test_brand_web_api_contract_fixture(world):
    w = world
    _approve(w, _draft(w, "brand", w["brand"], document_from_flat(VALUES)))
    response = request(w)
    assert response.status_code == 201, response.text
    live = {"request": BrandSiteRequest(site_id="northline", brand_id=w["brand"], mapping=BrandWebsiteMapping.model_validate(MAPPING))
            .model_dump(mode="json"), "response": response.json()}
    if os.environ.get("AMC_REGENERATE_FIXTURES") == "1":
        FIXTURE.write_text(json.dumps(live, sort_keys=True, indent=2) + "\n")
    else:
        recorded = json.loads(FIXTURE.read_text())
        assert _shape_matches(structure(live), structure(recorded)) == []


def test_interrupted_brand_compile_rolls_back_and_same_key_recovers(world, monkeypatch):
    """Synthetic fault injection: no partial heads, dependency edges or queue receipt survive."""
    from services.langgraph.persistence.idempotency import get_idempotency_record
    from services.langgraph.persistence.projects import list_project_artifacts

    w = world
    _approve(w, _draft(w, "brand", w["brand"], document_from_flat(VALUES)))
    before = [(a.artifact_id, a.version, a.content_hash) for a in list_project_artifacts(w["owner"], limit=1000)]
    original = service._put

    def interrupted(*args, **kwargs):
        if args[3] == "source":
            raise RuntimeError("synthetic interrupted compile")
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "_put", interrupted)
    with pytest.raises(RuntimeError, match="synthetic interrupted"):
        request(w, key="crash-retry")
    after = [(a.artifact_id, a.version, a.content_hash) for a in list_project_artifacts(w["owner"], limit=1000)]
    assert after == before
    scope = f"{w['tenant']}:alice:ucpo.brand-site:{w['owner']}"
    assert get_idempotency_record(scope, "crash-retry") is None
    assert service.list_sites(w["owner"]) == []
    monkeypatch.setattr(service, "_put", original)
    recovered = request(w, key="crash-retry")
    assert recovered.status_code == 201, recovered.text
    assert request(w, key="crash-retry").json() == recovered.json()


def test_interrupted_revision_keeps_old_heads_but_brand_guard_blocks_them(world, monkeypatch):
    from services.langgraph.persistence.idempotency import get_idempotency_record
    from services.langgraph.persistence.projects import list_project_artifacts

    w = world
    _approve(w, _draft(w, "brand", w["brand"], document_from_flat(VALUES)))
    first = request(w, key="before-revision").json()
    before = [(a.artifact_id, a.version, a.content_hash, a.status)
              for a in list_project_artifacts(w["owner"], limit=1000)]
    revised = {**VALUES, "verbal.messaging.cta": "Discuss your workflow"}
    _approve(w, _draft(w, "brand", w["brand"], document_from_flat(revised)))
    original = service._put

    def interrupted(*args, **kwargs):
        if args[3] == "source":
            raise RuntimeError("synthetic revision interruption")
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "_put", interrupted)
    with pytest.raises(RuntimeError, match="synthetic revision"):
        request(w, key="revision-retry")
    after = [(a.artifact_id, a.version, a.content_hash, a.status)
             for a in list_project_artifacts(w["owner"], limit=1000)]
    assert after == before
    scope = f"{w['tenant']}:alice:ucpo.brand-site:{w['owner']}"
    assert get_idempotency_record(scope, "revision-retry") is None
    blocked = service.run_build_tick(first["site"]["job_id"])
    assert blocked.final_state == "BLOCKED_ENVIRONMENT"
    assert any("BRAND_HANDOFF_STALE" in reason for reason in blocked.reasons)
    monkeypatch.setattr(service, "_put", original)
    second = request(w, key="revision-retry")
    assert second.status_code == 201, second.text
    image = "image-workflow-plate"
    assert second.json()["site"]["stages"][image]["action"] == "reused_unchanged"
    assert second.json()["site"]["stages"][image]["version"] == first["site"]["stages"][image]["version"]


def test_new_image_dependency_is_connected_and_invalidates_source(world):
    from services.langgraph.persistence.projects import _dependency_refs, revise_project_artifact

    w = world
    _approve(w, _draft(w, "brand", w["brand"], document_from_flat(VALUES)))
    assert request(w).status_code == 201
    mapping = copy.deepcopy(MAPPING)
    mapping["images"].append({"asset_id": "alternate-plate", "alt_key": mapping["images"][0]["alt_key"], "motif_seed": 12})
    result = request(w, mapping=mapping)
    assert result.status_code == 201, result.text
    stages = result.json()["site"]["stages"]
    image_id, source_id = stages["image-alternate-plate"]["artifact_id"], stages["source"]["artifact_id"]
    assert image_id in _dependency_refs(source_id)
    adapter = LocalStorageAdapter(Path(os.environ["AMC_EXPORT_ROOT"]))
    revise_project_artifact(project_id=w["owner"], artifact_id=image_id, actor="alice", adapter=adapter,
                            expected_version=stages["image-alternate-plate"]["version"],
                            content_text='<svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/></svg>')
    assert get_artifact(source_id)["status"] == "invalidated"
    tick = service.run_build_tick(result.json()["site"]["job_id"])
    assert tick.final_state == "BLOCKED_ENVIRONMENT" and any("SOURCE_SUPERSEDED" in r for r in tick.reasons)


def test_key_collision_and_cross_project_brand_fail_before_mutation(world):
    from services.langgraph.persistence.projects import list_project_artifacts

    w = world
    _approve(w, _draft(w, "brand", w["brand"], document_from_flat(VALUES)))
    before = [(a.artifact_id, a.version) for a in list_project_artifacts(w["owner"], limit=1000)]
    mapping = copy.deepcopy(MAPPING)
    alt = mapping["images"][0]["alt_key"]
    mapping["images"] += [{"asset_id": "same-one", "alt_key": alt}, {"asset_id": "same-two", "alt_key": alt}]
    collision = request(w, site="a" * 40, mapping=mapping)
    assert collision.status_code == 422 and "UCPO_ARTIFACT_KEY_COLLISION" in collision.text
    assert [(a.artifact_id, a.version) for a in list_project_artifacts(w["owner"], limit=1000)] == before
    as_user(w["mp"], "alice", role="operator", tenant=w["tenant"])
    cross = client.post(f"/ucpo/projects/{w['other']}/sites/from-brand", headers=headers(),
                        json={"site_id": "other-site", "brand_id": w["brand"], "mapping": MAPPING})
    assert cross.status_code == 422 and "CROSS_PROJECT_BRAND_BLOCKED" in cross.text
    assert not service.list_sites(w["other"])


def test_process_killed_mid_compile_does_not_publish_partial_state(world):
    """A real child process is killed after writes but before its DB transaction commits."""
    import select
    import subprocess
    import sys

    from services.langgraph.persistence import sqlite_db
    from services.langgraph.persistence.database import database_backend
    from services.langgraph.persistence.idempotency import get_idempotency_record
    from services.langgraph.persistence.projects import list_project_artifacts

    w = world
    _approve(w, _draft(w, "brand", w["brand"], document_from_flat(VALUES)))
    before = [(a.artifact_id, a.version, a.content_hash) for a in list_project_artifacts(w["owner"], limit=1000)]
    env = {k: os.environ[k] for k in ("PATH", "HOME", "DATABASE_URL") if k in os.environ}
    env.update({"AMC_DATABASE_BACKEND": database_backend(), "AMC_DB_PATH": str(Path(sqlite_db.DB_PATH).absolute()),
                "AMC_EXPORT_ROOT": os.environ["AMC_EXPORT_ROOT"], "AMC_OBJECT_STORAGE_BACKEND": "local",
                "AMC_AUTH_MODE": "local", "AMC_LOCAL_USER_ID": "alice", "AMC_LOCAL_ROLE": "operator",
                "AMC_LOCAL_TENANT_ID": w["tenant"], "AMC_LOCAL_PROJECT_IDS": "*",
                "AMC_MAX_RUNS_PER_TENANT_PER_HOUR": "0", "AMC_MAX_ACTIVE_RUNS_PER_TENANT": "0"})
    child = r'''
import json, os, sys, time
from services.langgraph.agency.ucpo import service
from services.langgraph.tests._project_os_support import client
original = service._put
def interrupted(*args, **kwargs):
    if args[3] == "source":
        print("READY_TO_KILL", flush=True)
        time.sleep(300)
    return original(*args, **kwargs)
service._put = interrupted
with open("examples/northline/website-mapping.json", encoding="utf-8") as f:
    mapping = json.load(f)
client.post("/ucpo/projects/" + sys.argv[1] + "/sites/from-brand",
            json={"site_id": "northline", "brand_id": sys.argv[2], "mapping": mapping},
            headers={"Idempotency-Key": "killed-compile"})
'''
    process = subprocess.Popen([sys.executable, "-c", child, w["owner"], w["brand"]], cwd=ROOT, env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        ready, _, _ = select.select([process.stdout], [], [], 45)
        assert ready and process.stdout.readline().strip() == "READY_TO_KILL", "child did not reach pre-commit fault point"
    finally:
        process.kill()
        process.communicate(timeout=15)
    assert process.returncode is not None and process.returncode != 0
    after = [(a.artifact_id, a.version, a.content_hash) for a in list_project_artifacts(w["owner"], limit=1000)]
    assert after == before
    scope = f"{w['tenant']}:alice:ucpo.brand-site:{w['owner']}"
    assert get_idempotency_record(scope, "killed-compile") is None
    recovered = request(w, key="killed-compile")
    assert recovered.status_code == 201, recovered.text


@pytest.mark.parametrize("same_key", (True, False), ids=("same-idempotency-key", "different-keys-same-site"))
def test_postgres_concurrent_brand_site_requests_are_serialized(world, monkeypatch, same_key):
    """Hold a real PG transaction open and observe the competing request's lock wait.

    This exercises the API, database advisory locks and artifact/job commits. It
    does not run a browser, approve a website or prove every concurrency path.
    """
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    import time

    from services.langgraph.persistence import durable_runs
    from services.langgraph.persistence.database import is_postgres, transaction
    from services.langgraph.persistence.idempotency import get_idempotency_record

    if not is_postgres():
        pytest.skip("NOT_RUN: requires a real PostgreSQL database for advisory-lock contention")
    w = world
    _approve(w, _draft(w, "brand", w["brand"], document_from_flat(VALUES)))
    as_user(monkeypatch, "alice", role="operator", tenant=w["tenant"])
    entered, release = Event(), Event()
    holder_pid: list[int] = []
    original = service._put

    def pause_first(*args, **kwargs):
        if args[3] == "source" and not entered.is_set():
            with transaction() as db:
                holder_pid.append(db.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"])
            entered.set()
            if not release.wait(30):
                raise TimeoutError("test did not release the held compile")
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "_put", pause_first)
    first_mapping = copy.deepcopy(MAPPING)
    second_mapping = copy.deepcopy(MAPPING)
    if not same_key:
        second_mapping["seed"] = first_mapping["seed"] + 1
    first_key, second_key = "concurrent-first", "concurrent-first" if same_key else "concurrent-second"

    def post(key, mapping):
        return client.post(f"/ucpo/projects/{w['owner']}/sites/from-brand",
                           json={"site_id": "northline", "brand_id": w["brand"], "mapping": mapping},
                           headers={"Idempotency-Key": key})

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(post, first_key, first_mapping)
        try:
            assert entered.wait(20) and holder_pid, "first compile never reached the held transaction"
            second = pool.submit(post, second_key, second_mapping)
            deadline = time.monotonic() + 15
            blocked = False
            while time.monotonic() < deadline:
                with transaction() as db:
                    row = db.execute("SELECT count(*) AS n FROM pg_stat_activity "
                                     "WHERE wait_event_type = 'Lock' AND wait_event = 'advisory' "
                                     "AND ? = ANY(pg_blocking_pids(pid))", (holder_pid[0],)).fetchone()
                if row["n"]:
                    blocked = True
                    break
                time.sleep(0.05)
            assert blocked, "second request never waited on a held PostgreSQL advisory lock"
        finally:
            release.set()
        one = first.result(timeout=60)
        two = second.result(timeout=60)
    assert one.status_code == two.status_code == 201, (one.text, two.text)
    one_body, two_body = one.json(), two.json()
    scope = f"{w['tenant']}:alice:ucpo.brand-site:{w['owner']}"
    first_receipt = get_idempotency_record(scope, first_key)
    assert first_receipt["status"] == "completed" and first_receipt["attempt_count"] == 1
    # A later replay returns the original receipt, even if another key advanced the site.
    assert post(first_key, first_mapping).json() == one_body
    assert post(second_key, second_mapping).json() == two_body
    assert get_idempotency_record(scope, first_key)["attempt_count"] == 1
    conflicting = copy.deepcopy(first_mapping)
    conflicting["seed"] += 2
    assert post(first_key, conflicting).status_code == 409
    assert get_idempotency_record(scope, first_key)["result"] == one_body
    if same_key:
        assert one_body == two_body
        assert one_body["site"]["job_id"] == two_body["site"]["job_id"]
    else:
        assert one_body["site"]["job_id"] != two_body["site"]["job_id"]
        second_receipt = get_idempotency_record(scope, second_key)
        assert second_receipt["status"] == "completed" and second_receipt["attempt_count"] == 1
        adapter = LocalStorageAdapter(Path(os.environ["AMC_EXPORT_ROOT"]))
        current = service.load_stages(w["owner"], "northline", adapter)
        assert current["brief"].seed == second_mapping["seed"]
        second_job = durable_runs.get_job(two_body["site"]["job_id"])
        expected_source = second_job["spec"]["ucpo"]["source"]
        assert all(current["entries"]["source"][key] == expected_source[key]
                   for key in ("artifact_id", "version", "content_hash"))
        assert service.SiteBuildHandler().precheck(second_job) == (None, [])
        old = durable_runs.get_job(one_body["site"]["job_id"])
        blocked_state, reasons = service.SiteBuildHandler().precheck(old)
        assert blocked_state == "BLOCKED_ENVIRONMENT" and any(
            "SOURCE_SUPERSEDED" in reason or "INPUT_STALE" in reason or "BRAND_HANDOFF_STALE" in reason for reason in reasons
        )


def test_postgres_inflight_build_cannot_seal_after_a_competing_revision(world, monkeypatch):
    """Synthetic build observation; contend at the real PG site lock before proof commit."""
    import base64
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    import time

    from services.langgraph.agency.ucpo.contracts import BuildResult
    from services.langgraph.persistence import durable_runs
    from services.langgraph.persistence.database import is_postgres, transaction
    from services.langgraph.persistence.projects import project_artifact_id
    from services.langgraph.tests.test_ucpo_pipeline import rendered_from_source

    if not is_postgres():
        pytest.skip("NOT_RUN: requires a real PostgreSQL database for commit/compile contention")
    w = world
    _approve(w, _draft(w, "brand", w["brand"], document_from_flat(VALUES)))
    first_response = request(w, key="build-before-revision")
    assert first_response.status_code == 201, first_response.text
    first_job_id = first_response.json()["site"]["job_id"]
    adapter = LocalStorageAdapter(Path(os.environ["AMC_EXPORT_ROOT"]))
    loaded = service.load_stages(w["owner"], "northline", adapter)
    export = {"index.html": base64.b64encode(b"SYNTHETIC TEST ONLY: no browser ran").decode()}
    build = BuildResult(status="PASSED", source_tree_hash=loaded["manifest"].tree_hash,
                        isolation={"note": "SYNTHETIC TEST ONLY"}, steps=(), dependency_manifest={},
                        output_hash=service.export_digest(export))
    qa = rendered_from_source(loaded["requirements"], loaded["ir"], loaded["files"]).model_copy(
        update={"build_output_hash": build.output_hash, "browser": {"name": "SYNTHETIC TEST ONLY"}})
    record = {"build": build.model_dump(mode="json"), "browser_qa": qa.model_dump(mode="json"), "export": export}
    build_ready, release_build, compile_held, release_compile = (Event() for _ in range(4))
    holder_pid: list[int] = []
    original_put = service._put

    def fake_dispatch(_self, job):
        assert job["job_id"] == first_job_id
        build_ready.set()
        if not release_build.wait(30):
            raise TimeoutError("test did not release the synthetic dispatch")
        stored = adapter.put_bytes(tenant_id=job["tenant_id"], project_id=job["project_id"], data=service._dump(record))
        return {"storage_uri": stored.storage_uri, "content_hash": stored.content_hash, "route": "SYNTHETIC TEST ONLY"}

    def pause_revision(*args, **kwargs):
        if args[3] == "source" and not compile_held.is_set():
            with transaction() as db:
                holder_pid.append(db.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"])
            compile_held.set()
            if not release_compile.wait(30):
                raise TimeoutError("test did not release the held revision")
        return original_put(*args, **kwargs)

    monkeypatch.setattr(service.SiteBuildHandler, "dispatch", fake_dispatch)
    monkeypatch.setattr(service, "_put", pause_revision)
    revised = copy.deepcopy(MAPPING)
    revised["seed"] += 1
    as_user(monkeypatch, "alice", role="operator", tenant=w["tenant"])

    def compile_revision():
        return client.post(f"/ucpo/projects/{w['owner']}/sites/from-brand",
                           json={"site_id": "northline", "brand_id": w["brand"], "mapping": revised},
                           headers={"Idempotency-Key": "competing-revision"})

    with ThreadPoolExecutor(max_workers=2) as pool:
        tick_future = pool.submit(service.run_build_tick, first_job_id)
        try:
            assert build_ready.wait(20), "old job did not reach synthetic dispatch"
            revision_future = pool.submit(compile_revision)
            assert compile_held.wait(20) and holder_pid, "revision did not hold the site transaction"
            release_build.set()
            deadline = time.monotonic() + 15
            blocked = False
            while time.monotonic() < deadline:
                with transaction() as db:
                    row = db.execute("SELECT count(*) AS n FROM pg_stat_activity "
                                     "WHERE wait_event_type = 'Lock' AND wait_event = 'advisory' "
                                     "AND ? = ANY(pg_blocking_pids(pid))", (holder_pid[0],)).fetchone()
                if row["n"]:
                    blocked = True
                    break
                time.sleep(0.05)
            assert blocked, "in-flight build never waited on the competing site's advisory lock"
        finally:
            release_build.set()
            release_compile.set()
        revision_response = revision_future.result(timeout=60)
        tick = tick_future.result(timeout=60)
    assert revision_response.status_code == 201, revision_response.text
    assert tick.final_state == "DORMANT"
    old = durable_runs.get_job(first_job_id)
    assert old["result"]["eligible_for_approval"] is False
    assert any("SOURCE_SUPERSEDED" in reason or "INPUT_STALE" in reason or "BRAND_HANDOFF_STALE" in reason
               for reason in old["result"]["reasons"])
    proof_id = project_artifact_id(w["owner"], "foundry-ucpo-northline-release_proof")
    assert get_artifact(proof_id) is None  # the synthetic old observation never became a release proof
    new = durable_runs.get_job(revision_response.json()["site"]["job_id"])
    assert service.SiteBuildHandler().precheck(new) == (None, [])
