"""VNEXUS temporal knowledge graph and creative multiverse: typing, cycles, impact, history, branches."""

from __future__ import annotations

import time
from uuid import uuid4

import pytest

from services.langgraph.agency.vnexus.genome import document_from_flat
from services.langgraph.agency.vnexus.graph import Edge, EdgeKind, Graph, GraphError, Node, NodeKind, diff_snapshots
from services.langgraph.agency.vnexus.multiverse import (
    BranchState,
    BranchTransitionError,
    ChangeSet,
    apply_changes,
    compare_branches,
    compare_with_base,
    compose,
    merge_change_sets,
    next_branch_state,
    rebase,
)
from services.langgraph.persistence.database import json_param, table, transaction
from services.langgraph.persistence.vnexus import now_iso
from services.langgraph.tests._project_os_support import as_user, client, headers
from services.langgraph.tests._vnexus_support import BRAND_DOC, _approve, _c, _draft, make_world


@pytest.fixture
def world(monkeypatch, tmp_path):
    return make_world(monkeypatch, tmp_path)


def N(i: str, kind: NodeKind, t: str = "2026-01-01", until: str | None = None) -> Node:
    return Node(node_id=i, kind=kind, label=i, valid_from=t, valid_to=until, content_hash=f"h-{i}")


def E(i: str, kind: EdgeKind, src: str, dst: str, t: str = "2026-01-01", until: str | None = None) -> Edge:
    return Edge(edge_id=i, kind=kind, src_node_id=src, dst_node_id=dst, valid_from=t, valid_to=until)


# --------------------------------------------------------------------------- pure graph


def test_edge_typing_and_cycle_rejection():
    g = Graph([N("d", NodeKind.DESIGN_DECISION), N("a", NodeKind.ASSET), N("p", NodeKind.PROMPT), N("ev", NodeKind.EVIDENCE),
               N("ap", NodeKind.APPROVAL), N("c", NodeKind.CAMPAIGN)],
              [E("e1", EdgeKind.IMPLEMENTS, "a", "d"), E("e2", EdgeKind.DEPENDS_ON, "d", "c")])
    g.check_edge(EdgeKind.GENERATED_BY, "a", "p")
    g.check_edge(EdgeKind.SUPPORTED_BY, "d", "ev")
    for kind, src, dst, msg in [(EdgeKind.APPROVED_BY, "d", "ev", "may not connect"), (EdgeKind.GENERATED_BY, "d", "p", "may not connect"),
                                (EdgeKind.SUPERSEDES, "a", "d", "same kind"), (EdgeKind.DEPENDS_ON, "c", "a", "cycle"),
                                (EdgeKind.DEPENDS_ON, "a", "a", "itself"), (EdgeKind.IMPLEMENTS, "a", "d", "already exists"),
                                (EdgeKind.DEPENDS_ON, "a", "missing", "endpoints")]:
        with pytest.raises(GraphError, match=msg):
            g.check_edge(kind, src, dst)
    g.check_edge(EdgeKind.CONFLICTS_WITH, "c", "a")  # symmetric relations are not lineage
    assert not g.find_cycles()
    looped = Graph(g.all_nodes.values(), [*g.edges, E("bad", EdgeKind.DEPENDS_ON, "c", "a")])
    assert looped.find_cycles() == [["a", "d", "c", "a"]]


