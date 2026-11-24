"""FRRE W1 acceptance: preservation, FSM properties F01-F15, contracts, guards and inertness.

Gate map (docs/frre/FRRE-v15-spec.md section 10, v18 G1 split):
G1A contracts and fixtures; G1B the FSM matches the model-checked design; G1C stale, replayed,
expired, revoked and cross-tenant permits are refused; G1D bounded retry/recovery termination;
G1G W1 adds no enabled effect path.
"""
from __future__ import annotations

import ast
import contextlib
import hashlib
import io
import runpy
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from services.langgraph.agency.frre import contracts as c
from services.langgraph.agency.frre import fsm, guards, policy
from services.langgraph.agency.frre.fsm import BUDGETED_EDGES, TERMINAL, TRANSITIONS, IncidentState as S

ROOT = Path(__file__).resolve().parents[3]
FRRE_DIR = ROOT / "services/langgraph/agency/frre"
CHECKER = ROOT / "services/langgraph/tests/fixtures/frre/fsm_check_v15.py"
SPEC = ROOT / "docs/frre/FRRE-v15-spec.md"
T0 = datetime(2026, 11, 24, 22, 0, tzinfo=timezone.utc)
D1, D2, D3 = ("sha256:" + ch * 64 for ch in "abc")
SHA = "977158d2750b5083bc99c82c8ff24cdf40e38f45"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- P0/P2: preserved originals ------------------------------------------------------------

def test_preserved_spec_is_byte_identical_to_the_original() -> None:
    assert _sha256(SPEC) == "11ec3dcf885864e9beaa58431afca8e57d9bceb2bcc20976270dde16b1b105f0"


def test_preserved_checker_is_byte_identical_to_the_original() -> None:
    assert _sha256(CHECKER) == "a905b8b950331fc53c4f90e0ef33f45180f87023b03823050c9324b0275756d8"


# --- G1B: differential test against the model-checked design -----------------------------

def _design() -> dict:
    with contextlib.redirect_stdout(io.StringIO()):
        return runpy.run_path(str(CHECKER))


def test_fsm_is_exactly_the_model_checked_design() -> None:
    model = _design()
    implemented = {s.value: {d.value for d in dsts} for s, dsts in TRANSITIONS.items()}
    assert implemented == {k: set(v) for k, v in model["T"].items()}
    assert {s.value for s in TERMINAL} == model["TERMINAL"]
    assert (len(implemented), sum(len(v) for v in implemented.values())) == (25, 96)


def test_f01_every_state_is_reachable_from_observed() -> None:
    assert fsm.reachable(S.OBSERVED) == set(S)


def test_f02_f03_no_nonterminal_dead_end_and_terminals_are_final() -> None:
    for state in S:
        assert bool(TRANSITIONS[state]) == (state not in TERMINAL), state


def test_f04_every_illegal_pair_is_refused_and_every_legal_pair_accepted() -> None:
    for src in S:
        for dst in S:
            if dst in TRANSITIONS[src]:
                fsm.assert_transition(src, dst)
            else:
                with pytest.raises(fsm.IllegalTransition):
                    fsm.assert_transition(src, dst)


def test_f05_effect_stages_are_entered_only_from_their_permit_state() -> None:
    for stage, gate in fsm.PERMIT_GATES.items():
        assert {s for s in S if stage in TRANSITIONS[s]} == {gate}, stage


# --- G1D: termination (SCC + ranking function over budgets) ------------------------------

def _is_acyclic(edges: dict) -> bool:
    indegree = {s: 0 for s in edges}
    for dsts in edges.values():
        for d in dsts:
            indegree[d] += 1
    queue, seen = [s for s, n in indegree.items() if n == 0], 0
    while queue:
        seen += 1
        for d in edges[queue.pop()]:
            indegree[d] -= 1
            if indegree[d] == 0:
                queue.append(d)
    return seen == len(edges)


def test_f11_removing_budgeted_edges_leaves_a_dag() -> None:
    assert not _is_acyclic(dict(TRANSITIONS)), "the design has cycles; budgets must break them"
    assert _is_acyclic(fsm.without_budgeted_edges())


