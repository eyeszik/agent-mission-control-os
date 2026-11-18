"""Builders for compiled-plans.json: RoleOS resolution, authority bindings, work orders and compiled plans."""
from __future__ import annotations

import itertools
import random
from typing import Any

from services.langgraph.agency.compiled import authority, backchain, change_control, decisions, hashing, planner
from services.langgraph.agency.role_os import RoleResolver, WorkOrderCompiler
from services.langgraph.tests import _compiled_fixture_core as core
from services.langgraph.tests._compiled_fixture_support import (
    AS_OF, HASH, case, compact_registry, plain, registry, variant_registries,
)

REGISTRY_NAMES = ("sealed", "elevated", "strict")
SKILLS = [q.skill_name for q in authority.N3_SPECIALISTS.values()]
ROLES = list(authority.N3_SPECIALISTS)


def _reg(name: str) -> Any:
    return variant_registries()[name]


# --------------------------------------------------------------------------
# Registry (compact), resolution, bindings, work orders
# --------------------------------------------------------------------------

def registries_section() -> dict[str, Any]:
    variants = variant_registries()
    out: dict[str, Any] = {"sealed": compact_registry(registry())}
    base = registry()
    for name in ("elevated", "strict"):
        reg = variants[name]
        edits = {}
        for role_id, role in reg.roles.items():
            if role.runtime_authority != base.roles[role_id].runtime_authority:
                edits[role.skill_name] = {k: v for k, v in role.runtime_authority.items()
                                          if base.roles[role_id].runtime_authority.get(k) != v}
        out[name] = {"registry_hash": reg.registry_hash, "grant_contract": reg.authority_registry["grant_contract"],
                     "authority_edits": edits}
    return out


def resolve_cases() -> list[dict[str, Any]]:
    queries: list[list[str]] = [[s] for s in SKILLS] + [
        ["copywriter"], ["Brand & Strategy"], ["copy", "design"], [], ["the of"], ["zzz"], ["a"], ["  Brand  "], ["branding"],
        ["publish"], ["Copywriting", "launch"], ["market-researcher", "x"], ["Çopy"], ["rights-and-clearances-manager"],
        ["accessibility-qa-analyst"], ["cloud-security-engineer"], ["mobile-engineer"], ["K"], ["İ"], ["engineering", "development"],
    ]
    out = []
    for q in queries:
        for dept, fam, limit in [(None, None, 5), ("creative", None, 3), ("brand", "brand-strategy", 1), (None, None, 0), (None, None, -2)]:
            args = ["sealed", q, dept, fam, limit]
            out.append(case("resolveRoles", args, lambda n, c, d, fm, lim: [
                m for m in RoleResolver(_reg(n)).resolve(c, department_hint=d, family_hint=fm, limit=lim)]))
    for skill, dept in [(q.skill_name, q.department) for q in authority.N3_SPECIALISTS.values()] + [
            ("brand-safety-officer", "quality"), ("copywriter", "nope"), ("", "x"), ("founder", "executive")]:
        for name in REGISTRY_NAMES:
            out.append(case("resolveSpecialist", [name, skill, dept], lambda n, s, d: authority.AuthorityBridge(_reg(n)).resolve_specialist(
                authority.SpecialistQuery(s, d))))
    return out


def _grant(role: str, op: str, target: str, **kw: Any) -> dict[str, Any]:
    return {"grant_id": kw.pop("grant_id", f"g-{role}-{op}"), "actor_role_id": role, "operation": op, "target": target,
            "issued_by": kw.pop("issued_by", "human:ad"), "expires_at": kw.pop("expires_at", "2026-12-31"), **kw}