def test_impact_evidence_history_and_time_travel():
    nodes = [N("brand", NodeKind.GENOME_VERSION, "2026-01-01", "2026-03-01"), N("brand2", NodeKind.GENOME_VERSION, "2026-03-01"),
             N("dec", NodeKind.DESIGN_DECISION), N("hero", NodeKind.ASSET), N("page", NodeKind.EXPERIENCE), N("ev", NodeKind.EVIDENCE),
             N("other", NodeKind.ASSET)]
    nodes[0] = nodes[0].model_copy(update={"superseded_by": "brand2"})
    edges = [E("1", EdgeKind.DEPENDS_ON, "dec", "brand2", "2026-03-01"), E("0", EdgeKind.DEPENDS_ON, "dec", "brand", "2026-01-01", "2026-03-01"),
             E("2", EdgeKind.IMPLEMENTS, "hero", "dec"), E("3", EdgeKind.DEPENDS_ON, "page", "hero"), E("4", EdgeKind.SUPPORTED_BY, "dec", "ev"),
             E("5", EdgeKind.SUPERSEDES, "brand2", "brand", "2026-03-01")]
    now = Graph(nodes, edges)
    hit = now.impact(["brand2"])
    assert [a["node_id"] for a in hit["affected"]] == ["dec", "hero", "page"]
    assert hit["affected"][-1]["path"] == ["brand2", "<-DEPENDS_ON-", "dec", "<-IMPLEMENTS-", "hero", "<-DEPENDS_ON-", "page"]
    assert "other" not in [a["node_id"] for a in hit["affected"]]
    support = now.evidence_for("hero")
    assert [e["node_id"] for e in support["evidence"]] == ["ev"] and support["considered"][:2] == ["hero", "dec"]
    assert now.evidence_for("other")["unsupported"] is True
    assert now.history("brand2") == ["brand", "brand2"]
    past = Graph(nodes, edges, as_of="2026-02-01")
    assert "brand" in past.nodes and "brand2" not in past.nodes
    assert [a["node_id"] for a in past.impact(["brand"])["affected"]] == ["dec", "hero", "page"]
    d = diff_snapshots(past.snapshot(), now.snapshot())
    assert d["nodes_added"] == ["brand2"] and d["nodes_removed"] == ["brand"] and not d["identical"]


# --------------------------------------------------------------------------- pure multiverse


def test_change_sets_apply_compose_compare_merge_and_rebase():
    base = BRAND_DOC
    a = ChangeSet(set={"visual.color.accent": "#1d4ed8", "verbal.voice.tone": "calm"})
    b = ChangeSet(set={"visual.color.accent": "#15803d"}, unset=("strategy.positioning.promise",))
    c = ChangeSet(set={"experience.navigation.style": "top-bar"})
    doc = apply_changes(base, a)
    assert doc.flatten()["visual.color.accent"] == "#1d4ed8" and base.flatten()["visual.color.accent"] == "#c2410c"
    with pytest.raises(ValueError, match="does not have"):
        apply_changes(base, ChangeSet(unset=("visual.nope",)))
    with pytest.raises(ValueError):
        ChangeSet(set={"x.y": 1}, unset=("x.y",))
    cmp = compare_branches(a, b)
    assert cmp["conflicts"] == [{"key": "visual.color.accent", "a": ["SET", "#1d4ed8"], "b": ["SET", "#15803d"]}]
    assert not cmp["mergeable"] and merge_change_sets(a, b)[0] is None
    merged, report = merge_change_sets(a, c)
    assert report["mergeable"] and merged.set == {**a.set, **c.set}
    assert merge_change_sets(a, c)[0].changes_hash == merged.changes_hash  # deterministic
    child = compose(a, ChangeSet(set={"verbal.voice.tone": "warm"}, unset=()))
    assert child.set["verbal.voice.tone"] == "warm" and child.set["visual.color.accent"] == "#1d4ed8"
    # Rebase: carried when the base change is disjoint, refused when both touch a key.
    newer = document_from_flat({**base.flatten(), "visual.typography.display": "Inter"}, constraints=list(base.constraints))
    carried, rep = rebase(base, newer, a)
    assert carried == a and rep["conflicts"] == []
    clash = document_from_flat({**base.flatten(), "visual.color.accent": "#000000"}, constraints=list(base.constraints))
    assert rebase(base, clash, a)[0] is None


def test_compare_with_base_reports_invariants_and_inherited_constraints():
    brand = BRAND_DOC
    project_base = document_from_flat({"visual.color.accent": "#1d4ed8", "visual.mark.shape": "ring"},
                                       constraints=[_c("mark-lock", "visual.mark.shape", "IMMUTABLE")])
    from services.langgraph.agency.vnexus.genome import GenomeLayer

    ancestors = [GenomeLayer(scope="brand", scope_ref="b", status="APPROVED", document=brand)]
    changes = ChangeSet(set={"visual.color.ink": "#777777", "visual.mark.shape": "square", "verbal.voice.tone": "calm"},
                        remove_constraints=("mark-lock",), add_constraints=(_c("tone-allowed", "verbal.voice.tone", "ALLOWED_VALUES",
                                                                                values=["calm"]),))
    report = compare_with_base(project_base, changes, ancestors, scope_ref="p", scope="project")
    kinds = sorted({v["kind"] for v in report["invariant_violations"]})
    assert kinds == ["IMMUTABLE_OVERRIDE", "INVARIANT_CHANGED", "INVARIANT_REMOVED"]
    assert report["constraints"]["added"] == ["tone-allowed"] and report["constraints"]["removed"] == ["mark-lock"]
    assert "ink-lock" in report["constraints"]["unchanged_inherited"]
    assert [m["key"] for m in report["values"]["modified"]] == ["visual.mark.shape"]
    assert report["promotable"] is False
    ok = compare_with_base(project_base, ChangeSet(set={"verbal.voice.tone": "calm"}), ancestors, scope_ref="p", scope="project")
    assert ok["promotable"] and not ok["invariant_violations"]


