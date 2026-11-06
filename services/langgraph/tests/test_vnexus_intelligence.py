"""VNEXUS marketing intelligence, prompt genome, design immune system and creative digital twin."""

from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest

from services.langgraph.agency.vnexus.genome import document_from_flat
from services.langgraph.agency.vnexus.marketing import sample_size_per_arm
from services.langgraph.persistence.database import json_param, table, transaction
from services.langgraph.tests._project_os_support import client, headers
from services.langgraph.tests._vnexus_support import BRAND_DOC, FULL_DOC, _approve, _c, _draft, make_world


@pytest.fixture
def world(monkeypatch, tmp_path):
    return make_world(monkeypatch, tmp_path)


@pytest.fixture
def approved(world):
    return {**world, "version": _approve(world, _draft(world, "brand", world["brand"], FULL_DOC))}


def _target(w):
    return {"scope": "brand", "scope_ref": w["brand"]}


# --------------------------------------------------------------------------- marketing


def test_sample_size_matches_the_textbook_case_and_refuses_impossible_rates():
    assert 385 <= sample_size_per_arm(0.5, 0.2, alpha=0.05, power=0.8) <= 390  # 0.50 vs 0.60, two-sided, 80% power
    assert sample_size_per_arm(0.05, 0.5, alpha=0.05, power=0.8) < sample_size_per_arm(0.05, 0.2, alpha=0.05, power=0.8)
    assert sample_size_per_arm(0.8, 0.5, alpha=0.05, power=0.8) is None


def test_campaign_plan_never_invents_and_stays_unpublished(approved):
    w = approved
    req = {"campaign_ref": "spring-list", "objective": "Grow the studio list", "channels": ["social_feed", "email"],
           "start": "2026-11-02", "weeks": 2, "cadence_per_week": {"social_feed": 3},
           "landing_url": "https://example.org/join?ref=1",
           "metrics": [{"name": "signup_rate", "numerator_event": "signup", "denominator_event": "landing_view", "source_system": "first-party"}],
           "hypotheses": [{"hypothesis_id": "h1", "change": "the 4:5 format leads", "segment_id": "primary", "metric": "signup_rate",
                           "rationale": "taller formats take more of the feed", "baseline_rate": 0.04, "baseline_source": "Q3 export",
                           "minimum_detectable_lift": 0.25},
                          {"hypothesis_id": "h2", "change": "warmer copy", "segment_id": "primary", "metric": "signup_rate",
                           "rationale": "matches the voice"}]}
    r = client.post(f"/vnexus/brands/{w['brand']}/campaigns", json={**_target(w), "project_id": w["owner"], "request": req}, headers=headers())
    assert r.status_code == 200, r.text
    plan = r.json()["plan"]
    assert plan["segments"][0]["evidence"] == "ASSUMED" and plan["assumptions"]
    assert {c["proof"] for c in plan["messaging_matrix"] if c["stage"] != "awareness"} == {"NEEDS_PROOF"}
    assert "NEEDS_PROOF" in plan["gaps"] and plan["brief"]["key_message"] == "Made slowly, used daily"  # the approved promise, verbatim
    assert len(plan["content_calendar"]) == 2 * 3 + 2 * 1
    assert {e["status"] for e in plan["content_calendar"]} == {"PLANNED"} and {e["publishing"] for e in plan["content_calendar"]} == {"DISABLED"}
    url = plan["channel_plans"][0]["variants"][0]["attribution"]["url"]
    assert url.startswith("https://example.org/join?ref=1&utm_source=social_feed") and "utm_campaign=spring-list" in url
    exps = {e["hypothesis_id"]: e for e in plan["experiments"]}
    assert exps["h1"]["sample_size_kind"] == "COMPUTED" and exps["h1"]["sample_size_per_arm"] > 1000
    assert exps["h2"]["sample_size_per_arm"] is None and exps["h2"]["sample_size_kind"].startswith("NOT_COMPUTABLE")
    graph = client.get(f"/vnexus/brands/{w['brand']}/graph").json()
    targets = [e for e in graph["edges"] if e["kind"] == "TARGETS"]
    assert len(targets) == 3  # one audience, two channels

    bad = {**req, "segments": [{"segment_id": "s", "name": "x", "evidence": "RESEARCHED"}]}
    assert client.post(f"/vnexus/brands/{w['brand']}/campaigns", json={**_target(w), "project_id": w["owner"], "request": bad},
                       headers=headers()).status_code == 422

    def measure(metric, value, source="first-party analytics export"):
        return client.post(f"/vnexus/projects/{w['owner']}/measurements", json={"campaign_ref": "spring-list", "metric": metric, "value": value,
                                                                               "unit": "count", "source": source, "source_ref": "export-1",
                                                                               "observed_at": "2026-11-09T00:00:00Z"})

    before = client.get(f"/vnexus/projects/{w['owner']}/campaigns/spring-list/report").json()["report"]
    assert before["metrics"][0]["rate"] is None and before["metrics"][0]["rate_kind"] == "NOT_MEASURED"
    assert measure("signup", 12).status_code == 201
    half = client.get(f"/vnexus/projects/{w['owner']}/campaigns/spring-list/report").json()["report"]["metrics"][0]
    assert half["rate"] is None  # denominator not measured yet: no rate is made up
    measure("landing_view", 400)
    full = client.get(f"/vnexus/projects/{w['owner']}/campaigns/spring-list/report").json()["report"]["metrics"][0]
    assert full["rate"] == 0.03 and full["rate_kind"] == "COMPUTED from MEASURED values"
    assert measure("signup", 1, source=" ").status_code == 422
    fc = client.post("/vnexus/forecast", json={"audience_size": 1000, "assumed_rate": 0.02, "assumption_source": "planning assumption"}).json()
    assert fc["forecast"]["kind"] == "SIMULATED" and "not measured" in fc["forecast"]["label"]


