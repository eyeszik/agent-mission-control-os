"""Builders for compiled-core.json: the pure building blocks of the compiled planner."""
from __future__ import annotations

import itertools
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from services.langgraph.agency.compiled import (
    autonomy, backchain, change_control, context, decisions, evidence, hashing, learning, measurement, ontology,
    validation,
)
from services.langgraph.agency.kernel.ontology import ArtifactType
from services.langgraph.tests._compiled_fixture_support import AS_OF, HASH, case, f

ARTS = [a.value for a in ArtifactType]
DOMAINS = [d.value for d in ontology.Domain]
ACTIONS = [a.value for a in backchain.ExternalAction]
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _rng(seed: int) -> random.Random:
    return random.Random(seed)


# --------------------------------------------------------------------------
# Python string semantics
# --------------------------------------------------------------------------

def _string_pool() -> list[str]:
    return [
        "", "abc", "ABC", "Hello World", "  padded  ", "\t\n tabs\r\n", "İstanbul", "ǅungla", "ß", "ﬃ", "ŉ", "ς", "ᾈ",
        "K", "Å", "İ", "ı", "ſ", "ǈ", "Ǆ", "ΑΒΓ", "ÀÉÎÕÜ", "straße", "Straße", "\u0085nel\u0085", "\x1ctext\x1f",
        "﻿trim﻿", "​zw​", " ls ", "　ideo　", " nbsp ", " ogham",
        "a b", "a  b\t\tc\n\nd", "😀 emoji 😀", "é combining", "𐐀𐐨 deseret", "𝐀𝐁 math", "Ａｂｃ fullwidth",
        "x\u0000y", "퟿", "￿\U00010000",
    ]


def _random_strings(r: random.Random, n: int) -> list[str]:
    pools = [range(0x20, 0x7F), range(0xC0, 0x250), range(0x370, 0x400), range(0x400, 0x530), range(0x1E00, 0x2000),
             range(0x2000, 0x2070), range(0xFF00, 0xFF5F), range(0x10400, 0x10450), range(0x1D400, 0x1D450)]
    out = []
    for _ in range(n):
        chars = []
        for _ in range(r.randint(1, 12)):
            cp = r.choice(r.choice(pools))
            if cp == 0x3A3:
                cp = 0x3A9
            chars.append(chr(cp))
        out.append("".join(chars))
    return out


def string_cases() -> list[dict[str, Any]]:
    r = _rng(11)
    strings = [s for s in _string_pool() if "Σ" not in s] + _random_strings(r, 150)
    out: list[dict[str, Any]] = []
    for s in strings:
        out.append(case("pyLower", [s], lambda x: x.lower()))
        out.append(case("pyCasefold", [s], lambda x: x.casefold()))
        out.append(case("pyStrip", [s], lambda x: x.strip()))
        out.append(case("collapseWhitespace", [s], _collapse))
    return out


def _collapse(text: str) -> str:
    import re

    return re.sub(r"\s+", " ", text)


def sigma_cases() -> list[dict[str, Any]]:
    """Python lowers U+03A3 by context; the twin refuses it. Each case records Python's answer."""
    words = ["ΑΣ", "ΣΑΣ", "Σ", "ΟΔΥΣΣΕΥΣ", "ΑΣ ΑΣ", "aΣ", "Σa", "ΑΣ.", "Α Σ"]
    out = []
    for w in words:
        c = case("pyLower", [w], lambda x: x.lower())
        c["ts_refuses"] = "ValueError"
        out.append(c)
    return out


def sort_cases() -> list[dict[str, Any]]:
    r = _rng(12)
    pool = ["a", "B", "é", "￿", "\U00010000", "\U0001f600", "", "ab", "a\U00010000", "a￿", "Z", "", "0", "９"]
    out = [case("sortStrings", [pool], lambda x: sorted(x))]
    for _ in range(40):
        items = r.sample(pool, r.randint(2, len(pool)))
        out.append(case("sortStrings", [items], lambda x: sorted(x)))
    return out


def round_cases() -> list[dict[str, Any]]:
    r = _rng(13)
    values = [0.5, 1.5, 2.5, 0.125, 2.675, 1e-7, 1 / 3, 2 / 3, 0.0, 1.0, 0.99999949, 0.0000005, 1234567.8912345, 0.5000005,
              0.0001235, 5e-07, 15e-07, 25e-07, 0.3333335, 0.6666665]
    values += [round(r.uniform(0, 1), r.randint(1, 9)) for _ in range(40)]
    return [case("pyRound", [v, n], lambda x, k: round(x, k)) for v in values for n in (4, 6)]


# --------------------------------------------------------------------------
# Hashing
# --------------------------------------------------------------------------

def _payloads() -> list[Any]:
    return [
        {"a": 1, "b": [1, 2, {"c": None}], "d": True}, [], {}, "plain", 7, None, [3, "x", f(1.0), f(0.1)],
        {"s": {"$set": ["b", "a", "c"]}, "n": {"$set": [3, 1, 2]}}, {"deep": [{"$set": ["x", "y"]}, {"$set": []}]},
        {"é": "ü", "😀": "\U0001f600", "z": " "}, {"big": {"$int": "9007199254740993"}, "neg": {"$int": "-9007199254740993"}},
        {"floats": [f(1e16), f(1e-5), f(123456789.125), f(-0.0), f(2.5e-7)]}, {"1": "a", "10": "b", "2": "c"},
        {"keep": 1, "skip": 2, "also": [f(3.0)]},
    ]


def hashing_cases() -> list[dict[str, Any]]:
    out = []
    for payload in _payloads():
        out.append(case("semanticHash", [payload, []], lambda p, e: hashing.semantic_hash(p, exclude=e)))
    out.append(case("semanticHash", [{"keep": 1, "skip": 2}, ["skip"]], lambda p, e: hashing.semantic_hash(p, exclude=e)))
    out.append(case("semanticHash", [[{"skip": 1}], ["skip"]], lambda p, e: hashing.semantic_hash(p, exclude=e)))
    r = _rng(14)
    for _ in range(30):
        pairs = [[r.choice(["ref:a", "work:b", "accept:c", "é"]), r.choice([HASH, "b" * 64, "x"])] for _ in range(r.randint(0, 6))]
        out.append(case("closureHash", [pairs], lambda p: hashing.closure_hash([tuple(x) for x in p])))
    return out