def test_branch_state_machine():
    assert next_branch_state(BranchState.OPEN, "submit") is BranchState.IN_REVIEW
    for state, action in [("PROMOTED", "submit"), ("REJECTED", "submit"), ("OPEN", "promote"), ("ARCHIVED", "submit"),
                          ("IN_REVIEW", "archive")]:
        with pytest.raises(BranchTransitionError):
            next_branch_state(BranchState(state), action)


# --------------------------------------------------------------------------- API


def _node(w, kind: str, label: str, **attrs) -> str:
    r = client.post(f"/vnexus/brands/{w['brand']}/graph/nodes", json={"kind": kind, "label": label, "attributes": attrs})
    assert r.status_code == 201, r.text
    return r.json()["node"]["node_id"]


def _edge(w, kind: str, src: str, dst: str, status: int = 201):
    r = client.post(f"/vnexus/brands/{w['brand']}/graph/edges", json={"kind": kind, "src_node_id": src, "dst_node_id": dst})
    assert r.status_code == status, r.text
    return r.json()


def test_graph_api_typed_acyclic_temporal_and_audited(world):
    w = world
    insight = _node(w, "Insight", "First homes are furnished slowly", source="FICTIONAL demo assumption")
    evidence = _node(w, "Evidence", "Assumption record", evidence_type="ASSUMPTION", note="no research exists for this fictional brand")
    decision = _node(w, "DesignDecision", "Warm off-white paper")
    asset = _node(w, "Asset", "Hero poster")
    _edge(w, "SUPPORTED_BY", decision, evidence)
    _edge(w, "IMPLEMENTS", decision, insight, status=409)          # DesignDecision cannot IMPLEMENT (typing)
    _edge(w, "DERIVED_FROM", decision, insight)
    _edge(w, "IMPLEMENTS", asset, decision)
    _edge(w, "DERIVED_FROM", insight, asset, status=409)            # would close a lineage cycle
    time.sleep(0.01)
    before = now_iso()
    time.sleep(0.01)
    sup = client.post(f"/vnexus/graph/nodes/{decision}/supersede", json={"label": "Cooler paper", "attributes": {"why": "contrast"}})
    assert sup.status_code == 201
    new_decision = sup.json()["node"]["node_id"]
    assert client.post(f"/vnexus/graph/nodes/{decision}/supersede", json={"label": "x"}).status_code == 409
    impact = client.post(f"/vnexus/brands/{w['brand']}/graph/impact", json={"node_ids": [insight]}).json()
    assert impact["affected"] == []  # the superseded decision (and what implemented it) is no longer current
    past = client.post(f"/vnexus/brands/{w['brand']}/graph/impact", json={"node_ids": [insight], "as_of": before}).json()
    assert [a["node_id"] for a in past["affected"]] == [decision, asset]
    ev = client.get(f"/vnexus/graph/nodes/{new_decision}/evidence").json()
    assert ev["unsupported"] is True and ev["history"] == [decision, new_decision]
    old_ev = client.get(f"/vnexus/graph/nodes/{decision}/evidence", params={"as_of": before}).json()
    assert [e["node_id"] for e in old_ev["evidence"]] == [evidence]
    diff = client.get(f"/vnexus/brands/{w['brand']}/graph/diff", params={"from": before}).json()
    assert diff["nodes_added"] == [new_decision] and diff["nodes_removed"] == [decision]
    view = client.get(f"/vnexus/brands/{w['brand']}/graph").json()
    assert view["lineage_cycles"] == [] and len(view["nodes"]) == 4
    trail = client.get(f"/vnexus/brands/{w['brand']}/audit").json()
    assert trail["verification"]["intact"] and any(e["action"] == "supersede" and e["subject_id"] == decision for e in trail["entries"])