def _product_graph(budgeted: dict, attempts: int = 3, recoveries: int = 3) -> dict:
    """(state, attempts_left, recoveries_left) graph under the budget rules."""
    start, graph, todo = (S.OBSERVED, attempts, recoveries), {}, [(S.OBSERVED, attempts, recoveries)]
    while todo:
        node = todo.pop()
        if node in graph:
            continue
        state, a, r = node
        succ = set()
        for dst in TRANSITIONS[state]:
            counter = budgeted.get((state, dst))
            if (counter == "attempts" and a == 0) or (counter == "recoveries" and r == 0):
                continue
            succ.add((dst, a - (counter == "attempts"), r - (counter == "recoveries")))
        graph[node] = succ
        todo.extend(succ)
    assert start in graph
    return graph


def _stranded(graph: dict) -> list:
    return [n for n, succ in graph.items() if not succ and n[0] not in TERMINAL]


def test_f11_f15_every_run_terminates_and_exhaustion_never_strands() -> None:
    graph = _product_graph(dict(BUDGETED_EDGES))
    assert _is_acyclic(graph), "a budgeted run must not revisit a (state, budget) point"
    assert _stranded(graph) == [], "an exhausted budget must still leave an exit"


def test_f15_negative_control_budget_on_rollback_exit_strands_incidents() -> None:
    # The v15 sketch put the recovery budget on ROLLED_BACK -> POST_RELEASE_OBSERVED. ROLLED_BACK
    # has no other exit, so exhausting the budget there strands the incident. The check must see it.
    moved = {k: v for k, v in BUDGETED_EDGES.items() if v != "recoveries"}
    moved[(S.ROLLED_BACK, S.POST_RELEASE_OBSERVED)] = "recoveries"
    assert any(n[0] is S.ROLLED_BACK for n in _stranded(_product_graph(moved)))


def test_f15_negative_control_an_unbudgeted_cycle_is_detected() -> None:
    unbudgeted = {k: v for k, v in BUDGETED_EDGES.items() if k != (S.QUARANTINED, S.PLANNED)}
    assert not _is_acyclic(_product_graph(unbudgeted))


# --- G1A: contracts ------------------------------------------------------------------------

def _budget(**kw) -> c.Budget:
    return c.Budget(**{"runtime_s": 600, "tokens": 0, "cost_usd_cents": 0, "files": 5, **kw})


def _plan(**kw) -> c.RepairPlan:
    base = dict(id="plan-1", incident_id="inc-1", tenant_id="t1", project_id="p1", baseline_sha=SHA,
                objective="restore pin", allowed_paths=("services/langgraph/agency/ucpo/source.py",),
                operations=("edit",), risk=c.EffectClass.REVERSIBLE, acceptance=(D1,), negative_controls=(D2,),
                recovery="revert the commit", budget=_budget(), required_authority=c.PermitStage.MUTATE)
    return c.RepairPlan(**{**base, **kw})


def _permit(**kw) -> c.Permit:
    base = dict(id="pm-1", stage=c.PermitStage.MUTATE, actor="frre-repair", tool="code_sandbox", target="repo",
                args_digest=D1, tenant_id="t1", project_id="p1", baseline_sha=SHA, plan_digest=D2,
                policy_digest=D3, environment="ci", issued_at=T0, expires_at=T0 + timedelta(hours=1))
    return c.Permit(**{**base, **kw})


def _incident(**kw) -> c.Incident:
    base = dict(id="inc-1", tenant_id="t1", project_id="p1", source="ci", event_ref="run/45325719395",
                fingerprint=D1, time=T0, baseline_sha=SHA, environment="ubuntu-latest", severity=c.Severity.HIGH,
                failure_class=c.FailureClass.CI_GATE, symptoms=("invariants gate exit 1",))
    return c.Incident(**{**base, **kw})


def _validation(**kw) -> c.Validation:
    base = dict(candidate_digest=D1, baseline_results={"gate": c.TestResult.FAIL},
                target_results={"gate": c.TestResult.PASS}, verifier="frre-trust", verdict="PASS")
    return c.Validation(**{**base, **kw})


