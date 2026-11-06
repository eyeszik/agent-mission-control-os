"""Method routing and delegation (docs/method-routing-delegation.md).

Covers the spec's validation list: every family, multi-label routing, the
simple short circuit, deterministic hashes under reordering, shadow duels,
minimal stacks, uncertainty-first ordering, capability gaps, authority that a
score cannot buy, missing tools/approvals, stale-context invalidation, cycles,
collision serialization, idempotent identity, bounded failure handling,
fail-closed external writes, separation of duties and non-duplication.
"""

from __future__ import annotations

import ast
import copy
import inspect
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from services.langgraph.agency.compiled import method_catalog as catalog_module
from services.langgraph.agency.compiled import method_mission as mission_module
from services.langgraph.agency.compiled import method_models as models_module
from services.langgraph.agency.compiled import method_router as router_module
from services.langgraph.agency.compiled.backchain import BackchainCycleError
from services.langgraph.agency.compiled.execution import Wave, WavePlan
from services.langgraph.agency.compiled.method_catalog import CATALOG_PATH, CatalogError, load_catalog, parse_catalog
from services.langgraph.agency.compiled.method_mission import (
    EXECUTOR_GAP,
    Attempt,
    MethodCompileError,
    _cap_waves,
    causal_closure,
    compile_method_mission,
    mutation_key,
    next_step,
    verify_context_chain,
)
from services.langgraph.agency.compiled.method_models import (
    MAX_SPECIALISTS_PER_WAVE,
    ObjectiveRequest,
    Slot,
)
from services.langgraph.agency.compiled.method_router import (
    MACRO_NEED,
    PREREQ_NODE,
    _prune,
    compile_method_plan,
    request_hash,
)
from services.langgraph.agency.kernel.ontology import ArtifactType
from services.langgraph.agency.role_os.registry import RoleOSRegistry
from services.langgraph.persistence.idempotency import reserve_idempotency
from services.langgraph.security.approval_authority import assert_may_decide
from services.langgraph.security.auth import Principal

ROOT = Path(__file__).resolve().parents[3]
REGISTRY = RoleOSRegistry(ROOT / "runtime" / "role_os")
CATALOG = load_catalog()

RECURRING_DEFECT = ObjectiveRequest(
    objective="Checkout defect keeps recurring",
    problem_recurs=True,
    root_cause_known=False,
    process_exists=True,
    measurement_available=False,
)

# One structural trigger per family.
FAMILY_TRIGGERS = {
    "PRIORITIZATION": {"items_to_rank": ("a", "b")},
    "DECISION": {"options": ("x", "y")},
    "PROCESS_IMPROVEMENT": {"process_exists": True, "current_state_known": True, "target_state_known": True},
    "ROOT_CAUSE": {"problem_recurs": True, "root_cause_known": False, "process_exists": True},
    "WORKFLOW_WASTE": {"waste_observed": True, "process_exists": True},
    "FLOW_BOTTLENECK": {"throughput_constrained": True},
    "PROCESS_VARIATION": {"variation_observed": True, "measurement_available": True},
    "RISK_FAILURE": {"consequence": "critical"},
    "CUSTOMER_REQUIREMENTS": {"customer_needs_unknown": True},
    "PROJECT_DELIVERY": {"deliverable_scope_defined": True, "solution_known": True},
    "UNCERTAIN_PRODUCT": {"solution_known": False, "uncertainty": "high"},
    "STRATEGY": {"strategic_question": True},
    "STRATEGY_EXECUTION": {"strategy_needs_alignment": True},
    "ACCOUNTABILITY": {"decision_rights_unclear": True},
    "CHANGE_ADOPTION": {"change_adoption_required": True},
    "SYSTEM_COMPLEXITY": {"system_coupling": "high", "feedback_loops_suspected": True},
    "RELIABILITY_DIGITAL_OPS": {"live_service": True, "incidents_recurring": True},
    "LEARNING": {"lessons_to_capture": True},
}


def _plan(**fields):
    return compile_method_plan(ObjectiveRequest(objective=fields.pop("objective", "Improve the outcome"), **fields))


