"""Design-style library: catalog, compatibility, dimension composition, prompts."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from services.langgraph.agency.design import (
    STYLE_DIMENSIONS,
    InvalidSelectionError,
    UnknownStyleError,
    analyze_style_compatibility,
    compile_design_prompt,
    compose_style_selection,
    direction_from_selection,
    get_style,
    load_style_library,
    load_style_registry,
    pending_references,
    style_catalog_snapshot,
)
from services.langgraph.agency.design.style_registry import CATALOG_PATH


# --------------------------------------------------------------------------- #
# Catalog
# --------------------------------------------------------------------------- #
def test_canonical_catalog_loads_and_validates():
    library = load_style_registry()
    assert library.version == "style-library-v1"
    names = {style.name for style in library.styles}
    # The initial entries named for this catalog must all be present.
    assert {"Tenebrism", "Coquette", "Bauhaus", "Glassmorphism", "Modular Typography", "Bento Box"} <= names


def test_known_styles_resolve():
    assert get_style("MOD-03").name == "Bauhaus"
    assert get_style("CLS-01").name == "Tenebrism"
    assert get_style("MOD-01").name == "Utilitarian"


def test_unknown_style_raises():
    with pytest.raises(UnknownStyleError):
        get_style("ZZZ-99")


def test_every_declared_dimension_is_in_the_shared_vocabulary():
    for style in load_style_registry().styles:
        assert set(style.design_dimensions) <= set(STYLE_DIMENSIONS), style.id


def test_pending_references_name_unmigrated_styles_only():
    library = load_style_registry()
    known = {style.id for style in library.styles}
    pending = pending_references(library)
    assert pending, "catalog references styles still awaiting migration"
    assert not set(pending) & known
    snapshot = style_catalog_snapshot(library)
    assert snapshot["pending_references"] == pending
    assert len(snapshot["styles"]) == len(library.styles)


def test_catalog_rejects_malformed_entries(tmp_path):
    payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    style = payload["styles"][0]

    broken = {**payload, "styles": [{**style, "compatible_with": ["MOD-03"], "incompatible_with": ["MOD-03"]}]}
    path = tmp_path / "overlap.json"
    path.write_text(json.dumps(broken))
    with pytest.raises(ValidationError):
        load_style_library(path)

    broken = {**payload, "styles": [{**style, "design_dimensions": ["not-a-dimension"]}]}
    path.write_text(json.dumps(broken))
    with pytest.raises(ValidationError):
        load_style_library(path)

    broken = {**payload, "styles": [style, style]}
    path.write_text(json.dumps(broken))
    with pytest.raises(ValidationError):
        load_style_library(path)

    broken = {**payload, "styles": [{**style, "compatible_with": ["lowercase-ref"]}]}
    path.write_text(json.dumps(broken))
    with pytest.raises(ValidationError):
        load_style_library(path)


# --------------------------------------------------------------------------- #
# Compatibility
# --------------------------------------------------------------------------- #
def test_declared_incompatibility_is_blocking():
    result = analyze_style_compatibility(["CLS-02", "MOD-01"])  # Coquette x Utilitarian
    assert result["blocking"] is True
    assert result["conflicts"]


def test_compatible_pair_is_not_blocking():
    result = analyze_style_compatibility(["MOD-03", "MOD-07"])
    assert result["blocking"] is False
    assert isinstance(result["warnings"], list)


def test_unsuitable_brief_produces_warning():
    result = analyze_style_compatibility(["CLS-02"], brief_text="operational dashboards for ops")
    assert any("unsuitable" in warning for warning in result["warnings"])


# --------------------------------------------------------------------------- #
# Composition by dimension
# --------------------------------------------------------------------------- #
def _three_layer():
    return [
        {"style_id": "MOD-03", "role": "primary", "strength": 0.8, "dimensions": ["layout", "geometry"], "locked": True},
        {"style_id": "CLS-01", "strength": 0.7, "dimensions": ["lighting", "texture"]},
        {"style_id": "MOD-07", "strength": 0.9, "dimensions": ["typography"]},
    ]


def test_each_dimension_resolves_to_its_assigned_style():
    composed = compose_style_selection(_three_layer(), {"objective": "premium campaign art"})
    assert composed.blocking is False
    assert composed.resolved_dimensions == {
        "layout": "MOD-03",
        "geometry": "MOD-03",
        "lighting": "CLS-01",
        "texture": "CLS-01",
        "typography": "MOD-07",
    }


def test_tokens_come_from_the_owning_style_per_dimension():
    composed = compose_style_selection(_three_layer())
    lighting = [t for t in composed.resolved_tokens if t.dimension == "lighting"]
    assert lighting and all(t.token == "Tenebrism" for t in lighting)
    assert any("key spotlight" in t.value for t in lighting)
    typography = [t for t in composed.resolved_tokens if t.dimension == "typography"]
    assert typography and all(t.token == "Modular Typography" for t in typography)


def test_only_one_style_contributes_identity_tokens():
    composed = compose_style_selection(_three_layer())
    identity_owners = {t.token for t in composed.resolved_tokens if t.dimension == "imagery"}
    assert identity_owners == {"Bauhaus"}  # the primary; no whole-prompt concatenation


def test_locked_layer_beats_stronger_unlocked_layer():
    composed = compose_style_selection(
        [
            {"style_id": "MOD-03", "strength": 0.2, "dimensions": ["layout"], "locked": True},
            {"style_id": "MOD-04", "strength": 1.0, "dimensions": ["layout"]},
        ]
    )
    assert composed.resolved_dimensions["layout"] == "MOD-03"


def test_strength_decides_unlocked_contention_and_primary_breaks_ties():
    stronger = compose_style_selection(
        [
            {"style_id": "MOD-03", "strength": 0.4, "dimensions": ["layout"]},
            {"style_id": "MOD-04", "strength": 0.9, "dimensions": ["layout"]},
        ]
    )
    assert stronger.resolved_dimensions["layout"] == "MOD-04"
    tie = compose_style_selection(
        [
            {"style_id": "MOD-03", "strength": 0.6, "dimensions": ["layout"]},
            {"style_id": "MOD-04", "role": "primary", "strength": 0.6, "dimensions": ["layout"]},
        ]
    )
    assert tie.resolved_dimensions["layout"] == "MOD-04"


def test_layer_strength_scales_contribution():
    weak = compose_style_selection([{"style_id": "CLS-01", "strength": 0.1, "dimensions": ["lighting"]}])
    strong = compose_style_selection([{"style_id": "CLS-01", "strength": 1.0, "dimensions": ["lighting"]}])
    def lighting_tokens(composed):
        return sum(1 for t in composed.resolved_tokens if t.dimension == "lighting")

    assert lighting_tokens(weak) < lighting_tokens(strong)


def test_double_lock_on_one_dimension_is_blocking():
    composed = compose_style_selection(
        [
            {"style_id": "MOD-03", "dimensions": ["layout"], "locked": True},
            {"style_id": "MOD-04", "dimensions": ["layout"], "locked": True},
        ]
    )
    assert composed.blocking is True
    assert any("locked by more than one style" in c for c in composed.conflicts)


def test_incompatible_selection_is_blocking_and_marked_in_prompt():
    composed = compose_style_selection([{"style_id": "CLS-02", "role": "primary"}, {"style_id": "MOD-01"}])
    assert composed.blocking is True
    assert "BLOCKED" in composed.prompt


def test_assignment_outside_declared_dimensions_warns():
    composed = compose_style_selection([{"style_id": "MOD-07", "dimensions": ["lighting"]}])
    assert any("does not declare" in w for w in composed.warnings)


def test_explicit_assignment_suppresses_false_overlap_warnings():
    # Tenebrism is assigned lighting/texture only, so it does not contend for palette.
    composed = compose_style_selection(_three_layer())
    assert not any("palette" in w for w in composed.warnings)


def test_selection_set_rules():
    with pytest.raises(InvalidSelectionError):
        compose_style_selection([{"style_id": "MOD-03", "role": "primary"}, {"style_id": "MOD-04", "role": "primary"}])
    with pytest.raises(InvalidSelectionError):
        compose_style_selection([{"style_id": "MOD-03"}, {"style_id": "MOD-03"}])
    with pytest.raises(InvalidSelectionError):
        compose_style_selection([])
    with pytest.raises(ValidationError):
        compose_style_selection([{"style_id": "MOD-03", "strength": 1.5}])
    with pytest.raises(UnknownStyleError):
        compose_style_selection([{"style_id": "ZZZ-99"}])


def test_composition_id_is_deterministic_and_selection_sensitive():
    a = compose_style_selection(_three_layer())
    b = compose_style_selection(_three_layer())
    assert a.composition_id == b.composition_id
    changed = _three_layer()
    changed[1]["strength"] = 0.3
    assert compose_style_selection(changed).composition_id != a.composition_id


# --------------------------------------------------------------------------- #
# Prompt compilation
# --------------------------------------------------------------------------- #
def test_prompt_is_structured_per_dimension():
    composed = compose_style_selection(_three_layer(), {"objective": "premium campaign art", "audience": "buyers"})
    assert "premium campaign art" in composed.prompt
    assert "Style system" in composed.prompt
    assert "Lighting (Tenebrism):" in composed.prompt
    assert "Layout (Bauhaus):" in composed.prompt
    assert "Typography (Modular Typography):" in composed.prompt
    assert "flat even lighting" in composed.negative_prompt


def test_compile_design_prompt_handles_minimal_input():
    prompt = compile_design_prompt({}, {"resolved_tokens": [], "conflicts": []})
    assert "Style system" in prompt


# --------------------------------------------------------------------------- #
# Direction attached to a DesignBrief
# --------------------------------------------------------------------------- #
def test_direction_applies_only_when_not_blocking():
    ok = direction_from_selection({"selections": _three_layer(), "rationale": "editorial drama"})
    assert ok.applied is True and ok.blocking is False
    assert ok.rationale == "editorial drama"
    blocked = direction_from_selection({"selections": [{"style_id": "CLS-02"}, {"style_id": "MOD-01"}]})
    assert blocked.applied is False and blocked.blocking is True


# --------------------------------------------------------------------------- #
# Design Mode API
# --------------------------------------------------------------------------- #
def _client():
    from fastapi.testclient import TestClient

    from services.langgraph.app.main import app

    return TestClient(app)


def test_api_lists_catalog_with_pending_references():
    response = _client().get("/design/styles")
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == "style-library-v1"
    assert {style["id"] for style in body["styles"]} >= {"CLS-01", "CLS-02", "MOD-03"}
    assert body["pending_references"] == pending_references()


def test_api_composes_by_dimension():
    response = _client().post(
        "/design/styles/compose",
        json={"selections": _three_layer(), "brief": {"objective": "launch key visual"}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["blocking"] is False
    assert body["resolved_dimensions"]["lighting"] == "CLS-01"
    assert "launch key visual" in body["prompt"]


def test_api_reports_blocking_conflicts_without_erroring():
    response = _client().post(
        "/design/styles/compose",
        json={"selections": [{"style_id": "CLS-02", "role": "primary"}, {"style_id": "MOD-01"}]},
    )
    assert response.status_code == 200
    assert response.json()["blocking"] is True


def test_api_rejects_invalid_selections():
    client = _client()
    unknown = client.post("/design/styles/compose", json={"selections": [{"style_id": "ZZZ-99"}]})
    assert unknown.status_code == 422
    two_primaries = client.post(
        "/design/styles/compose",
        json={"selections": [{"style_id": "MOD-03", "role": "primary"}, {"style_id": "MOD-04", "role": "primary"}]},
    )
    assert two_primaries.status_code == 422
    malformed = client.post("/design/styles/compose", json={"selections": [{"style_id": "bauhaus"}]})
    assert malformed.status_code == 422
    empty = client.post("/design/styles/compose", json={"selections": []})
    assert empty.status_code == 422


def test_api_requires_authentication(monkeypatch):
    monkeypatch.setenv("AMC_AUTH_MODE", "disabled")
    client = _client()
    assert client.get("/design/styles").status_code == 503
    assert client.post("/design/styles/compose", json={"selections": [{"style_id": "MOD-03"}]}).status_code == 503