def test_valid_contracts_construct_with_pessimistic_defaults() -> None:
    inc = _incident()
    assert (inc.state, inc.version, inc.schema_version) == (S.OBSERVED, 0, "amc-frre/v1")
    assert _plan().budget.effects == 0 and _budget().concurrency == 1
    assert _permit().candidate_digest is None
    assert _validation().verdict == "PASS"
    cap = c.Capability(failure_class=c.FailureClass.CI_GATE, handler="h", entrypoint="x", authority=c.PermitStage.READ)
    assert cap.enabled is False and cap.maturity is c.Maturity.DOCUMENTED


@pytest.mark.parametrize("build", [_incident, _plan, _permit, _validation])
def test_unknown_fields_are_rejected(build) -> None:
    with pytest.raises(ValidationError):
        build(surprise=True)


@pytest.mark.parametrize("bad", [{"fingerprint": "sha256:XYZ"}, {"baseline_sha": "main"}, {"tenant_id": ""},
                                 {"symptoms": ()}, {"version": -1}, {"failure_class": "WHATEVER"}])
def test_incident_rejects_malformed_values(bad) -> None:
    with pytest.raises(ValidationError):
        _incident(**bad)


def test_strict_mode_refuses_lax_coercion() -> None:
    with pytest.raises(ValidationError):
        _budget(runtime_s="600")


@pytest.mark.parametrize("path", ["scripts/verify_manifest.py", "manifest.json", ".github/workflows/ci.yml",
                                  "services/langgraph/security/auth.py", "services/langgraph/agency/kernel/roles.py",
                                  "supabase/migrations/x.sql", "services/langgraph/tests/fixtures/frre/fsm_check_v15.py",
                                  "services/langgraph/agency/frre/policy.py", "services/langgraph/agency/frre/guards.py",
                                  "../outside.py", "/etc/passwd"])
def test_plans_and_candidates_cannot_touch_the_protected_floor(path) -> None:
    assert policy.is_protected(path)
    with pytest.raises(ValidationError, match="protected"):
        _plan(allowed_paths=(path,))
    with pytest.raises(ValidationError, match="protected"):
        c.Candidate(id="cand-1", incident_id="inc-1", plan_digest=D1, patch_digest=D2, changed_files=(path,),
                    candidate_digest=D3, semantic_diff_digest=D1, attempt=1, cost_usd_cents=0, provenance="test")


@pytest.mark.parametrize("kw", [{"risk": c.EffectClass.IRREVERSIBLE},
                                {"protected_paths": ("services/langgraph/agency/ucpo/*",)},
                                {"budget": "huge"}])
def test_plan_refuses_irreversible_effects_and_self_contradicting_scope(kw) -> None:
    with pytest.raises(ValidationError):
        _plan(**kw)


@pytest.mark.parametrize("kw", [{"concurrency": 2}, {"effects": 2}, {"attempts": 4}, {"recoveries": 4}])
def test_budget_cannot_exceed_policy_limits(kw) -> None:
    with pytest.raises(ValidationError):
        _budget(**kw)


@pytest.mark.parametrize("kw", [{"stage": c.PermitStage.VALIDATE},
                                {"candidate_digest": D1},
                                {"stage": c.PermitStage.RELEASE, "candidate_digest": D1},
                                {"plan_digest": None},
                                {"expires_at": T0}])
def test_permit_binds_exactly_what_its_stage_requires(kw) -> None:
    with pytest.raises(ValidationError):
        _permit(**kw)


def test_reproduce_permit_needs_no_plan_and_no_candidate_hash() -> None:
    p = _permit(stage=c.PermitStage.REPRODUCE, plan_digest=None)
    assert p.plan_digest is None and p.candidate_digest is None


@pytest.mark.parametrize("kw", [{"skipped": ("e2e",)}, {"unknown": ("pg",)}, {"regressions": ("t",)},
                                {"target_results": {"gate": c.TestResult.SKIPPED}},
                                {"baseline_results": {"gate": c.TestResult.PASS}}])
def test_validation_pass_must_be_earned(kw) -> None:
    with pytest.raises(ValidationError):
        _validation(**kw)
    assert _validation(**kw, verdict="BLOCKED").verdict == "BLOCKED"