def _mission(plan, project_id="proj-method"):
    return compile_method_mission(plan, registry=REGISTRY, project_id=project_id)


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

SPEC_METHODS = [
    "Eisenhower Matrix", "Impact-Effort Matrix", "RICE Scoring", "Weighted Shortest Job First", "MoSCoW",
    "Weighted Scoring", "Cost of Delay", "Pareto Analysis", "Decision Matrix", "Weighted Decision Matrix",
    "Multi-Criteria Decision Analysis", "Analytic Hierarchy Process", "Cost-Benefit Analysis", "Decision Tree",
    "Expected Value Analysis", "Sensitivity Analysis", "Scenario Analysis", "DMAIC", "PDCA / PDSA",
    "A3 Problem Solving", "8D Problem Solving", "Kaizen", "Model for Improvement", "5 Whys", "Fishbone Diagram",
    "Fault Tree Analysis", "Kepner-Tregoe Problem Analysis", "Change Analysis", "Barrier Analysis", "Lean",
    "Value Stream Mapping", "Process Mapping", "SIPOC", "Spaghetti Diagram", "5S", "Standard Work", "Gemba Walk",
    "Kanban", "Theory of Constraints", "Drum-Buffer-Rope", "Bottleneck Analysis", "Capacity Analysis",
    "Queueing Analysis", "Little's Law", "Takt Time", "Cycle Time Analysis", "WIP Limits",
    "Statistical Process Control", "Control Chart", "Run Chart", "Process Capability (Cp/Cpk)", "Histogram",
    "Scatter Plot", "Check Sheet", "Design of Experiments", "Failure Modes and Effects Analysis", "Bow-Tie Analysis",
    "HAZOP", "Risk Matrix", "Risk Register", "Poka-Yoke", "Monte Carlo Simulation", "Voice of the Customer",
    "Quality Function Deployment", "Jobs To Be Done", "Kano Model", "Customer Journey Mapping",
    "Service Blueprinting", "Work Breakdown Structure", "Gantt Chart", "Critical Path Method", "PERT",
    "Critical Chain Project Management", "Stage-Gate", "Earned Value Management", "RACI", "Scrum", "Lean Startup",
    "Build-Measure-Learn", "Design Thinking", "Double Diamond", "Discovery/Delivery Dual Track",
    "Hypothesis-Driven Development", "SWOT / TOWS", "PESTLE", "Porter's Five Forces", "Value Chain Analysis",
    "VRIO", "Ansoff Matrix", "BCG Matrix", "Blue Ocean Strategy", "Scenario Planning", "Hoshin Kanri", "X-Matrix",
    "OKRs", "Balanced Scorecard", "Strategy Map", "OGSM", "SMART Goals", "RAPID", "DACI", "Governance Model",
    "ADKAR", "Kotter's 8-Step Model", "Lewin's Change Model", "McKinsey 7S", "Bridges Transition Model",
    "Force-Field Analysis", "Stakeholder Analysis", "Systems Thinking", "Causal Loop Diagram", "Stock-and-Flow Model",
    "System Dynamics Simulation", "Cynefin", "Soft Systems Methodology", "Site Reliability Engineering",
    "SLI/SLO/Error Budget", "Incident Management", "Blameless Postmortem", "ITIL Service Management", "COBIT",
    "NIST Risk Management Framework", "Observability", "After Action Review", "Retrospective", "Lessons Learned",
    "Knowledge Management",
]


