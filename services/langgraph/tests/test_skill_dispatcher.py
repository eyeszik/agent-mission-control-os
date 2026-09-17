"""Tests for the skill runtime: the capability-gated dispatch layer between a
role and an external tool (agency/skills/dispatcher.py).

No test performs a real network call. zo.py's own httpx.post is patched
wherever the zo_ask handler would otherwise reach the network.
"""

from __future__ import annotations

import httpx
import pytest

from services.langgraph.agency.kernel.ontology import Capability
from services.langgraph.agency.kernel.roles import RoleContractError
from services.langgraph.agency.skills import dispatcher
from services.langgraph.agency.skills.dispatcher import (
    Skill,
    SkillDispatchError,
    dispatch_skill,
    get_skill,
    skill_registry_snapshot,
)


# --- authorization: fails closed before the handler ever runs --------------


def test_unknown_role_raises_role_contract_error():
    with pytest.raises(RoleContractError):
        dispatch_skill("not_a_real_role", "zo_ask", {"prompt": "hello"})


def test_unknown_skill_raises_skill_dispatch_error():
    with pytest.raises(SkillDispatchError, match="Unknown skill"):
        dispatch_skill("market_researcher", "not_a_real_skill", {})


def test_role_without_the_required_capability_is_refused():
    # copywriter holds Capability.copywriting, not research_synthesis.
    with pytest.raises(SkillDispatchError, match="may not invoke"):
        dispatch_skill("copywriter", "zo_ask", {"prompt": "hello"})


def test_authorization_failure_names_the_missing_capability_and_role():
    with pytest.raises(SkillDispatchError) as excinfo:
        dispatch_skill("copywriter", "zo_ask", {"prompt": "hello"})
    message = str(excinfo.value)
    assert "research_synthesis" in message
    assert "copywriter" in message


def test_get_skill_raises_for_unknown_id():
    with pytest.raises(SkillDispatchError, match="Unknown skill"):
        get_skill("nonexistent")


def test_get_skill_returns_the_registered_skill():
    skill = get_skill("zo_ask")
    assert skill.skill_id == "zo_ask"
    assert skill.capability is Capability.research_synthesis


# --- execution: authorized calls never raise, they return an outcome -------


def test_authorized_dispatch_with_disabled_integration_returns_failed_outcome(monkeypatch):
    monkeypatch.delenv("AMC_ZO_MODE", raising=False)
    monkeypatch.delenv("ZO_API_KEY", raising=False)

    outcome = dispatch_skill("market_researcher", "zo_ask", {"prompt": "What is zo.computer?"})

    assert outcome.succeeded is False
    assert outcome.status == "FAILED"
    assert outcome.error_class == "ZoIntegrationError"
    assert outcome.result is None


def test_successful_dispatch_returns_success_outcome_with_result(monkeypatch):
    monkeypatch.setenv("AMC_ZO_MODE", "live")
    monkeypatch.setenv("ZO_API_KEY", "zo_sk_test_only")

    def fake_post(url, *, headers, json, timeout):
        return httpx.Response(200, json={"answer": "ok"}, request=httpx.Request("POST", url))

    import services.langgraph.integrations.zo as zo_module

    monkeypatch.setattr(zo_module.httpx, "post", fake_post)

    outcome = dispatch_skill("market_researcher", "zo_ask", {"prompt": "What is zo.computer?"})

    assert outcome.succeeded is True
    assert outcome.status == "SUCCESS"
    assert outcome.result == {"answer": "ok"}
    assert outcome.error_class is None


def test_dispatch_carries_role_and_skill_identity_in_the_outcome(monkeypatch):
    monkeypatch.delenv("AMC_ZO_MODE", raising=False)
    outcome = dispatch_skill("market_researcher", "zo_ask", {"prompt": "hi there"})
    assert outcome.role_id == "market_researcher"
    assert outcome.skill_id == "zo_ask"
    assert outcome.capability == "research_synthesis"


def test_provenance_excludes_result_and_error_message(monkeypatch):
    monkeypatch.delenv("AMC_ZO_MODE", raising=False)
    outcome = dispatch_skill("market_researcher", "zo_ask", {"prompt": "hi there"})
    provenance = outcome.provenance()
    assert "result" not in provenance
    assert "error_message" not in provenance
    assert provenance["status"] == "FAILED"
    assert provenance["skill_id"] == "zo_ask"


def test_empty_payload_defaults_to_empty_dict(monkeypatch):
    monkeypatch.delenv("AMC_ZO_MODE", raising=False)
    # Must not raise TypeError for missing payload; the ValueError from the
    # handler's own prompt validation is expected and captured as FAILED.
    outcome = dispatch_skill("market_researcher", "zo_ask", None)
    assert outcome.status == "FAILED"


# --- the zo_ask handler's own argument contract -----------------------------


def test_zo_ask_handler_rejects_missing_prompt():
    with pytest.raises(ValueError, match="prompt"):
        dispatcher._ask_zo_handler({})


def test_zo_ask_handler_rejects_blank_prompt():
    with pytest.raises(ValueError, match="prompt"):
        dispatcher._ask_zo_handler({"prompt": "   "})


def test_zo_ask_handler_forwards_timeout_seconds(monkeypatch):
    monkeypatch.setenv("AMC_ZO_MODE", "live")
    monkeypatch.setenv("ZO_API_KEY", "zo_sk_test_only")

    captured = {}

    def fake_post(url, *, headers, json, timeout):
        captured["timeout"] = timeout
        return httpx.Response(200, json={"answer": "ok"}, request=httpx.Request("POST", url))

    import services.langgraph.integrations.zo as zo_module

    monkeypatch.setattr(zo_module.httpx, "post", fake_post)

    dispatcher._ask_zo_handler({"prompt": "hello", "timeout_seconds": 5.0})
    assert captured["timeout"] == 5.0


# --- registry structure ------------------------------------------------------


def test_registry_is_keyed_by_its_own_skill_id():
    for skill_id, skill in dispatcher.SKILL_REGISTRY.items():
        assert skill_id == skill.skill_id


def test_skill_registry_snapshot_reports_availability(monkeypatch):
    monkeypatch.delenv("AMC_ZO_MODE", raising=False)
    monkeypatch.delenv("ZO_API_KEY", raising=False)
    snapshot = skill_registry_snapshot()
    assert snapshot["skill_runtime_version"] == dispatcher.SKILL_RUNTIME_VERSION
    zo_entry = next(item for item in snapshot["skills"] if item["skill_id"] == "zo_ask")
    assert zo_entry["capability"] == "research_synthesis"
    assert zo_entry["available"] is False


def test_skill_registry_snapshot_availability_becomes_true_when_live(monkeypatch):
    monkeypatch.setenv("AMC_ZO_MODE", "live")
    monkeypatch.setenv("ZO_API_KEY", "zo_sk_test_only")
    snapshot = skill_registry_snapshot()
    zo_entry = next(item for item in snapshot["skills"] if item["skill_id"] == "zo_ask")
    assert zo_entry["available"] is True


def test_skill_without_an_availability_check_reports_none():
    skill = Skill(
        skill_id="_test_only_skill",
        capability=Capability.research_synthesis,
        description="test fixture",
        handler=lambda payload: {},
    )
    assert skill.availability_check is None
