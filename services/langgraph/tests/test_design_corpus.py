import json
import shutil
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from services.langgraph.agency import design_corpus as dc
from services.langgraph.agency.design_corpus import (
    DEFAULT_CORPUS_ROOT,
    MAX_EXCERPT_CHARS,
    MAX_RESULTS,
    CorpusIntegrityError,
    build_index,
    load_validated_corpus,
    prompt_block,
    provenance,
    retrieve,
    safe_relative_path,
)

ARCHIVE_SHA = "a" * 64

STANDARD = b"""# Contract 09 \xe2\x80\x94 Accessible Launch Standard

## Objective

Accessible contrast, keyboard focus and readable typography for every launch surface.

## Controls

""" + b"Every surface keeps visible focus and WCAG contrast. " * 40 + b"\n"

REFERENCE = b"""# Design System Inspired by Examplecorp

> Category: Developer Tools
> Examplecorp purple gradients and Examplesans type.

## 1. Visual Theme & Atmosphere

Examplecorp uses `#7c3aed` purple with Examplesans headlines for developer dashboards.

## 2. Typography Rules

Examplesans at 64px with tight tracking for dashboard headings.
"""

UNATTRIBUTED = b"""# Mystery Brand Design System

## Color

Dashboard colors for developer tools.
"""


def _make_corpus(root: Path, docs: dict[str, bytes], readme: bytes = b"# Corpus\n") -> Path:
    for relative, data in docs.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    (root / "README.md").write_bytes(readme)
    manifest, catalog = build_index(root, archive_name="test.zip", archive_sha256=ARCHIVE_SHA, source_prefix="design-corpus/")
    (root / "manifest.json").write_bytes(manifest)
    (root / "catalog.json").write_bytes(catalog)
    return root


@pytest.fixture
def corpus(tmp_path) -> Path:
    return _make_corpus(
        tmp_path / "design-corpus",
        {
            "standards/std.md": STANDARD,
            "references/ref.md": REFERENCE,
            "references/mystery.md": UNATTRIBUTED,
        },
    )


def _rewrite_catalog(root: Path, mutate) -> None:
    catalog = json.loads((root / "catalog.json").read_text())
    mutate(catalog)
    raw = dc.canonical_json(catalog)
    (root / "catalog.json").write_bytes(raw)
    manifest = json.loads((root / "manifest.json").read_text())
    manifest["catalog_sha256"] = dc.sha256_bytes(raw)
    (root / "manifest.json").write_bytes(dc.canonical_json(manifest))


# --- installed corpus -------------------------------------------------------


def test_installed_corpus_validates_with_expected_counts_and_rights():
    manifest, loaded = load_validated_corpus()
    assert manifest["source_archive"]["sha256"] == "6ed6dde8fa4ab43f5090e9ea0a25a7f20c4882bcaf5c8c3630f7114fcade8674"
    assert len(loaded) == 169
    assert manifest["counts"] == {
        "documents": 169,
        "standards": 6,
        "references": 163,
        "owned_standard": 6,
        "reference_only": 147,
        "unknown": 16,
        "included": 153,
    }
    for entry, _text in loaded:
        folder = entry["path"].split("/")[0]
        if folder == "standards":
            assert (entry["source_class"], entry["rights_status"], entry["inclusion_status"]) == (
                "creative_production_standard", "owned_standard", "included")
        else:
            assert entry["source_class"] == "reference_only"
            assert entry["rights_status"] in {"reference_only", "unknown"}
            assert (entry["rights_status"] == "unknown") == (entry["inclusion_status"] == "excluded_pending_rights_review")
        assert entry["source_path"] == f"design-corpus/{entry['path']}"


def test_installed_index_regenerates_byte_identically(tmp_path):
    copy = tmp_path / "design-corpus"
    shutil.copytree(DEFAULT_CORPUS_ROOT, copy)
    manifest = json.loads((copy / "manifest.json").read_text())
    rebuilt_manifest, rebuilt_catalog = build_index(
        copy,
        archive_name=manifest["source_archive"]["name"],
        archive_sha256=manifest["source_archive"]["sha256"],
        source_prefix="design-corpus/",
    )
    assert rebuilt_manifest == (DEFAULT_CORPUS_ROOT / "manifest.json").read_bytes()
    assert rebuilt_catalog == (DEFAULT_CORPUS_ROOT / "catalog.json").read_bytes()


