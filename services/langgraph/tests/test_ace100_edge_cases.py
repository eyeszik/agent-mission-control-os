"""ACE v100 critical edge cases: INJECT -> ASSERT -> RECOVER -> VERIFY, through real code paths.

Each test injects the fault through the real API or persistence layer (sandbox
providers only), asserts the safe outcome, recovers through the supported path
and verifies the end state against independent evidence (sandbox read-back,
hash-chained history, reservations). The CI run of these tests on an exact
commit is the RECORD; nothing here contacts a real provider.

E01 provider commits, acknowledgement lost       E07 compensation partially fails
E02 stale worker races a new leaseholder         E08 encoded credentials vs persistent sinks
E03 duplicate delivery, concurrent dispatch      E09 Python/Zod validation drift
E04 provider without reliable reconciliation     E10 CI evidence for another SHA
E05 approval expires or is replayed              E11 signing or monitoring fails at release
E06 cross-tenant effect or evidence collision
"""

from __future__ import annotations

import base64
import threading
from datetime import datetime, timedelta, timezone

import pytest

from services.langgraph.agency.ace_evidence import gate_results_from_check_runs, production_status
from services.langgraph.agency.actions import gateway, governance
from services.langgraph.agency.actions.adapters import adapters
from services.langgraph.persistence import actions as adb
from services.langgraph.security.auth import Principal
from services.langgraph.tests._ace12_support import (
    CMS,
    REQUESTER,
    REVIEWER,
    SPEND,
    act_as,
    approvals_of,
    approve_all,
    decide,
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


def _effects(w, provider="sandbox.cms_publish"):
    return adb.sandbox_list(w["tenant"], provider=provider)


def _principal(w, user=REQUESTER, role="editor"):
    return Principal(user_id=user, tenant_id=w["tenant"], role=role, allowed_project_ids=frozenset({"*"}))


def test_e01_provider_commits_but_the_acknowledgement_is_lost(w):
    a = _approved(w, "sandbox.cms.publish_page", CMS)
    adapters()["sandbox.cms.publish_page"].fault = "timeout_after_effect"  # INJECT
    out = dispatch(a["action_id"]).json()["action"]
    adapters()["sandbox.cms.publish_page"].fault = None
    assert out["state"] == "UNKNOWN" and len(_effects(w)) == 1  # ASSERT: never reported as failed or done
    assert not governance.uncertainty(w["tenant"]).allow_high_risk_dispatch  # no new R3 effect meanwhile
    assert dispatch(a["action_id"]).status_code == 409  # UNKNOWN is never re-sent
    done = client.post(f"/actions/{a['action_id']}/reconcile").json()["action"]  # RECOVER: read back
    assert done["state"] == "COMPLETED" and len(_effects(w)) == 1  # VERIFY: one effect, adopted
    ev = client.get(f"/actions/{a['action_id']}/evidence").json()
    assert ev["chain"]["intact"] and any(o.get("matches") for o in ev["observation_receipts"])
    assert governance.uncertainty(w["tenant"]).allow_high_risk_dispatch


def test_e02_a_stale_worker_cannot_write_after_a_new_leaseholder_takes_over(w):
    a = _approved(w, "sandbox.cms.publish_page", CMS)
    row = gateway.settle(a["action_id"])
    past = datetime.now(timezone.utc) - timedelta(minutes=10)
    stale = adb.transition(row["action_id"], expected_version=row["version"], expected_states=(row["state"],),
                           to_state="DISPATCHING", actor="worker-old", reason="old worker leased the action",
                           updates={"lease_owner": "worker-old", "lease_expires_at": adb.iso(past), "attempts": 1})
    recovered = gateway.recover_stale()  # INJECT: the old worker's lease expired; recovery takes over
    assert [r["action_id"] for r in recovered] == [a["action_id"]]
    after = adb.get_request(a["action_id"])
    assert after["state"] == "FAILED" and after["reasons"] == ["NOT_APPLIED"]  # read back: nothing was applied
    with pytest.raises(adb.ActionConflict):  # ASSERT: the stale worker's late write is fenced by version
        adb.transition(a["action_id"], expected_version=stale["version"], expected_states=("DISPATCHING",),
                       to_state="OBSERVING", actor="worker-old", reason="late completion")
    assert adb.get_request(a["action_id"])["state"] == "FAILED" and _effects(w) == []
    retried = client.post(f"/actions/{a['action_id']}/retry").json()["action"]  # RECOVER
    assert retried["state"] == "COMPLETED" and len(_effects(w)) == 1  # VERIFY
    assert adb.verify_transition_chain(a["action_id"])["intact"]


def test_e03_duplicate_delivery_dispatches_exactly_one_effect(w):
    a = _approved(w, "sandbox.cms.publish_page", CMS)
    principal, outcomes = _principal(w), []

    def deliver():  # INJECT: the same work item delivered to four workers at once
        try:
            outcomes.append(gateway.dispatch(principal, a["action_id"])["state"])
        except gateway.GatewayError as exc:
            outcomes.append(exc.code)
        except Exception as exc:  # any other escape is a defect
            outcomes.append(f"UNEXPECTED:{type(exc).__name__}")

    threads = [threading.Thread(target=deliver) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not [o for o in outcomes if o.startswith("UNEXPECTED")], outcomes  # ASSERT
    assert outcomes.count("COMPLETED") == 1 and len(_effects(w)) == 1  # VERIFY
    assert adb.verify_transition_chain(a["action_id"])["intact"]


def test_e04_a_provider_that_cannot_be_read_back_escalates_and_is_never_resent(w):
    a = _approved(w, "sandbox.cms.publish_page", CMS)
    adapters()["sandbox.cms.publish_page"].fault = "timeout_after_effect"
    dispatch(a["action_id"])
    adapters()["sandbox.cms.publish_page"].fault = "observe_unreachable"  # INJECT: no reliable reconciliation
    states = [client.post(f"/actions/{a['action_id']}/reconcile").json()["action"]["state"] for _ in range(3)]
    assert states[-1] == "NEEDS_HUMAN" and len(_effects(w)) == 1  # ASSERT: escalated, never re-sent
    other = _approved(w, "sandbox.cms.publish_page", {**CMS, "path": "/other"})
    assert dispatch(other["action_id"]).json()["error"]["code"] == "HELD"  # uncertainty debt holds new R3 work
    adapters()["sandbox.cms.publish_page"].fault = None  # RECOVER: provider readable again
    assert client.post(f"/actions/{a['action_id']}/reconcile").json()["action"]["state"] == "COMPLETED"
    assert dispatch(other["action_id"]).json()["action"]["state"] == "COMPLETED"  # VERIFY
    assert len(_effects(w)) == 2


def test_e05_expired_or_replayed_approvals_never_authorize(w):
    a = propose(w, "sandbox.cms.publish_page", CMS, ttl_seconds=60)["action"]
    approve_all(w, a)
    later = datetime.now(timezone.utc) + timedelta(minutes=5)
    with pytest.raises(gateway.NotDispatchable):  # INJECT: expired before dispatch
        gateway.dispatch(_principal(w), a["action_id"], now=later)
    assert adb.get_request(a["action_id"])["state"] == "EXPIRED" and _effects(w) == []

    b = propose(w, "sandbox.cms.publish_page", {**CMS, "path": "/b"})["action"]
    c = propose(w, "sandbox.cms.publish_page", {**CMS, "path": "/c"})["action"]
    b_approval = approvals_of(b)["ACTION_EXECUTION"]
    assert decide(w, b_approval, REVIEWER) == 200
    assert decide(w, b_approval, REVIEWER) == 409  # INJECT: replay the same decision
    act_as(w, REQUESTER)
    assert dispatch(c["action_id"]).status_code == 409  # b's approval never authorizes c (different binding)
    assert dispatch(b["action_id"]).json()["action"]["state"] == "COMPLETED"  # VERIFY: only b ran
    assert len(_effects(w)) == 1


def test_e06_identical_requests_in_two_tenants_never_collide(w, monkeypatch, tmp_path):
    other = make_world(monkeypatch, tmp_path / "other")
    act_as(w, REQUESTER)
    mine = _approved(w, "sandbox.cms.publish_page", CMS, key="shared-key-1")  # INJECT: same key, same payload
    assert dispatch(mine["action_id"]).json()["action"]["state"] == "COMPLETED"
    act_as(other, REQUESTER)
    theirs = _approved(other, "sandbox.cms.publish_page", CMS, key="shared-key-1")
    assert theirs["action_id"] != mine["action_id"]
    assert dispatch(theirs["action_id"]).json()["action"]["state"] == "COMPLETED"
    assert len(_effects(w)) == 1 and len(_effects(other)) == 1  # ASSERT: separate effects, keyed per tenant
    assert _effects(w)[0]["effect_id"] != _effects(other)[0]["effect_id"]
    assert client.get(f"/actions/{mine['action_id']}/evidence").status_code == 404  # VERIFY: no cross-tenant evidence
    act_as(w, REQUESTER)
    assert client.get(f"/actions/{mine['action_id']}/evidence").status_code == 200


def test_e07_a_partially_failed_compensation_is_recorded_and_safely_rerun(w):
    a = _approved(w, "sandbox.ads.commit_spend", SPEND)
    assert dispatch(a["action_id"]).json()["action"]["state"] == "COMPLETED"
    act_as(w, REVIEWER)
    adapters()["sandbox.ads.commit_spend"].fault = "observe_unreachable"  # INJECT: refund applied, read-back lost
    r = client.post(f"/actions/{a['action_id']}/compensate", json={"reason": "client cancelled"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "COMPENSATION_UNCONFIRMED"  # ASSERT: no 500, no claim
    row = adb.get_request(a["action_id"])
    assert row["outcome"]["compensation"]["status"] == "UNCONFIRMED"
    assert adb.get_reservation(row["budget_reservation_id"])["status"] == "COMMITTED"  # not refunded on a guess
    adapters()["sandbox.ads.commit_spend"].fault = None
    out = client.post(f"/actions/{a['action_id']}/compensate", json={"reason": "client cancelled"}).json()["action"]  # RECOVER
    assert out["outcome"]["compensation"]["status"] == "CONFIRMED"
    assert out["outcome"]["compensation"]["observed_state"] == "REFUNDED"  # VERIFY
    effects = _effects(w, "sandbox.ads")
    assert len(effects) == 1 and effects[0]["state"] == "REFUNDED"  # applied once, not twice
    assert adb.get_reservation(out["budget_reservation_id"])["status"] == "REFUNDED"
    assert adb.verify_transition_chain(a["action_id"])["intact"]


def test_e08_encoded_credentials_are_refused_before_any_persistent_sink(w):
    from urllib.parse import quote

    token = "Authorization: Bearer sk-live-" + "9" * 32
    for label, smuggled in (("base64", base64.b64encode(token.encode()).decode()), ("percent", quote(quote(token)))):
        r = client.post("/actions", json={"capability_id": "sandbox.cms.create_draft", "project_id": w["project"],
                                          "environment": "SANDBOX", "args": {**CMS, "body": f"see {smuggled}"}},
                        headers={"Idempotency-Key": f"e08-{label}"})  # INJECT: an encoded bearer token
        assert r.status_code == 422 and r.json()["error"]["code"] == "SECRET_IN_PAYLOAD", label  # ASSERT
    assert adb.list_requests(w["tenant"]) == []  # VERIFY: nothing reached storage, history or evidence
    ok = client.post("/actions", json={"capability_id": "sandbox.cms.create_draft", "project_id": w["project"],
                                       "environment": "SANDBOX", "args": {**CMS, "body": base64.b64encode(b"plain words, no secrets").decode()}},
                     headers={"Idempotency-Key": "e08-benign"})
    assert ok.status_code == 201  # RECOVER: ordinary encoded content is still accepted


def test_e09_python_and_zod_vocabularies_cannot_drift():
    from services.langgraph.tests.test_ace12_contracts import _ts_enum
    from services.langgraph.agency.actions.fsm import ActionState

    assert _ts_enum("ActionStateSchema") == [s.value for s in ActionState]
    schema = (__import__("pathlib").Path(__file__).resolve().parents[3] / "packages/shared/src/schemas/agencyOs.ts").read_text()
    debt_states = schema.split("export const UncertaintyDebtSchema", 1)[1].split("state: z.enum([", 1)[1].split("])", 1)[0]
    assert [s.strip(" '") for s in debt_states.split(",")] == list(governance.UNRESOLVED_STATES)


def test_e10_ci_evidence_from_another_sha_never_counts():
    sha, other = "c" * 40, "d" * 40
    runs = [{"id": 1, "name": "Backend (compile + invariants + pytest)", "head_sha": other, "status": "completed",
             "conclusion": "success", "completed_at": "2026-10-15T00:00:00Z"}]  # INJECT: green, but for another commit
    collected = gate_results_from_check_runs(runs, sha=sha)
    assert {g.gate: g.status for g in collected.gates}["backend_sqlite"] == "UNVERIFIED"  # ASSERT
    assert production_status(collected=collected, merged_into_default=True)["release_permitted"] is False  # VERIFY


def test_e11_signing_or_monitoring_failure_blocks_release():
    from services.langgraph.tests.test_ace_release import SHA, decide, proof

    bundle = proof()
    signed_ok = decide(bundle)
    assert signed_ok.authorized
    lost_key = decide(bundle, keys={})  # INJECT: signing key unavailable at deploy time
    assert not lost_key.authorized and "INVALID_EVIDENCE_SIGNATURE" in lost_key.reasons
    from services.langgraph.tests.test_ace100_evidence import FULL, _all_pass

    collected = _all_pass(SHA)
    no_monitoring = FULL.model_copy(update={"telemetry_ingestion_verified": False})  # INJECT: monitoring down
    assert production_status(collected=collected, merged_into_default=True, operational=no_monitoring,
                             promotion=signed_ok)["release_permitted"] is False  # ASSERT
    assert production_status(collected=collected, merged_into_default=True, operational=FULL,
                             promotion=lost_key)["release_permitted"] is False
    ok = production_status(collected=collected, merged_into_default=True, operational=FULL, promotion=signed_ok)
    assert ok["release_permitted"] is True  # VERIFY: only with both restored
