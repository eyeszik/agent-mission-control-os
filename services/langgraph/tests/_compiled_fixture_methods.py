"""Builders for compiled-methods.json: the method catalog, router, missions and next-step logic."""
from __future__ import annotations

import copy
import json
import random
from typing import Any

from services.langgraph.agency.compiled import hashing, method_catalog, method_mission, method_models, method_router
from services.langgraph.tests._compiled_fixture_support import CATALOG_PATH, case, registry, variant_registries

TRI = [
    "current_state_known", "target_state_known", "process_exists", "root_cause_known", "solution_known", "measurement_available",
    "problem_recurs", "variation_observed", "waste_observed", "throughput_constrained", "customer_needs_unknown",
    "deliverable_scope_defined", "strategic_question", "strategy_needs_alignment", "decision_rights_unclear",
    "change_adoption_required", "feedback_loops_suspected", "live_service", "incidents_recurring", "lessons_to_capture",
]


def raw_catalog() -> dict[str, Any]:
    return json.loads(CATALOG_PATH.read_text())


def _catalog() -> method_catalog.MethodCatalog:
    return method_catalog.parse_catalog(raw_catalog())


def _request(**kw: Any) -> dict[str, Any]:
    return {"objective": "Improve the process", **kw}


def handwritten_requests() -> list[dict[str, Any]]:
    return [
        _request(), _request(objective="  Rank   these\titems  "), _request(items_to_rank=["a", "b", "c"]),
        _request(options=["x", "y"], consequence="high"), _request(options=["x", "y"], consequence="critical", uncertainty="high"),
        _request(process_exists=True, current_state_known=True, target_state_known=True),
        _request(problem_recurs=True, root_cause_known=False), _request(problem_recurs=True, root_cause_known=True, lessons_to_capture=True),
        _request(waste_observed=True, variation_observed=True, throughput_constrained=True),
        _request(deliverable_scope_defined=True, solution_known=True),
        _request(solution_known=False, uncertainty="high", strategic_question=True, strategy_needs_alignment=True),
        _request(customer_needs_unknown=True, decision_rights_unclear=True, change_adoption_required=True),
        _request(system_coupling="high", feedback_loops_suspected=True, live_service=True, incidents_recurring=True),
        _request(consequence="high", reversibility="irreversible", externality="external", options=["a", "b"]),
        _request(objective="Prioritize the backlog and decide between vendors with root cause analysis of variation"),
        _request(objective="CAFÉ strategy İstanbul 😀 decision"), _request(domains=["Web", " web ", "WEB", "Brand"]),
        _request(constraints=["b", "a", "a"], non_goals=["z"], desired_outcome="Outcome  text"),
        _request(measurement_available=True, waste_observed=True), _request(measurement_available=False, waste_observed=True),
        _request(items_to_rank=["a", "a"], options=["a", "a"]), _request(strategic_question=True, uncertainty="high", target_state_known=False),
        _request(options=["a", "b"], consequence="high", evidence_status="verified", data_sensitivity="regulated", time_pressure="high"),
    ]


def random_request(r: random.Random, cues: list[str]) -> dict[str, Any]:
    req: dict[str, Any] = {"objective": " ".join(r.sample(cues, r.randint(0, 3)) + ["goal"])}
    for key in r.sample(TRI, r.randint(0, 9)):
        req[key] = r.choice([True, False])
    if r.random() < 0.4:
        req["items_to_rank"] = [f"i{i}" for i in range(r.randint(0, 4))]
    if r.random() < 0.4:
        req["options"] = [f"o{i}" for i in range(r.randint(0, 4))]
    for key, values in {"uncertainty": ["low", "medium", "high"], "reversibility": ["reversible", "partially_reversible", "irreversible"],
                        "consequence": ["low", "medium", "high", "critical"], "externality": ["internal", "external"],
                        "system_coupling": ["low", "high"], "time_pressure": ["low", "high"]}.items():
        if r.random() < 0.4:
            req[key] = r.choice(values)
    return req


def _digest(plan: Any) -> dict[str, Any]:
    return {
        "plan_hash": plan.plan_hash, "stack_hash": plan.method_stack.stack_hash, "selected": list(plan.method_stack.selected()),
        "families": list(plan.problem_signature.problem_families), "unresolved": list(plan.unresolved),
        "confidence": plan.method_stack.selection_confidence,
        "envelopes": [[e.node_id, e.context_hash, e.side_effect_class, e.slot.value] for e in plan.delegation_envelopes],
        "gates": [g.gate_id for g in plan.human_gates], "duels": len(plan.shadow_duels),
        "certs": [[c.method_id, list(c.necessary_for)] for c in plan.minimality_certificates],
        "excluded": hashing.semantic_hash([e.model_dump(mode="json") for e in plan.method_stack.excluded_methods]),
        "classification": hashing.semantic_hash([e.model_dump(mode="json") for e in plan.classification]),
    }


def _plan(req: Any) -> method_models.MethodPlan:
    return method_router.compile_method_plan(method_models.ObjectiveRequest.model_validate(req), _catalog())


