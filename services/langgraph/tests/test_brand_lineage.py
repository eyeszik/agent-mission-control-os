"""Brand lineage correctness: synthetic parent → child → grandchild contracts (ISSUE-03)."""

import pytest
from services.langgraph.agency.brand_lineage import BrandLineage, BrandNode, LineageError


def _lineage_with_three_generations() -> BrandLineage:
    bl = BrandLineage()
    bl.add(BrandNode(id="parent", properties={"color": "#5b1a22", "font": "Serif", "tone": "elegant"}))
    bl.add(BrandNode(id="child-a", parent_id="parent", properties={"color": "#ff0000"}))
    bl.add(BrandNode(id="child-b", parent_id="parent", properties={"tone": "playful"}))
    bl.add(BrandNode(id="grandchild-a1", parent_id="child-a", properties={"font": "Sans"}))
    return bl


def test_parent_to_descendant_inheritance():
    bl = _lineage_with_three_generations()
    props, prov = bl.effective_properties("grandchild-a1")
    assert props["color"] == "#ff0000"  # inherited via child-a override
    assert props["tone"] == "elegant"   # from parent
    assert props["font"] == "Sans"      # own override


def test_child_override_precedence():
    bl = _lineage_with_three_generations()
    props_a, _ = bl.effective_properties("child-a")
    assert props_a["color"] == "#ff0000"  # child overrides parent
    props_b, _ = bl.effective_properties("child-b")
    assert props_b["color"] == "#5b1a22"  # inherits parent


def test_property_level_provenance():
    bl = _lineage_with_three_generations()
    _, prov = bl.effective_properties("grandchild-a1")
    assert prov["color"] == "child-a"
    assert prov["tone"] == "parent"
    assert prov["font"] == "grandchild-a1"


def test_branch_isolation():
    bl = _lineage_with_three_generations()
    # child-b should not see child-a's override
    props_b, _ = bl.effective_properties("child-b")
    assert props_b["color"] == "#5b1a22"


def test_permitted_propagation():
    bl = _lineage_with_three_generations()
    # Adding a new property to parent should be visible to descendants that don't override
    bl_new = BrandLineage()
    bl_new.add(BrandNode(id="p", properties={"a": "1"}))
    bl_new.add(BrandNode(id="c", parent_id="p", properties={"b": "2"}))
    props, _ = bl_new.effective_properties("c")
    assert props == {"a": "1", "b": "2"}


def test_stale_descendant_invalidation():
    bl = BrandLineage()
    assert bl.is_stale("child", parent_version=5, node_parent_version=3) is True
    assert bl.is_stale("child", parent_version=3, node_parent_version=3) is False


def test_cycle_rejection():
    bl = BrandLineage()
    bl.add(BrandNode(id="a"))
    bl.add(BrandNode(id="b", parent_id="a"))
    # b -> a would be a cycle if we try to re-parent a under b (not allowed via add, but test parent existence)
    # Duplicate add is rejected
    with pytest.raises(LineageError, match="duplicate"):
        bl.add(BrandNode(id="a"))
    # Self-parent
    with pytest.raises(LineageError):
        bl.add(BrandNode(id="c", parent_id="c"))
    # Cycle via lineage check: create chain and verify ancestors walk catches cycle
    # (The add-time check already prevents cycles via parent existence, but we test the invariant)
    assert "a" in bl.ancestors("b")


def test_deletion_and_referential_integrity():
    bl = _lineage_with_three_generations()
    with pytest.raises(LineageError, match="descendants exist"):
        bl.remove("parent")
    with pytest.raises(LineageError, match="descendants exist"):
        bl.remove("child-a")
    # Leaf can be removed
    bl.remove("grandchild-a1")
    assert "grandchild-a1" not in bl._nodes
    # Now child-a is leaf
    bl.remove("child-a")
    assert "child-a" not in bl._nodes


def test_empty_missing_malformed_lineage():
    bl = BrandLineage()
    with pytest.raises(LineageError, match="non-empty"):
        bl.add(BrandNode(id=""))
    with pytest.raises(LineageError, match="does not exist"):
        bl.add(BrandNode(id="x", parent_id="nonexistent"))
    with pytest.raises(LineageError, match="unknown"):
        bl.get("missing")
    with pytest.raises(LineageError, match="unknown"):
        bl.effective_properties("missing")


def test_deterministic_traversal_and_ordering():
    bl = BrandLineage()
    bl.add(BrandNode(id="root"))
    # Add children in non-alphabetical order; traversal must still be sorted
    bl.add(BrandNode(id="z-child", parent_id="root"))
    bl.add(BrandNode(id="a-child", parent_id="root"))
    descendants = bl.descendants("root")
    assert descendants == ["a-child", "z-child"]  # sorted


def test_graph_structure():
    bl = _lineage_with_three_generations()
    g = bl.lineage_graph()
    assert g["nodes"] == sorted(g["nodes"])
    assert ("parent", "child-a") in g["edges"]
    assert ("child-a", "grandchild-a1") in g["edges"]