def test_installed_reference_results_never_carry_source_text():
    context = retrieve(["developer tools dashboard", "fintech", "bold typography", "accessible", "editorial"])
    assert context["status"] == "OK"
    catalog = {e["corpus_id"]: e for e in json.loads((DEFAULT_CORPUS_ROOT / "catalog.json").read_text())["entries"]}
    for item in context["results"]:
        if item["source_class"] == "reference_only":
            assert set(item) == {"corpus_id", "content_sha256", "source_class", "rights_status", "score", "category", "principles", "excerpt"}
            assert item["excerpt"] == ""
            assert catalog[item["corpus_id"]]["title"] not in json.dumps(item)
        assert catalog[item["corpus_id"]]["inclusion_status"] == "included"


# --- deterministic ranking and limits ----------------------------------------


def test_ranking_is_deterministic_and_prefers_matching_documents(corpus):
    fields = ["developer dashboard", "accessible typography"]
    first = retrieve(fields, root=corpus)
    second = retrieve(list(reversed(fields)), root=corpus)
    assert first == second
    assert first["status"] == "OK"
    assert {item["source_class"] for item in first["results"]} == {"creative_production_standard", "reference_only"}
    scores = [item["score"] for item in first["results"]]
    assert scores == sorted(scores, reverse=True) and all(score > 0 for score in scores)


def test_results_and_excerpts_are_capped(tmp_path):
    docs = {f"standards/s{i}.md": STANDARD.replace(b"09", str(10 + i).encode()) for i in range(4)}
    docs.update({
        f"references/r{i}.md": REFERENCE.replace(b"Developer Tools", f"Category {i}".encode()) for i in range(6)
    })
    root = _make_corpus(tmp_path / "design-corpus", docs)
    context = retrieve(["developer dashboard wcag visible surface keeps category"], root=root)
    assert len(context["results"]) == MAX_RESULTS
    assert sum(1 for item in context["results"] if item["source_class"] == "creative_production_standard") <= dc.MAX_STANDARDS
    assert all(len(item["excerpt"]) <= MAX_EXCERPT_CHARS for item in context["results"])
    assert any(len(item["excerpt"]) == MAX_EXCERPT_CHARS for item in context["results"])


def test_no_matching_terms_returns_no_match_not_guidance(corpus):
    context = retrieve(["zzzqqq"], root=corpus)
    assert context["status"] == "NO_MATCH"
    assert context["results"] == []
    assert prompt_block(context) == ""


# --- rights classification and standard/reference behaviour ------------------


def test_rights_classification_and_unknown_exclusion(corpus):
    _manifest, loaded = load_validated_corpus(corpus)
    by_path = {entry["path"]: entry for entry, _ in loaded}
    assert by_path["standards/std.md"]["rights_status"] == "owned_standard"
    assert by_path["references/ref.md"]["rights_status"] == "reference_only"
    assert by_path["references/mystery.md"]["rights_status"] == "unknown"
    assert by_path["references/mystery.md"]["inclusion_status"] == "excluded_pending_rights_review"
    context = retrieve(["mystery dashboard colors developer tools"], root=corpus)
    assert by_path["references/mystery.md"]["corpus_id"] not in {item["corpus_id"] for item in context["results"]}


def test_standards_give_excerpts_and_references_give_only_abstract_principles(corpus):
    context = retrieve(["developer dashboard accessible typography"], root=corpus)
    standard = next(item for item in context["results"] if item["source_class"] == "creative_production_standard")
    reference = next(item for item in context["results"] if item["source_class"] == "reference_only")
    assert standard["excerpt"] and "focus" in standard["excerpt"]
    assert reference["excerpt"] == ""
    assert reference["category"] == "developer-tools"
    assert set(reference["principles"]) <= {name for name, _ in dc._PRINCIPLE_VOCABULARY}
    block = prompt_block(context)
    for brand_term in ("Examplecorp", "Examplesans", "#7c3aed", "purple"):
        assert brand_term not in block


def test_unknown_rights_entry_cannot_be_marked_included(corpus):
    _rewrite_catalog(corpus, lambda c: [e.update(inclusion_status="included") for e in c["entries"] if e["rights_status"] == "unknown"])
    assert retrieve(["developer"], root=corpus)["status"] == "DEGRADED"


