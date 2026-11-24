"""Guidance registry + prompt compiler cross-language parity fixture.

Python is the reference. `packages/guidance/tests/fixtures/guidance-parity.json`
records inputs and what `agency/guidance` (registry, router) and
`agency/prompt_compiler.py` return for them; `@amc/guidance` must reproduce
every entry. This test checks the stored entries still match Python, so a
change to either module fails here before it silently breaks the TS twin.

Cases:
- ``registry``: the real pack directory (`registry_hash`, per-pack hashes, the
  `verify_guidance_registry.py` line). The TS suite reads the same pack files.
- ``json``: the strict pack reader (`json.loads` + duplicate-key hook): parsed
  value (canonical text and `repr`) or the exact error.
- ``packs``: synthetic pack directories through `GuidanceRegistry.from_directory`.
- ``routes``: `route_guidance` over the real registry (handwritten and
  seeded-random requirements) and over synthetic registries.
- ``intake``: `intake_claims` (claim extraction regexes, casefold dedupe).
- ``compile``: `compile_prompt_packages` for handwritten, repository and
  seeded-random requests, covering every terminal and refusal state. UI_UX
  requests carry a replay of the Python `agency/ui_ux` compiler output, which
  the TS compiler takes through an injected adapter (that area is ported
  separately).
- ``validate``: `validate_prompt_package` on deliberately corrupted prompts.
- ``requests``: request payloads Pydantic rejects, and lax inputs it accepts
  that the TS twin refuses.

It also owns `packages/guidance/src/python-unicode.ts`: Python's `\\w`, `\\d`,
`\\s` and IGNORECASE tables and its `str.casefold()` table. Regenerate with AMC_REGENERATE_FIXTURES=1.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import string
import tempfile
import unicodedata
from pathlib import Path
from typing import Any, Callable

from pydantic import ValidationError

from services.langgraph.agency.guidance import default_registry, route_guidance
from services.langgraph.agency.guidance.registry import (
    REGISTRY_VERSION,
    GuidanceRegistry,
    _no_duplicate_object_pairs,
)
from services.langgraph.agency.prompt_compiler import (
    AssetRequirement,
    PromptCompilerRequest,
    PromptFamily,
    compile_prompt_packages,
    intake_claims,
    validate_prompt_package,
)
from services.langgraph.agency.ui_ux import (
    compile_uiux,
    directive_buckets,
    request_from_asset_requirement,
    serialize_spec_section,
)

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "packages/guidance"
FIXTURE = PACKAGE / "tests/fixtures/guidance-parity.json"
UNICODE_MODULE = PACKAGE / "src/python-unicode.ts"
PACKS = ROOT / "services/langgraph/agency/guidance/packs"
REPO_REQUESTS = [
    ROOT / "sample_prompt_request.json",
    *sorted((Path(__file__).resolve().parent / "fixtures/prompt_os").glob("*.json")),
]
FULL_LIMIT = 6000  # results up to this many canonical characters are stored verbatim


def canon(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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
    except (ValueError, KeyError) as exc:  # ValidationError and JSONDecodeError are ValueErrors
        return None, error_of(exc)


def stored(value: Any) -> dict[str, Any]:
    text = canon(value)
    out: dict[str, Any] = {"sha256": digest(text), "length": len(text)}
    if len(text) <= FULL_LIMIT:
        out["canonical"] = text
    return out


# --- Python's own character tables -----------------------------------------------

ALL_CHARS = "".join(map(chr, range(0x110000)))


def _ranges(code_points: list[int]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for cp in code_points:
        if out and out[-1][1] == cp - 1:
            out[-1] = (out[-1][0], cp)
        else:
            out.append((cp, cp))
    return out


def _matching(pattern: str, flags: int = 0) -> list[int]:
    return [m.start() for m in re.finditer(pattern, ALL_CHARS, flags)]


def _ignorecase_extras() -> dict[str, list[int]]:
    candidates = [cp for cp in _matching("[a-z]", re.IGNORECASE) if cp > 0x7F]
    extras: dict[str, list[int]] = {}
    for letter in string.ascii_lowercase:
        hits = [cp for cp in candidates if re.fullmatch(letter, chr(cp), re.IGNORECASE)]
        if hits:
            extras[letter] = hits
    return extras


def _render_ranges(name: str, ranges: list[tuple[int, int]]) -> list[str]:
    lines = [f"export const {name}: readonly CodePointRange[] = ["]
    for i in range(0, len(ranges), 4):
        lines.append("  " + " ".join(f"[0x{lo:x}, 0x{hi:x}]," for lo, hi in ranges[i:i + 4]))
    return lines + ["];", ""]


def _casefold_pairs() -> list[tuple[int, str]]:
    pairs = []
    for cp in range(0x110000):
        if 0xD800 <= cp <= 0xDFFF:
            continue
        folded = chr(cp).casefold()
        if folded != chr(cp):
            pairs.append((cp, folded))
    return pairs


def render_unicode_module() -> str:
    extras = _ignorecase_extras()
    pairs = _casefold_pairs()
    lines = [
        "// GENERATED by services/langgraph/tests/test_guidance_parity_fixture.py from Python's re engine and str.casefold().",
        "// Do not edit by hand. Regenerate with AMC_REGENERATE_FIXTURES=1.",
        "",
        "export type CodePointRange = readonly [number, number];",
        "",
        f"export const PYTHON_UNIDATA_VERSION = '{unicodedata.unidata_version}';",
        "",
        "/** Code points Python's `\\w` matches in a str pattern. */",
        *_render_ranges("WORD_RANGES", _ranges(_matching(r"\w"))),
        "/** Code points Python's `\\d` matches in a str pattern. */",
        *_render_ranges("DIGIT_RANGES", _ranges(_matching(r"\d"))),
        "/** Code points Python's `\\s` matches in a str pattern (same set as str.isspace()). */",
        *_render_ranges("SPACE_RANGES", _ranges(_matching(r"\s"))),
        "/** Non-ASCII code points Python's IGNORECASE treats as equal to an ASCII letter. */",
        "export const IGNORECASE_EXTRAS: Readonly<Record<string, readonly number[]>> = {",
        *[f"  {k}: [{', '.join(f'0x{cp:x}' for cp in v)}]," for k, v in extras.items()],
        "};",
        "",
        "/** [code point, casefolded text as code points] for every code point str.casefold() changes. */",
        "export const CASEFOLD_TABLE: ReadonlyArray<readonly [number, readonly number[]]> = [",
    ]
    for i in range(0, len(pairs), 6):
        lines.append(
            "  "
            + " ".join(
                f"[0x{cp:x}, [{', '.join(f'0x{ord(c):x}' for c in folded)}]],"
                for cp, folded in pairs[i:i + 6]
            )
        )
    return "\n".join([*lines, "];", ""])


# --- registry ----------------------------------------------------------------


def registry_case() -> dict[str, Any]:
    registry = default_registry()
    return {
        "version": REGISTRY_VERSION,
        "files": sorted(path.name for path in PACKS.glob("*.yaml")),
        "registry_hash": registry.registry_hash,
        "verifier_line": (
            "Guidance registry verified "
            f"({len(registry.packs)} pack(s), registry_hash={registry.registry_hash[:16]})"
        ),
        "packs": [{"id": pack.id, "content_hash": pack.content_hash} for pack in registry.packs],
    }


# --- strict JSON reader ------------------------------------------------------

JSON_TEXTS = [
    '{"a": 1, "b": 1.0, "c": [1e5, -0.0, 1E-7, 12345678901234567890, 0.1, 1e16, 1e-5]}',
    "NaN", "Infinity", "-Infinity", "1e400", "-0", "-0.0", "1E+2", " 1 ", "null", "true ", "false",
    '{"é":"\\u00e9\\ud83d\\ude00", "q": "it\'s", "d": "say \\"hi\\"", "both": "\'\\""}',
    '"\\ud800"', '"é\x7f\\u0085\\u00a0\\u2028"', '"\\/\\b\\f\\n\\r\\t"', '{ }', '[ ]', '{"":1}',
    '{"z": 1, "a": {"y": [true, null], "b": 2.5}}', '[1, [2, [3, {"k": "v"}]]]',
    '{"a":1,"a":2}', '{"x": {"b": 1, "b": 1}}', '[{"k": 1, "k": 2}, {"z" 1}]', '{"k": 1, "k": 2, "z" 1}',
    '', '{', '{"a" 1}', '{"a":1,}', '[1,]', '[1 2]', '{"a":1} x', '"abc', '"a\x01"', '"\\x"',
    '"\\u12G4"', '01', '-', '{a:1}', 'tru', '﻿{}', '1.5e', '  [ 1 ,  ', '{"a":1 "b":2}',
    '{"a"', '{"a":', '[', '\n\n  x', '{"a":1,  "b"  :  }', '-nan', '["a",\n  "b" "c"]', '[1,2',
    '{"a":1', '"abc\\', '"\\u12"', '{"a":1,"b"}', '[-]', '{"a":tru}', '"\U0001F600x\n"', '1 2',
    '[1,,2]', '{,}', '{"a":1,,"b":2}', '\t', '"\t"', '1.', '.5', '-01', '{"a":1}\n\n x',
    'é', '{"a": [1, 2', '"\U0001F600\\q"', '[1]\r\n]',
]


def json_cases() -> list[dict[str, Any]]:
    cases = []
    for text in JSON_TEXTS:
        value, error = capture(lambda: json.loads(text, object_pairs_hook=_no_duplicate_object_pairs))
        case: dict[str, Any] = {"text": text}
        if error is None:
            case["canonical"] = canon(value)
            case["repr"] = repr(value)
        else:
            case["error"] = error
        cases.append(case)
    return cases


# --- synthetic packs -----------------------------------------------------------


def base_pack(pack_id: str = "pg.test.alpha", **changes: Any) -> dict[str, Any]:
    pack: dict[str, Any] = {
        "id": pack_id,
        "schema_version": "1.0.0",
        "pack_version": "1.0.0",
        "domain": "BRANDING",
        "authority_class": "ADVISORY",
        "description": "Synthetic pack for parity tests.",
        "activation": {"asset_families": ["IMAGE"], "task_tags": ["brand"]},
        "sections": [
            {
                "id": f"{pack_id}.one",
                "purpose": "First section.",
                "directives": ["Do the first thing.", "Café — naïve ‘quotes’ \"double\" 'single'."],
                "directive_targets": ["visual", "composition"],
                "patterns": {"zeta": "last", "alpha": "first", "mid": "x"},
                "subsections": {"visual_identity": {"typography": ["Serif"], "color": {"b": "two", "a": "one"}}},
            },
            {
                "id": f"{pack_id}.two",
                "purpose": "Second section.",
                "activate_when": {"any": ["poster", "hero"], "all": []},
                "evaluation_criteria": ["Readable."],
                "anti_patterns": ["Clutter."],
                "evidence_requirements": ["Cite a source."],
            },
        ],
        "provenance": {"source": "parity", "version": "1"},
    }
    pack.update(changes)
    return pack


def trend_meta(**changes: Any) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "observed_at": "2026-01-01",
        "expires_at": "2026-06-01",
        "source_refs": ["src-1"],
        "confidence": 0.5,
        "trend_status": "EMERGING",
    }
    meta.update(changes)
    return meta


def dumps(payload: Any) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False)


def section_variant(**changes: Any) -> dict[str, Any]:
    pack = base_pack()
    pack["sections"][0].update(changes)
    return pack


def _hashed_base() -> str:
    from services.langgraph.agency.guidance.models import GuidancePack
    from services.langgraph.agency.guidance.registry import stable_guidance_hash

    model = GuidancePack.model_validate(base_pack())
    return stable_guidance_hash(model.model_dump(mode="json", exclude={"content_hash"}))


def pack_dir_cases() -> list[tuple[str, list[tuple[str, str]]]]:
    good = dumps(base_pack())
    beta = dumps(base_pack("pg.test.beta", dependencies=["pg.test.alpha"]))
    weird = (
        '{"id": "pg.test.raw", "schema_version": "1", "pack_version": "1", "domain": "MOTION",'
        ' "authority_class": "EVIDENCE_BOUND_ADVISORY", "description": "d", "activation": {},'
        ' "sections": [{"id": "s", "purpose": "p", "subsections": {"n": 1, "f": 1.0, "g": 2.5,'
        ' "neg": -0.0, "big": 123456789012345678901, "t": true, "z": null, "nan": NaN, "list": [1, 1.0, "x"]},'
        ' "dimensions": ["d1"]}], "provenance": {"source": "s", "version": "v"}}'
    )
    return [
        ("single", [("alpha.yaml", good)]),
        ("dependency", [("alpha.yaml", good), ("beta.yaml", beta)]),
        ("file-order-and-dotfiles", [("b.yaml", beta), ("A.yaml", good), (".hidden.yaml", dumps(base_pack("pg.test.dot"))), ("notes.txt", "{")]),
        ("raw-any-values", [("raw.yaml", weird)]),
        ("trend-int-confidence", [("t.yaml", dumps(base_pack(guidance_class="TREND_INTELLIGENCE", trend=trend_meta(confidence=1))))]),
        ("trend-float", [("t.yaml", dumps(base_pack(guidance_class="TREND_INTELLIGENCE", trend=trend_meta(applicability=["web"], avoid_when=["legal"]))))]),
        ("trend-missing", [("t.yaml", dumps(base_pack(guidance_class="TREND_INTELLIGENCE")))]),
        ("methodology-with-trend", [("t.yaml", dumps(base_pack(trend=trend_meta())))]),
        ("trend-confidence-range", [("t.yaml", dumps(base_pack(guidance_class="TREND_INTELLIGENCE", trend=trend_meta(confidence=1.5))))]),
        ("trend-no-sources", [("t.yaml", dumps(base_pack(guidance_class="TREND_INTELLIGENCE", trend=trend_meta(source_refs=[]))))]),
        ("duplicate-section-ids", [("d.yaml", dumps(base_pack(sections=[base_pack()["sections"][0]] * 2)))]),
        ("no-actionable-content", [("d.yaml", dumps(base_pack(sections=[{"id": "s", "purpose": "p", "output_targets": ["x"]}])))]),
        ("empty-sections", [("d.yaml", dumps(base_pack(sections=[])))]),
        ("extra-key", [("d.yaml", dumps(base_pack(owner="me")))]),
        ("extra-section-key", [("d.yaml", dumps(section_variant(weight=2)))]),
        ("bad-domain", [("d.yaml", dumps(base_pack(domain="SPACE")))]),
        ("bad-target", [("d.yaml", dumps(section_variant(directive_targets=["visual", "smell"])))]),
        ("bad-authority", [("d.yaml", dumps(base_pack(authority_class="AUTHORITATIVE")))]),
        ("budget-low", [("d.yaml", dumps(base_pack(context_budget={"max_sections": 0})))]),
        ("budget-chars-low", [("d.yaml", dumps(base_pack(context_budget={"max_chars": 255})))]),
        ("budget-ok", [("d.yaml", dumps(base_pack(context_budget={"max_sections": 50, "max_chars": 256})))]),
        ("empty-id", [("d.yaml", dumps(base_pack("")))]),
        ("missing-provenance", [("d.yaml", dumps({k: v for k, v in base_pack().items() if k != "provenance"}))]),
        ("pattern-not-string", [("d.yaml", dumps(section_variant(patterns={"a": 1})))]),
        ("string-for-list", [("d.yaml", dumps(section_variant(directives="Do it.")))]),
        ("content-hash-match", [("d.yaml", dumps(base_pack(content_hash=_hashed_base())))]),
        ("content-hash-mismatch", [("d.yaml", dumps(base_pack(content_hash="deadbeef")))]),
        ("duplicate-key", [("d.yaml", '{"id": "x", "id": "y"}')]),
        ("syntax-error", [("ok.yaml", good), ("bad.yaml", '{"id": "x",}')]),
        ("duplicate-pack-id", [("a.yaml", good), ("b.yaml", good)]),
        ("unresolved-dependency", [("b.yaml", dumps(base_pack(dependencies=["pg.zz", "pg.aa", "pg.it's"])))]),
        ("depends-and-conflicts", [("a.yaml", good), ("b.yaml", dumps(base_pack("pg.test.beta", dependencies=["pg.test.alpha"], conflicts_with=["pg.test.alpha"])))]),
        ("empty-directory", []),
        ("only-other-files", [("readme.md", "x")]),
        ("not-an-object", [("d.yaml", "[1, 2]")]),
        ("lax-int-from-float", [("d.yaml", dumps(base_pack(context_budget={"max_sections": 5.0})))]),
        ("index-like-key", [("d.yaml", dumps(section_variant(patterns={"b": "bee", "10": "ten", "a": "ay"})))]),
        ("crlf-file", [("d.yaml", dumps(base_pack()).replace("\n", "\r\n"))]),
        ("cr-only-file", [("d.yaml", dumps(base_pack()).replace("\n", "\r"))]),
    ]


LAX_PACK_CASES = {"lax-int-from-float"}


def load_dir(files: list[tuple[str, str]]) -> GuidanceRegistry:
    with tempfile.TemporaryDirectory() as directory:
        for name, text in files:
            (Path(directory) / name).write_text(text, encoding="utf-8")
        try:
            return GuidanceRegistry.from_directory(directory)
        except ValueError as exc:
            if directory not in str(exc):
                raise
            raise ValueError(str(exc).replace(directory, "<root>")) from None


def registry_summary(registry: GuidanceRegistry) -> dict[str, Any]:
    return {
        "registry_hash": registry.registry_hash,
        "packs": [
            {
                "id": pack.id,
                "content_hash": pack.content_hash,
                "dump": stored(pack),
                "section_reprs": [repr(section.model_dump(mode="json")) for section in pack.sections],
            }
            for pack in registry.packs
        ],
    }


def pack_cases() -> list[dict[str, Any]]:
    cases = []
    for name, files in pack_dir_cases():
        registry, error = capture(lambda: load_dir(files))
        case: dict[str, Any] = {"name": name, "files": [{"name": n, "text": t} for n, t in files]}
        if name in LAX_PACK_CASES:
            case["python_accepts"] = error is None
        if error is None:
            case["expect"] = registry_summary(registry)
        else:
            case["error"] = error
        cases.append(case)
    return cases


# --- requirements and routing ----------------------------------------------------

FAMILIES = [family.value for family in PromptFamily]
ASSET_TYPES = [
    "homepage hero image", "social graphic", "poster", "logo", "brand identity system", "landing page",
    "product launch video", "storyboard", "email newsletter", "pitch deck", "t-shirt merch artwork",
    "billboard", "packaging label", "display ad", "dashboard", "onboarding flow", "hero section",
    "motion logo sting", "print brochure", "short form video", "landing page copy", "brand guidelines",
    "ux microcopy", "key art", "typographic poster", "web app", "Social   Post!", "LOGO-system",
    "wordmark", "carousel", "error message", "design system", "headline", "thumbnail", "signage",
]
CHANNELS = [
    "web", "social", "print", "email", "advertising", "ooh", "app", "video", "tiktok", "instagram",
    "presentation", "product", "merch", "packaging", "youtube", "Web", "paid social", "blog",
]
OBJECTIVE_WORDS = [
    "brand", "identity", "campaign", "hook", "attention", "scroll", "series", "variants", "poster",
    "copy", "rewrite", "seo", "ui", "ux", "interface", "flow", "accessibility", "tokens", "motion",
    "hero", "landing page", "performance", "naming", "positioning", "merch", "packaging", "print",
    "signage", "email", "newsletter", "dashboard", "ai", "assistant", "trend", "metaphor", "headline",
    "thumbnail", "video", "opening", "reference", "carousel", "infographic", "design system",
    "implementation", "component", "mockup", "t-shirt", "pantone", "cmyk", "the", "for", "morning",
    "coffee", "Café", "naïve", "STRASSE", "İstanbul", "ſoft", "Kelvin", "a/b", "21st.dev",
]
DOMAINS = ["strategy", "verbal", "visual", "motion", "audio", "Visual", "unknown-domain"]
CAPABILITIES = [
    "TEXT_TO_IMAGE", "IMAGE_TO_IMAGE", "UI_GENERATION", "CODE_GENERATION", "TEXT_TO_VIDEO",
    "STRUCTURED_TEXT", "CAMERA_CONTROL", "AUDIO", "VECTOR", "MULTI_REFERENCE",
]
PACK_IDS = [pack.id for pack in default_registry().packs] + ["pg.unknown"]


def _phrase(r: random.Random, n: int) -> str:
    return " ".join(r.choice(OBJECTIVE_WORDS) for _ in range(n))


def random_requirement(r: random.Random, index: int, family: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "asset_id": f"asset-{index:03d}",
        "family": family or r.choice(FAMILIES),
        "asset_type": r.choice(ASSET_TYPES),
        "objective": f"Create {_phrase(r, r.randint(2, 8))}.",
        "audience": r.choice(["Busy professionals.", "Coffee lovers", "Designers who care about type."]),
        "channel": r.choice(CHANNELS),
        "destination": r.choice(["/", "Instagram feed 4:5", "A2 poster", "inbox"]),
    }
    optional: list[tuple[str, Callable[[], Any]]] = [
        ("business_reason", lambda: _phrase(r, 3)),
        ("required_brand_domains", lambda: r.sample(DOMAINS, r.randint(0, 3))),
        ("required_capabilities", lambda: r.sample(CAPABILITIES, r.randint(0, 2))),
        ("content_requirements", lambda: [_phrase(r, 4) for _ in range(r.randint(0, 2))]),
        ("quality_constraints", lambda: [_phrase(r, 3) for _ in range(r.randint(0, 2))]),
        ("negative_constraints", lambda: ["No visible text."]),
        ("guidance_overrides", lambda: {"include": r.sample(PACK_IDS, r.randint(0, 2)), "exclude": r.sample(PACK_IDS, r.randint(0, 2))}),
        ("production", lambda: {"width": 1080, "height": 1350, "duration_seconds": r.choice([6.0, 7.5, 15]), "fps": 24}),
    ]
    for key, make in optional:
        if r.random() < 0.5:
            payload[key] = make()
    return payload


HANDWRITTEN_REQUIREMENTS: list[tuple[str, dict[str, Any], dict[str, Any] | None]] = [
    ("copy-landing", {"family": "COPY", "asset_type": "landing page copy", "channel": "web", "objective": "Rewrite the landing headline for conversion and seo."}, None),
    ("ui-landing", {"family": "UI_UX", "asset_type": "landing page", "channel": "web", "objective": "Design a marketing website hero with motion and a pricing navbar."}, None),
    ("image-hero", {"family": "IMAGE", "asset_type": "homepage hero image", "channel": "web", "objective": "Create a documentary-style branded hero image for a marketing website."}, None),
    ("video-hook", {"family": "VIDEO", "asset_type": "short form video", "channel": "tiktok", "objective": "Open with a hook in the first second to stop the scroll; test variants."}, None),
    ("poster-series", {"family": "PRINT", "asset_type": "poster", "channel": "ooh", "objective": "A typographic poster series with an exact headline and a reference moodboard."}, None),
    ("merch", {"family": "PRINT", "asset_type": "t-shirt merch artwork", "channel": "merch", "objective": "Screenprint merch artwork, separate from the mockup."}, None),
    ("excluded-by-override", {"family": "COPY", "asset_type": "landing page copy", "channel": "web", "objective": "Copy."}, {"exclude": ["pg.branding.core"]}),
    ("forced-include", {"family": "IMAGE", "asset_type": "logo", "channel": "web", "objective": "A mark."}, {"include": ["pg.attention.hooks.v1", "pg.copy_content.v1"]}),
    ("include-and-exclude", {"family": "IMAGE", "asset_type": "logo", "channel": "web", "objective": "A mark."}, {"include": ["pg.visual_prompting.v1"], "exclude": ["pg.visual_prompting.v1"]}),
    ("hooks-excluded-type", {"family": "COPY", "asset_type": "ux microcopy", "channel": "social", "objective": "Hook attention."}, None),
    ("nothing-matches", {"family": "PRESENTATION", "asset_type": "zzz", "channel": "zzz", "objective": "zzz"}, None),
    ("studio-system", {"family": "UI_UX", "asset_type": "brand identity system", "channel": "web", "objective": "A design system with tokens, component library, ai assistant and implementation in react."}, None),
]


def requirement_payload(name: str, fields: dict[str, Any], override: dict[str, Any] | None) -> dict[str, Any]:
    payload = {"asset_id": name, "audience": "Busy professionals.", "destination": "/", **fields}
    if override is not None:
        payload["guidance_overrides"] = override
    return payload


def selection_summary(selection: Any) -> dict[str, Any]:
    return {
        "selected_pack_ids": selection.selected_pack_ids,
        "selected_section_ids": selection.selected_section_ids,
        "activation_reasons": selection.activation_reasons,
        "rejected_pack_ids": selection.rejected_pack_ids,
        "exclusion_reasons": selection.exclusion_reasons,
        "guidance_hash": selection.guidance_hash,
        "dump": stored(selection),
    }


def synthetic_registry_texts() -> dict[str, list[tuple[str, str]]]:
    root = base_pack("pg.syn.root", activation={"task_tags": ["zzz-never"]})
    child = base_pack(
        "pg.syn.child",
        dependencies=["pg.syn.root"],
        activation={"asset_families": ["IMAGE"], "asset_types": ["poster", "key art"], "channels": ["ooh"]},
        excludes={"channels": ["email"]},
        context_budget={"max_sections": 1, "max_chars": 256},
    )
    grandchild = base_pack(
        "pg.syn.grand",
        dependencies=["pg.syn.child"],
        activation={"brand_domains": ["visual", "motion"], "capabilities": ["TEXT_TO_IMAGE"]},
    )
    tight = base_pack("pg.syn.tight", activation={"asset_families": ["IMAGE"]}, context_budget={"max_chars": 900})
    return {
        "chain": [(f"{p['id']}.yaml", dumps(p)) for p in (root, child, grandchild)],
        "budget": [(f"{p['id']}.yaml", dumps(p)) for p in (tight,)],
    }


def route_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    registry = default_registry()
    for name, fields, override in HANDWRITTEN_REQUIREMENTS:
        payload = requirement_payload(name, fields, override)
        requirement = AssetRequirement.model_validate(payload)
        selection = route_guidance(requirement, registry, requirement.guidance_overrides)
        cases.append({"name": name, "registry": "default", "requirement": payload, "expect": selection_summary(selection)})
    r = random.Random(20261029)
    for index in range(70):
        payload = random_requirement(r, index)
        requirement = AssetRequirement.model_validate(payload)
        selection = route_guidance(requirement, registry, requirement.guidance_overrides)
        cases.append({"name": f"random-{index}", "registry": "default", "requirement": payload, "expect": selection_summary(selection)})
    synthetic = synthetic_registry_texts()
    scenarios = [
        ("chain-select", "chain", {"family": "IMAGE", "asset_type": "poster", "channel": "ooh", "objective": "A poster", "required_brand_domains": ["visual"], "required_capabilities": ["TEXT_TO_IMAGE"]}, None),
        ("chain-excluded-channel", "chain", {"family": "IMAGE", "asset_type": "poster", "channel": "email", "objective": "A poster"}, None),
        ("chain-dependency-excluded", "chain", {"family": "IMAGE", "asset_type": "poster", "channel": "ooh", "objective": "A poster"}, {"exclude": ["pg.syn.root"]}),
        ("chain-grand-forced", "chain", {"family": "COPY", "asset_type": "x", "channel": "y", "objective": "z"}, {"include": ["pg.syn.grand"]}),
        ("chain-mid-excluded", "chain", {"family": "IMAGE", "asset_type": "poster", "channel": "ooh", "objective": "A hero poster", "required_brand_domains": ["visual", "motion"], "required_capabilities": ["TEXT_TO_IMAGE"]}, {"exclude": ["pg.syn.child"]}),
        ("budget-hero", "budget", {"family": "IMAGE", "asset_type": "x", "channel": "y", "objective": "A hero"}, None),
        ("budget-plain", "budget", {"family": "IMAGE", "asset_type": "x", "channel": "y", "objective": "plain"}, None),
    ]
    for name, registry_name, fields, override in scenarios:
        payload = requirement_payload(name, fields, override)
        requirement = AssetRequirement.model_validate(payload)
        selection = route_guidance(requirement, load_dir(synthetic[registry_name]), requirement.guidance_overrides)
        files = [{"name": n, "text": t} for n, t in synthetic[registry_name]]
        cases.append({"name": name, "registry": registry_name, "files": files, "requirement": payload, "expect": selection_summary(selection)})
    return cases


# --- claim intake ----------------------------------------------------------------

SENTENCE_PARTS = [
    "The API returns results in under 200 ms", "Our SDK supports every provider", "We are the #1 coffee brand",
    "Better than any competitor in the market", "Licensed under a trademark agreement", "Calm mornings matter",
    "Uptime is 99.9% for all users", "It costs 5 usd per box", "We grow 3x every year", "Shipping takes 2 days",
    "The webhook fires on every order", "Industry-leading roasting", "Market leader since 1999",
    "number one in taste", "faster than light", "The ſdk works offline today", "Our İPI is stable",
    "A webhooks list is long", "modelling clay is fun", "Our KELVIN model is great", "٣ ms is the latency",
    "١٢ users joined", "We comply with WCAG and privacy law", "Customers love our audience", "short",
    "Straße and STRASSE are the same street", "STRASSE AND STRASSE ARE THE SAME STREET", "x" * 19, "y" * 20,
    "Price is $5 today", "Costs 5$ today", "A 10 % discount applies", "Speed 10x faster than before",
    "apiary bees are busy here", "the endpoint_v2 is new", "ﬁne ligatures are ﬁne here", "ΣΊΣΥΦΟΣ wrote this",
]
SEPARATORS = [". ", "! ", "? ", ". ", ".\x1c", ".﻿", ".\u0085", ".\n\n", ". \t ", "; ", ".", "?　"]


def random_content(r: random.Random) -> str:
    parts = [r.choice(SENTENCE_PARTS) + r.choice(SEPARATORS) for _ in range(r.randint(1, 7))]
    lead = r.choice(["", "  ", " ", "﻿"])
    return lead + "".join(parts) + r.choice(["", " ", " "])


def intake_cases() -> list[dict[str, Any]]:
    r = random.Random(7)
    payloads: list[dict[str, Any]] = [
        {"content": "Straße and STRASSE are the same street. STRASSE AND STRASSE ARE THE SAME STREET. Straße and STRASSE are the same street!"},
        {"content": "The API returns results in under 200 ms. Our audience grows.", "claims": [{"text": "  The API returns results in under 200 ms.  "}]},
        {"content": "The API returns results in under 200 ms. Again here.", "extract_content_claims": False, "claims": [{"text": "Seeded claim", "claim_type": "PROMISE"}]},
        {"content": "   ", "claims": [{"text": "x"}]},
    ]
    for _ in range(80):
        payload: dict[str, Any] = {"content": random_content(r)}
        if r.random() < 0.3:
            payload["claims"] = [{"text": r.choice(SENTENCE_PARTS) + r.choice([".", ""]), "claim_type": r.choice(["FACT", "PROMISE", "METRIC"])}]
        payloads.append(payload)
    cases = []
    for payload in payloads:
        request = PromptCompilerRequest.model_validate({"project_name": "intake", **payload})
        cases.append({"request": {"project_name": "intake", **payload}, "claims": canon([c.model_dump(mode="json") for c in intake_claims(request)])})
    return cases


# --- compile ------------------------------------------------------------------------


def brand_core() -> dict[str, Any]:
    return json.loads((ROOT / "sample_prompt_request.json").read_text())["brand_core"]


def uiux_replays(payload: dict[str, Any]) -> dict[str, Any]:
    request = PromptCompilerRequest.model_validate(payload)
    replays: dict[str, Any] = {}
    if request.brand_core is None:
        return replays
    for requirement in request.asset_requirements:
        if requirement.family is not PromptFamily.ui_ux:
            continue
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
        "final_state": result.final_state.value,
        "acceptance": result.acceptance.status.value,
        "confidence": result.confidence,
        "voids": result.voids,
        "packages": [
            {
                "package_id": p.package_id,
                "prompt_hash": p.prompt_hash,
                "context_hash": p.context_manifest.context_hash,
                "guidance_hash": p.context_manifest.guidance_hash,
                "validation": p.validation.status.value,
                "issues": p.validation.issues,
                "prompt_sha256": digest(p.generic_master_prompt),
            }
            for p in result.prompt_packages
        ],
        "dump": stored(result),
    }


def claim_id_for(text: str, index: int) -> str:
    return f"clm_{index:03d}_{hashlib.sha256(text.encode('utf-8')).hexdigest()[:10]}"


def base_request(**changes: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "project_name": "Northwind launch",
        "content": "The campaign should communicate disciplined, calm mornings.",
        "brand_core": brand_core(),
        "asset_requirements": [requirement_payload("hero", HANDWRITTEN_REQUIREMENTS[2][1], None)],
    }
    payload.update(changes)
    return payload


def handwritten_requests() -> list[tuple[str, dict[str, Any]]]:
    api = "The API returns results in under 200 ms."
    api_id = claim_id_for(api, 1)
    promise = "We promise delivery every Monday."
    reqs = [
        ("ready", base_request()),
        ("brand-missing", base_request(brand_core=None)),
        ("brand-missing-claims-only", base_request(brand_core=None, content="", claims=[{"text": "A claim"}])),
        ("no-requirements", base_request(asset_requirements=[])),
        ("research-incomplete", base_request(content=api)),
        ("research-resolved-by-evidence", base_request(content=api, evidence=[{"source_id": "s1", "title": "Docs", "source_class": "OFFICIAL", "claim_ids": [api_id], "summary": "Official docs.", "uri": "https://example.test/docs"}])),
        ("evidence-opposes", base_request(content=api, evidence=[{"source_id": "s1", "title": "Docs", "source_class": "PRIMARY", "claim_ids": [api_id], "supports": False, "summary": "Contradicts."}])),
        ("evidence-conflicted", base_request(content=api, evidence=[
            {"source_id": "s1", "title": "A", "source_class": "PRIMARY", "claim_ids": [api_id], "summary": "Yes."},
            {"source_id": "s2", "title": "B", "source_class": "COMMUNITY", "claim_ids": [api_id], "supports": False, "summary": "No."},
        ])),
        ("evidence-community-partial", base_request(content=api, evidence=[
            {"source_id": "s1", "title": "A", "source_class": "COMMUNITY", "claim_ids": [api_id], "summary": "Forum."},
            {"source_id": "s2", "title": "B", "source_class": "USER", "claim_ids": [api_id], "summary": "User."},
        ])),
        ("promise-no-stakeholder", base_request(content="", claims=[{"text": promise, "claim_type": "PROMISE", "source_ref": None}])),
        ("promise-sourced", base_request(content="", claims=[{"text": promise, "claim_type": "PROMISE", "source_ref": "contract-1", "stakeholder": "Northwind"}])),
        ("providers", base_request(providers=[
            {"provider": "acme", "model": "img-1", "verified": True, "families": ["IMAGE"], "capabilities": ["TEXT_TO_IMAGE"], "source_ref": "docs"},
            {"provider": "acme", "model": "img-0", "verified": True, "families": ["IMAGE"], "capabilities": ["VECTOR"]},
            {"provider": "beta", "model": "b", "verified": False, "families": ["IMAGE"], "capabilities": []},
            {"provider": "gamma", "model": "g", "verified": True, "families": ["VIDEO"], "capabilities": ["TEXT_TO_VIDEO"]},
        ])),
        ("exact-text-and-references", base_request(asset_requirements=[requirement_payload("poster", {
            "family": "PRINT", "asset_type": "typographic poster", "channel": "ooh", "objective": "Poster with the exact headline.",
            "exact_text": ["Mornings, deliberately.", "Tab\there \"quoted\" é   \x07", "$5.00 — today only"],
            "references": [
                {"ref_id": "ref-style", "role": "STYLE", "priority": 3, "note": "Palette only."},
                {"ref_id": "ref-id-b", "role": "IDENTITY", "priority": 2},
                {"ref_id": "ref-id-a", "role": "IDENTITY", "priority": 2},
                {"ref_id": "ref-start", "role": "START_FRAME"},
                {"ref_id": "ref-audio", "role": "AUDIO", "priority": 10},
            ],
        }, None)])),
        ("video-exact-text", base_request(asset_requirements=[requirement_payload("video", {
            "family": "VIDEO", "asset_type": "video ad", "channel": "youtube", "objective": "Hook in the first second.",
            "exact_text": ["Start today."], "references": [{"ref_id": "end", "role": "END_FRAME"}],
            "production": {"duration_seconds": 15, "fps": 30, "aspect_ratio": "9:16", "codec": "h264"},
        }, None)])),
        ("copy-exact-text", base_request(asset_requirements=[requirement_payload("copy", {
            "family": "COPY", "asset_type": "landing page copy", "channel": "web", "objective": "Landing copy.", "exact_text": ["Free shipping."],
        }, None)])),
        ("unknown-domains", base_request(asset_requirements=[requirement_payload("dom", {
            "family": "IMAGE", "asset_type": "poster", "channel": "print", "objective": "Poster.",
            "required_brand_domains": ["visual", "audio", "visual", "strategy"],
        }, None)])),
        ("multi-asset", base_request(asset_requirements=[
            requirement_payload(name, fields, override) for name, fields, override in HANDWRITTEN_REQUIREMENTS
            if fields["family"] != "UI_UX"
        ])),
        ("ui-ux", base_request(asset_requirements=[requirement_payload("ui", HANDWRITTEN_REQUIREMENTS[1][1], None)])),
        ("ui-ux-dashboard", base_request(asset_requirements=[requirement_payload("dash", {
            "family": "UI_UX", "asset_type": "dashboard", "channel": "app", "objective": "An operations dashboard for an AI assistant.",
            "content_requirements": ["Show queue depth."], "quality_constraints": ["Keyboard first."],
        }, None)])),
        ("computations", base_request(
            content="",
            claims=[
                {"text": "Revenue was 100 usd in March.", "claim_type": "METRIC", "source_ref": "ledger"},
                {"text": "Growth is 20% month over month.", "claim_type": "METRIC"},
                {"text": "Base price is fixed."},
            ],
            evidence=[{"source_id": "e1", "title": "Ledger", "source_class": "PRIMARY", "claim_ids": [claim_id_for("Revenue was 100 usd in March.", 1)], "summary": "Ledger."}],
            computations=[
                {"computation_id": "c2", "question": "Growth?", "expression_or_operation": "a/b", "tool_or_engine": "calc", "result": "20%", "provenance": "manual",
                 "input_claim_ids": [claim_id_for("Revenue was 100 usd in March.", 1)], "derived_claim_ids": [claim_id_for("Growth is 20% month over month.", 2)], "assumptions": ["Constant mix", "No refunds"]},
                {"computation_id": "c1", "question": "Bad?", "expression_or_operation": "x", "tool_or_engine": "calc", "result": "1", "provenance": "manual",
                 "input_claim_ids": ["clm_999_missing"], "derived_claim_ids": ["clm_zzz"]},
                {"computation_id": "c3", "question": "Pure?", "expression_or_operation": "2+2", "tool_or_engine": "calc", "result": "4", "provenance": "manual",
                 "derived_claim_ids": [claim_id_for("Base price is fixed.", 3)]},
                {"computation_id": "c4", "question": "Unverified?", "expression_or_operation": "y", "tool_or_engine": "calc", "result": "2", "provenance": "manual",
                 "input_claim_ids": [claim_id_for("Growth is 20% month over month.", 2)], "derived_claim_ids": [claim_id_for("Base price is fixed.", 3)]},
            ],
        )),
        ("no-extract", base_request(content=api, extract_content_claims=False)),
        ("series-binding", base_request(asset_requirements=[requirement_payload("series", {
            "family": "IMAGE", "asset_type": "social graphic", "channel": "social", "objective": "Series instance.",
            "series": {"family_id": "f", "family_version": "1", "instance_id": "f.01", "campaign_ref": "cmp", "concept_thesis": "t",
                       "emotional_function": "calm", "signature_devices": ["line"], "series_invariants": ["voice: warm"],
                       "variation": {"subject": "cup", "composition": "centered", "Zeta": "z"}, "concept_signature": "abc"},
        }, None)])),
    ]
    for path in REPO_REQUESTS:
        payload = json.loads(path.read_text())
        if "asset_requirements" in payload or "brand_core" in payload:
            if "family" not in payload:
                reqs.append((f"repo:{path.name}", payload))
    return reqs


def random_request(r: random.Random, index: int) -> dict[str, Any]:
    content = random_content(r) if r.random() < 0.8 else ""
    claims = []
    for _ in range(r.randint(0, 3)):
        claims.append({
            "text": r.choice(SENTENCE_PARTS) + ".",
            "claim_type": r.choice(["FACT", "PROMISE", "METRIC", "API_CLAIM", "OPINION", "USER_ASSERTION"]),
            **({"source_ref": "src"} if r.random() < 0.4 else {}),
            **({"stakeholder": "Northwind"} if r.random() < 0.3 else {}),
        })
    payload: dict[str, Any] = {
        "project_name": f"random project {index}",
        "content": content,
        "claims": claims,
        "brand_core": brand_core() if r.random() < 0.9 else None,
        "asset_requirements": [random_requirement(r, i, r.choice([f for f in FAMILIES if f != "UI_UX"] * 6 + ["UI_UX"])) for i in range(r.randint(0, 3))],
    }
    if not content and not claims and payload["brand_core"] is None:
        payload["content"] = "Fallback content that is long enough to count."
    probe = PromptCompilerRequest.model_validate(payload)
    ids = [c.claim_id for c in intake_claims(probe)]
    if ids and r.random() < 0.6:
        payload["evidence"] = [{
            "source_id": f"ev{k}", "title": "Source", "source_class": r.choice(["PRIMARY", "OFFICIAL", "SECONDARY", "COMMUNITY", "USER"]),
            "claim_ids": r.sample(ids, r.randint(1, len(ids))), "supports": r.random() < 0.8, "summary": "Evidence summary.",
            **({"freshness_class": "VOLATILE", "query": "q"} if r.random() < 0.3 else {}),
        } for k in range(r.randint(1, 3))]
    if ids and r.random() < 0.3:
        payload["computations"] = [{
            "computation_id": f"comp{k}", "question": "q", "expression_or_operation": "op", "tool_or_engine": "calc",
            "result": "r", "provenance": "p", "input_claim_ids": r.sample(ids, r.randint(0, len(ids))),
            "derived_claim_ids": r.sample(ids, 1), "assumptions": ["a"] if r.random() < 0.5 else [],
        } for k in range(r.randint(1, 2))]
    if r.random() < 0.4:
        payload["providers"] = [{
            "provider": "p", "model": f"m{k}", "verified": r.random() < 0.6, "families": r.sample(FAMILIES, 3),
            "capabilities": r.sample(CAPABILITIES, r.randint(0, 3)),
        } for k in range(r.randint(1, 3))]
    if r.random() < 0.2:
        payload["extract_content_claims"] = False
    return payload


def compile_cases() -> list[dict[str, Any]]:
    requests = handwritten_requests()
    r = random.Random(424242)
    requests += [(f"random-{i}", random_request(r, i)) for i in range(45)]
    cases = []
    for name, payload in requests:
        result = compile_prompt_packages(PromptCompilerRequest.model_validate(payload))
        cases.append({"name": name, "request": payload, "uiux": uiux_replays(payload), "expect": result_summary(result)})
    return cases


def validate_cases() -> list[dict[str, Any]]:
    poster = dict(handwritten_requests())["exact-text-and-references"]
    ui = dict(handwritten_requests())["ui-ux"]
    plans = [
        ("exact-text-corrupted", poster, "Mornings, deliberately.", "Mornings, deliberately!"),
        ("objective-removed", poster, "Poster with the exact headline.", "Poster."),
        ("audience-removed", poster, "Busy professionals.", "Someone."),
        ("unchanged", poster, "", ""),
        ("ui-spec-hash-removed", ui, "Spec hash: ", "Spec: "),
    ]
    cases = []
    for name, payload, old, new in plans:
        result = compile_prompt_packages(PromptCompilerRequest.model_validate(payload))
        package = result.prompt_packages[0]
        prompt = package.generic_master_prompt.replace(old, new) if old else package.generic_master_prompt
        strip_spec_hash = "Spec hash" in old
        if strip_spec_hash:
            prompt = prompt.replace(package.ui_ux_design.spec_hash, "")
        verdict = validate_prompt_package(package.asset_spec, package.context_manifest, prompt, package.provider_prompts, package.ui_ux_design)
        cases.append({"name": name, "request": payload, "uiux": uiux_replays(payload), "old": old, "new": new, "strip_spec_hash": strip_spec_hash, "expect": canon(verdict)})
    return cases


def request_cases() -> list[dict[str, Any]]:
    good = base_request()
    req = good["asset_requirements"][0]
    bad: list[tuple[str, dict[str, Any], bool]] = [
        ("no-intake", {"project_name": "p", "content": "  \n "}, False),
        ("empty-project", {**good, "project_name": ""}, False),
        ("extra-key", {**good, "owner": "x"}, False),
        ("bad-family", {**good, "asset_requirements": [{**req, "family": "AUDIO"}]}, False),
        ("bad-capability", {**good, "asset_requirements": [{**req, "required_capabilities": ["TELEPATHY"]}]}, False),
        ("bad-width", {**good, "asset_requirements": [{**req, "production": {"width": 0}}]}, False),
        ("bad-duration", {**good, "asset_requirements": [{**req, "production": {"duration_seconds": -1}}]}, False),
        ("bad-reference-priority", {**good, "asset_requirements": [{**req, "references": [{"ref_id": "r", "role": "STYLE", "priority": 11}]}]}, False),
        ("bad-reference-role", {**good, "asset_requirements": [{**req, "references": [{"ref_id": "r", "role": "SMELL"}]}]}, False),
        ("empty-claim", {**good, "claims": [{"text": ""}]}, False),
        ("bad-source-class", {**good, "evidence": [{"source_id": "s", "title": "t", "source_class": "RUMOUR", "summary": "x"}]}, False),
        ("empty-summary", {**good, "evidence": [{"source_id": "s", "title": "t", "source_class": "USER", "summary": ""}]}, False),
        ("brand-two-primaries", {**good, "brand_core": {**good["brand_core"], "logo_lockups": good["brand_core"]["logo_lockups"] * 2}}, False),
        ("brand-missing-field", {**good, "brand_core": {k: v for k, v in good["brand_core"].items() if k != "voice"}}, False),
        ("override-extra", {**good, "asset_requirements": [{**req, "guidance_overrides": {"include": [], "force": True}}]}, False),
        ("series-empty-thesis", {**good, "asset_requirements": [{**req, "series": {"family_id": "f", "family_version": "1", "instance_id": "i", "concept_thesis": "", "concept_signature": "s"}}]}, False),
        ("lax-numeric-string-width", {**good, "asset_requirements": [{**req, "production": {"width": "1600"}}]}, True),
        ("lax-string-bool", {**good, "extract_content_claims": "yes"}, True),
        ("lax-int-bool", {**good, "providers": [{"provider": "p", "model": "m", "verified": 1}]}, True),
    ]
    cases = []
    for name, payload, lax in bad:
        _, error = capture(lambda: PromptCompilerRequest.model_validate(payload))
        case: dict[str, Any] = {"name": name, "request": payload, "python_accepts": error is None}
        if error is not None:
            case["error"] = error
        if lax:
            case["lax"] = True
        cases.append(case)
    return cases


def build_fixture() -> dict[str, Any]:
    return {
        "generator": "services/langgraph/tests/test_guidance_parity_fixture.py",
        "registry": registry_case(),
        "json": json_cases(),
        "packs": pack_cases(),
        "routes": route_cases(),
        "intake": intake_cases(),
        "compile": compile_cases(),
        "validate": validate_cases(),
        "requests": request_cases(),
    }


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _regenerate() -> bool:
    return os.environ.get("AMC_REGENERATE_FIXTURES") == "1" or not FIXTURE.exists() or not UNICODE_MODULE.exists()


def test_guidance_parity_fixture_matches_python() -> None:
    fixture = build_fixture()
    module = render_unicode_module()
    text = json.dumps(fixture, indent=1, ensure_ascii=False) + "\n"
    if _regenerate():
        _write(FIXTURE, text)
        _write(UNICODE_MODULE, module)
    stored_fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert stored_fixture == json.loads(text), "guidance parity fixture is stale; regenerate with AMC_REGENERATE_FIXTURES=1"
    assert UNICODE_MODULE.read_text(encoding="utf-8") == module


def test_fixture_covers_every_terminal_and_refusal_state() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    states = {case["expect"]["final_state"] for case in fixture["compile"]}
    assert {"PROMPT_PACKAGE_READY", "BLOCKED", "RESEARCH_INCOMPLETE", "BRAND_SYSTEM_INCOMPLETE"} <= states
    validations = {pkg["validation"] for case in fixture["compile"] for pkg in case["expect"]["packages"]}
    assert {"PASS", "REPAIR"} <= validations
    assert fixture["registry"]["verifier_line"].endswith(f"registry_hash={fixture['registry']['registry_hash'][:16]})")
    assert any("error" in case for case in fixture["packs"])
    assert any(case["registry"] != "default" for case in fixture["routes"])