def bind_cases() -> list[dict[str, Any]]:
    r = random.Random(31)
    out = []
    effects = ["PURE", "DRAFT", "REVERSIBLE_WRITE", "IRREVERSIBLE_WRITE", "WEIRD"]
    for _ in range(420):
        role = r.choice([*ROLES, *ROLES, "nonexistent_role", ""])
        op = r.choice(["produce", "publish", "deploy", "media_spend"])
        target = r.choice([f"external:{op}", "artifact:x", f"external:{op}"])
        grants = []
        for _ in range(r.randint(0, 3)):
            grants.append(_grant(r.choice([role, role, "project-manager", "other"]), op if r.random() < 0.8 else "x",
                                 target if r.random() < 0.8 else "t", expires_at=r.choice(["2026-12-31", "2020-01-01", "", "2026-10-29"]),
                                 issued_by=r.choice(["human:ad", role, ""]), grant_id=r.choice(["g1", "", "g2"])))
        args = [r.choice(REGISTRY_NAMES), {
            "runtime_role_id": role, "side_effect_class": r.choice(effects), "operation": op, "target": target,
            "grants": grants, "approval_refs": r.choice([[], ["appr-1"], ["b", "a", "b"]]), "as_of": AS_OF,
            "creator_role_id": r.choice([None, role, "other"]),
        }, r.choice([{}, {}, {"project-manager": "sha256:1", "copywriter": "sha256:2"}])]
        out.append(case("bind", args, _bind))
    return out


def _bind(name: str, kw: dict[str, Any], source_hashes: dict[str, str]) -> Any:
    bridge = authority.AuthorityBridge(_reg(name), source_hashes=_role_hashes(name, source_hashes))
    grants = [authority.AuthorityGrant.model_validate(g) for g in kw["grants"]]
    return bridge.bind(**{**kw, "grants": grants})


def _role_hashes(name: str, by_skill: dict[str, str]) -> dict[str, str]:
    reg = _reg(name)
    return {rid: by_skill[role.skill_name] for rid, role in reg.roles.items() if role.skill_name in by_skill}


def work_order_cases() -> list[dict[str, Any]]:
    base = {"project_id": "p1", "mission_id": "m1", "phase_id": "P9", "objective": "Write copy",
            "required_capabilities": ["copywriter"], "acceptance_criteria": ["ok"]}
    variants: list[dict[str, Any]] = [
        base, {**base, "risk_level": "high"}, {**base, "risk_level": "critical", "approval_refs": ["a"]},
        {**base, "side_effect_class": "REVERSIBLE_WRITE"}, {**base, "side_effect_class": "REVERSIBLE_WRITE", "authority_refs": ["g"]},
        {**base, "side_effect_class": "IRREVERSIBLE_WRITE", "authority_refs": ["g"]},
        {**base, "side_effect_class": "IRREVERSIBLE_WRITE", "authority_refs": ["g"], "approval_refs": ["a"], "risk_level": "high"},
        {**base, "project_id": "  "}, {**base, "mission_id": ""}, {**base, "phase_id": " "}, {**base, "objective": "　"},
        {**base, "risk_level": "extreme"}, {**base, "side_effect_class": "NOPE"}, {**base, "acceptance_criteria": []},
        {**base, "phase_id": "P99"}, {**base, "required_capabilities": []}, {**base, "required_capabilities": ["the"]},
        {**base, "required_capabilities": ["qqqqzzzz"]}, {**base, "objective": "Écrire 😀 \"quoted\" \\ back\nslash\ttab \u0001 \u007f"},
        {**base, "department_hint": "creative", "family_hint": "copy"}, {**base, "input_refs": ["i"], "dependency_refs": ["d"],
                                                                       "required_artifact_refs": ["x"], "required_evidence": ["e"]},
        {**base, "tool_plan": ["t1", "t2"], "context_capsule_hash": HASH, "expected_state_transition": "ACTIVE", "next_route": "X"},
        {**base, "permission_refs": ["perm"]}, {**base, "phase_id": "P0", "required_capabilities": ["brand-strategist"]},
    ]
    return [case("compileWorkOrder", [name, kw], lambda n, k: WorkOrderCompiler(_reg(n)).compile(**k))
            for kw in variants for name in ("sealed", "elevated")]


# --------------------------------------------------------------------------
# Plan requests
# --------------------------------------------------------------------------

def _role_source_hashes(r: random.Random) -> dict[str, str] | None:
    if r.random() < 0.7:
        return None
    bridge = authority.AuthorityBridge(registry())
    out = {}
    for i, query in enumerate(authority.N3_SPECIALISTS.values()):
        role_id = bridge.resolve_specialist(query)
        if role_id and r.random() < 0.85:
            out[role_id] = f"sha256:{i:064x}"
    return out


