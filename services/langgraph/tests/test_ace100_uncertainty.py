"""ACE v100 uncertainty debt at the real dispatch boundary (the ACE v12 gateway).

While any of a tenant's effects has an unconfirmed outcome (UNKNOWN,
RECONCILING, NEEDS_HUMAN), no new R3+ effect is dispatched for that tenant. The
hold leaves the waiting action AUTHORIZED; reconciling the uncertain effect
releases it. Lower classes, other tenants and reads are unaffected.
"""

from __future__ import annotations

import pytest

from services.langgraph.agency.actions import governance
from services.langgraph.agency.actions.adapters import adapters
from services.langgraph.persistence import actions as adb
from services.langgraph.tests._ace12_support import (
    CMS,
    OWNER,
    REQUESTER,
    act_as,
    approve_all,
    dispatch,
    make_world,
    propose,
)
from services.langgraph.tests._project_os_support import client


@pytest.fixture
def w(monkeypatch, tmp_path):
    world = make_world(monkeypatch, tmp_path)
    yield world
    for a in adapters().values():
        a.fault = None


def _approved(w, capability, args, **kw):
    a = propose(w, capability, args, **kw)["action"]
    approve_all(w, a)
    return a


def _unknown(w, path="/uncertain") -> dict:
    """An R3 publication whose provider committed but whose acknowledgement was lost."""
    a = _approved(w, "sandbox.cms.publish_page", {**CMS, "path": path})
    adapters()["sandbox.cms.publish_page"].fault = "timeout_after_effect"
    try:
        assert dispatch(a["action_id"]).json()["action"]["state"] == "UNKNOWN"
    finally:
        adapters()["sandbox.cms.publish_page"].fault = None
    return a


def test_unconfirmed_effect_holds_new_r3_dispatch_until_reconciled(w):
    first = _unknown(w)
    second = _approved(w, "sandbox.cms.publish_page", {**CMS, "path": "/next"})
    held = dispatch(second["action_id"])
    body = held.json()
    assert held.status_code == 409 and body["error"]["code"] == "HELD"
    assert "UNCERTAINTY_DEBT:UNCERTAINTY_COUNT_EXCEEDED" in str(body)
    assert adb.get_request(second["action_id"])["state"] == "AUTHORIZED"  # a hold, not a block
    assert len(adb.sandbox_list(w["tenant"], provider="sandbox.cms_publish")) == 1  # only the uncertain effect exists

    # Recover: read the provider back. The effect exists, so the first action completes.
    assert client.post(f"/actions/{first['action_id']}/reconcile").json()["action"]["state"] == "COMPLETED"
    assert dispatch(second["action_id"]).json()["action"]["state"] == "COMPLETED"
    assert len(adb.sandbox_list(w["tenant"], provider="sandbox.cms_publish")) == 2


def test_lower_risk_work_continues_while_debt_is_outstanding(w):
    _unknown(w)
    draft = propose(w, "sandbox.cms.create_draft", {**CMS, "path": "/draft"})["action"]
    assert draft["effective_class"] == "R2"
    assert dispatch(draft["action_id"]).json()["action"]["state"] == "COMPLETED"
    research = propose(w, "sandbox.research.fetch_public", {"url": "https://example.com/", "purpose": "background"})["action"]
    assert dispatch(research["action_id"]).json()["action"]["state"] == "COMPLETED"


def test_needs_human_and_critical_classes_count(w):
    a = _approved(w, "sandbox.cms.publish_page", CMS)
    adapters()["sandbox.cms.publish_page"].fault = "observe_mismatch"
    dispatch(a["action_id"])
    assert client.post(f"/actions/{a['action_id']}/reconcile").json()["action"]["state"] == "NEEDS_HUMAN"
    debt = governance.uncertainty(w["tenant"])
    assert not debt.allow_high_risk_dispatch
    assert debt.unconfirmed_total == 1 and debt.unconfirmed_critical == 1


def test_another_tenants_uncertainty_never_holds_this_tenant(w, monkeypatch, tmp_path):
    other = make_world(monkeypatch, tmp_path / "other")
    _unknown(other)
    assert not governance.uncertainty(other["tenant"]).allow_high_risk_dispatch
    act_as(w, REQUESTER)
    mine = _approved(w, "sandbox.cms.publish_page", {**CMS, "path": "/mine"})
    assert governance.uncertainty(w["tenant"]).allow_high_risk_dispatch
    assert dispatch(mine["action_id"]).json()["action"]["state"] == "COMPLETED"


def test_a_possibly_truncated_snapshot_fails_closed(w, monkeypatch):
    _unknown(w)
    monkeypatch.setattr(governance, "UNCERTAINTY_SNAPSHOT_LIMIT", 0)
    debt = governance.uncertainty(w["tenant"])
    assert not debt.allow_high_risk_dispatch and "UNCERTAINTY_SNAPSHOT_INCOMPLETE" in debt.blockers


def test_debt_view_counts_tenant_wide_but_lists_only_accessible_projects(w):
    hidden = _unknown(w, "/hidden")
    act_as(w, OWNER)
    visible_action = propose(w, "sandbox.cms.publish_page", {**CMS, "path": "/visible"}, project=w["other"])["action"]
    approve_all(w, visible_action)
    act_as(w, OWNER, projects=w["other"])
    view = client.get("/actions/uncertainty").json()
    assert view["assessment"]["unconfirmed_total"] == 1 and view["assessment"]["allow_high_risk_dispatch"] is False
    assert [u["action_id"] for u in view["unresolved"]] == []  # the uncertain action is in a project this caller cannot see
    act_as(w, OWNER)
    listed = client.get("/actions/uncertainty").json()["unresolved"]
    assert [u["action_id"] for u in listed] == [hidden["action_id"]]
