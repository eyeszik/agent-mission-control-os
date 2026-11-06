"""N1–N4 governance kernel cross-language parity fixture (Python is the reference).

`packages/kernel/tests/fixtures/kernel-parity.json` records calls into
`services/langgraph/agency/kernel` and what Python returned (or raised) for
each. `@amc/kernel` must reproduce every entry exactly, errors included. This
test checks the stored entries still match Python, so a change to the kernel
fails here before it silently breaks the TypeScript twin. Regenerate with
AMC_REGENERATE_FIXTURES=1.

Every case is {"call": <name>, "args": [...], "ok": <result>} or
{"call": ..., "args": ..., "error": {"type": <exception class>, "message": str(exc)}}.
Values JSON cannot carry distinctly are tagged as in the canonical pilot:
{"$int": "<decimal>"}, {"$float": "<python repr>"}, {"$utf16": "<hex code units>"}.
"""
from __future__ import annotations

import itertools
import json
import os
import random
from pathlib import Path
from typing import Any, Callable

from pydantic import ValidationError

from services.langgraph.agency.kernel import lifecycle, ontology, registry, roles
from services.langgraph.agency.kernel.models import ArtifactStatus, EngagementStatus, WorkstreamStatus

FIXTURE = Path(__file__).resolve().parents[3] / "packages/kernel/tests/fixtures/kernel-parity.json"
TAGS = ("$int", "$float", "$utf16")
ENTITY_ENUMS = {"engagement": EngagementStatus, "workstream": WorkstreamStatus, "artifact": ArtifactStatus}


# --------------------------------------------------------------------------
# Tagged values
# --------------------------------------------------------------------------

def decode(node: Any) -> Any:
    if isinstance(node, list):
        return [decode(x) for x in node]
    if not isinstance(node, dict):
        return node
    if len(node) == 1 and next(iter(node)) in TAGS:
        tag, raw = next(iter(node.items()))
        if tag == "$int":
            return int(raw)
        if tag == "$float":
            return float(raw)
        return "".join(chr(int(unit, 16)) for unit in raw.split())
    return {k: decode(v) for k, v in node.items()}


def _f(x: float) -> dict[str, str]:
    return {"$float": repr(x)}


def _i(x: int) -> dict[str, str]:
    return {"$int": str(x)}


# --------------------------------------------------------------------------
# Dispatch: every call returns a JSON-able, order-deterministic result
# --------------------------------------------------------------------------

def _definition(value: str) -> dict[str, Any]:
    definition = ontology.department_definition(value)
    return {
        "department": definition.department.value,
        "mandate": definition.mandate,
        "capabilities": sorted(c.value for c in definition.capabilities),
        "owned_artifact_types": sorted(t.value for t in definition.owned_artifact_types),
        "release_reviewers": sorted(d.value for d in definition.release_reviewers),
    }


def _context(raw: dict[str, Any] | None) -> lifecycle.TransitionContext | None:
    if raw is None:
        return None
    fields = dict(raw)
    if "unmet_hard_dependencies" in fields:
        fields["unmet_hard_dependencies"] = tuple(fields["unmet_hard_dependencies"])
    return lifecycle.TransitionContext(**fields)


def _failures(items: list[lifecycle.GuardFailure]) -> list[list[str]]:
    return [[item.code, item.message] for item in items]


def _release(raw: dict[str, Any]) -> dict[str, Any]:
    context = _context(raw)
    assert context is not None
    return {
        "failures": _failures(lifecycle.release_guard_failures(context)),
        "is_degraded": context.is_degraded,
        "human_approved": context.human_approved,
    }


def _transition(entity: str, current: str, target: str, raw: dict[str, Any] | None) -> dict[str, Any]:
    context = _context(raw)
    failures = lifecycle.transition_failures(entity, current, target, context)
    assert lifecycle.transition_blockers(entity, current, target, context) == [f.message for f in failures]
    assert_error: str | None = None
    try:
        lifecycle.assert_transition(entity, current, target, context)
    except lifecycle.TransitionError as exc:
        assert_error = str(exc)
    return {
        "failures": _failures(failures),
        "can": lifecycle.can_transition(entity, current, target, context),
        "assert_error": assert_error,
    }