def _mission_digest(plan_dump: Any, registry_name: str) -> dict[str, Any]:
    plan = method_models.MethodPlan.model_validate(plan_dump)
    m = method_mission.compile_method_mission(plan, registry=variant_registries()[registry_name], project_id="proj", catalog=_catalog())
    return {
        "mission": m.mission, "phase_map": m.phase_map, "task_to_work_order": m.task_to_work_order,
        "work_orders": hashing.semantic_hash(m.work_orders), "eligibility": [e.__dict__ for e in m.eligibility],
        "proofs": [p.model_dump(mode="json") for p in m.non_authority_proofs], "graph_hash": m.graph.graph_hash,
        "graph_nodes": {k: [n.semantic_hash, n.status.value] for k, n in m.graph.nodes.items()}, "roots": m.graph.roots,
        "cells": {k: [c.cell_hash, c.status.value] for k, c in m.cells.items()},
        "waves": [[w.index, w.cells, w.serialized_reason] for w in m.wave_plan.waves], "held": m.wave_plan.held,
        "wave_hash": m.wave_plan.wave_hash, "executor": [m.executor_status, m.executor_reason],
    }


def apply_patch(raw: dict[str, Any], ops: list[list[Any]]) -> dict[str, Any]:
    """The tiny patch language both languages apply: set, append_copy, remove_method, strip_macro, clear."""
    c = copy.deepcopy(raw)
    for op in ops:
        if op[0] == "set":
            target: Any = c
            for key in op[1][:-1]:
                target = target[key]
            target[op[1][-1]] = op[2]
        elif op[0] == "append_copy":
            src: Any = c
            for key in op[2]:
                src = src[key]
            dst: Any = c
            for key in op[1]:
                dst = dst[key]
            dst.append(copy.deepcopy(src))
        elif op[0] == "remove_method":
            c["methods"] = [m for m in c["methods"] if m["method_id"] != op[1]]
        elif op[0] == "strip_macro":
            for m in c["methods"]:
                if m["slot"] == "MACRO":
                    m["expected_outputs"] = [o for o in m["expected_outputs"] if o != "macro:structured_cycle"]
        else:
            c["families"], c["methods"] = [], []
    return c


def catalog_cases() -> list[dict[str, Any]]:
    raw = raw_catalog()
    out = [case("parseCatalog", [[]], lambda ops: _catalog_summary(method_catalog.parse_catalog(apply_patch(raw, ops))))]
    first = raw["methods"][0]["method_id"]
    second = raw["methods"][1]["method_id"]
    patches: list[list[list[Any]]] = [
        [["set", ["schema_version"], "x"]], [["append_copy", ["methods"], ["methods", 0]]], [["append_copy", ["families"], ["families", 0]]],
        [["set", ["methods", 0, "family"], "NOPE"]], [["set", ["methods", 0, "applicability_predicates"], ["bad predicate"]]],
        [["set", ["methods", 0, "conflicts_with"], [second]]], [["set", ["methods", 0, "composable_with"], ["nope"]]],
        [["set", ["methods", 0, "provenance_status"], "SOURCE_CITED"], ["set", ["methods", 0, "source_refs"], []]],
        [["set", ["methods", 0, "effort"], 9]], [["set", ["methods", 0, "surprise"], 1]],
        [["set", ["methods", 0, "expected_outputs"], []]], [["set", ["methods", 0, "slot"], "NOPE"]],
        [["set", ["families", 0, "capability_terms"], []]], [["set", ["families", 0, "needs", "orphan:need"], "DECIDE"]],
        [["set", ["methods", 0, "contraindications"], ["family:X\n"]]], [["remove_method", first]], [["clear"]], [["strip_macro"]],
    ]
    return out + [case("parseCatalog", [ops], lambda o: _catalog_summary(method_catalog.parse_catalog(apply_patch(raw, o)))) for ops in patches]


def _catalog_summary(c: method_catalog.MethodCatalog) -> dict[str, Any]:
    return {"hash": c.catalog_hash, "families": sorted(c.families), "methods": sorted(c.methods)}


def predicate_cases() -> list[dict[str, Any]]:
    preds = ["process_exists==true", "process_exists==false", "process_exists!=true", "uncertainty==high", "uncertainty!=high",
             "consequence in high|critical", "process_exists in true|false", "reversibility==irreversible", "observed:waste_observed",
             "not_observed:waste_observed", "family:PROCESS_VARIATION", "domain:web", "nonexistent==1", "x in a|b", "garbage!", "",
             "consequence in", "a==b==c", "measurement_available==true", "objective==Improve", "constraints==x"]
    out = []
    for req in [_request(), _request(process_exists=True, waste_observed=True, consequence="high", domains=["web"]),
                _request(process_exists=False, measurement_available=True, uncertainty="high")]:
        for pred in preds:
            out.append(case("evaluatePredicate", [pred, req, ["PROCESS_VARIATION"]], lambda p, rq, fam: method_catalog.evaluate_predicate(
                p, method_router.build_signature(method_router.normalize_request(method_models.ObjectiveRequest.model_validate(rq)), tuple(fam)))))
    return out