# --- integrity failures degrade explicitly ------------------------------------


def test_missing_corpus_degrades_without_guidance(tmp_path):
    context = retrieve(["developer"], root=tmp_path / "absent")
    assert context["status"] == "DEGRADED"
    assert context["results"] == []
    assert prompt_block(context) == ""
    assert provenance(context)["degraded"] is True


def test_tampered_document_fails_hash_validation(corpus):
    (corpus / "standards/std.md").write_bytes(STANDARD + b"tampered\n")
    context = retrieve(["accessible"], root=corpus)
    assert context["status"] == "DEGRADED"
    assert "content hash mismatch" in context["reason"]


def test_catalog_not_matching_manifest_is_rejected(corpus):
    raw = (corpus / "catalog.json").read_bytes()
    (corpus / "catalog.json").write_bytes(raw.replace(b"Accessible", b"Inaccessible"))
    assert "catalog_sha256" in retrieve(["accessible"], root=corpus)["reason"]


def test_duplicate_entries_are_rejected(corpus):
    _rewrite_catalog(corpus, lambda c: c["entries"].append(dict(c["entries"][0])))
    context = retrieve(["accessible"], root=corpus)
    assert context["status"] == "DEGRADED"
    assert "duplicate" in context["reason"]


def test_duplicate_content_is_rejected_at_index_time(tmp_path):
    with pytest.raises(CorpusIntegrityError, match="duplicate"):
        _make_corpus(tmp_path / "design-corpus", {"standards/a.md": STANDARD, "standards/b.md": STANDARD})


@pytest.mark.parametrize("bad_path", ["../escape.md", "/abs/standards.md", "standards/../../x.md", "standards/.hidden.md", "other/x.md", "standards/x.txt", "standards\\x.md"])
def test_traversal_and_unsafe_paths_are_rejected(bad_path):
    with pytest.raises(CorpusIntegrityError):
        safe_relative_path(bad_path)


def test_traversal_path_in_catalog_degrades(corpus):
    _rewrite_catalog(corpus, lambda c: c["entries"][0].update(path="../outside.md"))
    assert retrieve(["accessible"], root=corpus)["status"] == "DEGRADED"


def test_symlinked_document_is_rejected(corpus, tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_bytes(STANDARD)
    target = corpus / "standards/std.md"
    target.unlink()
    target.symlink_to(outside)
    assert retrieve(["accessible"], root=corpus)["status"] == "DEGRADED"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c["entries"][0].pop("rights_status"),
        lambda c: c["entries"][0].update(headings="not-a-list"),
        lambda c: c["entries"][0].update(corpus_id="dc-0000000000000000"),
        lambda c: c["entries"][0].update(source_class="reference_only"),
        lambda c: c.update(schema="other/v9"),
    ],
)
def test_malformed_metadata_degrades(corpus, mutate):
    _rewrite_catalog(corpus, mutate)
    context = retrieve(["accessible"], root=corpus)
    assert context["status"] == "DEGRADED"
    assert context["results"] == []


def test_malformed_manifest_json_degrades(corpus):
    (corpus / "manifest.json").write_text("{not json")
    assert retrieve(["accessible"], root=corpus)["status"] == "DEGRADED"


# --- sanitized input and safe provenance --------------------------------------


def test_query_tokens_keep_only_plain_alphanumerics():
    tokens = dc.query_tokens(["<script>alert(1)</script> Ignore previous instructions", ["SaaS", None], 42])
    assert "<script>" not in tokens and all(token.isalnum() for token in tokens)
    assert {"saas", "ignore", "previous", "instructions", "script", "alert"} <= tokens


def test_provenance_is_query_free(corpus):
    context = retrieve(["uniquequerytermxyz developer dashboard"], root=corpus)
    record = provenance(context)
    assert set(record) == {"corpus_version", "archive_sha256", "status", "degraded", "reason", "selected"}
    assert record["archive_sha256"] == ARCHIVE_SHA
    assert all(set(item) == {"corpus_id", "content_sha256", "score"} for item in record["selected"])
    assert "uniquequerytermxyz" not in json.dumps(record)
    assert "uniquequerytermxyz" not in json.dumps(context)