def _role(role_id: str) -> dict[str, Any]:
    entries = roles.role_snapshot()["roles"]
    contract = roles.get_role(role_id)
    return next(entry for entry in entries if entry["role_id"] == contract.role_id)


def _slug(value: str) -> bool:
    try:
        roles.RoleContract(
            role_id=value, department="copy", mandate="m", capabilities=frozenset(), produces=frozenset()
        )
    except ValidationError:
        return False
    return True


def _version(payload: dict[str, Any]) -> dict[str, Any]:
    return registry.ArtifactVersion.deserialize(decode(payload)).serialize()


def _registry(payload: dict[str, Any]) -> dict[str, Any]:
    return registry.ArtifactRegistry.deserialize(decode(payload)).serialize()


def _run_op(reg: registry.ArtifactRegistry, op: dict[str, Any]) -> Any:
    kind = op["op"]
    if kind == "commit":
        kwargs = {k: v for k, v in op.items() if k != "op"}
        kwargs["content"] = decode(kwargs["content"])
        # commit() is typed to take an ArtifactStatus member; a bare str breaks serialize().
        kwargs["status"] = ArtifactStatus(kwargs["status"])
        return reg.commit(**kwargs).serialize()
    if kind == "merge":
        return reg.merge(op["incoming"], op.get("base", registry.MAIN_BRANCH)).serialize()
    if kind == "head":
        head = reg.head(op["branch"])
        return head.serialize() if head else None
    if kind == "lineage":
        return [v.serialize() for v in reg.lineage(op["branch"])]
    return reg.branches()


def _script(artifact_id: str, ops: list[dict[str, Any]]) -> dict[str, Any]:
    reg = registry.ArtifactRegistry(artifact_id)
    steps = [_capture(_run_op, reg, op) for op in ops]
    final = reg.serialize()
    assert registry.ArtifactRegistry.deserialize(final).serialize() == final
    assert [v.serialize() for v in reg.all_versions()] == final["versions"]
    return {"steps": steps, "final": final}


DISPATCH: dict[str, Callable[..., Any]] = {
    "resolve_department": lambda v: ontology.resolve_department(v).value,
    "resolve_artifact_type": lambda v: ontology.resolve_artifact_type(v).value,
    "department_definition": _definition,
    "owning_department": lambda v: ontology.owning_department(v).value,
    "assert_department_owns": ontology.assert_department_owns,
    "has_capability": ontology.has_capability,
    "allowed_transitions": lambda e, s: sorted(x.value for x in lifecycle.allowed_transitions(e, s)),
    "terminal_states": lambda e: sorted(x.value for x in lifecycle.terminal_states(e)),
    "release_guard_failures": _release,
    "transition": _transition,
    "get_role": _role,
    "roles_for_department": lambda d: [c.role_id for c in roles.roles_for_department(d)],
    "assert_role_may_produce": roles.assert_role_may_produce,
    "assert_evidence_sufficient": roles.assert_evidence_sufficient,
    "role_id_is_slug": _slug,
    "content_fingerprint": lambda v: registry.content_fingerprint(decode(v)),
    "version_deserialize": _version,
    "registry_deserialize": _registry,
    "registry_script": _script,
}


def _capture(fn: Callable[..., Any], *args: Any) -> dict[str, Any]:
    try:
        return {"ok": fn(*args)}
    except (ValueError, KeyError, TypeError) as exc:
        return {"error": {"type": type(exc).__name__, "message": str(exc)}}


def _case(call: str, *args: Any) -> dict[str, Any]:
    return {"call": call, "args": list(args), **_capture(DISPATCH[call], *args)}


# --------------------------------------------------------------------------
# Case builders
# --------------------------------------------------------------------------

DEPARTMENTS = [d.value for d in ontology.Department]
ARTIFACT_TYPES = [t.value for t in ontology.ArtifactType]
CAPABILITIES = [c.value for c in ontology.Capability]
BOGUS = ["", "bogus", "Strategy", " strategy", "café", "o'brien"]