# --------------------------------------------------------------------------- prompt genome


PROMPT = {"intent": "A still life of a stoneware plate on linen in morning light", "family": "IMAGE", "asset_type": "hero image",
          "constraints": ["No visible text."], "capabilities": ["TEXT_TO_IMAGE"], "output": {"width": 1600, "height": 900, "aspect_ratio": "16:9"}}


def test_prompt_genome_compiles_through_the_existing_compiler(approved):
    w = approved
    v1 = client.post(f"/vnexus/brands/{w['brand']}/prompts", json={"prompt_id": "hero-still", "document": PROMPT}).json()["prompt"]
    out = client.post(f"/vnexus/prompts/{v1['prompt_version_id']}/compile", json={**_target(w), "adapt_to": "generic_text_to_image"}).json()
    assert out["final_state"] == "PROMPT_PACKAGE_READY" and out["generation_firewall"] == "PROMPT_PACKAGE_READY"
    assert out["checks"]["terminal_state_ready"] and out["checks"]["inherited_constraints_carried"]
    assert any("visual.color.ink" in c for c in out["inherited_constraints"])
    assert out["adapted"]["provider_called"] is False and "No visible text." in out["adapted"]["body"]["negative_prompt"]
    v2 = client.post(f"/vnexus/brands/{w['brand']}/prompts", json={"prompt_id": "hero-still", "document": {**PROMPT,
                     "intent": "A still life of a stoneware bowl on linen in morning light", "exact_text": ["Made slowly"],
                     "family": "PRINT", "asset_type": "poster"}}).json()["prompt"]
    assert v2["version"] == 2 and v2["parent_version_id"] == v1["prompt_version_id"] and v2["source_kind"] == "AUTHORED"
    reg = client.post(f"/vnexus/brands/{w['brand']}/prompts/hero-still/regression", json=_target(w)).json()
    assert [r["final_state"] for r in reg["results"]] == ["PROMPT_PACKAGE_READY", "PROMPT_PACKAGE_READY"]
    assert set(reg["diffs"][0]["changed_fields"]) >= {"intent", "exact_text"} and 0 < reg["diffs"][0]["intent_lexical_overlap"] < 1
    # The second version demands exact text: the check reports whether the package preserved it.
    assert "exact_text_preserved" in reg["results"][1]["checks"]


def test_prompt_genome_refuses_an_incomplete_genome_and_never_fills_it(world):
    w = world
    _approve(w, _draft(w, "brand", w["brand"], BRAND_DOC))
    v = client.post(f"/vnexus/brands/{w['brand']}/prompts", json={"prompt_id": "hero", "document": PROMPT}).json()["prompt"]
    out = client.post(f"/vnexus/prompts/{v['prompt_version_id']}/compile", json=_target(w)).json()
    assert out["final_state"] == "GENOME_INCOMPLETE" and out["package"] is None
    assert "visual.imagery.style" in out["missing_genome_keys"] and "visual.logo.min_size" in out["missing_genome_keys"]