def test_catalog_covers_every_family_and_named_method_with_honest_provenance():
    assert set(CATALOG.families) == set(FAMILY_TRIGGERS)
    names = {m.name for m in CATALOG.methods.values()}
    assert not set(SPEC_METHODS) - names
    aliases = {a for m in CATALOG.methods.values() for a in m.aliases}
    assert {"Responsibility Assignment Matrix".lower(), "House of Quality".lower(), "Cp/Cpk".lower()} <= {a.lower() for a in aliases}
    assert all(m.provenance_status == "DESCRIPTION_UNVERIFIED" and not m.source_refs for m in CATALOG.methods.values())


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda raw: raw["methods"].append(copy.deepcopy(raw["methods"][0])), "duplicate method"),
        (lambda raw: raw["methods"][0].update(applicability_predicates=["vibes are good"]), "unparseable predicate"),
        (lambda raw: raw["methods"][0].update(provenance_status="SOURCE_CITED"), "SOURCE_CITED requires source_refs"),
        (lambda raw: next(m for m in raw["methods"] if m["method_id"] == "scrum")["conflicts_with"].remove("stage_gate"), "not symmetric"),
        (lambda raw: raw["families"][0]["needs"].update({"output:unservable": "DIAGNOSE"}), "no covering method"),
    ],
)
def test_catalog_validation_rejects_bad_entries(mutate, message):
    raw = json.loads(CATALOG_PATH.read_text())
    mutate(raw)
    with pytest.raises((CatalogError, ValueError), match=message):
        parse_catalog(raw)


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("family", sorted(FAMILY_TRIGGERS))
def test_every_family_routes_compiles_and_resolves_specialists(family):
    plan = _plan(**FAMILY_TRIGGERS[family])
    assert family in plan.problem_signature.problem_families
    assert plan.method_stack.selected()
    assert not [u for u in plan.unresolved if u.startswith("NO_APPLICABLE_METHOD")]
    compiled = _mission(plan)
    assert len(compiled.work_orders) == len(plan.delegation_envelopes)
    assert all(wo["accountable_role_id"] in REGISTRY.roles for wo in compiled.work_orders)
    assert compiled.executor_status == EXECUTOR_GAP


def test_simple_request_short_circuits_to_one_prioritization_method():
    plan = _plan(objective="prioritize tasks", items_to_rank=("write report", "fix login bug", "plan offsite"))
    assert plan.problem_signature.problem_families == ("PRIORITIZATION",)
    assert plan.method_stack.selected() == ("impact_effort_matrix",)
    assert len(plan.delegation_envelopes) == 1 and not plan.method_stack.macro_methodologies
    assert not plan.human_gates


def test_recurring_defect_compiles_the_full_lifecycle_chain():
    plan = compile_method_plan(RECURRING_DEFECT)
    stack = plan.method_stack
    assert stack.macro_methodologies == ("dmaic",)
    assert stack.diagnostic_methods == ("five_whys",)
    assert stack.decision_methods == ("decision_matrix",)
    assert stack.execution_methods == ("standard_work",)
    assert stack.control_methods == ("run_chart",)
    assert stack.learning_methods == ("after_action_review",)


def test_keywords_alone_never_route_and_clarifications_are_bounded():
    plan = _plan(objective="We must prioritize, decide on a strategy, fix the bottleneck and reduce risk and waste")
    assert plan.problem_signature.problem_families == ()
    assert "NO_STRUCTURAL_EVIDENCE" in plan.unresolved
    clarifications = [g for g in plan.human_gates if g.kind == "CLARIFICATION"]
    assert 1 <= len(clarifications) <= 3
    assert not plan.delegation_envelopes
    with pytest.raises(MethodCompileError, match="PLAN_EMPTY"):
        _mission(plan)


def test_multi_label_routing_deduplicates_shared_work():
    plan = _plan(problem_recurs=True, options=("vendor a", "vendor b"))
    assert set(plan.problem_signature.problem_families) >= {"ROOT_CAUSE", "DECISION"}
    covering = [e for e in plan.delegation_envelopes if "decision:option_selected" in e.expected_outputs]
    assert len(covering) == 1


def test_equivalent_inputs_hash_identically_and_plans_are_reproducible():
    a = ObjectiveRequest(objective="Prioritize   the backlog", items_to_rank=("b", "a", "c"), domains=("Digital", "web"))
    b = ObjectiveRequest(objective="Prioritize the backlog ", items_to_rank=("c", "a", "b", "a"), domains=("web", "digital"))
    assert request_hash(a) == request_hash(b)
    assert compile_method_plan(a).plan_hash == compile_method_plan(b).plan_hash
    assert compile_method_plan(RECURRING_DEFECT) == compile_method_plan(RECURRING_DEFECT)
    assert _mission(compile_method_plan(a)).task_to_work_order == _mission(compile_method_plan(b)).task_to_work_order