def _ontology_cases() -> list[dict[str, Any]]:
    cases = [_case("resolve_department", v) for v in DEPARTMENTS + BOGUS]
    cases += [_case("resolve_artifact_type", v) for v in ARTIFACT_TYPES + BOGUS]
    cases += [_case("department_definition", v) for v in DEPARTMENTS + BOGUS]
    cases += [_case("owning_department", v) for v in ARTIFACT_TYPES + BOGUS]
    pairs = itertools.product(DEPARTMENTS + ["bogus"], ARTIFACT_TYPES + ["bogus"])
    cases += [_case("assert_department_owns", d, t) for d, t in pairs]
    pairs = itertools.product(DEPARTMENTS + ["bogus"], CAPABILITIES + ["bogus"])
    cases += [_case("has_capability", d, c) for d, c in pairs]
    return cases


GUARD_DOMAIN: dict[str, list[Any]] = {
    "generation_mode": [None, "FALLBACK_DEGRADED", "LIVE"],
    "approval_exists": [False, True],
    "approval_resolved": [False, True],
    "approval_decision": [None, "approve", "reject"],
    "brand_safety_passed": [None, True, False],
    "brand_safety_advisory": [False, True],
    "external_side_effect": [False, True],
    "spend_authorized": [False, True],
    "unmet_hard_dependencies": [[], ["zeta", "alpha", "\U0001f600", ""]],
}


def _all_contexts() -> list[dict[str, Any]]:
    keys = list(GUARD_DOMAIN)
    return [dict(zip(keys, values)) for values in itertools.product(*GUARD_DOMAIN.values())]


CLEAN = {"approval_exists": True, "approval_resolved": True, "approval_decision": "approve",
         "brand_safety_passed": True}
REPRESENTATIVE: list[dict[str, Any] | None] = [
    None, {}, CLEAN, {**CLEAN, "generation_mode": "FALLBACK_DEGRADED"},
    {**CLEAN, "unmet_hard_dependencies": ["b", "a"]}, {**CLEAN, "external_side_effect": True},
    {"approval_exists": True, "approval_resolved": True, "brand_safety_passed": False,
     "brand_safety_advisory": True},
    {"approval_exists": True, "unmet_hard_dependencies": ["dep"], "generation_mode": "LIVE"},
]


def _lifecycle_cases(r: random.Random) -> list[dict[str, Any]]:
    contexts = _all_contexts()
    cases = [_case("release_guard_failures", ctx) for ctx in contexts]
    for entity, enum_cls in ENTITY_ENUMS.items():
        states = [s.value for s in enum_cls]
        cases += [_case("allowed_transitions", entity, s) for s in states + ["bogus"]]
        cases.append(_case("terminal_states", entity))
        for current, target in itertools.product(states, states):
            # An illegal edge is reported alone, whatever the context, so two contexts suffice there.
            legal = target in {t.value for t in lifecycle.allowed_transitions(entity, current)}
            representative = REPRESENTATIVE if legal else REPRESENTATIVE[:3]
            cases += [_case("transition", entity, current, target, ctx) for ctx in representative]
            if legal and _is_gated(entity, target):
                cases += [_case("transition", entity, current, target, ctx) for ctx in r.sample(contexts, 48)]
        cases += [_case("transition", entity, "bogus", states[0], None),
                  _case("transition", entity, states[0], "bogus", None)]
    cases += [_case("allowed_transitions", "bogus", "draft"), _case("terminal_states", "bogus"),
              _case("transition", "bogus", "draft", "draft", None)]
    return cases


def _is_gated(entity: str, target: str) -> bool:
    gated = {s.value for s in lifecycle.CLIENT_VISIBLE_TRANSITIONS[entity]}
    gated |= {s.value for s in lifecycle.DEPENDENCY_GATED_TRANSITIONS[entity]}
    return target in gated


def _role_cases() -> list[dict[str, Any]]:
    role_ids = sorted(roles.ROLE_REGISTRY)
    cases = [_case("get_role", v) for v in role_ids + BOGUS]
    cases += [_case("roles_for_department", d) for d in DEPARTMENTS + BOGUS]
    pairs = itertools.product(role_ids + ["bogus"], ARTIFACT_TYPES + ["bogus"])
    cases += [_case("assert_role_may_produce", rid, t) for rid, t in pairs]
    pairs = itertools.product(role_ids + ["bogus"], range(-1, 5))
    cases += [_case("assert_evidence_sufficient", rid, n) for rid, n in pairs]
    slugs = ["a", "role_1", "my-role", "_", "-", "", "a b", "a.b", "émile", "数据", "a/b", "A_B-c9", "x\n"]
    cases += [_case("role_id_is_slug", s) for s in slugs]
    return cases


