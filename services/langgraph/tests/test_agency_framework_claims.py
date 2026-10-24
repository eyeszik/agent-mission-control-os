"""Short marketing claims: detection, then substantiation, then policy, then a person.

The Project OS knowledge extractor ignores sentences under six words, which is
right for ingesting sources and wrong for marketing copy, where "Free" or
"Save 30%" is a whole claim. ``claims.detect_claims`` finds claims by their
signals, not their length; it never decides whether a claim is true, never
rejects copy and never approves it. All copy here is fictional.
"""

from __future__ import annotations

import pytest

from services.langgraph.agency.operating_framework import claims
from services.langgraph.tests.framework_support import (
    afw,  # noqa: F401 - fixture
    artifact,
    client,
    create_project,
    evidence,
    instantiate,
    key,
    ok,
)


def _one(text: str) -> claims.Claim:
    found = claims.detect_claims(text)
    assert len(found) == 1, (text, found)
    return found[0]


@pytest.mark.parametrize(("text", "expected"), [
    ("Free", {"PRICE"}),
    ("Best", {"ABSOLUTE"}),
    ("Guaranteed", {"ABSOLUTE"}),
    ("Save 30%", {"PRICE", "QUANTIFIED"}),
    ("No fees", {"PRICE"}),
    ("Carbon neutral", {"ENVIRONMENTAL"}),
    ("Fast", {"SUBJECTIVE"}),
])
def test_each_supplied_short_claim_is_detected_with_its_class(text, expected):
    claim = _one(text)
    assert set(claim.classes) == expected, claim


def test_a_short_claim_and_its_long_equivalent_get_the_same_classes():
    for short, long in [
        ("Free", "Every order from the fictional shop ships to you completely free of charge."),
        ("Save 30%", "Customers who switch to the annual plan save 30% compared with paying monthly."),
        ("Carbon neutral", "Our whole fictional supply chain has been certified carbon neutral since this spring."),
    ]:
        assert set(_one(short).classes) <= set(_one(long).classes) | {"FACTUAL"}, (short, long)


def test_substantiation_and_policy_are_separate_from_detection():
    free, best, fast = _one("Free"), _one("Best"), _one("Fast")
    assert free.substantiation == "EVIDENCE_REQUIRED" and free.policy_route == "HUMAN_REVIEW"
    assert best.substantiation == "EVIDENCE_REQUIRED"
    # Puffery still goes to a person, but it is not something a document can prove.
    assert fast.substantiation == "REVIEW_AS_OPINION" and fast.policy_route == "HUMAN_REVIEW"
    for claim in (free, best, fast):
        assert claim.decision == "NONE: detection only; a person decides"


def test_qualifiers_disclaimers_and_quotations_are_recorded_not_dropped():
    qualified = _one("Free shipping on orders over $50*")
    assert {"PRICE", "QUANTIFIED", "QUALIFIED"} <= set(qualified.classes)
    assert "*" in qualified.qualifiers and "on orders over" in qualified.qualifiers
    upto = _one("Save up to 30%")
    assert "QUALIFIED" in upto.classes and "up to" in upto.qualifiers
    quote = _one("“Best tea I have ever had,” said a fictional customer.")
    assert "THIRD_PARTY_QUOTE" in quote.classes and "ABSOLUTE" in quote.classes
    assert quote.policy_route == "HUMAN_REVIEW"  # a quotation repeats a claim; it does not substantiate it


def test_unicode_and_punctuation_variants_normalise_to_the_same_claim():
    assert _one("Ｆｒｅｅ").normalized == _one("Free").normalized == "free"  # fullwidth
    assert _one("Free!").normalized == _one("Free.").normalized == "free"
    assert _one("Guaranteed™").classes == _one("Guaranteed").classes
    assert _one("Carbon neutral").normalized == "carbon neutral"
    # A qualifier mark is not punctuation noise: "Free*" is a different claim from "Free".
    assert _one("Free*").normalized != _one("Free").normalized


def test_questions_are_ambiguous_and_navigation_text_is_not_a_claim():
    assert _one("Is it really free?").ambiguous is True
    for text in ("Menu", "Contact us", "Learn more", "About the team", "Home"):
        assert claims.detect_claims(text) == [], text