def test_capability_cannot_be_enabled_without_promotion() -> None:
    base = dict(failure_class=c.FailureClass.CI_GATE, handler="h", entrypoint="x", authority=c.PermitStage.READ)
    for extra in ({"enabled": True}, {"enabled": True, "promotion_ref": "apr-1"}):
        with pytest.raises(ValidationError):
            c.Capability(**base, **extra)
    ok = c.Capability(**base, enabled=True, promotion_ref="apr-1", maturity=c.Maturity.ENABLED)
    assert ok.enabled


def test_diagnosis_cannot_select_an_unreproduced_cause() -> None:
    hyp = c.Hypothesis(cause="pin drift", classification=c.CauseClass.DEPENDENCY)
    for selected in (0, 5):
        with pytest.raises(ValidationError):
            c.Diagnosis(incident_id="inc-1", tenant_id="t1", hypotheses=(hyp,), selected_cause=selected)
    repro = hyp.model_copy(update={"reproduction": "REPRODUCED"})
    assert c.Diagnosis(incident_id="inc-1", tenant_id="t1", hypotheses=(repro,), selected_cause=0).selected_cause == 0


def _transition(src: S, dst: S, **kw) -> c.Transition:
    base = dict(incident_id="inc-1", tenant_id="t1", from_state=src, to_state=dst, actor="frre-tick", time=T0,
                expected_version=4, new_version=5, idempotency_key=f"k-{src.value}-{dst.value}", fencing_token=7,
                reason="test")
    return c.Transition(**{**base, **kw})


@pytest.mark.parametrize("kw", [{"to_state": S.RESOLVED}, {"new_version": 7}])
def test_transition_contract_refuses_illegal_edges_and_non_cas_versions(kw) -> None:
    with pytest.raises((ValidationError, fsm.IllegalTransition)):
        _transition(S.PLANNED, S.MUTATION_AUTHORIZED, **kw)


def test_transition_into_an_effect_stage_requires_a_permit() -> None:
    with pytest.raises(ValidationError, match="permit"):
        _transition(S.MUTATION_AUTHORIZED, S.SANDBOXED)


def test_outcome_cannot_claim_resolution_or_invent_metrics() -> None:
    with pytest.raises(ValidationError):
        c.Outcome(incident_id="inc-1", state=S.RESOLVED, recovery="n/a", next_action="none")
    with pytest.raises(ValidationError):
        c.Outcome(incident_id="inc-1", state=S.NO_ACTION, recovery="n/a", next_action="none", metrics={"mttd": "4m"})


# --- G1C: permits and the decision guard ------------------------------------------------

def _ctx(**kw) -> guards.PermitContext:
    base = dict(stage=c.PermitStage.MUTATE, now=T0 + timedelta(minutes=5), tenant_id="t1", project_id="p1",
                baseline_sha=SHA, policy_digest=D3, plan_digest=D2)
    return guards.PermitContext(**{**base, **kw})


def test_a_matching_permit_has_no_refusals() -> None:
    assert guards.permit_refusals(_permit(), _ctx()) == ()


@pytest.mark.parametrize("permit_kw,ctx_kw,code", [
    ({}, {"now": T0 + timedelta(hours=2)}, "PERMIT_EXPIRED"),
    ({}, {"now": T0 - timedelta(minutes=1)}, "PERMIT_NOT_YET_VALID"),
    ({}, {"revoked": frozenset({"pm-1"})}, "PERMIT_REVOKED"),
    ({"revocation_ref": "owner-revoked"}, {}, "PERMIT_REVOKED"),
    ({}, {"used_permit_ids": frozenset({"pm-1"})}, "PERMIT_REPLAYED"),
    ({}, {"tenant_id": "t2"}, "TENANT_MISMATCH"),
    ({}, {"project_id": "p2"}, "PROJECT_MISMATCH"),
    ({}, {"baseline_sha": "0" * 40}, "BASELINE_DRIFT"),
    ({}, {"policy_digest": D1}, "POLICY_DRIFT"),
    ({}, {"plan_digest": D1}, "PLAN_MISMATCH"),
    ({}, {"stage": c.PermitStage.VALIDATE}, "PERMIT_STAGE_MISMATCH"),
    ({"stage": c.PermitStage.VALIDATE, "candidate_digest": D1}, {"stage": c.PermitStage.VALIDATE,
                                                                  "candidate_digest": D2}, "CANDIDATE_MISMATCH"),
])
def test_stale_replayed_expired_revoked_and_cross_tenant_permits_are_refused(permit_kw, ctx_kw, code) -> None:
    assert code in guards.permit_refusals(_permit(**permit_kw), _ctx(**ctx_kw))