def validation_cases() -> list[dict[str, Any]]:
    bad = [{}, {"objective": ""}, {"objective": "x" * 2001}, {"objective": "x", "surprise": 1}, {"objective": "x", "uncertainty": "huge"},
           {"objective": "x", "options": ["a"] * 51}, {"objective": "x", "items_to_rank": ["a"] * 501}, {"objective": 5},
           {"objective": "x", "live_service": "yes"}, {"objective": "x", "live_service": 1}, {"objective": "x", "domains": "web"},
           {"objective": "😀" * 2000}, {"objective": "😀" * 2001}, {"objective": "x", "desired_outcome": "y" * 2001}, []]
    return [case("validateObjectiveRequest", [b], lambda x: method_models.ObjectiveRequest.model_validate(x)) for b in bad]


def request_cases() -> list[dict[str, Any]]:
    out = []
    for req in handwritten_requests():
        out.append(case("normalizeRequest", [req], lambda x: method_router.normalize_request(method_models.ObjectiveRequest.model_validate(x))))
        out.append(case("requestHash", [req], lambda x: method_router.request_hash(method_models.ObjectiveRequest.model_validate(x))))
    return out


def plan_and_mission_cases() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    cat = raw_catalog()
    cues = sorted({c for f in cat["families"] for c in f.get("lexical_cues", [])})
    r = random.Random(41)
    requests = handwritten_requests() + [random_request(r, cues) for _ in range(70)]
    plans, missions, chains = [], [], []
    for i, req in enumerate(requests):
        call = "compileMethodPlan" if i < 6 else "compileMethodPlanDigest"
        plans.append(case(call, [req], (lambda x: _plan(x)) if call == "compileMethodPlan" else (lambda x: _digest(_plan(x)))))
    for i, req in enumerate(requests):
        try:
            dump = _plan(req).model_dump(mode="json")
        except Exception:  # noqa: BLE001 - failing plans are already recorded above
            continue
        if i % 2 == 0 and len(missions) < 30:
            name = "sealed" if i % 4 else "elevated"
            missions.append({**case("compileMethodMission", [dump, name], _mission_digest), "request": req})
        if len(chains) < 12 and len(dump["delegation_envelopes"]) >= 2:
            chains.extend(_chain_cases(dump))
    return plans, missions, chains


def _chain_cases(dump: dict[str, Any]) -> list[dict[str, Any]]:
    out = [case("verifyContextChain", [dump], lambda p: method_mission.verify_context_chain(method_models.MethodPlan.model_validate(p)))]
    envs = dump["delegation_envelopes"]
    for idx in (0, len(envs) - 1):
        tampered = copy.deepcopy(dump)
        tampered["delegation_envelopes"][idx]["objective"] += " (changed)"
        out.append(case("verifyContextChain", [tampered], lambda p: method_mission.verify_context_chain(method_models.MethodPlan.model_validate(p))))
        out.append(case("causalClosure", [dump, [envs[idx]["node_id"]]], lambda p, c: method_mission.causal_closure(method_models.MethodPlan.model_validate(p), c)))
    return out


def next_step_cases() -> list[dict[str, Any]]:
    r = random.Random(42)
    out = []
    for _ in range(300):
        history = []
        for _ in range(r.randint(0, 7)):
            a: dict[str, Any] = {"succeeded": r.random() < 0.1}
            if r.random() < 0.8:
                a["failure_class"] = r.choice(["TRANSIENT", "ACCEPTANCE", "AUTHORITY", "DEPENDENCY_STALE", "TOOL_UNAVAILABLE"])
            if r.random() < 0.5:
                a["failure_fingerprint"] = r.choice(["f1", "f1", "f2", ""])
            if r.random() < 0.5:
                a["progress"] = r.choice([0.1, 0.2, 0.2, 0.5, 1])
            if r.random() < 0.4:
                a["retrieval_new_evidence"] = r.choice([True, False])
            history.append(a)
        out.append(case("nextStep", [r.choice([0, 1, 3]), history], lambda lim, h: method_mission.next_step(
            _Env(lim), [method_mission.Attempt.model_validate(x) for x in h])))
    out.append(case("mutationKey", [{"tenant_id": "t", "project_id": "p", "mission_id": "m", "node_id": "n", "operation": "o", "input_hash": "h"}],
                    lambda kw: method_mission.mutation_key(**kw)))
    return out


class _Env:
    def __init__(self, retry_limit: int):
        self.retry_limit = retry_limit


def build_methods() -> dict[str, Any]:
    plans, missions, chains = plan_and_mission_cases()
    return {
        "catalog": [raw_catalog()], "parse": catalog_cases(), "predicates": predicate_cases(), "validation": validation_cases(),
        "requests": request_cases(), "plans": plans, "missions": missions, "chains": chains, "next_steps": next_step_cases(),
        "registry_note": [registry().registry_hash],
    }