def test_markup_segments_are_read_separately():
    found = claims.detect_claims('<nav><a href="/">Home</a></nav><span class="badge">Free</span><p>Learn more</p>'
                                 "<h2>Save 30%</h2>")
    assert [c.normalized for c in found] == ["free", "save 30%"]


# ------------------------------------------------------------------------------ through the API

# Each short claim ends its own sentence, exactly where the Project OS extractor (six-word floor) cannot see it.
SHOP = ('<html lang="en"><h1>Halden Tea (fictional).</h1><span class="badge">Free.</span> <p>Ships in 2 days.</p>'
        "<p>Every blend is certified organic and packed by hand in small batches.</p>"
        '<a href="/about">Learn more.</a></html>')


def _plan_with_page(monkeypatch):
    project_id = create_project()
    plan_id = instantiate(project_id)["plan"]["plan_id"]
    page = artifact(project_id, "shop-page", "app_build_spec", SHOP)
    return project_id, plan_id, page


def _mutation(plan_id: str, page: str, find: str, replace: str, expected: list[str]) -> dict:
    return ok(client.post(f"/agency-framework/plans/{plan_id}/assurance/mutation", headers=key(), json={
        "base_ref": page, "mutation_class": "CLAIM_CHANGE", "find": find, "replace": replace,
        "expected_findings": expected, "test_fixture_ref": "fixture:claims:short"}), 201)["record"]


def test_a_changed_short_claim_is_detected_and_a_non_claim_change_is_not(afw, monkeypatch):
    _, plan_id, page = _plan_with_page(monkeypatch)
    days = _mutation(plan_id, page, "Ships in 2 days.", "Ships in 9 days.", ["CLAIM_CHANGED"])
    assert days["status"] == "DETECTED", days["body"]
    badge = _mutation(plan_id, page, ">Free.<", ">Free*.<", ["CLAIM_CHANGED"])
    assert badge["status"] == "DETECTED"
    nav = _mutation(plan_id, page, "Learn more.", "Read more.", [])
    assert nav["status"] == "DETECTED" and nav["body"]["observed_findings"] == []  # no false positive
    spacing = _mutation(plan_id, page, "Ships in 2 days.", "Ships  in  2  days.", [])
    assert spacing["body"]["observed_findings"] == []


def test_meaning_inventories_claims_and_links_only_evidence_a_person_supplied(afw, monkeypatch):
    project_id, plan_id, page = _plan_with_page(monkeypatch)
    certificate = evidence(monkeypatch, project_id, "Courier contract (fictional). Standard parcels are delivered within "
                                                    "two working days anywhere in the country.")
    record = ok(client.post(f"/agency-framework/plans/{plan_id}/assurance/meaning", headers=key(), json={
        "task_ids": ["AGM-10-001"], "interpreted_obligation": "The shop page makes only substantiated claims.",
        "output_refs": [page], "claim_evidence": [{"claim": "Ships in 2 days.", "evidence_refs": [certificate]}]}), 201)
    inventory = {c["normalized"]: c for c in record["record"]["body"]["claims"]["items"]}
    assert inventory["ships in 2 days"]["substantiation"] == "EVIDENCE_LINKED_UNVERIFIED"
    assert inventory["ships in 2 days"]["evidence_refs"] == [certificate]
    assert inventory["free"]["substantiation"] == "UNSUBSTANTIATED"
    assert "learn more" not in inventory
    summary = record["record"]["body"]["claims"]
    assert summary["state"] == "UNSUBSTANTIATED_CLAIMS" and summary["unsubstantiated"] >= 1
    assert summary["decision"] == "NONE: a person decides at review; nothing is rejected or approved here"

    unknown = client.post(f"/agency-framework/plans/{plan_id}/assurance/meaning", headers=key(), json={
        "interpreted_obligation": "x" * 5, "output_refs": [page],
        "claim_evidence": [{"claim": "Lowest prices anywhere", "evidence_refs": [certificate]}]})
    assert unknown.status_code == 422 and unknown.json()["error"]["code"] == "UNKNOWN_CLAIM"
    fabricated = client.post(f"/agency-framework/plans/{plan_id}/assurance/meaning", headers=key(), json={
        "interpreted_obligation": "x" * 5, "output_refs": [page],
        "claim_evidence": [{"claim": "Free", "evidence_refs": ["knowledge:does-not-exist"]}]})
    assert fabricated.status_code == 422 and fabricated.json()["error"]["code"] == "REF_REJECTED"