def _graph_for(req: dict[str, Any]) -> Any:
    """The graph the planner will build for `req`, so approvals can be bound to its real hashes."""
    spine = decisions.DecisionSpine([decisions.DecisionNode.model_validate(d) for d in req.get("decisions", [])])
    try:
        return core._compile(req["deliverables"], req.get("existing_artifacts", {}), spine.accepted_by_kind(), req.get("evidence", []))
    except Exception:  # noqa: BLE001 - an invalid request has no graph; the plan case records its error
        return None


def _scope(graph: Any, approval_id: str, refs: list[str], r: random.Random, **kw: Any) -> dict[str, Any]:
    scope = change_control.build_scope(
        graph, approval_id=approval_id, subjects={ref: graph.nodes[ref].semantic_hash for ref in refs}, artifact_hashes={},
        policy_version=kw.get("policy_version", "amc-approval/v1"), reviewer_ref=kw.get("reviewer", "human:client"),
        decision=kw.get("decision", "approve"))
    return scope.model_dump(mode="json")


def _decorate(req: dict[str, Any], r: random.Random) -> dict[str, Any]:
    graph = _graph_for(req)
    if graph is None:
        return req
    nodes = list(graph.nodes)
    interesting = [n for n in nodes if n.startswith(("deliverable:", "accept:", "external:", "work:", "ref:"))]
    approvals = []
    for i in range(r.choice([0, 0, 1, 2, 3])):
        refs = r.sample(interesting, min(len(interesting), r.randint(1, 2)))
        approvals.append(_scope(graph, f"appr-{i}", refs, r, decision=r.choice(["approve"] * 4 + ["reject"]),
                                reviewer=r.choice(["human:client"] * 4 + [None]),
                                policy_version=r.choice(["amc-approval/v1"] * 5 + ["amc-approval/v2"])))
    if approvals:
        req["approvals"] = approvals
    grants = []
    for node in graph.nodes.values():
        if node.type.value == "EXTERNAL_ACTION" and r.random() < 0.7:
            action = node.id.split(":")[1]
            grants.append(_grant(r.choice([node.runtime_role_id, node.runtime_role_id, "project-manager"]), action, f"external:{action}",
                                 expires_at=r.choice(["2026-12-31"] * 3 + ["2020-01-01", ""]), issued_by=r.choice(["human:ad"] * 3 + [node.runtime_role_id])))
    if grants:
        req["grants"] = grants
    ext = {s["external_action"] for s in req["deliverables"] if s.get("external_action")}
    if ext and r.random() < 0.6:
        req["provider_status"] = {a: r.choice(["VERIFIED", "VERIFIED", "PENDING"]) for a in sorted(ext)}
    if r.random() < 0.2:
        req["artifact_hashes"] = {r.choice(nodes): "f" * 64}
    if r.random() < 0.15:
        req["policy_version"] = "amc-approval/v2"
    results = []
    for node in graph.nodes.values():
        if node.type.value == "VALIDATION_OBLIGATION" and r.random() < 0.4:
            for ob in r.sample(node.validation_obligations, min(len(node.validation_obligations), r.randint(1, 4))):
                results.append({"node_id": node.id, "obligation": ob, "status": r.choice(["PASS", "PASS", "FAIL"]),
                                "validator_ref": r.choice(["creator", "rev-1", "brand.governance"]),
                                "attempt": r.randint(1, 3), "failure_fingerprint": r.choice([None, "fp"])})
    for node_id in [n for n in nodes if n.startswith("ref:")][:2]:
        results.append({"node_id": node_id, "obligation": "PROFILE:BRAND_COHESION", "status": r.choice(["PASS", "FAIL"]),
                        "validator_ref": "brand.governance"})
    if results:
        req["validation_results"] = results
    return req


def random_plan_request(r: random.Random, idx: int) -> dict[str, Any]:
    req: dict[str, Any] = {"project_id": f"proj-{idx}", "as_of": AS_OF,
                           "deliverables": [core.random_spec(r, i) for i in range(r.randint(1, 3))]}
    if r.random() < 0.6:
        req["existing_artifacts"] = core.random_existing(r)
    if r.random() < 0.7:
        req["evidence"] = core.random_evidence(r)
    if r.random() < 0.4:
        req["decisions"] = [_random_decision(r, k) for k in r.sample([k.value for k in backchain.DecisionKind], r.randint(1, 3))]
    if r.random() < 0.4:
        req["genome"] = [core._assertion(r) for _ in range(r.randint(1, 5))]
    if r.random() < 0.3:
        req["volatile_constraints"] = [core._constraint(r) for _ in range(r.randint(1, 3))]
    if r.random() < 0.5:
        req["generation_modes"] = {a: r.choice(["PROVIDER_SUCCESS", "FALLBACK_DEGRADED"]) for a in r.sample(core.ARTS, r.randint(1, 4))}
    return _decorate(req, r)