# --------------------------------------------------------------------------
# Ontology tables, overlays and exception routing
# --------------------------------------------------------------------------

def _ontology_tables() -> dict[str, Any]:
    return {
        "stages": ontology.LIFECYCLE_STAGES,
        "overlays": [{"overlay_id": o.overlay_id, "name": o.name, "stages": list(o.stages),
                      "domains": sorted(d.value for d in o.domains)} for o in ontology.MASTER_BUILDER_OVERLAYS],
        "process_maps": ontology.DOMAIN_PROCESS_MAPS,
        "exceptions": {k: v.value for k, v in ontology.EXCEPTION_CATALOG.items()},
        "artifact_stage": {a.value: s for a, s in ontology.ARTIFACT_STAGE.items()},
        "phases": {a.value: ontology.roleos_phase_for(a) for a in ontology.ARTIFACT_STAGE},
        "consequential": ontology.CONSEQUENTIAL_STAGES,
        "domains": DOMAINS,
        "process_elements": [e.value for e in ontology.ProcessElement],
        "failure_routes": [e.value for e in ontology.FailureRoute],
    }


def ontology_cases() -> list[dict[str, Any]]:
    r = _rng(15)
    out = [case("ontologyTables", [], _ontology_tables)]
    subsets = [[d] for d in DOMAINS] + [list(p) for p in itertools.combinations(DOMAINS, 2)]
    subsets += [r.sample(DOMAINS, r.randint(3, 9)) for _ in range(120)] + [[], ["BRAND", "BRAND"]]
    for subset in subsets:
        for live in (False, True):
            out.append(case("selectOverlays", [subset, live], lambda d, lv: list(ontology.select_overlays(d, live_service=lv))))
    for bad in (["NOPE"], ["BRAND", "web"], [""], [3]):
        out.append(case("selectOverlays", [bad, False], lambda d, lv: ontology.select_overlays(d, live_service=lv)))
    for kind in [*ontology.EXCEPTION_CATALOG, "never-seen", "", "Tool_Failure"]:
        out.append(case("routeException", [kind], lambda k: ontology.route_exception(k)))
    return out


# --------------------------------------------------------------------------
# Validation profiles, obligations, evaluation and release blockers
# --------------------------------------------------------------------------

def _validation_tables() -> dict[str, Any]:
    return {
        "profiles": [{"profile_id": p.profile_id, "stage": p.stage.value, "skill": p.validator_skill,
                      "department": p.validator_department, "volatile_keys": list(p.volatile_keys)}
                     for p in validation.VALIDATION_PROFILES],
        "base": [s.value for s in validation.BASE_OBLIGATIONS],
        "stages": [s.value for s in validation.ValidationStage],
        "max_repair_attempts": validation.MAX_REPAIR_ATTEMPTS,
    }


def _domain_sets() -> list[list[str]]:
    return [[], ["BRAND"], ["MOBILE_APP"], ["VIDEO", "CONTENT"], ["WEB", "SOFTWARE"], ["MOTION", "MOBILE_APP"], ["UX_UI", "WEB"]]


def obligation_cases() -> list[dict[str, Any]]:
    out = [case("validationTables", [], _validation_tables)]
    for art in ARTS:
        for domains in _domain_sets():
            for ext, live in itertools.product((False, True), repeat=2):
                out.append(case("obligationsFor", [art, domains, ext, live],
                                lambda a, d, e, lv: list(validation.obligations_for(ArtifactType(a), d, external_action=e, live_service=lv))))
    out.append(case("obligationsFor", ["not_a_type", [], False, False],
                    lambda a, d, e, lv: validation.obligations_for(ArtifactType(a), d, external_action=e, live_service=lv)))
    pools = [validation.obligations_for(ArtifactType(a), ["MOBILE_APP", "WEB"], external_action=True, live_service=True) for a in ARTS]
    for obligations in pools:
        out.append(case("volatileKeysFor", [list(obligations)], lambda o: list(validation.volatile_keys_for(o))))
    out.append(case("volatileKeysFor", [["PROFILE:NOPE"]], lambda o: validation.volatile_keys_for(o)))
    return out


def route_cases() -> list[dict[str, Any]]:
    obligations = ["PROVENANCE", "FRESHNESS", "PROFILE:GROUNDING", "EVIDENCE_FLOOR:2", "SECURITY", "PROFILE:SECURITY", "AUTHORITY",
                   "APPROVAL_SCOPE", "SCHEMA", "PROFILE:BRAND_COHESION", "COMPLETION_PROOF"]
    node_sets = [[], ["work:market_analysis"], ["work:research_brief"], ["work:app_build_spec", "work:copy_variant"],
                 ["work:implementation_plan"], ["work:copy_variant", "work:market_analysis", "work:research_brief"]]
    out = []
    for ob, node, nodes in itertools.product(obligations, ["validate:copy_variant", "validate:app_build_spec", "plain", "ref:x"], node_sets):
        out.append(case("routeFailure", [ob, node, nodes], lambda o, n, g: validation.route_failure(o, n, {k: 1 for k in g})))
    return out


def _result(node: str, ob: str, status: str, ref: str, attempt: int, fp: str | None) -> dict[str, Any]:
    return {"node_id": node, "obligation": ob, "status": status, "validator_ref": ref, "attempt": attempt,
            "failure_fingerprint": fp}


def evaluation_cases() -> list[dict[str, Any]]:
    r = _rng(16)
    out = []
    obligations = ["SCHEMA", "PROVENANCE", "PROFILE:GROUNDING", "EVIDENCE_FLOOR:1", "SECURITY", "AUTHORITY", "COMPLETION_PROOF"]
    for _ in range(70):
        node = r.choice(["validate:market_analysis", "validate:app_build_spec"])
        results = []
        for ob in r.sample(obligations, r.randint(0, len(obligations))):
            for attempt in range(1, r.randint(1, 5)):
                results.append(_result(r.choice([node, node, "validate:other"]), ob, r.choice(["PASS", "FAIL", "FAIL"]),
                                       r.choice(["creator", "rev-1", "rev-2"]), attempt, r.choice([None, "fp1", "fp1", "fp2"])))
        r.shuffle(results)
        args = [node, r.sample(obligations, r.randint(1, len(obligations))), results, r.choice(["creator", "rev-1"]),
                r.choice(["low", "medium", "high", "critical", "weird"]),
                r.sample(["work:market_analysis", "work:research_brief", "work:app_build_spec", "x"], r.randint(0, 4))]
        out.append(case("evaluateValidation", args, lambda n, o, res, c, risk, g: validation.evaluate_validation(
            n, o, [validation.ValidationResult.model_validate(x) for x in res], creator_ref=c, risk_level=risk,
            graph_nodes={k: 1 for k in g})))
    bad = [[{"node_id": "n", "obligation": "o", "status": "MAYBE", "validator_ref": "v"}],
           [{"node_id": "n", "obligation": "o", "status": "PASS", "validator_ref": "v", "extra": 1}],
           [{"node_id": "n", "obligation": "o", "status": "PASS"}],
           [{"node_id": "n", "obligation": "o", "status": "PASS", "validator_ref": "v", "attempt": "2"}]]
    for results in bad:
        out.append(case("evaluateValidation", ["n", ["o"], results, "c", "low", []], lambda n, o, res, c, risk, g: validation.evaluate_validation(
            n, o, [validation.ValidationResult.model_validate(x) for x in res], creator_ref=c, risk_level=risk, graph_nodes={})))
    return out