def test_shadow_duel_is_deterministic_and_bounded():
    request = ObjectiveRequest(objective="Pick a CRM vendor", options=("A", "B", "C"), consequence="high", uncertainty="high")
    first, second = compile_method_plan(request), compile_method_plan(request)
    assert first.shadow_duels and first.shadow_duels == second.shadow_duels
    duel = first.shadow_duels[0]
    assert len(duel.candidates) == 2 and duel.winner in duel.candidates


def test_every_selected_method_is_counterfactually_necessary():
    for request in (RECURRING_DEFECT, ObjectiveRequest(objective="x", **FAMILY_TRIGGERS["RELIABILITY_DIGITAL_OPS"], change_adoption_required=True)):
        plan = compile_method_plan(request)
        needs = {n for e in plan.delegation_envelopes for n in e.expected_outputs}
        selected = list(plan.method_stack.selected())
        for cert in plan.minimality_certificates:
            assert cert.necessary_for and cert.redundant is False
            rest = {o for m in selected if m != cert.method_id for o in CATALOG.methods[m].expected_outputs}
            assert set(cert.necessary_for) - rest, cert.method_id
        assert {c.method_id for c in plan.minimality_certificates} == set(selected)
        assert needs  # non-empty plan


def test_unservable_need_is_reported_not_papered_over():
    plan = _plan(problem_recurs=True, root_cause_known=False)  # no known process to standardise
    assert "NO_APPLICABLE_METHOD:execute:corrective_action_implemented" in plan.unresolved


def test_redundant_method_is_pruned():
    needs = {"output:root_cause_identified"}
    assert _prune(["fishbone_diagram", "five_whys"], CATALOG, needs) == ["fishbone_diagram"]


def test_macro_slot_only_when_work_spans_three_slots():
    assert MACRO_NEED not in {n for e in _plan(items_to_rank=("a", "b")).delegation_envelopes for n in e.expected_outputs}
    plan = compile_method_plan(RECURRING_DEFECT)
    assert plan.method_stack.macro_methodologies


def test_uncertainty_first_measurement_plan_precedes_measuring_methods():
    plan = compile_method_plan(RECURRING_DEFECT)
    order = [e.node_id for e in plan.delegation_envelopes]
    assert PREREQ_NODE in order
    slot_of = {e.node_id: e.slot for e in plan.delegation_envelopes}
    first_measure = min(i for i, n in enumerate(order) if slot_of[n] in {Slot.CONTROL, Slot.DIAGNOSE} and n != PREREQ_NODE)
    assert order.index(PREREQ_NODE) < first_measure
    assert order.index("m:five_whys") < order.index("m:decision_matrix") < order.index("m:standard_work")
    assert "ASSUMPTION:measurement_plan_precedes_measurement_methods" in plan.unresolved


# ---------------------------------------------------------------------------
# Delegation, authority, invalidation
# ---------------------------------------------------------------------------

def test_mission_uses_canonical_adapter_with_explicit_phases_and_provenance():
    plan = compile_method_plan(RECURRING_DEFECT)
    compiled = _mission(plan)
    assert set(compiled.phase_map) == {e.node_id for e in plan.delegation_envelopes}
    for wo in compiled.work_orders:
        assert wo["phase_id"] == compiled.phase_map[wo["_runtime"]["mission_task_id"]]
        assert wo["context_capsule_hash"] == plan.plan_hash
        assert wo["work_order_id"].startswith("wo-")
    # E4: outputs are planning refs, never silently new N1 artifact types.
    produced = {ref for wo in compiled.work_orders for ref in wo["required_artifact_refs"]}
    assert not produced & {a.value for a in ArtifactType}


def test_consequential_work_compiles_but_is_never_execution_ready():
    compiled = _mission(compile_method_plan(RECURRING_DEFECT))
    standard_work = next(wo for wo in compiled.work_orders if wo["_runtime"]["mission_task_id"] == "m:standard_work")
    assert standard_work["_runtime"]["execution_ready"] is False
    gate = next(g for g in compiled.eligibility if g.node_id == "m:standard_work")
    assert not gate.eligible_to_execute and "MISSING_AUTHORITY_REF" in gate.blockers
    assert "cell:standard_work" in compiled.blocked_nodes
    assert {"cell:run_chart", "cell:after_action_review"} <= set(compiled.blocked_nodes)
    assert all(p.authority_delta == 0 and p.authority_after == () for p in compiled.non_authority_proofs)