def _random_decision(r: random.Random, kind: str) -> dict[str, Any]:
    d = core._decision(kind)
    if r.random() < 0.7:
        d.update({"status": "ACCEPTED", "selected_option": "A", "approved_by": "human:cd", "required_approver": "human:cd"})
    return d


def _volatile(key: str, **kw: Any) -> dict[str, Any]:
    return {"key": key, "source_ref": "official:docs", "retrieved_at": "2026-09-26", "value": "verified-ref",
            "verification_status": "VERIFIED", "expires_or_recheck_at": "2026-12-26", **kw}


def handwritten_requests() -> list[tuple[str, dict[str, Any]]]:
    sp = core.spec
    ev = core.CAMPAIGN_EVIDENCE
    campaign = sp("campaign", "campaign_package", domains=["BRAND", "CONTENT"], acceptance_criteria=["on-brief", "brand-safe"])
    guidelines = sp("guidelines", "brand_guidelines_doc", domains=["BRAND"])
    base = {"project_id": "hw", "as_of": AS_OF}
    out: list[tuple[str, dict[str, Any]]] = []
    out.append(("multidiscipline", {**base, "deliverables": [campaign, guidelines]}))
    out.append(("copy_only", {**base, "deliverables": [sp("copy", "copy_variant", domains=["CONTENT"])],
                              "existing_artifacts": {"brand_platform": HASH, "creative_concept": "b" * 64}}))
    out.append(("campaign_with_evidence_and_decisions", {
        **base, "deliverables": [campaign], "evidence": ev,
        "decisions": [core._decision(k, status="ACCEPTED", selected_option="A", approved_by="human:cd", required_approver="human:cd")
                      for k in ("positioning", "brand_platform", "creative_direction")]}))
    out.append(("reversed_deliverables", {**base, "deliverables": [guidelines, campaign]}))
    app = sp("app", "app_build_spec", domains=["MOBILE_APP"], external_action="deploy")
    app_existing = {"design_system_spec": HASH, "product_spec": HASH, "campaign_package": HASH, "qa_report": HASH}
    out.append(("mobile_release_stale_volatile", {**base, "deliverables": [app], "existing_artifacts": app_existing}))
    out.append(("mobile_release_verified_volatile", {
        **base, "deliverables": [app], "existing_artifacts": app_existing, "volatile_constraints": [
            _volatile("app_store.requirements"), _volatile("security.testing_standard"), _volatile("accessibility.standard")]}))
    launch = sp("launch", "campaign_package", external_action="publish")
    launch_existing = {"campaign_package": HASH, "qa_report": HASH, "release_record": HASH}
    graph = core._compile([launch], launch_existing, {}, [])
    scope = change_control.build_scope(graph, approval_id="appr-launch", subjects={"deliverable:dlaunch": graph.nodes["deliverable:dlaunch"].semantic_hash},
                                      artifact_hashes={}, policy_version="amc-approval/v1", reviewer_ref="human:client",
                                      decision="approve").model_dump(mode="json")
    bcohesion = {"node_id": "ref:campaign_package", "obligation": "PROFILE:BRAND_COHESION", "status": "PASS", "validator_ref": "brand.governance"}
    release = {**base, "deliverables": [launch], "existing_artifacts": launch_existing, "validation_results": [bcohesion],
               "generation_modes": {"campaign_package": "PROVIDER_SUCCESS"}}
    out.append(("release_missing_authority", release))
    out.append(("release_authorized", {**release, "approvals": [scope], "provider_status": {"publish": "VERIFIED"}, "grants": [
        _grant("release_manager", "publish", "external:publish", issued_by="human:account-director")]}))
    out.append(("release_degraded", {**release, "approvals": [scope], "provider_status": {"publish": "VERIFIED"},
                                     "generation_modes": {"campaign_package": "FALLBACK_DEGRADED"}, "grants": [
                                         _grant("release_manager", "publish", "external:publish", issued_by="human:ad")]}))
    out.append(("release_stale_approval", {**release, "approvals": [scope], "artifact_hashes": {"ref:campaign_package": "9" * 64}}))
    out.append(("unmodelled_output", {**base, "deliverables": [sp("master", "film_master")]}))
    out.append(("film_rights", {**base, "deliverables": [sp("film", "campaign_package", domains=["VIDEO", "CONTENT"], external_action="publish")],
                                "existing_artifacts": {"brand_platform": HASH, "brand_core": HASH, "identity_guidelines": HASH, "positioning_statement": HASH}}))
    out.append(("spend", {**base, "deliverables": [sp("spend", "media_plan", external_action="media_spend")], "evidence": ev}))
    out.append(("live_service", {**base, "deliverables": [sp("ops", "release_record", live_service=True, domains=["WEB", "ANALYTICS"], external_action="distribute")]}))
    out.append(("genome", {**base, "deliverables": [campaign], "genome": [
        {"key": "audience.primary", "domain": "BRAND", "value_or_ref": "founders", "source_refs": ["brief:1"], "epistemic_status": "VERIFIED_FACT"},
        {"key": "tone", "domain": "CONTENT", "value_or_ref": "warm", "epistemic_status": "ASSUMPTION", "confidence": 1},
        {"key": "tone", "domain": "CONTENT", "value_or_ref": "bold", "epistemic_status": "INFERENCE", "freshness": "2026-12-01"},
        {"key": "claim", "domain": "BRAND", "value_or_ref": "x", "epistemic_status": "VERIFIED_FACT"}]}))
    out.append(("six_validation_results", {**base, "deliverables": [campaign], "evidence": ev, "validation_results": [
        {"node_id": "validate:campaign_package", "obligation": "PROFILE:BRAND_COHESION", "status": "FAIL", "validator_ref": "x", "attempt": a,
         "failure_fingerprint": "same"} for a in range(1, 6)]}))
    return out


