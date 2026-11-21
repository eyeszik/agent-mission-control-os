"""Brand OS 4.0 index and the newly written F01-F08 drafts: identity, provenance pinning and ordered steps."""

import hashlib
import json

import pytest
from pydantic import ValidationError

from services.langgraph.agency.sop.brand_os_source import (
    DATA_DIR,
    INDEX_FILE,
    BrandOsIndex,
    load_index,
    procedure_steps,
    summarize,
    verified_draft_bytes,
)

# Transcribed independently of the index file, from the owner-supplied identity list.
EXPECTED = """\
F01|D01|Founder DNA Interview
F02|D01|Brand Discovery Questionnaire
F03|D01|Customer Desire Mapping
F04|D01|Competitive Identity Audit
F05|D01|Category Opportunity Scanner
F06|D01|Research Confidence Ledger
F07|D02|Category Ownership Architect
F08|D02|Unique Value Proposition Builder
F09|D02|Brand Purpose Designer
F10|D02|Positioning Territory Generator
F11|D02|Brand Architecture Planner
F12|D02|Premium Value Strategist
F13|D03|Brand Naming Laboratory
F14|D03|Name Risk Screener
F15|D03|Tagline & Slogan Generator
F16|D03|Brand Story Architect
F17|D03|Voice Identity Compiler
F18|D03|Message Hierarchy Generator
F19|D04|Logo Concept Director
F20|D04|Brand Symbolism Laboratory
F21|D04|Typography Director
F22|D04|Color Psychology & Accessibility Studio
F23|D04|Packaging Design Strategist
F24|D04|Brand Guidelines Compiler
F25|D05|Emotional Decision Mapper
F26|D05|Jobs-to-Be-Done Interpreter
F27|D05|Objection Intelligence Engine
F28|D05|Trust Architecture Designer
F29|D05|Customer Identity Mapper
F30|D05|Customer Journey Emotion Audit
F31|D06|Hook Point Generator
F32|D06|Direct-Response Copywriter
F33|D06|Offer Architect
F34|D06|Campaign Concept Generator
F35|D06|Landing Page Strategist
F36|D06|Creative Experiment Designer
F37|D07|Multi-Platform Content Strategist
F38|D07|Short-Form Video Scriptwriter
F39|D07|Editorial Campaign Planner
F40|D07|Creative Prompt Engineer
F41|D07|Brand Voice Consistency Editor
F42|D07|Content Repurposing Engine
F43|D08|Website Brand Experience Architect
F44|D08|Conversion Journey Auditor
F45|D08|E-commerce Product Storyteller
F46|D08|Customer Onboarding Designer
F47|D08|Retention & Loyalty Strategist
F48|D08|Service Recovery Voice Designer
F49|D09|Go-to-Market Architect
F50|D09|Brand Extension Evaluator
F51|D09|Partnership & Collaboration Planner
F52|D09|Market Expansion Planner
F53|D09|Launch Campaign Director
F54|D09|Revenue Scenario Planner
F55|D10|Brand Health Dashboard Designer
F56|D11|AI Creative Review Board
F57|D11|Brand Consistency Auditor
F58|D11|Client Workflow Orchestrator
F59|D12|Marketing Experiment Analyst
F60|D12|Brand Risk & Compliance Reviewer"""
STEP_COUNTS = {"F01": 8, "F02": 8, "F03": 8, "F04": 7, "F05": 8, "F06": 8, "F07": 8, "F08": 8}


def _raw() -> dict:
    return json.loads(INDEX_FILE.read_text(encoding="utf-8"))


def test_all_sixty_identities_match_the_supplied_list_in_order():
    actual = [f"{e.sop_id}|{e.department_id}|{e.name}" for e in load_index().entries]
    assert actual == EXPECTED.splitlines()
    assert {e.sop_id for e in load_index().entries if e.batch == "BATCH_1"} == {f"F{n:02d}" for n in range(1, 13)}