# -- registry ----------------------------------------------------------------

def _random_float(r: random.Random) -> float:
    kind = r.randrange(3)
    if kind == 0:
        return r.uniform(-1, 1) * 10 ** r.randint(-30, 30)
    if kind == 1:
        return round(r.uniform(-1000, 1000), r.randint(0, 6))
    return float(r.randint(-(10**6), 10**6))


def _random_text(r: random.Random) -> str:
    alphabet = ["a", "Z", "0", " ", "é", "ß", "中", "～", "\U0001f600", "\n", '"', "\\", "\x7f", "\x01", "\t", "/"]
    return "".join(r.choice(alphabet) for _ in range(r.randint(0, 6)))


def _random_value(r: random.Random, depth: int) -> Any:
    kind = r.randrange(8 if depth < 3 else 6)
    if kind == 0:
        return r.choice([None, True, False])
    if kind == 1:
        return _i(r.randint(-(2**70), 2**70))
    if kind == 2:
        return _i(r.randint(-1000, 1000))
    if kind == 3:
        return _f(_random_float(r))
    if kind in (4, 5):
        return _random_text(r)
    if kind == 6:
        return [_random_value(r, depth + 1) for _ in range(r.randint(0, 4))]
    keys = {_random_text(r) for _ in range(r.randint(0, 4))} - set(TAGS)
    return {k: _random_value(r, depth + 1) for k in keys}


def _fingerprint_cases(r: random.Random) -> list[dict[str, Any]]:
    handwritten: list[Any] = [
        None, True, False, _i(0), _i(-7), _i(2**53 + 1), _i(-(2**80)), _f(0.0), _f(-0.0), _f(1.0),
        _f(1e16), _f(1.5e16), _f(1e-05), _f(0.0001), _f(123456789012345.6), _f(1e22), _f(5e-324),
        _f(1.7976931348623157e308), _f(float("nan")), _f(float("inf")), _f(float("-inf")), _f(0.1),
        "", "plain", "café", "\U0001f600", "\x00\x1f\x7f", 'q"b\\s/', "\b\f\n\r\t", {"$utf16": "61 d800 62"},
        [], {}, {"b": 1, "a": [1, {"c": None}]}, {"\U0001f600": 1, "ﬁ": 2, "z": 3, "é": 4, "": 5},
        {"$utf16x": "not a tag"}, [_i(1), _f(1.5), "s", None, True, [], {}],
    ]
    cases = [_case("content_fingerprint", v) for v in handwritten]
    return cases + [_case("content_fingerprint", _random_value(r, 0)) for _ in range(300)]


def _commit(branch: str, status: str, content: Any, **extra: Any) -> dict[str, Any]:
    op = {"op": "commit", "branch": branch, "status": status, "artifact_type": "copy_variant",
          "owner_department": "copy", "content": content}
    op.update(extra)
    return op


def _matrix_scripts() -> list[dict[str, Any]]:
    cases = []
    for base, incoming in itertools.product(ArtifactStatus, ArtifactStatus):
        ops = [_commit("main", "draft", "v1"), _commit("feature", incoming.value, "incoming"),
               _commit("main", base.value, "base"), {"op": "merge", "incoming": "feature"}]
        cases.append(_case("registry_script", f"matrix-{base.value}-{incoming.value}", ops))
    return cases