def release_cases() -> list[dict[str, Any]]:
    out = []
    modes = [None, "FALLBACK_DEGRADED", "PROVIDER_SUCCESS", "other"]
    decisions_ = [None, "approve", "reject", "pending"]
    for mode, dec, brand, ext, spend, unmet in itertools.product(
            modes, decisions_, [None, True, False], (False, True), (False, True), [[], ["a"], ["b", "a"]]):
        facts = {"generation_mode": mode, "approval_decision": dec, "brand_safety_passed": brand, "external_side_effect": ext,
                 "spend_authorized": spend, "unmet_hard_dependencies": unmet}
        out.append(case("releaseBlockers", [facts], lambda x: validation.release_blockers(**x)))
    return out


# --------------------------------------------------------------------------
# Autonomy
# --------------------------------------------------------------------------

def _suitability(r: random.Random) -> dict[str, Any]:
    lv = ["low", "medium", "high"]
    return {
        "determinism": r.choice(lv), "ambiguity": r.choice(lv), "consequence": r.choice(lv), "reversible": r.random() < 0.7,
        "data_sensitivity": r.choice(lv), "creative_judgment": r.choice(lv), "factual_verifiability": r.choice(lv),
        "tool_reliability": r.choice(lv), "evaluation_history": r.choice([0, 0, 1, 5, 500]),
        "legal_public_financial_or_client_binding": r.random() < 0.2, "rights_privacy_security_uncertain": r.random() < 0.15,
        "evidence_sufficient": r.random() < 0.85, "performance_score": r.choice([None, 0.5, 1, 0.0]),
        "governance_approval_ref": r.choice([None, None, "gov:1"]), "proven_narrow_scope": r.random() < 0.4,
    }


def autonomy_cases() -> list[dict[str, Any]]:
    r = _rng(17)
    out = []
    for _ in range(350):
        out.append(case("classify", [_suitability(r)], lambda t: autonomy.classify(autonomy.TaskSuitability.model_validate(t))))
    bad = [{"determinism": "low"}, {**_suitability(r), "extra": 1}, {**_suitability(r), "determinism": "extreme"},
           {**_suitability(r), "evaluation_history": -1}, {**_suitability(r), "reversible": "yes"}]
    for item in bad:
        out.append(case("classify", [item], lambda t: autonomy.classify(autonomy.TaskSuitability.model_validate(t))))
    kinds = [*ARTS, None, "film_master"]
    for art, eff, evi, rights in itertools.product(kinds, ["PURE", "DRAFT", "REVERSIBLE_WRITE", "IRREVERSIBLE_WRITE"],
                                                   (True, False), (True, False)):
        args = [{"artifact_type": art, "side_effect_class": eff, "evidence_sufficient": evi, "rights_uncertain": rights}]
        out.append(case("suitabilityForNode", args, lambda d: autonomy.suitability_for_node(**d)))
    return out


# --------------------------------------------------------------------------
# Evidence: triangulation, rule promotion, volatile firewall, instants
# --------------------------------------------------------------------------

def _candidate(r: random.Random, idx: int) -> dict[str, Any]:
    c: dict[str, Any] = {"id": f"rule.{idx}", "statement": "s", "source_class": r.choice([s.value for s in evidence.SourceClass])}
    optional = {
        "source_refs": r.choice([[], ["spec:1"], ["spec:1", "repo:x"]]), "jurisdiction": r.choice([None, "EU", "GB"]),
        "freshness": r.choice([None, "2026-01-01"]), "recheck_at": r.choice([None, "2026-01-01", "2027-01-01", "2026-10-29"]),
        "organization_specific": r.random() < 0.3, "volatility": r.choice([v.value for v in evidence.Volatility]),
        "evidence_strength": r.choice([v.value for v in evidence.EvidenceStrength]),
        "conflicts": r.choice([[], [], ["c1"]]), "target_layer": r.choice([v.value for v in evidence.TargetLayer]),
        "status": r.choice(["SOURCE_CLAIM"] * 6 + [v.value for v in evidence.RuleStatus]),
        "runtime_ref": r.choice([None, "x.py"]), "domain": r.choice([[], ["BRAND"]]),
    }
    for key, value in optional.items():
        if r.random() < 0.85:
            c[key] = value
    return c


def _promotion_context(r: random.Random) -> dict[str, Any]:
    ctx: dict[str, Any] = {"as_of": r.choice(["2026-10-29", "2026-01-01", "2028-01-01"])}
    for key, value in {"applicability_verified": r.random() < 0.7, "repository_contract_compatible": r.choice([None, True, False]),
                       "org_policy_approval_ref": r.choice([None, "approval:1"]),
                       "jurisdictions_in_scope": r.choice([[], ["EU"], ["GB", "EU"]])}.items():
        if r.random() < 0.9:
            ctx[key] = value
    return ctx