def test_graph_detects_cycles_written_around_the_api(world):
    w = world
    a, b = _node(w, "Asset", "a"), _node(w, "Asset", "b")
    _edge(w, "DEPENDS_ON", a, b)
    with transaction(write=True) as db:
        db.execute(f"""INSERT INTO {table('vnexus_graph_edges')} (edge_id, tenant_id, brand_id, kind, src_node_id, dst_node_id,
                   provenance, valid_from, created_by, created_at) VALUES (?, ?, ?, 'DEPENDS_ON', ?, ?, ?, '2000-01-01', 'x', 'x')""",
                   (f"edge-{uuid4().hex}", w["tenant"], w["brand"], b, a, json_param({})))
    assert client.get(f"/vnexus/brands/{w['brand']}/graph").json()["lineage_cycles"]


def test_branch_lifecycle_promotion_through_approval(world):
    w = world
    v1 = _approve(w, _draft(w, "brand", w["brand"], BRAND_DOC))
    graph = client.get(f"/vnexus/brands/{w['brand']}/graph").json()
    kinds = sorted(n["kind"] for n in graph["nodes"])
    assert kinds == ["Approval", "GenomeVersion"] and graph["edges"][0]["kind"] == "APPROVED_BY"

    def fork(name, changes, **extra):
        r = client.post(f"/vnexus/brands/{w['brand']}/branches", json={"base_version_id": v1["version_id"], "name": name,
                                                                       "hypothesis": "explore", "changes": changes, **extra},
                        headers=headers())
        assert r.status_code == 201, r.text
        return r.json()["branch"]

    blue = fork("blue accent", {"set": {"visual.color.accent": "#1d4ed8"}})
    green = fork("green accent", {"set": {"visual.color.accent": "#15803d", "verbal.voice.tone": "calm"}})
    nav = fork("nav", {"set": {"experience.navigation.style": "top-bar"}})
    bad = fork("ink change", {"set": {"visual.color.ink": "#999999"}})
    sub = fork("blue + tone", {"set": {"verbal.voice.tone": "warm"}}, parent_branch_id=blue["branch_id"])
    assert sub["changes"]["set"] == {"visual.color.accent": "#1d4ed8", "verbal.voice.tone": "warm"}

    two = client.get(f"/vnexus/branches/{blue['branch_id']}/compare/{green['branch_id']}").json()["comparison"]
    assert two["comparable"] and two["conflicts"][0]["key"] == "visual.color.accent"
    conflict = client.post(f"/vnexus/branches/{blue['branch_id']}/merge", json={"other_branch_id": green["branch_id"], "name": "m"},
                           headers=headers())
    assert conflict.status_code == 409 and conflict.json()["detail"]["report"]["conflicts"]
    merged = client.post(f"/vnexus/branches/{blue['branch_id']}/merge", json={"other_branch_id": nav["branch_id"], "name": "blue+nav"},
                         headers=headers())
    assert merged.status_code == 201 and merged.json()["branch"]["state"] == "OPEN"

    cmp = client.get(f"/vnexus/branches/{bad['branch_id']}/compare").json()["comparison"]
    assert not cmp["promotable"]
    assert [v["kind"] for v in cmp["invariant_violations"]] == ["INVARIANT_CHANGED"]
    blocked = client.post(f"/vnexus/branches/{bad['branch_id']}/submit", headers=headers())
    assert blocked.status_code == 409

    ev = client.post(f"/vnexus/branches/{blue['branch_id']}/evaluations")
    assert ev.status_code == 201 and ev.json()["evaluation"]["kind"] == "DETERMINISTIC"
    fb = client.post(f"/vnexus/branches/{blue['branch_id']}/feedback", json={"text": "Blue reads colder than the brief", "decision": "revise"})
    assert fb.json()["evaluation"]["payload"]["text"] == "Blue reads colder than the brief"
    assert client.post(f"/vnexus/branches/{blue['branch_id']}/feedback", json={"text": "x", "decision": "love"}).status_code == 422

    submitted = client.post(f"/vnexus/branches/{blue['branch_id']}/submit", headers=headers())
    assert submitted.status_code == 200, submitted.text
    proposal = submitted.json()["proposal"]
    assert proposal["origin"] == "BRANCH_PROMOTION" and proposal["status"] == "IN_REVIEW"
    assert client.put(f"/vnexus/branches/{blue['branch_id']}", json={"expected_revision": 99, "changes": {"set": {}}}).status_code == 409
    as_user(w["mp"], "bob", role="reviewer", tenant=w["tenant"])
    assert client.post(f"/approvals/{proposal['approval_id']}/decide", json={"decision": "approve"}, headers=headers()).status_code == 200
    promoted = client.get(f"/vnexus/branches/{blue['branch_id']}").json()["branch"]
    assert promoted["state"] == "PROMOTED" and [e["kind"] for e in promoted["evaluations"]] == ["DETERMINISTIC", "HUMAN"]
    as_user(w["mp"], "alice", role="editor", tenant=w["tenant"])
    assert client.get(f"/vnexus/versions/{v1['version_id']}").json()["version"]["status"] == "SUPERSEDED"

    # The green branch's base is now stale: submit refuses, rebase reports the conflicting key.
    assert client.post(f"/vnexus/branches/{green['branch_id']}/submit", headers=headers()).status_code == 409
    rb = client.post(f"/vnexus/branches/{green['branch_id']}/rebase")
    assert rb.status_code == 409 and rb.json()["detail"]["report"]["conflicts"] == ["visual.color.accent"]
    nav_rb = client.post(f"/vnexus/branches/{nav['branch_id']}/rebase").json()
    assert nav_rb["report"]["rebased"] is True and nav_rb["branch"]["base_version_id"] == proposal["version_id"]

    g = client.get(f"/vnexus/brands/{w['brand']}/graph").json()
    current = [n for n in g["nodes"] if n["kind"] == "GenomeVersion"]
    assert len(current) == 1 and current[0]["attributes"]["ref"] == proposal["version_id"]
    kinds = {(e["kind"]) for e in g["edges"]}
    assert {"APPROVED_BY", "DERIVED_FROM"} <= kinds
    lineage = client.get(f"/vnexus/graph/nodes/{current[0]['node_id']}/evidence").json()
    assert lineage["approvals"] and len(lineage["history"]) == 2

    archived = client.post(f"/vnexus/branches/{bad['branch_id']}/archive")
    assert archived.json()["branch"]["state"] == "ARCHIVED"
    assert client.post(f"/vnexus/branches/{bad['branch_id']}/archive").status_code == 409