def test_maximal_routing_score_cannot_buy_authority(monkeypatch):
    from services.langgraph.agency.role_os import resolver as resolver_module

    original = resolver_module.RoleResolver.resolve

    def inflated(self, *args, **kwargs):
        return [m.__class__(**{**m.__dict__, "score": 10**9, "coverage": 1.0}) for m in original(self, *args, **kwargs)]

    monkeypatch.setattr(resolver_module.RoleResolver, "resolve", inflated)
    compiled = _mission(compile_method_plan(RECURRING_DEFECT))
    proof = next(p for p in compiled.non_authority_proofs if p.node_id == "m:standard_work")
    assert proof.routing_score_used == 10**9 and proof.authority_delta == 0
    gate = next(g for g in compiled.eligibility if g.node_id == "m:standard_work")
    assert not gate.eligible_to_execute


def test_authority_escalation_by_the_compiler_is_detected(monkeypatch):
    from services.langgraph.agency.role_os import work_order as work_order_module

    original = work_order_module.WorkOrderCompiler.compile

    def escalating(self, **kwargs):
        wo = original(self, **kwargs)
        wo["authority_refs"] = ["self-granted"]
        return wo

    monkeypatch.setattr(work_order_module.WorkOrderCompiler, "compile", escalating)
    with pytest.raises(MethodCompileError, match="ROUTER_AUTHORITY_ESCALATION"):
        _mission(compile_method_plan(RECURRING_DEFECT))


def test_irreversible_external_work_fails_closed():
    plan = compile_method_plan(RECURRING_DEFECT.model_copy(update={"reversibility": "irreversible", "externality": "external"}))
    env = next(e for e in plan.delegation_envelopes if e.slot is Slot.EXECUTE)
    assert env.side_effect_class == "IRREVERSIBLE_WRITE" and env.retry_limit == 0
    gate = next(g for g in plan.human_gates if g.node_id == env.node_id)
    assert "exact_approval_ref" in gate.requires and gate.separation_of_duties
    eligibility = next(g for g in _mission(plan).eligibility if g.node_id == env.node_id)
    assert not eligibility.policy_pass and "MISSING_EXACT_APPROVAL_REF" in eligibility.blockers
    assert next_step(env, [Attempt(failure_class="TRANSIENT", failure_fingerprint="t1")]).action == "ESCALATE_HUMAN"


def test_missing_tool_blocks_execution():
    plan = _plan(items_to_rank=("a", "b"))
    env = plan.delegation_envelopes[0].model_copy(update={"tool_plan": ("web.search",)})
    tampered = plan.model_copy(update={"delegation_envelopes": (env,)})
    gate = _mission(tampered).eligibility[0]
    assert not gate.tool_available and "TOOL_UNAVAILABLE" in gate.blockers


def test_stale_upstream_context_invalidates_only_the_causal_closure():
    plan = compile_method_plan(RECURRING_DEFECT)
    envs = list(plan.delegation_envelopes)
    idx = next(i for i, e in enumerate(envs) if e.node_id == "m:decision_matrix")
    envs[idx] = envs[idx].model_copy(update={"inputs": (*envs[idx].inputs, "late-breaking constraint")})
    changed = plan.model_copy(update={"delegation_envelopes": tuple(envs)})
    stale = verify_context_chain(changed)
    assert stale[0] == "m:decision_matrix"
    closure = causal_closure(changed, ["m:decision_matrix"])
    assert closure == ("m:decision_matrix", "m:standard_work", "m:run_chart", "m:after_action_review")
    assert "m:five_whys" not in stale
    gates = {g.node_id: g for g in _mission(changed).eligibility}
    assert "DEPENDENCY_OR_CONTEXT_STALE" in gates["m:decision_matrix"].blockers
    assert gates["m:five_whys"].dependencies_current