def test_original_prompt_import_is_byte_exact_and_inventory_is_honest(approved):
    w = approved
    empty = client.get(f"/vnexus/brands/{w['brand']}/prompts").json()["inventory"]
    assert empty == {**empty, "expected_originals": 14, "imported_originals": 0, "missing": 14, "status": "SOURCE_REQUIRED"}
    text = "  Exact original prompt — with  double spaces,\ttabs and «quotes».\n"
    r = client.post(f"/vnexus/brands/{w['brand']}/prompts/import", json={"prompt_id": "original-01", "text": text,
                                                                           "source_ref": "operator upload 2026-10-11"})
    assert r.status_code == 201, r.text
    row = r.json()["prompt"]
    assert row["source_kind"] == "ORIGINAL_IMPORT" and row["source_hash"] == hashlib.sha256(text.encode()).hexdigest()
    assert row["document"]["source_text"] == text
    inv = client.get(f"/vnexus/brands/{w['brand']}/prompts").json()["inventory"]
    assert inv["imported_originals"] == 1 and inv["missing"] == 13 and inv["status"] == "PARTIAL_IMPORT"
    smuggled = client.post(f"/vnexus/brands/{w['brand']}/prompts", json={"prompt_id": "x", "document": {**PROMPT, "source_text": "fake"}})
    assert smuggled.status_code == 422
    doc = dict(row["document"])
    doc["source_text"] = text + " edited"
    with transaction(write=True) as db:
        db.execute(f"UPDATE {table('vnexus_prompt_genomes')} SET document = ? WHERE prompt_version_id = ?",
                   (json_param(doc), row["prompt_version_id"]))
    assert client.post(f"/vnexus/prompts/{row['prompt_version_id']}/compile", json=_target(w)).status_code == 409


# --------------------------------------------------------------------------- immune system and twin


def _identity(w, deliverables):
    r = client.post(f"/vnexus/brands/{w['brand']}/production/identity",
                    json={**_target(w), "project_id": w["owner"], "deliverables": deliverables}, headers=headers())
    assert r.status_code == 200, r.text
    return r.json()


def test_immune_scan_detects_drift_after_a_genome_change_and_remediates_only_what_is_safe(approved):
    w = approved
    produced = _identity(w, ["monogram", "icon_family", "typography_specimen"])
    assert all(o["state"] == "QC_PASSED" for o in produced["outputs"])
    clean = client.post(f"/vnexus/brands/{w['brand']}/immune/scan", json=_target(w)).json()
    assert clean["healthy"] and clean["outputs_scanned"] == len(produced["outputs"])
    # Approve a nearby ink colour and a different display face.
    changed = document_from_flat({**FULL_DOC.flatten(), "visual.color.ink": "#1c1f24", "visual.typography.display": "Inter"},
                                 constraints=[c for c in FULL_DOC.constraints if c.constraint_id != "ink-lock"])
    _approve(w, _draft(w, "brand", w["brand"], changed))
    dirty = client.post(f"/vnexus/brands/{w['brand']}/immune/scan", json=_target(w)).json()
    codes = {f["code"] for f in dirty["findings"]}
    assert {"OFF_PALETTE_COLOUR", "STALE_GENOME_SOURCE", "UNAPPROVED_TYPEFACE"} <= codes and not dirty["healthy"]
    snappable = [f for f in dirty["findings"] if f["code"] == "OFF_PALETTE_COLOUR" and f["remediation"]]
    typeface = [f for f in dirty["findings"] if f["code"] == "UNAPPROVED_TYPEFACE"]
    assert snappable and snappable[0]["remediation"]["to"] == "#1c1f24"
    fix = client.post(f"/vnexus/brands/{w['brand']}/immune/remediate",
                      json={**_target(w), "finding_ids": [snappable[0]["finding_id"], typeface[0]["finding_id"], "fnd-unknown"]}).json()
    assert [a["kind"] for a in fix["applied"]] == ["SNAP_COLOUR"] and fix["applied"][0]["new_version"] == fix["applied"][0]["previous_version"] + 1
    assert {r["reason"] for r in fix["refused"]} == {"no deterministic, reversible repair exists", "not in the current scan"}
    after = client.post(f"/vnexus/brands/{w['brand']}/immune/scan", json=_target(w)).json()
    assert snappable[0]["finding_id"] not in {f["finding_id"] for f in after["findings"]}
    assert any(f["code"] == "ARTIFACT_CHANGED" for f in after["findings"])  # the repaired bytes differ from the produced hash, visibly