def error_requests() -> list[tuple[str, Any]]:
    sp = core.spec
    d = sp("x", "copy_variant")
    base = {"project_id": "e", "as_of": AS_OF, "deliverables": [d]}
    return [
        ("bad_domain", {**base, "deliverables": [sp("x", "copy_variant", domains=["NOPE"])]}),
        ("duplicate_ids", {**base, "deliverables": [d, d]}),
        ("no_deliverables", {**base, "deliverables": []}),
        ("too_many_deliverables", {**base, "deliverables": [sp(i, "copy_variant") for i in range(51)]}),
        ("empty_project", {**base, "project_id": ""}), ("long_project", {**base, "project_id": "p" * 201}),
        ("short_as_of", {**base, "as_of": "2026"}), ("extra_field", {**base, "surprise": 1}),
        ("missing_deliverables", {"project_id": "e", "as_of": AS_OF}), ("string_for_list", {**base, "genome": "x"}),
        ("bad_enum", {**base, "deliverables": [{**d, "external_action": "teleport"}]}),
        ("no_criteria", {**base, "deliverables": [{**d, "acceptance_criteria": []}]}),
        ("bad_grant", {**base, "grants": [{"grant_id": "g"}]}), ("bad_scope", {**base, "approvals": [{"approval_id": "a"}]}),
        ("bad_status", {**base, "validation_results": [{"node_id": "n", "obligation": "o", "status": "MAYBE", "validator_ref": "v"}]}),
        ("lax_int_string", {**base, "validation_results": [{"node_id": "n", "obligation": "o", "status": "PASS", "validator_ref": "v", "attempt": "2"}]}),
        ("lax_bool_string", {**base, "deliverables": [{**d, "live_service": "yes"}]}),
        ("not_an_object", []), ("unicode_len_ok", {**base, "project_id": "😀" * 150}), ("unicode_len_bad", {**base, "project_id": "😀" * 201}),
    ]


# --------------------------------------------------------------------------
# Plan results
# --------------------------------------------------------------------------

