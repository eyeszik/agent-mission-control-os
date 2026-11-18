"""Prompt families cross-language parity fixture (Python is the reference).

`packages/prompt-families/tests/fixtures/prompt-families-parity.json` records
inputs and what `agency/prompt_families` returns for them; `@amc/prompt-families`
must reproduce every entry. Cases:

- ``signatures``: `concept_signature` and `duplicate_reason` over handwritten and
  seeded-random variations and accepted lists (whitespace/case normalisation,
  the 3-of-4 near-duplicate rule).
- ``repairs``: `repair_variation` (highest-level axis first, at most 3 passes).
- ``plans``: `plan_instances` over specs and prior ledgers, including exhausted
  option sets (REJECTED_DUPLICATE).
- ``compile``: `compile_prompt_family` end to end (through the guidance compiler):
  the repository requests, every surface family and medium, reused and exhausted
  ledgers, hooks, paid-media specs and seeded-random families. UI_UX instances
  carry a replay of the Python UI/UX compiler, which the TS twin takes through an
  injected adapter.
- ``roles``, ``capabilities``: the pure tables and lookups.
- ``requests``: payloads Pydantic rejects, and lax inputs it accepts that the TS
  twin refuses.

`resolve_functional_roles` needs the sealed RoleOS registry and stays in Python.
Regenerate with AMC_REGENERATE_FIXTURES=1.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
from pathlib import Path
from typing import Any, Callable

from pydantic import ValidationError

from services.langgraph.agency.prompt_compiler import PromptFamily
from services.langgraph.agency.prompt_families import (
    EXTERNAL_CAPABILITIES,
    FUNCTIONAL_ROLE_BINDINGS,
    PromptFamilyRequest,
    compile_prompt_family,
    external_capability_status,
    family_hash,
    functional_roles_for,
    plan_instances,
)
from services.langgraph.agency.prompt_families.compiler import build_requirements
from services.langgraph.agency.prompt_families.ledger import (
    concept_signature,
    duplicate_reason,
    repair_variation,
)
from services.langgraph.agency.prompt_families.models import (
    AXIS_PRIORITY,
    ConceptLedger,
    ConceptLedgerEntry,
    ConceptSignature,
    LedgerStatus,
    ProductionMedium,
    PromptFamilySpec,
    VariationAxis,
)
from services.langgraph.agency.ui_ux import (
    compile_uiux,
    directive_buckets,
    request_from_asset_requirement,
    serialize_spec_section,
)

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "packages/prompt-families"
FIXTURE = PACKAGE / "tests/fixtures/prompt-families-parity.json"
PROMPT_OS = Path(__file__).resolve().parent / "fixtures/prompt_os"
FULL_LIMIT = 6000
AXES = [axis.value for axis in AXIS_PRIORITY]


def canon(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def stored(value: Any) -> dict[str, Any]:
    text = canon(value)
    out: dict[str, Any] = {"sha256": hashlib.sha256(text.encode()).hexdigest(), "length": len(text)}
    if len(text) <= FULL_LIMIT:
        out["canonical"] = text
    return out


def error_of(exc: BaseException) -> dict[str, Any]:
    if isinstance(exc, ValidationError):
        issues = []
        for item in exc.errors():
            issue: dict[str, Any] = {"loc": list(item["loc"]), "type": item["type"]}
            if item["type"] == "value_error":
                issue["msg"] = item["msg"]
            issues.append(issue)
        return {"type": "ValidationError", "errors": issues}
    return {"type": type(exc).__name__, "message": str(exc)}


def capture(fn: Callable[[], Any]) -> tuple[Any, dict[str, Any] | None]:
    try:
        return fn(), None
    except ValueError as exc:
        return None, error_of(exc)


def repo_requests() -> dict[str, dict[str, Any]]:
    out = {"sample": json.loads((ROOT / "sample_prompt_family_request.json").read_text())}
    for name in ("paid_media", "print_merch", "social_series"):
        out[name] = json.loads((PROMPT_OS / f"{name}.json").read_text())
    return out


BRAND = repo_requests()["sample"]["brand_core"]


# --- signatures / repairs -------------------------------------------------------------

POOL = [
    "Sunrise", "sunrise ", "SUNRISE", "a  kettle\tas a metronome", "A kettle as a metronome", "steam", "Steam",
    "İstanbul light", "STRASSE", "Straße", "ſoft focus", "centered", "off-centre diagonal", "tight overhead",
    "low horizon", "a cup", "two hands", "line", "Solid silhouette", "solid  silhouette", "x", "y", "z",
    " wide ", "wide", "Kelvin", "KELVIN", "ǅ", "ǆ",
]


def random_variation(r: random.Random) -> dict[str, str]:
    axes = r.sample(AXES, r.randint(0, 6))
    return {axis: r.choice(POOL) for axis in axes}


def random_axes(r: random.Random) -> dict[str, list[str]]:
    chosen = r.sample(AXES, r.randint(1, 7))
    return {axis: r.sample(POOL, r.randint(1, 5)) for axis in chosen}


def signature_of(variation: dict[str, str]) -> ConceptSignature:
    return concept_signature(variation)


def signature_cases() -> list[dict[str, Any]]:
    r = random.Random(1812)
    variations = [
        {}, {"concept_metaphor": "Sunrise"}, {"concept_metaphor": "sunrise", "composition": "wide", "subject": "cup", "graphic_device": "line"},
        {"concept_metaphor": " SUNRISE ", "composition": "Wide", "subject": "Cup", "graphic_device": "LINE", "lighting": "x"},
        {"concept_metaphor": "İstanbul", "composition": "STRASSE"}, {"concept_metaphor": "a  b\tc d"},
        {"concept_metaphor": " ", "composition": ""},
    ] + [random_variation(r) for _ in range(120)]
    cases = []
    for i, variation in enumerate(variations):
        accepted = [signature_of(random_variation(r)) for _ in range(r.randint(0, 4))]
        if i % 3 == 0:
            accepted.append(signature_of({**variation, "lighting": "different"}))
        if i % 5 == 0:
            accepted.append(signature_of({k: v for k, v in list(variation.items())[:3]}))
        signature = concept_signature(variation)
        cases.append({
            "variation": variation,
            "signature": signature.model_dump(mode="json"),
            "accepted": [item.model_dump(mode="json") for item in accepted],
            "duplicate_reason": duplicate_reason(signature, accepted),
        })
    return cases


def repair_cases() -> list[dict[str, Any]]:
    r = random.Random(9)
    cases = []
    for _ in range(150):
        axes = random_axes(r)
        variation = {axis: r.choice(options) for axis, options in axes.items()}
        accepted = [signature_of({axis: r.choice(options) for axis, options in axes.items()}) for _ in range(r.randint(0, 6))]
        accepted.append(signature_of(variation))
        axes_enum = {VariationAxis(k): v for k, v in axes.items()}
        repaired, log = repair_variation(variation, axes_enum, accepted)
        cases.append({
            "variation": variation,
            "axes": axes,
            "accepted": [item.model_dump(mode="json") for item in accepted],
            "repaired": repaired,
            "log": log,
        })
    return cases


# --- family specs ------------------------------------------------------------------------

WEIGHTS = [(0.7, 0.3), (0.5, 0.5), (0.6, 0.4), (0.9, 0.1), (0.25, 0.75), (1.0, 0.0), (0.0, 1.0)]
SURFACES = [family.value for family in PromptFamily]
MEDIA = [medium.value for medium in ProductionMedium]


def random_spec(r: random.Random, index: int, surface: str | None = None) -> dict[str, Any]:
    sc, nb = r.choice(WEIGHTS)
    spec: dict[str, Any] = {
        "family_id": f"fam.{index}-{r.randint(0, 99)}",
        "version": "1.0.0",
        "business_objective": r.choice(["Build recognition for the campaign.", "Sell the autumn blend.", "A series about mornings."]),
        "audience": "Busy professionals.",
        "surface_family": surface or r.choice(SURFACES),
        "asset_type": r.choice(["social graphic", "poster", "display ad", "landing page copy", "short form video", "merchandise artwork"]),
        "channel": r.choice(["social", "web", "advertising", "merch", "ooh"]),
        "destination": r.choice(["Instagram feed 4:5", "A2 poster", "inbox", "/"]),
        "variation_axes": random_axes(r),
        "instance_count": r.randint(1, 9),
        "series_consistency": sc,
        "novelty_budget": nb,
    }
    optional: list[tuple[str, Callable[[], Any]]] = [
        ("niche", lambda: "specialty coffee"),
        ("emotional_function", lambda: "calm resolve"),
        ("content_requirements", lambda: ["Show a ceramic cup.", "Natural light."]),
        ("exact_text", lambda: r.sample(["Mornings, deliberately.", "Start today.", "Tab\there \"q\" é"], r.randint(1, 2))),
        ("negative_constraints", lambda: ["No visible lettering."]),
        ("references", lambda: [{"ref_id": f"r{k}", "role": r.choice(["IDENTITY", "STYLE", "COMPOSITION"]), "priority": r.randint(1, 5)} for k in range(r.randint(1, 3))]),
        ("invariants", lambda: {"brand_voice": "warm", "signature_devices": ["amber line"], "claim_limits": ["no health claims"], "accessibility": ["contrast"], "logo_rules": "top-left"}),
        ("campaign", lambda: {"campaign_id": "cmp-1", "objective": "Recognition", "audience": "Pros", "verbal_thesis": r.choice(["A good morning is made.", None]), "promise": "Calm.", "cta": r.choice(["Start now", None])}),
        ("production", lambda: random_production(r)),
    ]
    for key, make in optional:
        if r.random() < 0.5:
            spec[key] = make()
    return spec


def random_production(r: random.Random) -> dict[str, Any]:
    production: dict[str, Any] = {"medium": r.choice(MEDIA)}
    if r.random() < 0.6:
        production["background"] = r.choice(["TRANSPARENT", "SOLID", "UNSPECIFIED"])
    if r.random() < 0.6:
        production["vendor_profile"] = "vendor-a"
    if r.random() < 0.5:
        production["print_method"] = "screenprint"
    export: dict[str, Any] = {}
    for key in ("color_space", "resolution", "format", "bleed", "safe_area"):
        if r.random() < 0.4:
            export[key] = "x"
    if r.random() < 0.3:
        export["duration_seconds"] = r.choice([6, 7.5])
    if export:
        production["export"] = export
    return production


def random_ledger(r: random.Random, spec: dict[str, Any]) -> dict[str, Any]:
    entries = []
    for k in range(r.randint(0, 5)):
        variation = {axis: r.choice(options) for axis, options in spec["variation_axes"].items()}
        status = r.choice([LedgerStatus.accepted, LedgerStatus.accepted, LedgerStatus.rejected_duplicate])
        entries.append(ConceptLedgerEntry(
            family_id="prior", instance_id=f"prior.{k}", signature=concept_signature(variation), status=status, variation=variation,
        ))
    return ConceptLedger(entries=entries, rejected_patterns=["abc"] if entries else []).model_dump(mode="json")


def plan_cases() -> list[dict[str, Any]]:
    r = random.Random(33)
    cases = []
    specs = [random_spec(r, i) for i in range(60)]
    specs.append({**random_spec(r, 99), "variation_axes": {"concept_metaphor": ["a", "b"]}, "instance_count": 9})
    for spec in specs:
        model = PromptFamilySpec.model_validate(spec)
        ledger = ConceptLedger.model_validate(random_ledger(r, spec))
        instances = plan_instances(model, ledger.accepted())
        cases.append({
            "spec": spec,
            "ledger": ledger.model_dump(mode="json"),
            "family_hash": family_hash(model),
            "instances": [item.model_dump(mode="json") for item in instances],
        })
    return cases


# --- compile -----------------------------------------------------------------------------


def uiux_replays(payload: dict[str, Any]) -> dict[str, Any]:
    request = PromptFamilyRequest.model_validate(payload)
    spec = request.family
    if spec.surface_family is not PromptFamily.ui_ux:
        return {}
    instances = plan_instances(spec, request.ledger.accepted())
    replays: dict[str, Any] = {}
    for requirement in build_requirements(spec, instances):
        ir = compile_uiux(request_from_asset_requirement(requirement, request.brand_core))
        replays[requirement.asset_id] = {
            "dump": canon(ir),
            "spec_hash": ir.spec_hash,
            "terminal": ir.terminal.value,
            "evaluation": [
                {"engine": f.engine.value, "severity": f.severity.value, "subject": f.subject, "message": f.message, "repaired": f.repaired}
                for f in ir.evaluation
            ],
            "approval_required": list(ir.approval_required),
            "directive_buckets": directive_buckets(ir),
            "spec_section": serialize_spec_section(ir),
        }
    return replays


def result_summary(result: Any) -> dict[str, Any]:
    return {
        "terminal_state": result.terminal_state,
        "blocked_reasons": result.blocked_reasons,
        "compiler_state": result.compiler_result.final_state.value,
        "instance_status": [item.status.value for item in result.instances],
        "repairs": [item.repairs for item in result.instances],
        "family_hash": result.family_hash,
        "roles": result.responsible_functional_roles,
        "evaluation": result.evaluation.model_dump(mode="json"),
        "ledger": stored(result.ledger),
        "dump": stored(result),
    }


def handwritten_requests() -> list[tuple[str, dict[str, Any]]]:
    repo = repo_requests()
    out = [(f"repo:{name}", payload) for name, payload in repo.items()]
    social = repo["social_series"]
    first = compile_prompt_family(PromptFamilyRequest.model_validate(social))
    out.append(("reused-ledger", {**social, "ledger": first.ledger.model_dump(mode="json")}))
    tiny = {**social, "family": {**social["family"], "variation_axes": {"concept_metaphor": ["a", "b"]}, "instance_count": 6}}
    out.append(("exhausted-options", tiny))
    done = compile_prompt_family(PromptFamilyRequest.model_validate(tiny))
    out.append(("exhausted-ledger", {**tiny, "ledger": done.ledger.model_dump(mode="json")}))
    for surface in SURFACES:
        family = {**social["family"], "family_id": f"surface.{surface.lower()}", "surface_family": surface, "instance_count": 2}
        out.append((f"surface-{surface}", {**social, "family": family}))
    for medium in MEDIA:
        family = {**social["family"], "family_id": f"medium.{medium.lower()}", "instance_count": 2, "production": {"medium": medium}}
        out.append((f"medium-{medium}", {**social, "family": family}))
    claims = {"claims": [{"text": "We are the #1 coffee brand."}], "content": "The API returns results in under 200 ms."}
    out.append(("blocking-claims", {**social, **claims}))
    return out


def random_request(r: random.Random, index: int) -> dict[str, Any]:
    spec = random_spec(r, index)
    payload: dict[str, Any] = {"project_name": f"project {index}", "brand_core": BRAND, "family": spec}
    if r.random() < 0.5:
        payload["ledger"] = random_ledger(r, spec)
    if r.random() < 0.3:
        payload["content"] = "Calm mornings matter to disciplined people."
    if r.random() < 0.3:
        payload["hooks"] = [{"hook_id": "h", "territory": "t", "text": "x", "status": "CANDIDATE", "creative_score": 0.5}]
    return payload


def compile_cases() -> list[dict[str, Any]]:
    r = random.Random(555)
    requests = handwritten_requests() + [(f"random-{i}", random_request(r, i)) for i in range(40)]
    cases = []
    for name, payload in requests:
        result = compile_prompt_family(PromptFamilyRequest.model_validate(payload))
        cases.append({"name": name, "request": payload, "uiux": uiux_replays(payload), "expect": result_summary(result)})
    return cases


# --- roles / capabilities ------------------------------------------------------------------


def role_cases() -> dict[str, Any]:
    return {
        "bindings": {
            key: [b.functional_role, b.skill_name, b.department, b.match]
            for key, b in sorted(FUNCTIONAL_ROLE_BINDINGS.items())
        },
        "for": [
            {"family": family, "medium": medium, "roles": functional_roles_for(PromptFamily(family), ProductionMedium(medium))}
            for family in SURFACES
            for medium in MEDIA
        ],
    }


def capability_cases() -> dict[str, Any]:
    names = [*EXTERNAL_CAPABILITIES, "search", "  ogenic   god  toolkit ", "wolfram ", "ads_manager", "straße", "unknown thing", "", "ſearch"]
    return {
        "known": sorted(EXTERNAL_CAPABILITIES),
        "lookups": [
            {"name": name, "result": [c.name, c.status, c.repository_surface, c.note]}
            for name in names
            for c in [external_capability_status(name)]
        ],
    }


# --- request validation --------------------------------------------------------------------


def request_cases() -> list[dict[str, Any]]:
    good = repo_requests()["social_series"]
    spec = good["family"]
    base = {"hook_id": "h", "territory": "t", "text": "x"}
    bad: list[tuple[str, dict[str, Any], bool]] = [
        ("bad-weights", {**good, "family": {**spec, "series_consistency": 0.5, "novelty_budget": 0.2}}, False),
        ("weights-isclose", {**good, "family": {**spec, "series_consistency": 0.7, "novelty_budget": 0.3000000001}}, False),
        ("empty-options", {**good, "family": {**spec, "variation_axes": {"concept_metaphor": []}}}, False),
        ("blank-option", {**good, "family": {**spec, "variation_axes": {"concept_metaphor": ["a", "  "]}}}, False),
        ("duplicate-options", {**good, "family": {**spec, "variation_axes": {"concept_metaphor": ["a", "a"]}}}, False),
        ("no-axes", {**good, "family": {**spec, "variation_axes": {}}}, False),
        ("unknown-axis", {**good, "family": {**spec, "variation_axes": {"mood": ["a"]}}}, False),
        ("bad-family-id", {**good, "family": {**spec, "family_id": "Bad Id"}}, False),
        ("family-id-newline", {**good, "family": {**spec, "family_id": "ok\n"}}, False),
        ("instance-count-high", {**good, "family": {**spec, "instance_count": 25}}, False),
        ("instance-count-zero", {**good, "family": {**spec, "instance_count": 0}}, False),
        ("extra-family-key", {**good, "family": {**spec, "mood": "x"}}, False),
        ("extra-request-key", {**good, "owner": "x"}, False),
        ("missing-brand", {k: v for k, v in good.items() if k != "brand_core"}, False),
        ("hook-approved-no-ref", {**good, "hooks": [{**base, "status": "APPROVED_FOR_TEST"}]}, False),
        ("hook-measured-no-obs", {**good, "hooks": [{**base, "status": "MEASURED", "approval_ref": "a"}]}, False),
        ("hook-winner-no-metric", {**good, "hooks": [{**base, "status": "WINNER_BY_METRIC", "approval_ref": "a", "observations": [{"metric": "ctr", "value": 0.1, "window_start": "a", "window_end": "b", "source": "s"}]}]}, False),
        ("hook-winner-wrong-metric", {**good, "hooks": [{**base, "status": "WINNER_BY_METRIC", "approval_ref": "a", "winner_metric": "cvr", "observations": [{"metric": "ctr", "value": 0.1, "window_start": "a", "window_end": "b", "source": "s"}]}]}, False),
        ("hook-score-range", {**good, "hooks": [{**base, "creative_score": 1.5}]}, False),
        ("observation-negative-sample", {**good, "hooks": [{**base, "observations": [{"metric": "m", "value": 1, "window_start": "a", "window_end": "b", "source": "s", "sample_size": -1}]}]}, False),
        ("hook-bad-status", {**good, "hooks": [{**base, "status": "WINNING"}]}, False),
        ("paid-media-mutation", {**good, "paid_media": [{"objective": "o", "audience": "a", "platform_mutation": True}]}, False),
        ("paid-media-execution", {**good, "paid_media": [{"objective": "o", "audience": "a", "execution": "LIVE"}]}, False),
        ("paid-media-ok", {**good, "paid_media": [{"objective": "o", "audience": "a"}]}, False),
        ("hook-winner-ok", {**good, "hooks": [{**base, "status": "WINNER_BY_METRIC", "approval_ref": "a", "winner_metric": "ctr", "observations": [{"metric": "ctr", "value": 1, "window_start": "a", "window_end": "b", "source": "s"}]}]}, False),
        ("bad-medium", {**good, "family": {**spec, "production": {"medium": "HOLOGRAM"}}}, False),
        ("lax-instance-count-string", {**good, "family": {**spec, "instance_count": "3"}}, True),
        ("lax-weight-string", {**good, "family": {**spec, "series_consistency": "0.7"}}, True),
        ("lax-bool-claims", {**good, "extract_content_claims": 1}, False),
    ]
    cases = []
    for name, payload, lax in bad:
        _, error = capture(lambda: PromptFamilyRequest.model_validate(payload))
        case: dict[str, Any] = {"name": name, "request": payload, "python_accepts": error is None}
        if error is not None:
            case["error"] = error
        if lax:
            case["lax"] = True
        cases.append(case)
    return cases


def build_fixture() -> dict[str, Any]:
    return {
        "generator": "services/langgraph/tests/test_prompt_families_parity_fixture.py",
        "signatures": signature_cases(),
        "repairs": repair_cases(),
        "plans": plan_cases(),
        "compile": compile_cases(),
        "roles": role_cases(),
        "capabilities": capability_cases(),
        "requests": request_cases(),
    }


def test_prompt_families_parity_fixture_matches_python() -> None:
    text = json.dumps(build_fixture(), indent=1, ensure_ascii=False) + "\n"
    if os.environ.get("AMC_REGENERATE_FIXTURES") == "1" or not FIXTURE.exists():
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(text, encoding="utf-8")
    stored_fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert stored_fixture == json.loads(text), "prompt-families parity fixture is stale; regenerate with AMC_REGENERATE_FIXTURES=1"


def test_fixture_covers_every_family_state() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    terminals = {case["expect"]["terminal_state"] for case in fixture["compile"]}
    assert terminals == {"PROMPT_PACKAGE_READY", "BLOCKED"}
    statuses = {s for case in fixture["compile"] for s in case["expect"]["instance_status"]}
    assert statuses == {"ACCEPTED", "REJECTED_DUPLICATE"}
    assert any(case["expect"]["repairs"] and any(case["expect"]["repairs"]) for case in fixture["compile"])
    assert any("error" in case for case in fixture["requests"])