def _handwritten_scripts() -> list[dict[str, Any]]:
    scripts = {
        "branch before main": [_commit("feature", "draft", "x")],
        "fast forward": [_commit("main", "approved", "a"), _commit("f", "draft", "b"),
                         {"op": "merge", "incoming": "f"}, {"op": "branches"}],
        "identical content": [_commit("main", "released", {"k": 1}), _commit("f", "draft", "x"),
                              _commit("main", "released", "y"), _commit("f", "draft", "y"),
                              {"op": "merge", "incoming": "f"}],
        "degraded": [_commit("main", "draft", "a"), _commit("f", "draft", "b", generation_mode="FALLBACK_DEGRADED"),
                     {"op": "merge", "incoming": "f"}],
        "type mismatch": [_commit("main", "draft", "a"),
                          _commit("f", "draft", "b", artifact_type="design_brief", owner_department="design"),
                          {"op": "merge", "incoming": "f"}],
        "wrong owner": [_commit("main", "draft", "a", owner_department="design")],
        "unknown type": [_commit("main", "draft", "a", artifact_type="bogus")],
        "unknown dept": [_commit("main", "draft", "a", owner_department="bogus")],
        "missing branches": [{"op": "merge", "incoming": "f"}, _commit("main", "draft", "a"),
                             {"op": "merge", "incoming": "f"}, {"op": "merge", "incoming": "main", "base": "nope"},
                             {"op": "head", "branch": "nope"}, {"op": "lineage", "branch": "nope"}],
        "metadata and assumptions": [_commit("main", "draft", "a", assumptions=["z", "a"],
                                             metadata={"k": [1, "é"]}, generation_mode="LIVE"),
                                     _commit("main", "draft", "b", metadata={}),
                                     {"op": "head", "branch": "main"}, {"op": "lineage", "branch": "main"}],
        "self merge": [_commit("main", "draft", "a"), {"op": "merge", "incoming": "main"}],
    }
    return [_case("registry_script", name, ops) for name, ops in scripts.items()]


SCRIPT_TYPES = [("copy_variant", "copy"), ("copy_variant", "copy"), ("copy_variant", "copy"),
                ("design_brief", "design"), ("design_brief", "copy")]
SCRIPT_BRANCHES = ["main", "main", "b1", "b2", "b3"]
SCRIPT_CONTENT: list[Any] = ["a", "b", {"k": 1}, {"k": _f(1.0)}, [1, 2], None]


def _random_op(r: random.Random) -> dict[str, Any]:
    kind = r.randrange(10)
    if kind < 6:
        artifact_type, department = r.choice(SCRIPT_TYPES)
        return _commit(r.choice(SCRIPT_BRANCHES), r.choice(list(ArtifactStatus)).value, r.choice(SCRIPT_CONTENT),
                       artifact_type=artifact_type, owner_department=department,
                       generation_mode=r.choice([None, None, "LIVE", "FALLBACK_DEGRADED"]))
    if kind < 9:
        return {"op": "merge", "incoming": r.choice(SCRIPT_BRANCHES), "base": r.choice(SCRIPT_BRANCHES)}
    return r.choice([{"op": "branches"}, {"op": "head", "branch": r.choice(SCRIPT_BRANCHES)},
                     {"op": "lineage", "branch": r.choice(SCRIPT_BRANCHES)}])


def _random_scripts(r: random.Random) -> list[dict[str, Any]]:
    return [_case("registry_script", f"random-{i}", [_random_op(r) for _ in range(r.randint(1, 14))])
            for i in range(100)]


VALID_VERSION = {"artifact_id": "art", "branch": "main", "version": 2, "status": "draft",
                 "artifact_type": "copy_variant", "owner_department": "copy", "content_hash": "h"}