def plan_digest(plan: Any) -> dict[str, Any]:
    return {
        "plan_hash": plan.plan_hash, "graph_hash": plan.graph.graph_hash, "node_count": len(plan.graph.nodes),
        "overlays": plan.overlays, "genome_hash": plan.genome_hash, "registry_hash": plan.registry_hash,
        "bindings": {k: [b.binding_hash, b.status.value, b.specialist_role_id, b.side_effect_ceiling] for k, b in plan.bindings.items()},
        "capsules": {k: c.capsule_hash for k, c in plan.capsules.items()},
        "work_orders": {k: [w.work_order_hash, w.execution_ready, w.blockers] for k, w in plan.work_orders.items()},
        "cells": {k: [c.cell_hash, c.status.value, c.blockers] for k, c in plan.cells.items()},
        "waves": [[w.index, w.cells, w.serialized_reason] for w in plan.waves.waves], "held": plan.waves.held,
        "wave_hash": plan.waves.wave_hash,
        "autonomy": {k: [a.route.value, a.level.value, a.reasons] for k, a in plan.autonomy.items()},
        "executable": plan.executable, "blocked": plan.blocked, "human_gates": plan.human_gates,
        "release_readiness": plan.release_readiness, "uncertainty_first": plan.uncertainty_first,
        "activated_specialists": plan.activated_specialists, "dormant": plan.dormant_specialist_count,
        "shared_genome_refs": plan.shared_genome_refs, "jit_skills": plan.jit_skills,
        "node_cards": {k: [c.unresolved, hashing.semantic_hash(c.dimensions)] for k, c in plan.node_cards.items()},
        "summary": plan.summary(),
    }


def _plan(name: str, request: Any, source_hashes: dict[str, str] | None) -> planner.CompiledAgencyPlan:
    req = planner.CompiledAgencyRequest.model_validate(request)
    index = None
    if source_hashes is not None:
        from services.langgraph.agency.compiled.role_sources import RoleSourceEntry, RoleSourceIndex

        index = RoleSourceIndex([RoleSourceEntry(rid, f"departments/{i}/SKILL.md", h, 1) for i, (rid, h) in enumerate(source_hashes.items())])
    return planner.compile_agency_plan(req, registry=_reg(name), source_index=index)


def plan_cases() -> list[dict[str, Any]]:
    r = random.Random(32)
    out = []
    full = {"multidiscipline", "copy_only", "release_authorized"}
    for label, req in handwritten_requests():
        call = "compileAgencyPlan" if label in full else "compileAgencyPlanDigest"
        reg = "sealed"
        out.append({**case(call, [reg, req, None], lambda n, q, s: _plan(n, q, s) if call == "compileAgencyPlan"
                           else plan_digest(_plan(n, q, s))), "label": label})
    for label, req in handwritten_requests():
        if label in ("release_authorized", "release_missing_authority", "mobile_release_verified_volatile", "spend", "film_rights"):
            for reg in ("elevated", "strict"):
                out.append({**case("compileAgencyPlanDigest", [reg, req, None], lambda n, q, s: plan_digest(_plan(n, q, s))),
                            "label": f"{label}@{reg}"})
    hashes = {rid: f"sha256:{i:064x}" for i, rid in enumerate(filter(None, (authority.AuthorityBridge(registry()).resolve_specialist(q)
                                                                              for q in authority.N3_SPECIALISTS.values())))}
    out.append({**case("compileAgencyPlanDigest", ["sealed", handwritten_requests()[0][1], hashes],
                       lambda n, q, s: plan_digest(_plan(n, q, s))), "label": "source_index"})
    for label, req in error_requests():
        out.append({**case("compileAgencyPlanDigest", ["sealed", req, None], lambda n, q, s: plan_digest(_plan(n, q, s))), "label": label})
    for i in range(88):
        req = random_plan_request(r, i)
        out.append(case("compileAgencyPlanDigest", [r.choice(REGISTRY_NAMES), req, _role_source_hashes(r)],
                        lambda n, q, s: plan_digest(_plan(n, q, s))))
    return out


def build_plans() -> dict[str, Any]:
    return {
        "registries": [registries_section()], "resolve": resolve_cases(), "bind": bind_cases(), "work_orders": work_order_cases(),
        "plans": plan_cases(),
    }


__all__ = ["build_plans", "plan_digest", "plain", "itertools"]