def _facts(state: S = S.PLANNED, **kw) -> guards.IncidentFacts:
    base = dict(tenant_id="t1", state=state, version=4, last_fencing_token=7, attempts_left=3, recoveries_left=3,
                halted=False, permit_refusals=(), validation_verdict="PASS", post_release_healthy=True)
    return guards.IncidentFacts(**{**base, **kw})


def test_a_fully_evidenced_move_is_applied_with_a_cas_version() -> None:
    d = guards.decide(_transition(S.PLANNED, S.MUTATION_AUTHORIZED), _facts())
    assert (d.kind, d.codes, d.new_version) == ("APPLY", (), 5)


@pytest.mark.parametrize("facts_kw,code", [
    ({"halted": None}, "HALT_STATE_UNKNOWN"), ({"halted": True}, "HALTED"),
    ({"state": S.DIAGNOSED}, "STALE_STATE"), ({"version": 5}, "CAS_CONFLICT"),
    ({"last_fencing_token": 8}, "FENCED_STALE_LEASE"), ({"tenant_id": "t2"}, "TENANT_MISMATCH"),
])
def test_decide_refuses_unknown_halt_stale_state_cas_fencing_and_tenant(facts_kw, code) -> None:
    d = guards.decide(_transition(S.PLANNED, S.MUTATION_AUTHORIZED), _facts(**facts_kw))
    assert d.kind == "REFUSE" and code in d.codes and d.new_version is None


def test_idempotent_replay_is_a_noop_but_never_across_tenants() -> None:
    t = _transition(S.PLANNED, S.MUTATION_AUTHORIZED)
    assert guards.decide(t, _facts(applied_idempotency_keys=frozenset({t.idempotency_key}))).kind == "NOOP"
    other = _facts(tenant_id="t2", applied_idempotency_keys=frozenset({t.idempotency_key}))
    assert guards.decide(t, other).kind == "REFUSE"


@pytest.mark.parametrize("facts_kw,code", [({"permit_refusals": None}, "PERMIT_UNCHECKED:MUTATE"),
                                           ({"permit_refusals": ("PERMIT_EXPIRED",)}, "PERMIT_EXPIRED")])
def test_effect_stage_needs_a_checked_clean_permit(facts_kw, code) -> None:
    t = _transition(S.MUTATION_AUTHORIZED, S.SANDBOXED, permit_id="pm-1")
    d = guards.decide(t, _facts(S.MUTATION_AUTHORIZED, **facts_kw))
    assert d.kind == "REFUSE" and code in d.codes


def test_no_unsupported_success_validated_and_resolved_need_evidence() -> None:
    to_validated = _transition(S.VALIDATION_AUTHORIZED, S.VALIDATED, permit_id="pm-2")
    for verdict in (None, "FAIL", "BLOCKED"):
        d = guards.decide(to_validated, _facts(S.VALIDATION_AUTHORIZED, validation_verdict=verdict))
        assert "VALIDATION_NOT_PASSED" in d.codes
    to_resolved = _transition(S.POST_RELEASE_OBSERVED, S.RESOLVED)
    for healthy in (None, False):
        d = guards.decide(to_resolved, _facts(S.POST_RELEASE_OBSERVED, post_release_healthy=healthy))
        assert "RECOVERY_NOT_OBSERVED" in d.codes


def test_g1g_release_is_refused_even_with_a_clean_permit_in_w1() -> None:
    d = guards.decide(_transition(S.RELEASE_APPROVED, S.RELEASED, permit_id="pm-3"), _facts(S.RELEASE_APPROVED))
    assert d.kind == "REFUSE" and d.codes == ("DELIVERY_DISABLED",)