def test_immune_restores_missing_provenance_and_flags_tampering(approved):
    w = approved
    ad = client.post(f"/vnexus/brands/{w['brand']}/production/art-direction", json={**_target(w), "project_id": w["owner"],
                     "request": {"objective": "Launch", "medium": "POSTER"}}, headers=headers()).json()
    graph = client.get(f"/vnexus/brands/{w['brand']}/graph").json()
    edge = next(e for e in graph["edges"] if e["src_node_id"] == ad["graph_node"] and e["kind"] == "DERIVED_FROM")
    assert client.delete(f"/vnexus/brands/{w['brand']}/graph/edges/{edge['edge_id']}").status_code == 200
    scan = client.post(f"/vnexus/brands/{w['brand']}/immune/scan", json=_target(w)).json()
    missing = next(f for f in scan["findings"] if f["code"] == "MISSING_PROVENANCE")
    assert missing["remediation"]["kind"] == "LINK_PROVENANCE"
    fix = client.post(f"/vnexus/brands/{w['brand']}/immune/remediate", json={**_target(w), "finding_ids": [missing["finding_id"]]}).json()
    assert fix["applied"][0]["status"] == "APPLIED"
    assert "MISSING_PROVENANCE" not in {f["code"] for f in client.post(f"/vnexus/brands/{w['brand']}/immune/scan", json=_target(w)).json()["findings"]}
    audit = client.get(f"/vnexus/brands/{w['brand']}/audit").json()
    assert audit["verification"]["intact"] and any(e["action"] == "remediate" for e in audit["entries"])


def test_digital_twin_simulates_without_changing_anything(approved):
    w = approved
    _identity(w, ["monogram", "icon_family"])
    child = _approve(w, _draft(w, "project", w["owner"], document_from_flat(
        {"visual.color.accent": "#1d4ed8"}, constraints=[_c("accent-hex", "visual.color.accent", "HEX_COLOR")])))
    snap = client.get(f"/vnexus/brands/{w['brand']}/twin").json()
    assert {s["scope"] for s in snap["approved_scopes"]} == {"brand", "project"} and snap["produced_outputs"] >= 2
    before_versions = client.get(f"/vnexus/brands/{w['brand']}/versions").json()["versions"]
    safe = client.post(f"/vnexus/brands/{w['brand']}/twin/simulate", json={**_target(w), "changes": {"set": {"verbal.voice.tone": ["calm"]}}}).json()
    assert safe["projection"] == "WOULD_BE_PROMOTABLE" and safe["regeneration_needed"] >= 2 and "SIMULATION" in safe["label"]
    risky = client.post(f"/vnexus/brands/{w['brand']}/twin/simulate", json={**_target(w), "changes": {
        "set": {"visual.color.ink": "#999999"}, "add_constraints": [{"constraint_id": "accent-lock", "key": "visual.color.accent", "kind": "IMMUTABLE"}]}}).json()
    assert risky["projection"] == "WOULD_BLOCK"
    assert any(v["kind"] == "INVARIANT_CHANGED" for v in risky["own"]["invariant_violations"])
    project = next(d for d in risky["descendants"] if d["scope_ref"] == w["owner"])
    assert ["visual.color.accent", "IMMUTABLE_OVERRIDE"] in project["new_conflicts"]
    assert client.get(f"/vnexus/brands/{w['brand']}/versions").json()["versions"] == before_versions  # nothing was written
    assert child["status"] == "APPROVED"
    outage = client.get(f"/vnexus/projects/{w['owner']}/twin/provider-outage/local.chromium_raster").json()
    assert outage["blocked_capabilities"] == ["RASTER_PNG"] and "SIMULATION" in outage["label"]


def test_intelligence_routes_are_isolated(approved, monkeypatch):
    w = approved
    from services.langgraph.tests._project_os_support import as_user

    as_user(monkeypatch, "mallory", role="admin", tenant=f"tenant-other-{uuid4().hex[:6]}")
    assert client.post(f"/vnexus/brands/{w['brand']}/immune/scan", json=_target(w)).status_code == 404
    assert client.get(f"/vnexus/brands/{w['brand']}/twin").status_code == 404
    assert client.get(f"/vnexus/brands/{w['brand']}/prompts").status_code == 404
    assert client.post(f"/vnexus/projects/{w['owner']}/measurements", json={"campaign_ref": "c", "metric": "m", "value": 1, "unit": "u",
                                                                           "source": "s", "source_ref": "r", "observed_at": "2026-01-01"}).status_code == 403
