"""UCPO pure stages: brief -> requirements -> site IR -> source, lineage, coverage, linker, proof. No execution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from services.langgraph.agency.foundry import psem
from services.langgraph.agency.ucpo.contracts import BrowserVerification, CheckResult, WebsiteBrief
from services.langgraph.agency.ucpo.release import parse_ref, seal_proof, stale_reasons
from services.langgraph.agency.ucpo.requirements import compile_requirements, diff_requirements
from services.langgraph.agency.ucpo.semantic import IntentLinker, evaluate
from services.langgraph.agency.ucpo.site import check_colour_plan, colour_plan, compile_site
from services.langgraph.agency.ucpo.source import (
    SourcePolicyError,
    check_path,
    generate_source,
    pack_tree,
    reconcile_tree,
    scan,
    unpack_tree,
    verify_tree,
)

ROOT = Path(__file__).resolve().parents[3]
SAMPLE = json.loads((ROOT / "sample_ucpo_website.json").read_text())


def brief(**changes) -> WebsiteBrief:
    return WebsiteBrief.model_validate({**SAMPLE, **changes})


def line(b: WebsiteBrief | None = None):
    b = b or brief()
    pkg = compile_requirements(b, project_ref="prj-fixture")
    genome = psem.compile_psem_genome(psem.psem_brief(b.organization, seed=b.seed), project_id="prj-fixture")
    doc, css, sh = psem.compile_psem_tokens(genome)
    arch, ir = compile_site(b, pkg, genome, token_refs={"dtcg_source_hash": sh})
    files, manifest = generate_source(ir, genome, css)
    return b, pkg, genome, arch, ir, files, manifest


def rendered_from_source(pkg, ir, files) -> BrowserVerification:
    """A verification as the runner would record it for a faithful render (used to test the evaluator, not the browser)."""
    content = json.loads(files["content/site.json"])
    ev: dict[str, dict[str, list[str]]] = {}
    for page in ir.pages:
        e: dict[str, list[str]] = {"__title__": [content["pages"][page.page_id]["doc_title"]], "__lang__": [ir.locale],
                                   "req.lang": [ir.locale], "req.brand": [f"{ir.organization} -> /"],
                                   page.req_refs["page"]: [content["pages"][page.page_id]["doc_title"]]}
        for p in ir.pages:
            e[f"req.nav.{p.page_id}"] = [f"{p.title} -> {p.route}"]
        texts = [ir.organization]
        for s in page.sections:
            for field, ref in s.req_refs.items():
                if field.startswith("item:"):
                    it = s.items[int(field.split(":")[1])]
                    e[ref] = [it.title + (f" | {it.body}" if it.body else "")]
                elif field == "cta":
                    e[ref] = [f"{s.cta['label']} -> {s.cta['href']}"]
                elif field == "image":
                    e[ref] = [content["images"][s.image]["alt"]]
                else:
                    e[ref] = [getattr(s, field)]
                texts += e[ref]
        e["__text__"] = [" ".join(texts)]
        ev[page.route] = e
    checks = tuple(CheckResult(check=c, route=r.route, result="PASS", req_refs=(ref,))
                   for r in ir.pages for c, ref in (("axe", "req.a11y.automated"), ("reflow", "req.responsive.reflow"),
                                                   ("text_zoom_200", "req.text.zoom"), ("reduced_motion", "req.motion.reduced"),
                                                   ("keyboard_focus", "req.keyboard.focus"), ("console_clean", "req.console.clean"),
                                                   ("no_external_requests", "req.network.none"), ("psem_colours", "req.psem.colour")))
    return BrowserVerification(status="PASSED", build_output_hash="b" * 64, browser={"name": "fixture"}, checks=checks,
                               dom_evidence=ev)


# ------------------------------------------------------------------ brief and requirements


@pytest.mark.parametrize("change", [
    {"pages": [{**SAMPLE["pages"][1]}]},                                             # no index page
    {"cta_target": "https://evil.invalid/x"},                                        # external CTA
    {"cta_target": "visit#nowhere"},                                                 # unknown anchor
    {"cta_label": ""},                                                               # a section carries a CTA without a label
    {"required_phrases": ["made slowly"], "forbidden_phrases": ["slowly"]},          # contradictory phrase rules
    {"images": [{"asset_id": "plate-kiln", "alt": "x", "rights": "licensed"}]},      # licensed without a licence ref
])
def test_brief_refuses_inconsistent_or_unsafe_input(change):
    with pytest.raises(ValidationError):
        brief(**change)


def test_requirement_ids_are_structural_and_stable_across_copy_edits():
    a = compile_requirements(brief(), project_ref="p")
    pages = json.loads(json.dumps(SAMPLE["pages"]))
    pages[0]["sections"][1]["heading"] = "One clay body, four glazes"
    b = compile_requirements(brief(pages=pages), project_ref="p")
    assert [r.req_id for r in a.requirements] == [r.req_id for r in b.requirements]
    assert diff_requirements(a, b) == {"added": [], "removed": [], "changed": ["req.index.s2.heading"]}
    assert IntentLinker.compare(a, b)["details"]["req.index.s2.heading"]["after"]["text"] == "One clay body, four glazes"


def test_every_brief_promise_becomes_a_requirement():
    pkg = compile_requirements(brief(), project_ref="p")
    kinds = {r.kind for r in pkg.requirements}
    assert {"SECTION_HEADING", "ITEM_TEXT", "CTA", "IMAGE_ALT", "IMAGE_RIGHTS", "REQUIRED_PHRASE", "FORBIDDEN_PHRASE",
            "A11Y_AUTOMATED", "NO_EXTERNAL_REQUESTS", "PSEM_COLOUR"} <= kinds
    texts = {r.subject.get("text") for r in pkg.requirements}
    for page in SAMPLE["pages"]:
        for s in page["sections"]:
            assert s["heading"] in texts and all(i["title"] in texts for i in s.get("items", []))


# ------------------------------------------------------------------ site IR and PSEM


def test_site_ir_copies_brief_text_verbatim_and_alternates_psem_grounds():
    b, pkg, genome, arch, ir, *_ = line()
    home = ir.pages[0]
    assert [s.scheme for s in home.sections] == ["charcoal", "paper", "charcoal", "paper"]
    assert home.sections[0].heading == SAMPLE["pages"][0]["sections"][0]["heading"]
    assert all(s.accent == "none" for s in home.sections if s.scheme == "paper")
    assert {s.accent for s in home.sections if s.scheme == "charcoal"} == {"signal_red"}  # one accent per page
    assert not check_colour_plan(ir)
    assert ir.verification_contract and arch.navigation == ("index", "works", "visit")
    assert ir.pages[2].sections[0].section_id == "hours" and home.sections[0].cta["href"] == "/visit/#hours"


def test_colour_plan_never_puts_an_accent_on_paper():
    for scheme in ("paper", "charcoal"):
        for accent in ("signal_red", "amber", "none"):
            for fg, bg, use, _ in colour_plan(scheme, accent if scheme == "charcoal" else "none"):
                psem.check_usage(fg, bg, use)
                assert not (fg in psem.ACCENTS and bg == "paper")


def test_illegal_ir_colours_are_reported():
    *_, ir, _, _ = line()
    bad_page = ir.pages[0].model_copy(update={"sections": tuple(
        s.model_copy(update={"accent": "amber"}) if i == 2 else s for i, s in enumerate(ir.pages[0].sections))})
    bad = ir.model_copy(update={"pages": (bad_page, *ir.pages[1:])})
    assert any("one accent per composition" in e for e in check_colour_plan(bad))


# ------------------------------------------------------------------ source policy


def test_source_is_deterministic_hashed_and_carries_requirement_ids():
    *_, files, manifest = line()
    *_, files2, manifest2 = line()
    assert files == files2 and manifest == manifest2 and not verify_tree(files, manifest)
    assert "data-req={s.req_refs.heading}" in files["components/Section.tsx"].decode()
    content = json.loads(files["content/site.json"])
    assert content["pages"]["index"]["sections"][0]["req_refs"]["heading"] == "req.index.s1.heading"
    assert json.loads(files["package.json"])["dependencies"]["next"] == "16.4.2"
    assert set(files) >= {"app/page.tsx", "app/works/page.tsx", "app/visit/page.tsx", "public/assets/plate-kiln.svg"}


@pytest.mark.parametrize("path", ["../etc/passwd", "/abs.ts", "app/../../x.ts", "scripts/x.ts", "evil.sh", "app\\x.ts", "app/./x.tsx"])
def test_unsafe_paths_are_refused(path):
    with pytest.raises(SourcePolicyError):
        check_path(path)


@pytest.mark.parametrize("code", ["<div dangerouslySetInnerHTML={{__html: x}} />", "eval('1')", "new Function('x')",
                                  "fetch('/x')", "const c = require('child_process')", "process.env.SECRET",
                                  "const u = 'https://cdn.evil.invalid/x.js'", "import('./x')", "@import url(x.css);"])
def test_forbidden_code_constructs_are_found(code):
    assert scan("components/X.tsx" if not code.startswith("@") else "app/x.css", code.encode())


@pytest.mark.parametrize("svg", ['<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
                                 '<svg xmlns="http://www.w3.org/2000/svg" onload="x()"></svg>',
                                 '<svg xmlns="http://www.w3.org/2000/svg"><image href="https://x.invalid/a.png"/></svg>'])
def test_svg_assets_with_active_or_external_content_are_found(svg):
    assert scan("public/assets/x.svg", svg.encode())


def test_bundle_round_trip_rejects_tampering():
    *_, files, manifest = line()
    out, m = unpack_tree(pack_tree(files, manifest))
    assert out == files and m == manifest
    tampered = json.loads(pack_tree(files, manifest))
    tampered["files"]["components/Section.tsx"] += "\neval('1')\n"
    with pytest.raises(SourcePolicyError):
        unpack_tree(json.dumps(tampered).encode())
    tampered = json.loads(pack_tree(files, manifest))
    tampered["files"]["content/site.json"] = tampered["files"]["content/site.json"].replace("Stoneware", "Ironware")
    with pytest.raises(SourcePolicyError, match="changed content/site.json"):
        unpack_tree(json.dumps(tampered).encode())


def test_regeneration_preserves_human_edits(tmp_path):
    from services.langgraph.agency.ucpo.source import export_tree

    *_, files, manifest = line()
    first = export_tree(tmp_path, files)
    assert len(first["write"]) == len(files)
    edited = tmp_path / "components" / "SiteFooter.tsx"
    edited.write_text(edited.read_text() + "\n// edited by a person\n")
    pages = json.loads(json.dumps(SAMPLE["pages"]))
    pages[0]["sections"][0]["body"] = "Halden Fen is a two-person studio in a fictional town."
    *_, files2, manifest2 = line(brief(pages=pages))
    plan = export_tree(tmp_path, files2, manifest)
    assert plan["preserved"] == ["components/SiteFooter.tsx"] and plan["conflicts"] == []
    assert "content/site.json" in plan["write"]
    assert "edited by a person" in edited.read_text()
    assert reconcile_tree(manifest, {"UCPO.md": b"mine"}, {"UCPO.md": b"theirs"})["conflicts"] == ["UCPO.md"]


# ------------------------------------------------------------------ coverage and the intent linker


def test_coverage_is_unresolved_until_rendered_and_never_counts_not_run():
    b, pkg, genome, arch, ir, files, manifest = line()
    report, _ = evaluate(pkg, arch=arch, ir=ir, files=files, manifest=manifest)
    assert report.release_blocked and report.coverage < 1
    assert all(e.status == "UNRESOLVED" for e in report.entries if "rendered" in e.stages and e.stages["rendered"] == "NOT_RUN")
    full, _ = evaluate(pkg, arch=arch, ir=ir, files=files, manifest=manifest, verification=rendered_from_source(pkg, ir, files))
    assert full.coverage == 1.0 and not full.release_blocked and not full.debt


def test_loss_is_located_at_the_first_stage_that_lost_it():
    b, pkg, genome, arch, ir, files, manifest = line()
    v = rendered_from_source(pkg, ir, files)
    ev = {r: dict(e) for r, e in v.dom_evidence.items()}
    ev["/"].pop("req.index.s3.item1")                                   # omitted in the DOM
    ev["/"]["req.index.s1.heading"] = ["Stoneware, made quickly."]       # changed in the DOM
    v = v.model_copy(update={"dom_evidence": ev})
    report, _ = evaluate(pkg, arch=arch, ir=ir, files=files, manifest=manifest, verification=v)
    entries = {e.req_id: e for e in report.entries}
    assert entries["req.index.s3.item1"].status == "OMITTED" and entries["req.index.s3.item1"].loss_stage == "rendered"
    assert entries["req.index.s1.heading"].status == "UNAPPROVED_CHANGE"
    assert report.release_blocked and {d.req_id for d in report.debt} == {"req.index.s3.item1", "req.index.s1.heading"}
    approved, _ = evaluate(pkg, arch=arch, ir=ir, files=files, manifest=manifest, verification=v,
                           approved_changes={"req.index.s1.heading": "approval:fixture"})
    assert {e.req_id: e.status for e in approved.entries}["req.index.s1.heading"] == "APPROVED_CHANGE"
    # A source-stage loss is located at source, not rendered.
    content = json.loads(files["content/site.json"])
    content["pages"]["works"]["sections"][1]["items"] = content["pages"]["works"]["sections"][1]["items"][:2]
    broken = {**files, "content/site.json": json.dumps(content).encode()}
    report2, _ = evaluate(pkg, arch=arch, ir=ir, files=broken, manifest=manifest)
    assert {e.req_id: e.loss_stage for e in report2.entries}["req.works.s2.item2"] == "source"


def test_forbidden_phrase_and_failed_check_block_release():
    b, pkg, genome, arch, ir, files, manifest = line()
    v = rendered_from_source(pkg, ir, files)
    ev = {r: dict(e) for r, e in v.dom_evidence.items()}
    ev["/works/"]["__text__"] = [ev["/works/"]["__text__"][0] + " The best in the world."]
    checks = tuple(c.model_copy(update={"result": "FAIL", "detail": "color-contrast"}) if c.check == "axe" and c.route == "/"
                   else c for c in v.checks)
    report, _ = evaluate(pkg, arch=arch, ir=ir, files=files, manifest=manifest,
                         verification=v.model_copy(update={"dom_evidence": ev, "checks": checks}))
    st = {e.req_id: e.status for e in report.entries}
    assert st["req.forbid.1"] == "UNAPPROVED_CHANGE" and st["req.a11y.automated"] == "UNAPPROVED_CHANGE"


def test_intent_linker_traces_inspects_and_proposes_without_applying():
    b, pkg, genome, arch, ir, files, manifest = line()
    v = rendered_from_source(pkg, ir, files)
    report, _ = evaluate(pkg, arch=arch, ir=ir, files=files, manifest=manifest, verification=v)
    L = IntentLinker(pkg, report, ir=ir, manifest=manifest, verification=v)
    t = L.trace("req.index.s1.cta")
    assert t["ir"] == ["section:index-s1.cta"] and "content/site.json" in t["source"]
    assert t["rendered"]["/"] == ["Plan a studio visit -> /visit/#hours"]
    assert {r["req_id"] for r in L.inspect("hours")["requirements"]} >= {"req.visit.s1.heading", "req.visit.s1.item0"}
    impact = L.impact_analysis(["req.visit.s1.heading"])
    assert impact["routes"] == ["/visit/"] and "release_proof" in impact["regenerate"]
    assert L.find_omissions() == [] and L.propose_repair("req.index.s1.cta")["proposal"] is None
    blocked, _ = evaluate(pkg, arch=arch, ir=ir, files=files, manifest=manifest)
    L2 = IntentLinker(pkg, blocked, ir=ir, manifest=manifest)
    repair = L2.propose_repair("req.a11y.automated")
    assert repair["applied"] is False and repair["proposal"]
    with pytest.raises(KeyError):
        L.trace("req.invented")


# ------------------------------------------------------------------ release proof


def test_release_proof_is_eligible_only_when_every_gate_passes_and_never_deploys():
    from services.langgraph.agency.ucpo.contracts import BuildResult

    b, pkg, genome, arch, ir, files, manifest = line()
    v = rendered_from_source(pkg, ir, files)
    full, _ = evaluate(pkg, arch=arch, ir=ir, files=files, manifest=manifest, verification=v)
    build = BuildResult(status="PASSED", source_tree_hash=manifest.tree_hash, isolation={}, steps=(), dependency_manifest={},
                        output_hash="b" * 64)
    refs = {"source": "artifact:a1@v2"}
    ok = seal_proof(project_ref="p", site_id="s", revisions={}, artifact_refs=refs, build=build, qa=v, coverage=full)
    assert ok.eligible_for_approval and ok.deployment == "NOT_AUTHORIZED"
    blocked = seal_proof(project_ref="p", site_id="s", revisions={}, artifact_refs=refs,
                         build=build.model_copy(update={"status": "BLOCKED_ISOLATION", "output_hash": None}), qa=None, coverage=full)
    assert not blocked.eligible_for_approval and "isolation:BLOCKED" in blocked.reasons and "browser_qa:NOT_RUN" in blocked.reasons
    other = seal_proof(project_ref="p", site_id="s", revisions={}, artifact_refs=refs, build=build,
                       qa=v.model_copy(update={"build_output_hash": "c" * 64}), coverage=full)
    assert not other.eligible_for_approval
    assert parse_ref("artifact:prj-x:foundry-ucpo-s-source@v12") == ("prj-x:foundry-ucpo-s-source", 12)
    heads = {"a1": {"version": 3, "status": "draft"}}
    assert stale_reasons(ok, heads.get) == ["PROOF_STALE:source: v2 -> v3"]
    assert stale_reasons(ok, {"a1": {"version": 2, "status": "invalidated"}}.get)[0].startswith("PROOF_STALE:source")