def _deserialize_cases() -> list[dict[str, Any]]:
    variants: list[dict[str, Any]] = [
        VALID_VERSION, {**VALID_VERSION, "version": "3"}, {**VALID_VERSION, "version": " -4 "},
        {**VALID_VERSION, "version": "1_000"}, {**VALID_VERSION, "version": _f(2.9)},
        {**VALID_VERSION, "version": _f(-2.9)}, {**VALID_VERSION, "version": True}, {**VALID_VERSION, "version": "x"},
        {**VALID_VERSION, "version": "3.0"}, {**VALID_VERSION, "version": None}, {**VALID_VERSION, "status": "bogus"},
        {**VALID_VERSION, "artifact_type": "bogus"}, {**VALID_VERSION, "owner_department": "bogus"},
        {**VALID_VERSION, "assumptions": ["a", "b"]}, {**VALID_VERSION, "assumptions": None},
        {**VALID_VERSION, "assumptions": "ab\U0001f600"}, {**VALID_VERSION, "metadata": None},
        {**VALID_VERSION, "metadata": {"x": 1}}, {**VALID_VERSION, "parent_version": 1, "forked_from": 1,
                                                    "generation_mode": "LIVE"},
        {k: v for k, v in VALID_VERSION.items() if k != "branch"},
        {k: v for k, v in VALID_VERSION.items() if k != "content_hash"},
        {**VALID_VERSION, "status": "bogus", "artifact_type": "bogus"},
    ]
    cases = [_case("version_deserialize", v) for v in variants]
    registries: list[dict[str, Any]] = [
        {"registry_version": registry.REGISTRY_VERSION, "artifact_id": "art", "versions": [VALID_VERSION]},
        {"registry_version": registry.REGISTRY_VERSION, "artifact_id": "art", "versions": []},
        {"registry_version": "amc-agency-registry/n4-v0", "artifact_id": "art", "versions": []},
        {"artifact_id": "art", "versions": []}, {"registry_version": registry.REGISTRY_VERSION, "versions": []},
        {"registry_version": registry.REGISTRY_VERSION, "artifact_id": "art"},
        {"registry_version": _i(4), "artifact_id": "art", "versions": []},
    ]
    return cases + [_case("registry_deserialize", v) for v in registries]


def _snapshots() -> dict[str, Any]:
    return {
        "ontology": ontology.ontology_snapshot(),
        "lifecycle": lifecycle.lifecycle_snapshot(),
        "roles": roles.role_snapshot(),
        "merge_matrix": [[b.value, i.value, res.value] for (b, i), res in registry.MERGE_MATRIX.items()],
        "self_checks": {
            "validate_matrices": lifecycle.validate_matrices(),
            "validate_registry": roles.validate_registry(),
            "validate_merge_matrix": registry.validate_merge_matrix(),
        },
        "versions": {
            "ontology": ontology.ONTOLOGY_VERSION, "lifecycle": lifecycle.LIFECYCLE_VERSION,
            "roles": roles.ROLE_CONTRACT_VERSION, "registry": registry.REGISTRY_VERSION,
            "main_branch": registry.MAIN_BRANCH,
        },
    }


def build_fixture() -> dict[str, Any]:
    r = random.Random(4242)
    cases = _ontology_cases() + _lifecycle_cases(r) + _role_cases() + _fingerprint_cases(r)
    cases += _matrix_scripts() + _handwritten_scripts() + _random_scripts(r) + _deserialize_cases()
    return {"protocol": "amc-kernel-parity/v1", "snapshots": _snapshots(), "cases": cases}


def _write(fixture: dict[str, Any]) -> None:
    head = {k: v for k, v in fixture.items() if k != "cases"}
    lines = [json.dumps(case, ensure_ascii=True, sort_keys=True) for case in fixture["cases"]]
    body = json.dumps(head, indent=1, ensure_ascii=True, sort_keys=True)[:-2]
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(body + ',\n "cases": [\n' + ",\n".join(lines) + "\n ]\n}\n")


def _load() -> dict[str, Any]:
    if os.environ.get("AMC_REGENERATE_FIXTURES") == "1" or not FIXTURE.exists():
        _write(build_fixture())
    return json.loads(FIXTURE.read_text())


def test_fixture_snapshots_match_python_reference() -> None:
    assert _load()["snapshots"] == json.loads(json.dumps(_snapshots()))


def test_fixture_cases_match_python_reference() -> None:
    fixture = _load()
    assert len(fixture["cases"]) > 5000
    for case in fixture["cases"]:
        expected = {k: v for k, v in case.items() if k in ("ok", "error")}
        actual = json.loads(json.dumps(_capture(DISPATCH[case["call"]], *case["args"])))
        assert actual == expected, (case["call"], case["args"])


def test_fixture_covers_every_case_kind() -> None:
    calls = {case["call"] for case in _load()["cases"]}
    assert calls == set(DISPATCH)
    errors = {case["error"]["type"] for case in _load()["cases"] if "error" in case}
    assert errors == {"OntologyError", "TransitionError", "RoleContractError", "MergeError", "ValueError",
                      "KeyError", "TypeError"}