def test_budget_decrements_monotonically_and_exhaustion_leaves_an_exit() -> None:
    replan = _transition(S.QUARANTINED, S.PLANNED)
    d = guards.decide(replan, _facts(S.QUARANTINED, attempts_left=2))
    assert (d.kind, d.attempts_left, d.consumed) == ("APPLY", 1, "attempts")
    assert guards.decide(replan, _facts(S.QUARANTINED, attempts_left=0)).codes == ("BUDGET_EXHAUSTED:attempts",)
    escape = guards.decide(_transition(S.QUARANTINED, S.ESCALATED), _facts(S.QUARANTINED, attempts_left=0))
    assert escape.kind == "APPLY" and escape.attempts_left == 0
    rollback = _transition(S.RECOVERY_REQUIRED, S.ROLLED_BACK)
    assert guards.decide(rollback, _facts(S.RECOVERY_REQUIRED, recoveries_left=0)).kind == "REFUSE"
    assert guards.decide(_transition(S.RECOVERY_REQUIRED, S.ESCALATED),
                         _facts(S.RECOVERY_REQUIRED, recoveries_left=0)).kind == "APPLY"


def test_authority_noninterference_incident_content_is_not_a_guard_input() -> None:
    fields = set(guards.IncidentFacts.__dataclass_fields__)
    assert not fields & {"severity", "symptoms", "confidence", "summary", "source", "evidence"}


def test_corrupt_guard_inputs_fail_closed() -> None:
    clean = _facts()
    for corrupt in (replace(clean, halted=None), replace(clean, permit_refusals=None, state=S.MUTATION_AUTHORIZED)):
        target = S.SANDBOXED if corrupt.state is S.MUTATION_AUTHORIZED else S.MUTATION_AUTHORIZED
        t = _transition(corrupt.state, target, permit_id="pm-1")
        assert guards.decide(t, corrupt).kind == "REFUSE"


# --- G1G: inertness -----------------------------------------------------------------------

ALLOWED_IMPORTS = {"__future__", "dataclasses", "datetime", "enum", "fnmatch", "typing", "pydantic"}


def test_frre_modules_import_nothing_that_can_take_an_effect() -> None:
    for module in sorted(FRRE_DIR.glob("*.py")):
        tree = ast.parse(module.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                names = set() if node.level else {(node.module or "").split(".")[0]}
            else:
                continue
            assert names <= ALLOWED_IMPORTS, (module.name, names)


def test_w1_is_inert_no_live_code_references_frre() -> None:
    roots = [ROOT / "services/langgraph", ROOT / "apps/web/app", ROOT / "apps/web/lib", ROOT / "scripts"]
    offenders = []
    for root in roots:
        for path in root.rglob("*"):
            if path.suffix not in {".py", ".ts", ".tsx"} or FRRE_DIR in path.parents:
                continue
            if "tests" in path.parts or "node_modules" in path.parts:
                continue
            if "agency.frre" in path.read_text(errors="ignore") or "agency/frre" in path.read_text(errors="ignore"):
                offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_importing_frre_loads_no_route_worker_persistence_or_integration_module() -> None:
    probe = ("import sys; sys.path.insert(0, %r); import services.langgraph.agency.frre.guards; "
             "bad = [m for m in sys.modules if m.startswith(('services.langgraph.api', 'services.langgraph.persistence', "
             "'services.langgraph.runtime', 'services.langgraph.integrations', 'services.langgraph.graph'))]; "
             "print(bad)") % str(ROOT)
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=60, check=True)
    assert out.stdout.strip() == "[]"


def test_policy_literals_are_fail_closed() -> None:
    assert not any((policy.AUTO_MERGE, policy.AUTO_PROMOTION, policy.SELF_APPROVAL, policy.POLICY_SELF_MUTATION,
                    policy.PRODUCTION_WRITE, policy.ENABLED_BY_DEFAULT, policy.DELIVERY_ENABLED))
    assert (policy.DEFAULT_MAX_ATTEMPTS, policy.DEFAULT_MAX_RECOVERIES, policy.CONCURRENCY_PER_WORKSPACE) == (3, 3, 1)