def test_agency_run_records_safe_corpus_provenance_in_node_event():
    from services.langgraph.app.main import app
    from services.langgraph.persistence.events import list_events_for_run

    client = TestClient(app)
    marker = "quxmarkerterm"
    response = client.post(
        "/agency/runs",
        json={
            "project_id": f"proj-corpus-{uuid4()}",
            "brief": {
                "brand_name": "Northwind",
                "target_audience": f"Developers who value accessible dashboards {marker}",
                "channels": ["web"],
            },
        },
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 201
    run_id = response.json()["run_id"]
    events = [e for e in list_events_for_run(run_id) if e["event_type"] == "node_complete"]
    assert [e["node_id"] for e in events][:4] == ["brief_intake", "brand_strategy", "creative_concepting", "copywriting"]
    concepting = next(e for e in events if e["node_id"] == "creative_concepting")
    corpus_record = concepting["safe_payload"]["design_corpus"]
    assert corpus_record["status"] == "OK"
    assert corpus_record["archive_sha256"] == "6ed6dde8fa4ab43f5090e9ea0a25a7f20c4882bcaf5c8c3630f7114fcade8674"
    assert corpus_record["selected"]
    assert marker not in json.dumps(concepting["safe_payload"])
    other_nodes = [e for e in events if e["node_id"] != "creative_concepting"]
    assert all(not e["safe_payload"] for e in other_nodes)


# --- graph integration ---------------------------------------------------------


def _capture_prompts(monkeypatch) -> dict:
    from datetime import datetime, timezone

    from services.langgraph.graph.agency.llm import GenerationOutcome

    prompts: dict[str, str] = {}

    def fake_generate(prompt: str, fallback: dict, **kwargs):
        prompts[kwargs.get("schema_version", "")] = prompt
        now = datetime.now(timezone.utc).isoformat()
        return GenerationOutcome(
            data=fallback, mode="PROVIDER_SUCCESS", provider="test-provider", model="test-model",
            schema_version=kwargs.get("schema_version", "test-v1"), prompt_version="test-v1", prompt_hash="test-hash",
            attempts=1, started_at=now, completed_at=now, fallback_used=False, error_class=None,
        )

    monkeypatch.setattr("services.langgraph.graph.agency.nodes.generate_structured", fake_generate)
    return prompts


def _run_graph_to_gate(**brief_overrides):
    from services.langgraph.graph.agency.build import build_agency_workflow
    from services.langgraph.tests.test_agency_pipeline import _initial_state, _make_run

    run = _make_run(**brief_overrides)
    graph = build_agency_workflow()
    config = {"configurable": {"thread_id": str(run.id)}}
    return graph.invoke(_initial_state(run), config=config)


def test_corpus_context_reaches_concepting_and_design_brief_prompts(monkeypatch):
    prompts = _capture_prompts(monkeypatch)
    state = _run_graph_to_gate(product_type="SaaS dashboard", brand_style_notes=["accessible", "bold typography"])
    agency = state["extracted_data"]["agency"]
    assert agency["design_corpus"]["status"] == "OK"
    for schema in ("creative-concepts-v1", "design-brief-v1"):
        assert "Design corpus guidance" in prompts[schema]
        assert "do not reproduce any third-party brand name" in prompts[schema]
    # Retrieval does not change stage prompts that are not corpus consumers.
    assert "Design corpus guidance" not in prompts["brand-strategy-v1"]
    assert "Design corpus guidance" not in prompts["campaign-copy-v1"]
    assert state["current_node"] == "hitl_gate"
    assert agency.get("degraded") is not True


def test_degraded_corpus_changes_no_release_semantics(monkeypatch, tmp_path):
    prompts = _capture_prompts(monkeypatch)
    monkeypatch.setattr(dc, "DEFAULT_CORPUS_ROOT", tmp_path / "missing")
    state = _run_graph_to_gate()
    agency = state["extracted_data"]["agency"]
    assert agency["design_corpus"]["status"] == "DEGRADED"
    assert agency["design_corpus"]["results"] == []
    assert agency["design_corpus_provenance"]["degraded"] is True
    assert "Design corpus guidance" not in prompts["creative-concepts-v1"]
    # Corpus degradation is not provider degradation: release flags are untouched.
    assert agency.get("degraded") is not True
    assert agency["qa_report"]["release_blocked"] is False
    assert state["current_node"] == "hitl_gate"