def test_only_f01_to_f08_have_procedures_and_all_are_newly_authored_drafts():
    with_source = {e.sop_id: e for e in load_index().entries if e.procedure_source}
    assert sorted(with_source) == [f"F0{n}" for n in range(1, 9)]
    assert all(e.procedure_source.origin == "NEWLY_AUTHORED_SOP" for e in with_source.values())
    assert all(e.procedure_status == "SOURCE_UNAVAILABLE" for e in load_index().entries if e.sop_id not in with_source)
    assert _raw()["draft_pack"]["origin"] == "NEWLY_AUTHORED_SOP"


def test_every_pinned_digest_is_the_sha256_of_the_committed_draft_bytes():
    for entry in load_index().entries:
        if entry.procedure_source:
            data = (DATA_DIR / entry.procedure_source.path).read_bytes()
            assert hashlib.sha256(data).hexdigest() == entry.procedure_source.sha256, entry.sop_id
            assert b"Newly generated reconstruction; not a recovered historical original" in data
            assert verified_draft_bytes(entry) == data


def test_every_draft_has_its_ordered_steps_and_every_section_the_intake_needs():
    for sop_id, count in STEP_COUNTS.items():
        summary = summarize(sop_id)
        assert [s.sequence for s in summary.steps] == list(range(1, count + 1)), sop_id
        text = verified_draft_bytes(load_index().entry(sop_id)).decode("utf-8")
        for heading in ("## Purpose", "## Procedure", "## Output"):
            assert heading in text, (sop_id, heading)
        assert summary.original_authenticated is False and summary.runtime_authorized == "NOT_AUTHORIZED"
    assert summarize("F09").steps == () and summarize("F09").procedure_status == "SOURCE_UNAVAILABLE"


def test_step_extraction_rejects_gaps_reordering_and_missing_sections():
    with pytest.raises(ValueError, match="numbered 1..n"):
        procedure_steps("## Procedure\n1. a\n3. b\n## Output\n")
    with pytest.raises(ValueError, match="numbered 1..n"):
        procedure_steps("## Procedure\n2. a\n1. b\n")
    with pytest.raises(ValueError, match="no '## Procedure'"):
        procedure_steps("## Output\n1. a\n")
    with pytest.raises(ValueError, match="no numbered steps"):
        procedure_steps("## Procedure\nprose only\n## Output\n")
    steps = procedure_steps("## Procedure\n1. first\nnot a step\n2. second\n## Output\n3. not counted\n")
    assert [s.text for s in steps] == ["first", "second"]


def test_the_index_rejects_missing_duplicate_misbatched_or_mislabelled_entries():
    cases = [
        (lambda r: r["entries"].pop(), "F01-F60 exactly once"),
        (lambda r: r["entries"].__setitem__(1, r["entries"][0]), "F01-F60 exactly once"),
        (lambda r: r["entries"][20].__setitem__("batch", "BATCH_1"), "wrong batch"),
        (lambda r: r["entries"][0]["procedure_source"].__setitem__("origin", "ORIGINAL_CANONICAL_SOP"), "origin"),
        (lambda r: r["entries"][8].__setitem__("procedure_status", "NEWLY_AUTHORED_DRAFT"), "needs a procedure_source"),
        (lambda r: r["entries"][1].__setitem__("procedure_source", r["entries"][0]["procedure_source"]), "another SOP"),
        (lambda r: r.__setitem__("unexpected", True), "unexpected"),
    ]
    for mutate, message in cases:
        raw = _raw()
        mutate(raw)
        with pytest.raises(ValidationError, match=message):
            BrandOsIndex.model_validate(raw)


def test_a_draft_path_cannot_escape_the_data_directory(monkeypatch):
    entry = load_index().entry("F01")
    forged = entry.procedure_source.model_copy(update={"path": "brand_os/F01_x.md"})
    escaped = entry.model_copy(update={"procedure_source": forged.model_copy(update={"path": "brand_os/../../contracts.py"})})
    from services.langgraph.agency.sop.brand_os_source import draft_bytes

    with pytest.raises(PermissionError):
        draft_bytes(escaped)