def promotion_cases() -> list[dict[str, Any]]:
    r = _rng(18)
    out = []
    for i in range(250):
        out.append(case("evaluatePromotion", [_candidate(r, i), _promotion_context(r)],
                        lambda c, x: evidence.evaluate_promotion(evidence.RuleCandidate.model_validate(c),
                                                                 evidence.PromotionContext.model_validate(x))))
    for item in evidence.SPEC_RULE_CANDIDATES:
        out.append(case("evaluatePromotion", [item.model_dump(mode="json"), {"as_of": AS_OF, "applicability_verified": True,
                                                                           "repository_contract_compatible": True}],
                        lambda c, x: evidence.evaluate_promotion(evidence.RuleCandidate.model_validate(c),
                                                                 evidence.PromotionContext.model_validate(x))))
    for as_of in ("2026-10-29", "2030-01-01", "2020-01-01"):
        out.append(case("ruleLedger", [as_of], lambda a: evidence.rule_ledger(a)))
    out.append(case("evaluatePromotion", [{"id": "x"}, {"as_of": AS_OF}], lambda c, x: evidence.evaluate_promotion(
        evidence.RuleCandidate.model_validate(c), evidence.PromotionContext.model_validate(x))))
    out.append(case("evaluatePromotion", [{"id": "x", "statement": "s", "source_class": "NOPE"}, {"as_of": AS_OF}],
                    lambda c, x: evidence.evaluate_promotion(evidence.RuleCandidate.model_validate(c),
                                                             evidence.PromotionContext.model_validate(x))))
    return out


def triangulation_cases() -> list[dict[str, Any]]:
    r = _rng(19)
    classes = [s.value for s in evidence.SourceClass]
    out = []
    for _ in range(80):
        sources = [{"id": f"s{i}", "title": "t", "canonical_ref": "r", "source_type": r.choice(classes), "publisher": "p"}
                   for i in range(r.randint(0, 5))]
        refs = [f"s{r.randint(0, 6)}" for _ in range(r.randint(0, 4))]
        claim = {"id": "c", "statement": "x", "label": r.choice(["FACT", "GAP", "CONFLICT"]), "source_refs": refs}
        out.append(case("triangulationDeficits", [claim, sources], lambda c, s: evidence.triangulation_deficits(
            evidence.Claim.model_validate(c), [evidence.SourceRecord.model_validate(x) for x in s])))
    return out


# Spellings the twin's date parser must reproduce exactly (Python-valid and inside the documented subset).
def _supported_instants(r: random.Random) -> list[str]:
    dates = ["2026-10-29", "20261029", "2026-W44-4", "2024-02-29", "0001-01-01", "9999-12-31", "2026-12-31", "2000-02-29"]
    seps = ["T", " ", "t", "x", "_"]
    times = ["10", "10:00", "1000", "10:00:00", "100000", "10:00:00.5", "10:00:00,5", "10:00:00.1234567", "23:59:59.999999",
             "00:00:00", "10:00:00.000000001"]
    zones = ["", "Z", "+00:00", "-05:30", "+0530", "+05", "-0000", "+05:30:15", "-00:00:30", "+23:59"]
    out = [f"{d}{s}{t}{z}" for d in dates for s in ("T",) for t in times[:6] for z in zones[:5]]
    out += [f"{r.choice(dates)}{r.choice(seps)}{r.choice(times)}{r.choice(zones)}" for _ in range(400)]
    return sorted(set(out)) + ["2026-10-29", "2026-W44-4", "2026-10-29T10:00:00Z"]


def _unsupported_or_invalid_instants() -> list[str]:
    return ["2026-02-30", "2026-13-01", "0000-01-01", "2026-1-1", "２０２６-01-01", "", " ", "x", "2026-10-29T", "2026-10-29T10:0",
            "2026-10-29T24:00:00+00:00", "2026-10-29T10:60:00+00:00", "2026-10-29T10:00:60+00:00", "2026-10-29T10:00:00+24:00",
            "2026-10-29T10:00:00Z+00:00", "2026-10-29T10:00:00z", "2026-10-29T10:00:00", "2026-10-29T10:00", "20261029T100000",
            "2026-W53-1", "2026-W44-8", "0001-01-01T00:00:00+01:00", "9999-12-31T23:59:59-01:00", "2026-10-29T10:00:00+5",
            "2026-10-29T10:00:00+05:3", "2026-10-29 10:00:00 +00:00", "+2026-10-29", "2026/10/29", "2026-10-29T10:00:00.Z",
            "2026-10-29T10:00:00+05:30:15.5", "2026-W44", "2026W444", "2026W44", "20261029", "2026-10-29T10:00:00,Z"]