def test_cyclic_delegation_graph_is_rejected():
    plan = compile_method_plan(RECURRING_DEFECT)
    envs = list(plan.delegation_envelopes)
    envs[0] = envs[0].model_copy(update={"dependencies": (envs[-1].node_id,)})
    with pytest.raises(BackchainCycleError):
        _mission(plan.model_copy(update={"delegation_envelopes": tuple(envs)}))


def test_colliding_mutations_are_serialized():
    plan = _plan(**FAMILY_TRIGGERS["CHANGE_ADOPTION"], **FAMILY_TRIGGERS["SYSTEM_COMPLEXITY"], **FAMILY_TRIGGERS["WORKFLOW_WASTE"])
    diag = [e for e in plan.delegation_envelopes if e.slot is Slot.DIAGNOSE]
    assert len(diag) >= 2
    locked = {e.node_id: e.model_copy(update={"mutation_targets": ("doc:shared",)}) for e in diag[:2]}
    envs = tuple(locked.get(e.node_id, e) for e in plan.delegation_envelopes)
    compiled = _mission(plan.model_copy(update={"delegation_envelopes": envs}))
    waves_with = [w for w in compiled.wave_plan.waves if {f"cell:{n.split(':', 1)[1]}" for n in locked} & set(w.cells)]
    assert len(waves_with) == 2
    assert any(w.serialized_reason == "RESOURCE_OR_MUTATION_COLLISION" for w in waves_with)


def test_wave_specialist_cap():
    plan = WavePlan(waves=(Wave(index=0, cells=tuple(f"cell:{i:02d}" for i in range(11))),), held={}, wave_hash="x")
    capped = _cap_waves(plan)
    assert [len(w.cells) for w in capped.waves] == [MAX_SPECIALISTS_PER_WAVE, 3]
    assert capped.waves[1].serialized_reason == "MAX_SPECIALISTS_PER_WAVE"


def test_capability_gap_is_reported_not_invented():
    raw = json.loads(CATALOG_PATH.read_text())
    for family in raw["families"]:
        if family["family_id"] == "PRIORITIZATION":
            family["capability_terms"] = ["zzqx"]
    gap_catalog = parse_catalog(raw)
    plan = compile_method_plan(ObjectiveRequest(objective="rank", items_to_rank=("a", "b")), gap_catalog)
    with pytest.raises(MethodCompileError, match="CAPABILITY_GAP"):
        compile_method_mission(plan, registry=REGISTRY, project_id="p", catalog=gap_catalog)


# ---------------------------------------------------------------------------
# Idempotency and bounded control
# ---------------------------------------------------------------------------

def test_mutation_identity_is_semantic_and_duplicates_conflict():
    args = dict(tenant_id="t", project_id="p", mission_id="m", node_id="n", operation="apply", input_hash="h")
    assert mutation_key(**args) == mutation_key(**args)
    assert mutation_key(**args) != mutation_key(**{**args, "input_hash": "h2"})
    assert "time" not in inspect.signature(mutation_key).parameters
    first = _mission(compile_method_plan(RECURRING_DEFECT))
    second = _mission(compile_method_plan(RECURRING_DEFECT))
    assert [wo["idempotency"] for wo in first.work_orders] == [wo["idempotency"] for wo in second.work_orders]
    scope, key = "scope-method-router", mutation_key(**args)
    assert reserve_idempotency(scope, key, "payload-a", 60)["state"] in {"new", "replay", "in_progress"}
    assert reserve_idempotency(scope, key, "payload-b", 60)["state"] == "conflict"


@pytest.fixture
def draft_env():
    return compile_method_plan(RECURRING_DEFECT).delegation_envelopes[0]