def test_rejected_branch_keeps_provenance(world):
    w = world
    v1 = _approve(w, _draft(w, "brand", w["brand"], BRAND_DOC))
    br = client.post(f"/vnexus/brands/{w['brand']}/branches", json={"base_version_id": v1["version_id"], "name": "loud",
                                                                    "changes": {"set": {"verbal.voice.tone": "loud"}}},
                     headers=headers()).json()["branch"]
    proposal = client.post(f"/vnexus/branches/{br['branch_id']}/submit", headers=headers()).json()["proposal"]
    as_user(w["mp"], "bob", role="reviewer", tenant=w["tenant"])
    client.post(f"/approvals/{proposal['approval_id']}/decide", json={"decision": "reject"}, headers=headers())
    got = client.post(f"/vnexus/branches/{br['branch_id']}/settle").json()["branch"]
    assert got["state"] == "REJECTED" and got["proposal_version_id"] == proposal["version_id"]
    assert client.get(f"/vnexus/versions/{v1['version_id']}").json()["version"]["status"] == "APPROVED"
    trail = client.get(f"/vnexus/brands/{w['brand']}/audit", params={"subject_id": br["branch_id"]}).json()["entries"]
    assert [e["action"] for e in trail] == ["fork", "submit", "reject"]


def test_branch_and_graph_isolation(world, monkeypatch):
    w = world
    v1 = _approve(w, _draft(w, "brand", w["brand"], BRAND_DOC))
    br = client.post(f"/vnexus/brands/{w['brand']}/branches", json={"base_version_id": v1["version_id"], "name": "x",
                                                                    "changes": {"set": {}}}, headers=headers()).json()["branch"]
    node = _node(w, "Asset", "a")
    as_user(monkeypatch, "mallory", role="admin", tenant=f"tenant-other-{uuid4().hex[:6]}")
    assert client.get(f"/vnexus/branches/{br['branch_id']}").status_code == 404
    assert client.get(f"/vnexus/brands/{w['brand']}/graph").status_code == 404
    assert client.get(f"/vnexus/graph/nodes/{node}/evidence").status_code == 404
    as_user(monkeypatch, "victor", role="viewer", tenant=w["tenant"])
    assert client.post(f"/vnexus/brands/{w['brand']}/graph/nodes", json={"kind": "Asset", "label": "v"}).status_code == 403
    assert client.post(f"/vnexus/branches/{br['branch_id']}/feedback", json={"text": "hi"}).status_code == 403
    assert client.get(f"/vnexus/brands/{w['brand']}/graph").status_code == 200