def instant_cases() -> list[dict[str, Any]]:
    r = _rng(20)
    out = []
    for text in _supported_instants(r) + _unsupported_or_invalid_instants():
        c = case("constraintInstant", [text], lambda v: (evidence._constraint_instant(v) - EPOCH) // timedelta(microseconds=1))
        if "ok" in c:
            c["ok"] = {"$int": str(c["ok"])}
        else:
            c["loose"] = True
        out.append(c)
    return out


def _constraint(r: random.Random) -> dict[str, Any]:
    stamps = ["2026-09-26", "2026-10-29", "2026-10-30", "2026-09-26T10:00:00Z", "2026-10-29T12:00:00+02:00",
              "2026-10-29T00:00:00+00:00", "2027-01-01", "2026-10-28T23:59:59Z", "2026-10-29T10:00:00", "garbage"]
    c: dict[str, Any] = {"key": r.choice(["app_store.requirements", "security.testing_standard", "accessibility.standard", "x"])}
    optional = {
        "source_ref": r.choice(["official:docs", "official", "", "  ", None]),
        "retrieved_at": r.choice(stamps + [None]), "effective_date": r.choice(stamps + [None, None]),
        "value": r.choice(["v", " v ", "", "   ", None]),
        "verification_status": r.choice(["VERIFIED", "VERIFIED", "VERIFIED", "UNVERIFIED", "EXPIRED"]),
        "expires_or_recheck_at": r.choice(stamps + [None, ""]),
    }
    for key, value in optional.items():
        if r.random() < 0.92:
            c[key] = value
    return c


def volatile_cases() -> list[dict[str, Any]]:
    r = _rng(21)
    out = []
    for _ in range(350):
        out.append(case("volatileStatus", [_constraint(r), r.choice([AS_OF, "2026-10-29T10:00:00Z", "2026-10-29T12:00:00+02:00"])],
                        lambda c, a: evidence.volatile_status(evidence.VolatileConstraint.model_validate(c), a)))
    for _ in range(30):
        constraints = [_constraint(r) for _ in range(r.randint(0, 4))]
        out.append(case("volatileReleaseBlockers", [constraints, AS_OF], lambda cs, a: evidence.volatile_release_blockers(
            [evidence.VolatileConstraint.model_validate(c) for c in cs], a)))
    return out


# --------------------------------------------------------------------------
# Context: genome and capsules
# --------------------------------------------------------------------------

def _assertion(r: random.Random) -> dict[str, Any]:
    a: dict[str, Any] = {"key": r.choice(["audience", "tone", "market", "name", "budget"]),
                         "domain": r.choice(["BRAND", "CONTENT", "WEB", "FILM"]),
                         "value_or_ref": r.choice(["founders", "warm", "eu", "ref:1", "x"])}
    optional = {
        "source_refs": r.choice([[], ["brief:1"], ["a", "b"]]), "epistemic_status": r.choice([e.value for e in context.GenomeEpistemic]),
        "confidence": r.choice([None, 0.5, 1, 0.25]), "freshness": r.choice([None, "2026-12-01"]),
        "sensitivity": r.choice(["internal", "public"]), "owner_ref": r.choice([None, "h:1"]),
        "decision_refs": r.choice([[], ["d:1"]]), "artifact_refs": r.choice([[], ["accept:x"]]),
    }
    for key, value in optional.items():
        if r.random() < 0.8:
            a[key] = value
    return a


def context_cases() -> list[dict[str, Any]]:
    r = _rng(22)
    out = []
    for _ in range(40):
        assertions = [_assertion(r) for _ in range(r.randint(0, 7))]
        out.append(case("projectGenome", [assertions], lambda a: context.project_genome(
            [context.GenomeAssertion.model_validate(x) for x in a])))
        capsule_args = [assertions, {"objective": "obj", "acceptance_criteria": r.sample(["b", "a", "c"], r.randint(0, 3)),
                                     "domains": r.sample(["BRAND", "WEB", "CONTENT"], r.randint(0, 3)),
                                     "genome_keys": r.sample(["tone", "market"], r.randint(0, 2)),
                                     "approved_decision_refs": ["positioning@abc"], "artifact_refs": ["ref:x", "accept:y"],
                                     "dependency_hashes": {"ref:x": HASH, "accept:y": "b" * 64},
                                     "hard_constraints": ["c2", "c1"], "authority_refs": ["auth:1"],
                                     "tool_permissions": ["langgraph.workflow"]}]
        out.append(case("projectCapsule", capsule_args, lambda a, kw: context.project_capsule(
            context.project_genome([context.GenomeAssertion.model_validate(x) for x in a]), **kw)))
    for current in ({"ref:x": HASH, "accept:y": "b" * 64}, {"ref:x": HASH}, {"ref:x": "c" * 64, "accept:y": "b" * 64}, {}):
        out.append(case("capsuleFreshness", [current], lambda cur: context.capsule_freshness(
            context.project_capsule(context.project_genome([]), objective="o", acceptance_criteria=[], domains=[],
                                    dependency_hashes={"ref:x": HASH, "accept:y": "b" * 64}), cur)))
    for sets in ([], [["a", "b"]], [["a", "b"], ["b", "c"]], [["a"], ["b"]], [[], ["a"]]):
        out.append(case("hoistSharedRefs", [sets], lambda s: list(context.hoist_shared_refs(
            [context.ContextCapsule(objective="o", acceptance_criteria=(), relevant_genome_refs=tuple(x), approved_decision_refs=(),
                                    artifact_refs=(), dependency_refs=(), hard_constraints=(), authority_refs=(), tool_permissions=(),
                                    open_questions=(), freshness_deadlines=(), dependency_hashes=(), capsule_hash="h") for x in s]))))
    return out


# --------------------------------------------------------------------------
# Backchain graphs
# --------------------------------------------------------------------------

def spec(idx: Any, contract: str, **kw: Any) -> dict[str, Any]:
    return {"id": f"d{idx}", "requested_outcome": f"Outcome {idx}", "output_contract": contract,
            "acceptance_criteria": kw.pop("acceptance_criteria", ["on-brief"]), **kw}


def random_spec(r: random.Random, idx: int) -> dict[str, Any]:
    contract = r.choice(ARTS) if r.random() < 0.92 else r.choice(["film_master", "broadcast_master", "x"])
    item = spec(idx, contract, acceptance_criteria=r.sample(["on-brief", "brand-safe", "complete"], r.randint(1, 3)))
    optional = {
        "constraints": r.sample(["no-jargon", "short"], r.randint(0, 2)), "priority": r.choice([None, 1, 3]),
        "domains": r.sample(DOMAINS, r.randint(0, 3)),
        "external_action": r.choice([None] * 5 + ACTIONS), "live_service": r.random() < 0.2,
    }
    for key, value in optional.items():
        if r.random() < 0.8:
            item[key] = value
    return item


def random_existing(r: random.Random) -> dict[str, str]:
    return {a: r.choice([HASH, "b" * 64, "c" * 40]) for a in r.sample(ARTS, r.randint(0, 8))}


def random_evidence(r: random.Random) -> list[dict[str, Any]]:
    out = []
    for art in r.sample(ARTS, r.randint(0, 8)):
        for i in range(r.randint(0, 3)):
            out.append({"ref": f"ev:{art}:{i}", "supports": [art], "verified": r.random() < 0.8})
    return out


def _accepted_kinds(r: random.Random) -> dict[str, str]:
    return {k.value: r.choice([HASH, "d" * 64]) for k in r.sample(list(backchain.DecisionKind), r.randint(0, 4))}


def _compile(deliverables: list[dict[str, Any]], existing: dict[str, str], accepted: dict[str, str], ev: list[dict[str, Any]]):
    return backchain.compile_backchain(
        [backchain.DeliverableSpec.model_validate(d) for d in deliverables], existing_artifacts=existing,
        accepted_decisions=accepted, evidence=[backchain.EvidenceItem.model_validate(e) for e in ev])


def _graph_extras(g: Any) -> dict[str, Any]:
    return {
        "unresolved": backchain.unresolved_leaves(g),
        "work_nodes": [n.id for n in g.work_nodes()],
        "ancestors": {n: sorted(g.ancestors(n)) for n in g.nodes},
        "descendants": {n: sorted(g.descendants([n])) for n in g.nodes},
        "dependents": {n: sorted(s) for n, s in g.dependents().items()},
    }


def backchain_full(deliverables: Any, existing: Any, accepted: Any, ev: Any) -> dict[str, Any]:
    g = _compile(deliverables, existing, accepted, ev)
    return {"graph": g, **_graph_extras(g)}


def backchain_digest(deliverables: Any, existing: Any, accepted: Any, ev: Any) -> dict[str, Any]:
    g = _compile(deliverables, existing, accepted, ev)
    return {
        "graph_hash": g.graph_hash, "roots": g.roots, "topological_order": g.topological_order, "eliminated": g.eliminated,
        "redundant_candidates": g.redundant_candidates, "dedup_hits": g.dedup_hits,
        "node_hashes": {n: node.semantic_hash for n, node in g.nodes.items()},
        "node_status": {n: [node.status.value, node.resolution.value] for n, node in g.nodes.items()},
        "purposes": hashing.semantic_hash({n: node.purpose for n, node in g.nodes.items()}),
        "unresolved": backchain.unresolved_leaves(g), "work_nodes": [n.id for n in g.work_nodes()],
        "closure": hashing.semantic_hash({n: sorted(g.ancestors(n)) for n in g.nodes}),
        "descendants": hashing.semantic_hash({n: sorted(g.descendants([n])) for n in g.nodes}),
    }


def handwritten_graphs() -> list[list[Any]]:
    campaign = spec("campaign", "campaign_package", domains=["BRAND", "CONTENT"], acceptance_criteria=["on-brief", "brand-safe"])
    guidelines = spec("guidelines", "brand_guidelines_doc", domains=["BRAND"])
    copy = spec("copy", "copy_variant", domains=["CONTENT"])
    evidence_all = [{"ref": f"ev:{a}:{i}", "supports": [a], "verified": True}
                    for a in ("research_brief", "market_analysis", "positioning_statement", "brand_core", "brand_platform",
                              "identity_guidelines", "product_spec", "measurement_plan") for i in range(3)]
    return [
        [[campaign], {}, {}, []],
        [[campaign], {}, {}, evidence_all],
        [[campaign, guidelines], {}, {k.value: HASH for k in backchain.DecisionKind}, evidence_all],
        [[copy], {"brand_platform": HASH, "creative_concept": "b" * 64}, {}, []],
        [[spec("app", "app_build_spec", domains=["MOBILE_APP"], external_action="deploy")],
         {"design_system_spec": HASH, "product_spec": HASH, "campaign_package": HASH, "qa_report": HASH}, {}, []],
        [[spec("launch", "campaign_package", external_action="publish")], {"campaign_package": HASH, "qa_report": HASH, "release_record": HASH}, {}, []],
        [[spec("spend", "media_plan", external_action="media_spend")], {}, {}, evidence_all],
        [[spec("master", "film_master")], {}, {}, []],
        [[spec("a", "copy_variant"), spec("a", "copy_variant")], {}, {}, []],
        [[], {}, {}, []],
        [[spec("x", "research_brief")], {}, {}, []],
        [[spec("m", "measurement_plan", live_service=True, domains=["WEB", "ANALYTICS"])], {}, {}, evidence_all],
        [[spec("pay", "release_record", external_action="pay")], {}, {}, []],
        [[spec("sm", "campaign_package", external_action="media_spend"), spec("pub", "campaign_package", external_action="publish")], {}, {}, evidence_all],
        [[{"id": "bad", "requested_outcome": "o", "output_contract": "copy_variant", "acceptance_criteria": []}], {}, {}, []],
        [[{"id": "bad", "requested_outcome": "o", "output_contract": "copy_variant", "acceptance_criteria": ["a"], "external_action": "teleport"}], {}, {}, []],
    ]


def backchain_cases() -> list[dict[str, Any]]:
    out = []
    for i, args in enumerate(handwritten_graphs()):
        out.append(case("compileBackchain" if i < 5 or i >= 8 else "compileBackchainDigest", args, backchain_full if i < 5 or i >= 8 else backchain_digest))
    r = _rng(23)
    for _ in range(2):
        specs = [random_spec(r, i) for i in range(r.randint(1, 4))]
        out.append(case("compileBackchain", [specs, random_existing(r), _accepted_kinds(r), random_evidence(r)], backchain_full))
    for _ in range(55):
        specs = [random_spec(r, i) for i in range(r.randint(1, 5))]
        out.append(case("compileBackchainDigest", [specs, random_existing(r), _accepted_kinds(r), random_evidence(r)], backchain_digest))
    return out


# --------------------------------------------------------------------------
# Decision spine and change control (on a fixed campaign graph)
# --------------------------------------------------------------------------

CAMPAIGN = [spec("campaign", "campaign_package", domains=["BRAND", "CONTENT"], acceptance_criteria=["on-brief", "brand-safe"])]
CAMPAIGN_EVIDENCE = [{"ref": f"ev:{a}:{i}", "supports": [a], "verified": True}
                     for a in ("research_brief", "market_analysis", "positioning_statement", "brand_core", "brand_platform",
                               "identity_guidelines") for i in range(3)]


def _decision(kind: str, **kw: Any) -> dict[str, Any]:
    return {"id": f"dec-{kind}", "kind": kind, "question": f"Which {kind}?", "alternatives": ["A", "B"], "owner": "agent:strategy",
            **kw}


def _campaign_graph(accepted: dict[str, str] | None = None):
    return _compile(CAMPAIGN, {}, accepted or {}, CAMPAIGN_EVIDENCE)


def decision_script(initial: list[dict[str, Any]], steps: list[list[Any]]) -> list[dict[str, Any]]:
    graph = _campaign_graph()
    spine = decisions.DecisionSpine([decisions.DecisionNode.model_validate(d) for d in initial])
    results = []
    for step in steps:
        op, rest = step[0], step[1:]
        try:
            if op == "propose":
                value: Any = spine.propose(decisions.DecisionNode.model_validate(rest[0]))
            elif op == "accept":
                value = spine.accept(backchain.DecisionKind(rest[0]), selected_option=rest[1], approver_ref=rest[2])
            elif op == "revise":
                value = list(spine.revise(backchain.DecisionKind(rest[0]), graph, **rest[1]))
            elif op == "current":
                value = spine.current(backchain.DecisionKind(rest[0]))
            elif op == "effective":
                value = spine.effective_status(spine.current(backchain.DecisionKind(rest[0])))
            elif op == "accepted":
                value = spine.accepted_by_kind()
            elif op == "versions":
                value = [[v.model_dump(mode="json"), v.decision_hash] for v in spine.versions]
            else:
                value = decisions.uncertainty_priority(graph)
            results.append({"ok": plain_value(value)})
        except Exception as exc:  # noqa: BLE001 - recorded
            from services.langgraph.tests._compiled_fixture_support import error_record

            results.append({"error": error_record(exc)})
    return results


def plain_value(value: Any) -> Any:
    from services.langgraph.tests._compiled_fixture_support import plain

    return plain(value)


def decision_cases() -> list[dict[str, Any]]:
    kinds = ["positioning", "brand_platform", "creative_direction"]
    scripts: list[tuple[list[Any], list[Any]]] = [
        ([], [["propose", _decision("positioning")], ["current", "positioning"], ["accepted"],
              ["accept", "positioning", "A", "human:cd"], ["accepted"], ["accept", "positioning", "A", "human:cd"],
              ["revise", "positioning", {"alternatives": ["A", "B", "C"], "question": "Revised?"}], ["uncertainty"],
              ["versions"], ["effective", "positioning"]]),
        ([], [["propose", _decision("positioning", status="ACCEPTED")], ["propose", _decision("positioning")],
              ["propose", _decision("positioning")], ["propose", _decision("positioning")]]),
        ([], [["accept", "scope", "A", "h"], ["revise", "scope", {}], ["current", "scope"]]),
        ([_decision("strategy", required_approver="human:cd")],
         [["accept", "strategy", "Z", "human:cd"], ["accept", "strategy", "A", ""], ["accept", "strategy", "A", "agent:strategy"],
          ["accept", "strategy", "A", "human:other"], ["accept", "strategy", "A", "human:cd"], ["revise", "strategy", {"version": 9}],
          ["revise", "strategy", {"id": "x", "status": "ACCEPTED"}], ["revise", "strategy", {"zzz": 1}],
          ["revise", "strategy", {"owner": "agent:other", "assumptions": ["a1"]}], ["accepted"], ["versions"]]),
    ]
    for kind in kinds:
        scripts[0][1].extend([["propose", _decision(kind)], ["accept", kind, "B", "human:cd"]])
    scripts.append(([], [["propose", _decision(k)] for k in kinds] + [["accept", k, "A", "human:cd"] for k in kinds]
                    + [["revise", k, {"question": f"Re-{k}?"}] for k in kinds] + [["accepted"], ["uncertainty"]]))
    return [case("decisionScript", [initial, steps], decision_script) for initial, steps in scripts]


def scope_args(approval_id: str, subjects: dict[str, str], **kw: Any) -> dict[str, Any]:
    return {"approval_id": approval_id, "subjects": subjects, "artifact_hashes": kw.pop("artifact_hashes", {}),
            "policy_version": kw.pop("policy_version", "amc-approval/v1"), "reviewer_ref": kw.pop("reviewer_ref", "human:client"),
            "decision": kw.pop("decision", "approve"), **kw}


def change_script(ops: list[list[Any]]) -> list[dict[str, Any]]:
    from services.langgraph.tests._compiled_fixture_support import error_record

    graph = _campaign_graph({"positioning": HASH, "brand_platform": HASH, "creative_direction": HASH})
    hashes = {n: node.semantic_hash for n, node in graph.nodes.items()}
    results = []
    scopes: list[Any] = []
    for op in ops:
        name, rest = op[0], op[1:]
        try:
            if name == "buildScope":
                spec_ = dict(rest[0])
                subjects = {k: hashes[k] if v == "$node" else v for k, v in spec_.pop("subjects").items()}
                scope = change_control.build_scope(graph, subjects=subjects, **spec_)
                scopes.append(scope)
                value: Any = [scope, scope.scope_hash]
            elif name == "evaluate":
                scope = scopes[rest[0]]
                value = change_control.evaluate_scope(
                    scope, current_subject_hashes=hashes if rest[1] == "$nodes" else rest[1],
                    current_closure_hash=scope.dependency_closure_hash if rest[2] == "$same" else rest[2],
                    current_policy_version=rest[3], preservation_permitted=rest[4], high_risk_change=rest[5])
            elif name == "closure":
                value = change_control.dependency_closure_hash(graph, rest[0], rest[1])
            elif name == "blast":
                changes = {ref: (old if old != "$node" else hashes[ref], new) for ref, (old, new) in rest[0].items()}
                value = change_control.compute_blast_radius(graph, changes, approvals=[scopes[i] for i in rest[1]])
            elif name == "dna":
                value = change_control.artifact_dna(graph, rest[0], evidence_refs=rest[1], approvals=[scopes[i] for i in rest[2]])
            else:
                value = sorted(graph.nodes)
            results.append({"ok": plain_value(value)})
        except Exception as exc:  # noqa: BLE001 - recorded
            results.append({"error": error_record(exc)})
    return results


def change_cases() -> list[dict[str, Any]]:
    root = "deliverable:dcampaign"
    scripts = [
        [["nodes"], ["buildScope", scope_args("a1", {root: "$node"})],
         ["buildScope", scope_args("a2", {"accept:market_analysis": "$node"}, reviewer_ref="human:lead")],
         ["buildScope", scope_args("a3", {root: "$node"}, decision="reject")],
         ["buildScope", scope_args("a4", {root: "$node"}, reviewer_ref=None)],
         ["buildScope", scope_args("a5", {"unknown:ref": HASH}, preview_hash="p", timestamp="2026-01-01T00:00:00Z")],
         ["evaluate", 0, "$nodes", "$same", "amc-approval/v1", True, False],
         ["evaluate", 0, "$nodes", "$same", "amc-approval/v2", True, False],
         ["evaluate", 0, "$nodes", "$same", "amc-approval/v2", True, True],
         ["evaluate", 0, "$nodes", "other", "amc-approval/v1", True, False],
         ["evaluate", 0, {}, "$same", "amc-approval/v1", True, False],
         ["evaluate", 0, "$nodes", "$same", "amc-approval/v1", False, True],
         ["evaluate", 2, "$nodes", "$same", "amc-approval/v1", True, False],
         ["evaluate", 3, "$nodes", "$same", "amc-approval/v1", True, False],
         ["closure", [root], {}], ["closure", [root], {"work:copy_variant": HASH}], ["closure", ["nope"], {}],
         ["closure", ["accept:market_analysis", root], {"accept:brand_platform": "z"}],
         ["blast", {"decision:brand_platform": ["$node", "n" * 64]}, [0, 1]],
         ["blast", {"decision:brand_platform": ["$node", "$node"]}, [0, 1]],
         ["blast", {"work:research_brief": ["$node", "q" * 64], "nope": ["a", "b"]}, [0, 1, 4]],
         ["blast", {"external:x": ["a", "b"]}, []],
         ["dna", root, {"copy_variant": ["ev:1", "ev:2"], "brand_platform": ["ev:3"]}, [0, 1]],
         ["dna", "work:copy_variant", {}, [1]], ["dna", "missing", {}, []]],
    ]
    return [case("changeScript", [ops], change_script) for ops in scripts]


# --------------------------------------------------------------------------
# Learning ledger and measurement
# --------------------------------------------------------------------------

def _signal(idx: int, **kw: Any) -> dict[str, Any]:
    return {"id": f"sig-{idx}", "tenant_scope": kw.pop("tenant", "tenant-a"), "run_refs": ["run-1"], "observation": "obs",
            "evidence_refs": kw.pop("evidence_refs", ["shadow:1"]), "target_heuristic": kw.pop("target", "routing_ranking"), **kw}


def ledger_script(steps: list[list[Any]]) -> list[dict[str, Any]]:
    from services.langgraph.tests._compiled_fixture_support import error_record

    ledger = learning.LearningLedger()
    results: list[dict[str, Any]] = []
    sealed: list[Any] = []
    for step in steps:
        op, rest = step[0], step[1:]
        try:
            if op == "append":
                signal = ledger.append(learning.LearningSignal.model_validate(rest[0]))
                sealed.append(signal)
                value: Any = signal
            elif op == "entries":
                value = ledger.entries(rest[0])
            elif op == "verify":
                value = ledger.verify_chain()
            elif op == "proposals":
                value = ledger.proposals
            elif op == "tamper":
                # replay a ledger whose entry `rest[0]` has been altered, then one that is intact
                entries = [s.model_copy(update=({"observation": "tampered"} if i == rest[0] else {})) for i, s in enumerate(sealed)]
                value = [e.hash for e in learning.LearningLedger.replay(entries).entries(entries[0].tenant_scope)]
            else:
                value = [e.hash for e in learning.LearningLedger.replay(sealed).entries(rest[0])]
            results.append({"ok": plain_value(value)})
        except Exception as exc:  # noqa: BLE001 - recorded
            results.append({"error": error_record(exc)})
    return results


def learning_cases() -> list[dict[str, Any]]:
    steps = [
        ["append", _signal(1)], ["append", _signal(2, target="n3_authority")], ["append", _signal(3, target="unknown_thing")],
        ["append", _signal(4, evidence_refs=[])], ["append", _signal(5, target="secrets", evidence_refs=[])],
        ["append", _signal(1)], ["append", _signal(6, tenant="")], ["append", _signal(7, tenant="tenant-b", confidence=0.5)],
        ["append", _signal(8, created_at="2026-01-01T00:00:00Z", confidence=1)], ["entries", "tenant-a"], ["entries", "tenant-b"],
        ["entries", "nobody"], ["verify"], ["proposals"], ["replay", "tenant-a"], ["tamper", 1], ["tamper", 0],
        ["append", {"id": "bad", "tenant_scope": "t"}], ["append", {**_signal(9), "status": "APPLIED"}],
    ]
    return [case("ledgerScript", [steps], ledger_script)]


def _event(r: random.Random, seq: int, kind: str, node: str | None, base: int) -> dict[str, Any]:
    stamps = ["2026-01-01T0{h}:00:00+00:00", "2026-01-01T0{h}:00:00Z", "2026-01-01T0{h}:00:00", "2026-01-01T0{h}:30:00.5+00:00"]
    pick = r.choice(stamps)
    e: dict[str, Any] = {"sequence": seq, "event_type": kind}
    if node is not None:
        e["node_id"] = node
    for key in ("started_at", "completed_at", "observed_at"):
        if r.random() < 0.85:
            e[key] = pick.format(h=min(9, base + r.randint(0, 2))) if r.random() < 0.9 else r.choice(["garbage", "", None, 5])
    if kind == "approval_decided":
        e["safe_payload"] = r.choice([{"decision": "approve"}, {"decision": "reject"}, {}, None])
    return e


def measurement_cases() -> list[dict[str, Any]]:
    r = _rng(24)
    stages = ["brand_strategy", "creative_concepting", "copywriting", "design_brief", "campaign_assembly", "brand_safety_qa",
              "delivery", "unknown_stage", None]
    kinds = ["node_complete", "node_complete", "node_error", "approval_requested", "approval_decided", "artifact_generated", "other"]
    out = []
    for _ in range(120):
        rows = [_event(r, i, r.choice(kinds), r.choice(stages), i % 6) for i in range(r.randint(0, 9))]
        if r.random() < 0.3:
            r.shuffle(rows)
        planned = r.sample(["positioning_statement", "creative_concept", "copy_variant", "design_brief", "campaign_package",
                            "research_brief"], r.randint(0, 6))
        out.append(case("measureRun", [rows, planned], lambda e, p: measurement.measure_run(e, planned_artifacts=p)))
    for _ in range(80):
        planned = r.sample("abcdef", r.randint(0, 6))
        observed = r.sample("abcdefgh", r.randint(0, 7)) + r.choice([[], ["a"], ["a", "a"]])
        out.append(case("conformance", [planned, observed], lambda p, o: measurement.conformance(p, o)))
    mixed = [{"sequence": 1, "event_type": "node_complete", "node_id": "brand_strategy", "started_at": "2026-01-01T00:00:00+00:00",
              "completed_at": "2026-01-01T01:00:00"}]
    out.append(case("measureRun", [mixed, []], lambda e, p: measurement.measure_run(e, planned_artifacts=p)))
    return out


def build_core() -> dict[str, Any]:
    return {
        "strings": string_cases(), "sigma": sigma_cases(), "sorting": sort_cases(), "rounding": round_cases(),
        "hashing": hashing_cases(), "ontology": ontology_cases(), "obligations": obligation_cases(), "routes": route_cases(),
        "evaluation": evaluation_cases(), "release": release_cases(), "autonomy": autonomy_cases(),
        "promotion": promotion_cases(), "triangulation": triangulation_cases(), "instants": instant_cases(),
        "volatile": volatile_cases(), "context": context_cases(), "backchain": backchain_cases(),
        "decisions": decision_cases(), "change_control": change_cases(), "learning": learning_cases(),
        "measurement": measurement_cases(),
    }