def test_failure_control_is_bounded(draft_env):
    assert next_step(draft_env, [Attempt(succeeded=True)]).action == "DONE"
    assert next_step(draft_env, [Attempt(failure_class="TRANSIENT", failure_fingerprint="a")]).action == "RETRY"
    twice = [Attempt(failure_class="TRANSIENT", failure_fingerprint="a")] * 2
    assert next_step(draft_env, twice).reason.startswith("CIRCUIT_BREAKER")
    many = [Attempt(failure_class="TRANSIENT", failure_fingerprint=f"f{i}") for i in range(4)]
    assert next_step(draft_env, many).reason == "RETRY_BUDGET_EXHAUSTED"
    assert next_step(draft_env, [Attempt(failure_class="ACCEPTANCE", failure_fingerprint="x")]).action == "REPAIR"
    repairs = [Attempt(failure_class="ACCEPTANCE", failure_fingerprint=f"r{i}") for i in range(4)]
    assert next_step(draft_env, repairs).reason == "REPAIR_BUDGET_EXHAUSTED"
    drift = [Attempt(failure_class="ACCEPTANCE", failure_fingerprint=f"d{i}", progress=0.4) for i in range(3)]
    assert next_step(draft_env, drift).action == "RECLASSIFY_PROBLEM"
    no_evidence = [Attempt(failure_class="TRANSIENT", failure_fingerprint=f"e{i}", retrieval_new_evidence=False) for i in range(2)]
    assert next_step(draft_env, no_evidence).reason == "NO_NEW_EVIDENCE_TWICE"
    assert next_step(draft_env, [Attempt(failure_class="DEPENDENCY_STALE")]).action == "INVALIDATE_AND_RECOMPILE"
    assert next_step(draft_env, [Attempt(failure_class="AUTHORITY")]).action == "ESCALATE_HUMAN"


# ---------------------------------------------------------------------------
# Governance boundaries
# ---------------------------------------------------------------------------

def test_material_decisions_and_authority_gates_require_separated_human_review():
    plan = _plan(options=("a", "b"), consequence="high")
    decision_gates = [g for g in plan.human_gates if g.kind == "MATERIAL_DECISION"]
    assert decision_gates and all(g.separation_of_duties for g in decision_gates)
    assert all("assert_may_decide" in g.enforced_by for g in decision_gates)
    assert any(u.startswith("DECISION_PENDING:") for u in plan.unresolved)
    creator = Principal(user_id="creator", tenant_id="t", role="admin", allowed_project_ids=frozenset({"*"}))
    import os
    old = os.environ.pop("AMC_ALLOW_SELF_APPROVAL", None)
    try:
        with pytest.raises(HTTPException):
            assert_may_decide(creator, "creator", "approve", subject="method plan")
    finally:
        if old is not None:
            os.environ["AMC_ALLOW_SELF_APPROVAL"] = old


@pytest.mark.parametrize("module", [models_module, catalog_module, router_module, mission_module])
def test_method_layer_reuses_canonical_owners_and_writes_nothing(module):
    tree = ast.parse(Path(inspect.getsourcefile(module)).read_text())
    defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    assert not defined & {
        "WorkOrderCompiler", "MissionWorkOrderAdapter", "RoleResolver", "RoleOSRegistry",
        "ApprovalRecord", "ArtifactRegistry", "TransitionContext", "Principal", "OutboxDispatcher",
    }
    imported = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not any("persistence" in m or "api." in m for m in imported), imported
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not names & {"transaction", "record_event", "enqueue_outbox"}


def test_authority_gate_states_everything_the_work_order_blocks_on():
    plan = compile_method_plan(RECURRING_DEFECT)
    gate = next(g for g in plan.human_gates if g.node_id == "m:standard_work")
    assert set(gate.requires) == {"authority_ref", "permission_ref", "approval_ref"}
    blockers = next(g for g in _mission(plan).eligibility if g.node_id == "m:standard_work").blockers
    assert set(blockers) == {"MISSING_AUTHORITY_REF", "MISSING_HIGH_RISK_APPROVAL_REF", "MISSING_PERMISSION_REF"}


def test_method_plan_cli(capsys):
    from services.langgraph.agency.cli import main

    code = main(["method-plan", "--input", str(ROOT / "sample_method_request.json")])
    out = capsys.readouterr().out
    assert code == 1  # the consequential node is blocked, by design
    assert "macro: dmaic" in out and "executor: EXECUTOR_GAP" in out
    assert main(["method-plan", "--input", str(ROOT / "sample_method_request.json"), "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["mission"]["executor_status"] == "EXECUTOR_GAP"
