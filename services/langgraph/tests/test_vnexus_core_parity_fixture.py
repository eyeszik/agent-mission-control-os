"""VNEXUS core cross-language parity fixture (Python is the reference).

`packages/vnexus/tests/fixtures/vnexus-core-parity.json` records inputs and what
`services/langgraph/agency/vnexus` returns for each: genome documents, layer
resolution, constraint evaluation, document diffs, the temporal graph, the
multiverse change sets, the immune-scan checks, the marketing arithmetic, the
art-director scorer and the prompt-genome helpers. `@amc/vnexus` must
reproduce every entry. This test checks the stored entries still match Python,
so a change to any of those modules fails here before it silently breaks the
TypeScript twin.

It also owns `packages/vnexus/src/python-tables.ts`: the sRGB linearisation table
(the C library's `pow`, which `Math.pow` does not reproduce bit for bit) and the
tables of Python's `\\w`, `\\d` and `\\s`.

Encoding: an integral float is `{"$f": "2.0"}` (JSON cannot tell 2.0 from 2); NaN
and infinity use the same tag. Errors are `{"type": <exception class>, "message":
<str(exc)>}`; a Pydantic ValidationError records only `custom`, the messages of the
model's own validators (the built-in messages are Pydantic's wording).

Regenerate with AMC_REGENERATE_FIXTURES=1. All values are fictional.
"""
from __future__ import annotations

import json
import math
import os
import random
import re
import unicodedata
from pathlib import Path
from typing import Any, Callable, Optional

from pydantic import ValidationError

from services.langgraph.agency.vnexus import art_director, genome as g, graph as gr, immune, marketing, multiverse as mv, prompt_genome
from services.langgraph.agency.execution_fabric.verifiers import colors_in, delta_e76
from services.langgraph.agency.ui_ux.tokens import wcag_contrast_ratio
import statistics

PACKAGE = Path(__file__).resolve().parents[3] / "packages/vnexus"
FIXTURE = PACKAGE / "tests/fixtures/vnexus-core-parity.json"
TABLES = PACKAGE / "src/python-tables.ts"


def render_tables() -> str:

    out = ["// GENERATED from CPython 3.11 (owned by services/langgraph/tests/test_vnexus_core_parity_fixture.py).",
           "// Do not edit by hand.", ""]
    lin = []
    for c in range(256):
        x = c / 255
        lin.append(repr(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4))
    out.append("/** sRGB channel value 0..255 -> linear light, as Python computes it (`pow` is the C library's). */")
    out.append("export const SRGB_LINEAR: readonly number[] = [")
    for i in range(0, 256, 4):
        out.append("  " + ", ".join(lin[i:i + 4]) + ",")
    out.append("];")
    out.append("")

    word = re.compile(r"\w")
    ranges = []
    start = prev = None
    for cp in range(0x110000):
        if 0xD800 <= cp <= 0xDFFF:
            ok = False
        else:
            ok = bool(word.match(chr(cp)))
        if ok:
            if start is None:
                start = cp
            prev = cp
        elif start is not None:
            ranges.append((start, prev))
            start = None
    if start is not None:
        ranges.append((start, prev))
    out.append(f"/** Code points Python's `\\w` matches in a str pattern ({len(ranges)} ranges). */")
    out.append("export const WORD_RANGES: ReadonlyArray<readonly [number, number]> = [")
    for i in range(0, len(ranges), 4):
        out.append("  " + ", ".join(f"[0x{a:x}, 0x{b:x}]" for a, b in ranges[i:i + 4]) + ",")
    out.append("];")
    out.append("")
    out.append("function escapeCp(cp: number): string {")
    out.append("  return `\\\\u{${cp.toString(16)}}`;")
    out.append("}")
    out.append("")
    out.append("/** A regex character class body for Python's `\\w`; use with the `u` flag. */")
    out.append("export const PY_WORD_CLASS = `[${WORD_RANGES.map(([a, b]) => `${escapeCp(a)}-${escapeCp(b)}`).join('')}]`;")
    out.append("")
    spaces = "".join(chr(cp) for cp in range(0x110000) if not (0xD800 <= cp <= 0xDFFF) and chr(cp).isspace())
    out.append("/** Characters `str.strip()` removes by default (`str.isspace()`). */")
    out.append("export const PY_SPACE_CHARS: string = '" + "".join(f"\\u{ord(c):04x}" for c in spaces) + "';")

    digit_ranges = []
    start = prev = None
    zeros = []
    for cp in range(0x110000):
        ok = (not (0xD800 <= cp <= 0xDFFF)) and bool(re.match(r"\d", chr(cp)))
        if ok:
            if unicodedata.decimal(chr(cp)) == 0:
                zeros.append(cp)
            if start is None:
                start = cp
            prev = cp
        elif start is not None:
            digit_ranges.append((start, prev))
            start = None
    out.append("")
    out.append("export const DIGIT_RANGES: ReadonlyArray<readonly [number, number]> = [")
    for i in range(0, len(digit_ranges), 4):
        out.append("  " + ", ".join(f"[0x{a:x}, 0x{b:x}]" for a, b in digit_ranges[i:i + 4]) + ",")
    out.append("];")
    out.append("/** Code points of the digit zero of every decimal-digit block (`\\d` matches Unicode Nd). */")
    out.append("export const DIGIT_ZEROS: readonly number[] = [" + ", ".join(f"0x{z:x}" for z in zeros) + "];")
    out.append("/** A regex character class body for Python's `\\d`; use with the `u` flag. */")
    out.append("export const PY_DIGIT_CLASS = `[${DIGIT_RANGES.map(([a, b]) => `${escapeCp(a)}-${escapeCp(b)}`).join('')}]`;")
    out.append("/** A regex character class body for Python's `\\s`; use with the `u` flag. */")
    out.append("export const PY_SPACE_CLASS = `[${Array.from(PY_SPACE_CHARS, (c) => escapeCp(c.codePointAt(0) ?? 0)).join('')}]`;")


    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- encoding


def enc(value: Any) -> Any:
    """JSON-able form with every float that is integral (or not finite) tagged."""
    if isinstance(value, bool) or value is None or isinstance(value, (int, str)):
        return value
    if isinstance(value, float):
        if math.isfinite(value) and value != int(value):
            return value
        return {"$f": repr(value)}
    if isinstance(value, dict):
        return {str(k): enc(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [enc(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return [enc(v) for v in sorted(value)]
    if hasattr(value, "model_dump"):
        return enc(value.model_dump(mode="json"))
    raise TypeError(f"cannot encode {type(value).__name__}")


def err(exc: BaseException) -> dict[str, Any]:
    if isinstance(exc, ValidationError):
        custom = [e["msg"][len("Value error, "):] for e in exc.errors() if e["type"] == "value_error"]
        return {"type": "ValidationError", "custom": custom}
    return {"type": type(exc).__name__, "message": str(exc)}


CASES: list[dict[str, Any]] = []
GRAPHS: list[dict[str, Any]] = []


def case(call: str, fn: Callable[[], Any], args: dict[str, Any], note: str = "") -> None:
    record: dict[str, Any] = {"call": call, "args": enc(args)}
    if note:
        record["note"] = note
    try:
        record["ok"] = enc(fn())
        if isinstance(record["ok"], int) and not isinstance(record["ok"], bool) and abs(record["ok"]) > 2 ** 53:
            record["ok"] = str(record["ok"])  # JSON numbers lose precision here; the TS twin refuses these results
            record["lax_divergence"] = True
    except (ValueError, KeyError, TypeError, ZeroDivisionError, OverflowError, RuntimeError) as exc:
        record["error"] = err(exc)
    CASES.append(record)


# --------------------------------------------------------------------------- genome


def doc_dump(doc: g.GenomeDocument) -> dict[str, Any]:
    return {"dump": doc.model_dump(mode="json"), "hash": doc.content_hash, "flat": [[k, v] for k, v in doc.flatten().items()]}


def c(cid: str, key: str, kind: str, params: Optional[dict[str, Any]] = None, severity: str = "BLOCKING", rationale: str = "") -> dict[str, Any]:
    body: dict[str, Any] = {"constraint_id": cid, "key": key, "kind": kind, "severity": severity, "rationale": rationale}
    if params is not None:
        body["params"] = params
    return body


def layer(scope: str, ref: str, status: str, chromosomes: dict[str, Any], constraints: Optional[list[dict[str, Any]]] = None,
          **extra: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {"chromosomes": chromosomes}
    if constraints is not None:
        doc["constraints"] = constraints
    return {"scope": scope, "scope_ref": ref, "status": status, "document": doc, **extra}


def resolve_out(layers: list[dict[str, Any]], preview_ref: Optional[str]) -> dict[str, Any]:
    r = g.resolve([g.GenomeLayer.model_validate(x) for x in layers], preview_ref=preview_ref)
    return {"resolution": r.model_dump(mode="json"), "hash": r.resolution_hash, "blocking": [f.model_dump(mode="json") for f in r.blocking]}


COLORS = ["#000000", "#ffffff", "#1a1a1a", "#f5f5f0", "#0a66c2", "#e63946", "#777777", "#767676", "#2a9d8f", "#fefefe", "#0a66c3", "#ff00ff"]
POOLS: dict[str, list[Any]] = {
    "visual.color.ink": COLORS, "visual.color.paper": COLORS, "visual.color.accent": COLORS, "visual.color.muted": COLORS + ["red"],
    "visual.typography.display": ["Inter", "Georgia", "Söhne", "Helvetica Neue"], "visual.typography.body": ["Inter", "Georgia"],
    "visual.motion.pace": ["slow", "fast", "measured"], "strategy.audience.primary": ["founders", "designers", "parents of toddlers", "🎨 makers"],
    "experience.accessibility.standard": ["WCAG 2.2 AA", "WCAG 2.2 AAA"], "production.output.dpi": [72, 144, 300, 300.0, 150.5, True, None],
    "verbal.voice.tone": [["warm", "direct"], ["calm"], "warm", []], "visual.shape_grammar.swiss_editorial": [0.5, 1.0, 0.25, 1, 0.0],
    "strategy.positioning.promise": ["Make it simple", "Ship daily", ""], "visual.logo.mark": [None, "orbit", "spark"],
}
KEYS = sorted(POOLS)
SCOPES = [("brand", "b1"), ("project", "p1"), ("page", "p1/home"), ("component", "p1/home/hero"), ("asset", "p1/home/hero/img")]
STATUSES = ["APPROVED"] * 7 + ["DRAFT", "IN_REVIEW", "EXPERIMENTAL", "REJECTED", "SUPERSEDED"]


def rand_constraint(r: random.Random) -> dict[str, Any]:
    key = r.choice(KEYS)
    cid = r.choice(["c1", "c2", "c3", "c4", "c5.x", "c-6"])
    kind = r.choice(["IMMUTABLE", "REQUIRED", "ALLOWED_VALUES", "RANGE", "HEX_COLOR", "MIN_CONTRAST", "IMMUTABLE", "ALLOWED_VALUES"])
    sev = r.choice(["BLOCKING", "ERROR", "WARNING", "INFO"])
    if kind == "ALLOWED_VALUES":
        pool = [v for v in POOLS[key] if isinstance(v, (str, int, float))] or ["x"]
        return c(cid, key, kind, {"values": r.sample(pool, k=min(len(pool), r.randint(1, 3)))}, sev)
    if kind == "RANGE":
        lo, hi = r.choice([(0, 300), (0.0, 1.0), (72, 144.5), (150, 150), (0.25, 0.75)])
        return c(cid, key, kind, {"min": lo, "max": hi}, sev)
    if kind == "MIN_CONTRAST":
        return c(cid, "visual.color." + r.choice(["ink", "accent", "muted"]), kind,
                 {"against": "visual.color." + r.choice(["paper", "ink", "nonexistent"]), "ratio": r.choice([3, 4.5, 7.0, 2.25, 21, 1])}, sev)
    return c(cid, key, kind, None, sev, r.choice(["", "because", "für alle"]))


def rand_doc(r: random.Random, with_constraints: bool = True) -> dict[str, Any]:
    chromosomes: dict[str, dict[str, Any]] = {}
    for key in r.sample(KEYS, k=r.randint(1, 6)):
        head, _, rest = key.partition(".")
        chromosomes.setdefault(head, {})[rest] = r.choice(POOLS[key])
    cons: list[dict[str, Any]] = []
    for cc in ([rand_constraint(r) for _ in range(r.randint(0, 3))] if with_constraints else []):
        if all(x["constraint_id"] != cc["constraint_id"] for x in cons):
            cons.append(cc)
    prov = [{"key": "visual.color.ink", "kind": r.choice(["USER_SUPPLIED", "INFERRED"]), "note": "n"}] if r.random() < 0.3 else []
    return {"chromosomes": chromosomes, "constraints": cons, "provenance": prov}


def rand_layers(r: random.Random) -> list[dict[str, Any]]:
    picks = [s for s in SCOPES if r.random() < 0.7] or [SCOPES[0]]
    if r.random() < 0.15:
        r.shuffle(picks)
    out = []
    for scope, ref in picks:
        out.append({"scope": scope, "scope_ref": ref, "status": r.choice(STATUSES), "document": rand_doc(r)})
    return out


def genome_cases(r: random.Random) -> None:
    full = {"chromosomes": {"visual": {"color.ink": "#101010", "typography.display": "Inter", "shape_grammar.x": 2.0, "motion.k": 1e-07},
                            "strategy": {"audience.primary": "everyone", "values": ["a", "b"]},
                            "production": {"output.dpi": 300, "media.flag": True, "licensing.note": None, "delivery.nan": 0.1}},
            "constraints": [c("a1", "visual.color.ink", "HEX_COLOR"), c("a2", "visual.color.paper", "MIN_CONTRAST", {"against": "visual.color.ink", "ratio": 4.5}),
                            c("a3", "production.output.dpi", "RANGE", {"min": 72, "max": 600.5}),
                            c("a4", "visual.typography.display", "ALLOWED_VALUES", {"values": ["Inter", "Georgia"]}),
                            c("a5", "visual.color.accent", "IMMUTABLE"), c("a6", "strategy.audience.primary", "REQUIRED")],
            "provenance": [{"key": "visual.color.ink", "kind": "IMPORTED", "source_ref": "s", "note": "n"}]}
    valid_docs: list[tuple[str, Any]] = [
        ("empty", {}), ("default fields", {"chromosomes": {}}), ("full", full), ("unicode", {"chromosomes": {"verbal": {"voice.tone": ["café", "日本語", "🎨"]}}}),
        ("key with trailing newline", {"chromosomes": {"visual": {"color.ink\n": "#000000"}}}),
        ("six dotted parts", {"chromosomes": {"visual": {"a.b.c.d.e.f": 1}}}),
        ("float values", {"chromosomes": {"visual": {"a": 1.5, "b": 2.0, "c": -0.0, "d": 1e300, "e": 5e-324}}}),
        ("string at limit", {"chromosomes": {"verbal": {"voice.long": "x" * 2000}}}),
        ("string of 2000 astral characters", {"chromosomes": {"verbal": {"voice.long": "🎨" * 2000}}}),
        ("list at limit", {"chromosomes": {"verbal": {"voice.list": ["y" * 300] * 50}}}),
        ("keys at limit", {"chromosomes": {"visual": {f"k{i}": i for i in range(200)}}}),
        ("constraints at limit", {"constraints": [c(f"id{i}", "visual.color.ink", "REQUIRED") for i in range(200)]}),
        ("min contrast ratio bounds", {"constraints": [c("m1", "visual.color.ink", "MIN_CONTRAST", {"against": "visual.color.paper", "ratio": 1}),
                                                       c("m2", "visual.color.ink", "MIN_CONTRAST", {"against": "visual.color.paper", "ratio": 21.0})]}),
        ("range int and float mix", {"constraints": [c("r1", "visual.motion.speed", "RANGE", {"min": 1, "max": 1.0})]}),
        ("constraint id patterns", {"constraints": [c("a", "visual.x", "REQUIRED"), c("0.a-b_c", "visual.x", "REQUIRED"), c("a" * 80, "visual.x", "REQUIRED")]}),
        ("rationale at limit", {"constraints": [{**c("r", "visual.x", "REQUIRED"), "rationale": "é" * 500}]}),
        ("constraint key with trailing newline", {"constraints": [c("n", "visual.x\n", "REQUIRED")]}),
        ("every provenance kind", {"provenance": [{"key": "k", "kind": k} for k in ["USER_SUPPLIED", "IMPORTED", "INFERRED", "DEFAULTED", "UNRESOLVED"]]}),
    ]
    for note, doc in valid_docs:
        case("parse_document", lambda d=doc: doc_dump(g.GenomeDocument.model_validate(d)), {"input": doc}, note)
    bad_docs: list[tuple[str, Any]] = [
        ("wrong schema", {"schema_version": "amc-vnexus-genome/v2"}), ("extra field", {"chromosomes": {}, "extra": 1}),
        ("unknown chromosome", {"chromosomes": {"colour": {"a": 1}}}), ("bad key uppercase", {"chromosomes": {"visual": {"Color": 1}}}),
        ("bad key leading digit", {"chromosomes": {"visual": {"1a": 1}}}), ("bad key seven parts", {"chromosomes": {"visual": {"a.b.c.d.e.f.g": 1}}}),
        ("nan value", {"chromosomes": {"visual": {"a": float("nan")}}}), ("inf value ok", {"chromosomes": {"visual": {"a": float("inf")}}}),
        ("string too long", {"chromosomes": {"verbal": {"voice.long": "x" * 2001}}}), ("list too long", {"chromosomes": {"verbal": {"voice.l": ["a"] * 51}}}),
        ("list item too long", {"chromosomes": {"verbal": {"voice.l": ["a" * 301]}}}), ("list of numbers", {"chromosomes": {"verbal": {"voice.l": [1, 2]}}}),
        ("dict value", {"chromosomes": {"verbal": {"voice.l": {"a": 1}}}}), ("too many keys", {"chromosomes": {"visual": {f"k{i}": i for i in range(201)}}}),
        ("too many constraints", {"constraints": [c(f"id{i}", "visual.color.ink", "REQUIRED") for i in range(201)]}),
        ("duplicate constraint ids", {"constraints": [c("d", "visual.x", "REQUIRED"), c("d", "visual.y", "REQUIRED")]}),
        ("bad constraint key chromosome", {"constraints": [c("a", "colour.x", "REQUIRED")]}), ("bad constraint key no rest", {"constraints": [c("a", "visual", "REQUIRED")]}),
        ("bad constraint key rest", {"constraints": [c("a", "visual.X", "REQUIRED")]}), ("constraint id uppercase", {"constraints": [c("A", "visual.x", "REQUIRED")]}),
        ("constraint id trailing newline", {"constraints": [c("a\n", "visual.x", "REQUIRED")]}), ("constraint id too long", {"constraints": [c("a" * 81, "visual.x", "REQUIRED")]}),
        ("allowed values missing", {"constraints": [c("a", "visual.x", "ALLOWED_VALUES")]}), ("allowed values empty", {"constraints": [c("a", "visual.x", "ALLOWED_VALUES", {"values": []})]}),
        ("allowed values too many", {"constraints": [c("a", "visual.x", "ALLOWED_VALUES", {"values": list(range(101))})]}),
        ("range missing", {"constraints": [c("a", "visual.x", "RANGE")]}), ("range inverted", {"constraints": [c("a", "visual.x", "RANGE", {"min": 5, "max": 1})]}),
        ("range bool", {"constraints": [c("a", "visual.x", "RANGE", {"min": True, "max": 2})]}), ("range string", {"constraints": [c("a", "visual.x", "RANGE", {"min": "1", "max": 2})]}),
        ("contrast ratio too high", {"constraints": [c("a", "visual.x", "MIN_CONTRAST", {"against": "visual.y", "ratio": 21.5})]}),
        ("contrast ratio too low", {"constraints": [c("a", "visual.x", "MIN_CONTRAST", {"against": "visual.y", "ratio": 0.5})]}),
        ("contrast against not str", {"constraints": [c("a", "visual.x", "MIN_CONTRAST", {"against": 3, "ratio": 4})]}),
        ("contrast ratio bool", {"constraints": [c("a", "visual.x", "MIN_CONTRAST", {"against": "visual.y", "ratio": True})]}),
        ("params on immutable", {"constraints": [c("a", "visual.x", "IMMUTABLE", {"x": 1})]}), ("params on hex colour", {"constraints": [c("a", "visual.x", "HEX_COLOR", {"x": 1})]}),
        ("unknown kind", {"constraints": [c("a", "visual.x", "FROZEN")]}), ("unknown severity", {"constraints": [c("a", "visual.x", "REQUIRED", None, "FATAL")]}),
        ("rationale too long", {"constraints": [{**c("a", "visual.x", "REQUIRED"), "rationale": "x" * 501}]}), ("constraint extra", {"constraints": [{**c("a", "visual.x", "REQUIRED"), "z": 1}]}),
        ("provenance bad kind", {"provenance": [{"key": "k", "kind": "GUESSED"}]}), ("provenance note too long", {"provenance": [{"key": "k", "kind": "IMPORTED", "note": "n" * 301}]}),
        ("chromosomes not a dict", {"chromosomes": [1]}), ("constraints not a list", {"constraints": "no"}), ("two problems", {"chromosomes": {"visual": {"Bad": 1}}, "constraints": [c("a", "colour.x", "REQUIRED")]}),
        ("invalid key then too long value", {"chromosomes": {"visual": {"Bad": 1, "ok": "x" * 2001}}}),
    ]
    for note, doc in bad_docs:
        case("parse_document", lambda d=doc: doc_dump(g.GenomeDocument.model_validate(d)), {"input": doc}, note)
    for note, con in [("ok", c("a", "visual.x", "REQUIRED")), ("bad key", c("a", "x.y", "REQUIRED")), ("ranged", c("b", "visual.x", "RANGE", {"min": 0, "max": 1}))]:
        case("parse_constraint", lambda d=con: g.GenomeConstraint.model_validate(d).model_dump(mode="json"), {"input": con}, note)
    layer_inputs: list[tuple[str, Any]] = [
        ("ok", layer("brand", "b1", "APPROVED", {})), ("with version", layer("page", "p/x", "DRAFT", {}, version=3, version_id="v3")),
        ("empty scope_ref", layer("brand", "", "APPROVED", {})), ("bad scope", layer("planet", "x", "APPROVED", {})), ("bad status", layer("brand", "x", "LIVE", {})),
        ("long scope_ref", layer("brand", "é" * 300, "APPROVED", {})), ("too long scope_ref", layer("brand", "é" * 301, "APPROVED", {})),
        ("extra", {**layer("brand", "b", "APPROVED", {}), "z": 1}), ("missing document", {"scope": "brand", "scope_ref": "b", "status": "APPROVED"}),
    ]
    for note, inp in layer_inputs:
        case("parse_layer", lambda d=inp: g.GenomeLayer.model_validate(d).model_dump(mode="json"), {"input": inp}, note)
    lax: list[tuple[str, str, Any]] = [
        ("parse_layer", "version given as a numeric string", layer("brand", "b", "APPROVED", {}, version="3")),
        ("parse_layer", "version given as an integral float", layer("brand", "b", "APPROVED", {}, version=3.0)),
        ("parse_layer", "version given as a bool", layer("brand", "b", "APPROVED", {}, version=True)),
        ("parse_document", "integer beyond 2^53 as a value", {"chromosomes": {"visual": {"big": 2 ** 60}}}),
        ("parse_document", "integer beyond 2^63 as a value", {"chromosomes": {"visual": {"big": 2 ** 70}}}),
    ]
    for call, note, inp in lax:
        fn = (lambda d=inp: g.GenomeLayer.model_validate(d).model_dump(mode="json")) if call == "parse_layer" else (lambda d=inp: doc_dump(g.GenomeDocument.model_validate(d)))
        before = len(CASES)
        case(call, fn, {"input": inp}, note)
        CASES[before]["lax_divergence"] = True
    for action in ["submit", "approve", "reject", "withdraw", "supersede", "publish", "__proto__", "constructor", ""]:
        for status in ["DRAFT", "EXPERIMENTAL", "IN_REVIEW", "APPROVED", "REJECTED", "SUPERSEDED", "LIVE"]:
            case("next_status", lambda a=action, s=status: g.next_status(g.VersionStatus(s), a).value, {"current": status, "action": action})
    for scope, ref in [(s, x) for s in ["brand", "project", "page", "component", "asset"] for x in ["p1", "p1/a", "p1/a/b", "p1/a/b/c", "", "a b", "p1/", "p1/a\n", "é/x", "p1/a/b/c/d", "-x"]]:
        case("scope_ref_project", lambda s=scope, x=ref: g.scope_ref_project(g.Scope(s), x, brand_owner_project="owner"), {"scope": scope, "scope_ref": ref})
        case("ancestor_refs", lambda s=scope, x=ref: [[a.value, b] for a, b in g.ancestor_refs(g.Scope(s), x, "b1")], {"scope": scope, "scope_ref": ref})
    for chromosomes, flat in [("a", {"visual.color.ink": "#000000", "visual.color.paper": "#ffffff", "strategy.x": 1.0}), ("b", {"colour.x": 1}), ("c", {"visual.Bad": 1}), ("d", {})]:
        case("document_from_flat", lambda f=flat: doc_dump(g.document_from_flat(f)), {"flat": [[k, v] for k, v in flat.items()]}, chromosomes)
    for i in range(60):
        doc = rand_doc(r)
        case("parse_document", lambda d=doc: doc_dump(g.GenomeDocument.model_validate(d)), {"input": doc}, f"random {i}")
        case("self_check", lambda d=doc: [f.model_dump(mode="json") for f in g.self_check(g.GenomeDocument.model_validate(d))], {"document": doc}, f"random {i}")


def resolve_cases(r: random.Random) -> None:
    base = layer("brand", "b1", "APPROVED", {"visual": {"color.ink": "#101010", "color.paper": "#fafafa"}},
                 [c("lock", "visual.color.ink", "IMMUTABLE"), c("contrast", "visual.color.ink", "MIN_CONTRAST", {"against": "visual.color.paper", "ratio": 4.5})])
    scenarios: list[tuple[str, list[dict[str, Any]], Optional[str]]] = [
        ("no layers", [], None), ("single approved", [base], None),
        ("immutable override", [base, layer("project", "p1", "APPROVED", {"visual": {"color.ink": "#ff0000"}})], None),
        ("immutable same value", [base, layer("project", "p1", "APPROVED", {"visual": {"color.ink": "#101010"}})], None),
        ("immutable equal int float", [layer("brand", "b1", "APPROVED", {"production": {"output.dpi": 300}}, [c("l", "production.output.dpi", "IMMUTABLE")]),
                                       layer("project", "p1", "APPROVED", {"production": {"output.dpi": 300.0}})], None),
        ("contrast violation", [base, layer("project", "p1", "APPROVED", {"visual": {"color.paper": "#222222"}})], None),
        ("unapproved skipped", [base, layer("project", "p1", "DRAFT", {"visual": {"color.paper": "#ffffff"}})], None),
        ("preview applied", [base, layer("project", "p1", "DRAFT", {"visual": {"color.paper": "#ffffff"}})], "p1"),
        ("preview of approved is not a preview", [base, layer("project", "p1", "APPROVED", {"visual": {"color.paper": "#ffffff"}})], "p1"),
        ("preview unknown ref", [base], "nope"),
        ("scope order", [layer("page", "p1/a", "APPROVED", {"visual": {"color.paper": "#ffffff"}}), layer("project", "p1", "APPROVED", {"visual": {"color.ink": "#000000"}})], None),
        ("same scope twice", [layer("project", "p1", "APPROVED", {"visual": {"color.ink": "#000000"}}), layer("project", "p2", "APPROVED", {"visual": {"color.ink": "#111111"}})], None),
        ("constraint redefinition", [layer("brand", "b1", "APPROVED", {}, [c("x", "visual.a", "REQUIRED")]), layer("project", "p1", "APPROVED", {}, [c("x", "visual.a", "IMMUTABLE")])], None),
        ("constraint same redefinition", [layer("brand", "b1", "APPROVED", {}, [c("x", "visual.a", "REQUIRED")]), layer("project", "p1", "APPROVED", {}, [c("x", "visual.a", "REQUIRED")])], None),
        ("required missing", [layer("brand", "b1", "APPROVED", {}, [c("req", "visual.color.ink", "REQUIRED")])], None),
        ("constrained key missing", [layer("brand", "b1", "APPROVED", {}, [c("r", "visual.color.ink", "HEX_COLOR")])], None),
        ("contrast pair not colours", [layer("brand", "b1", "APPROVED", {"visual": {"color.ink": "red", "color.paper": "#ffffff"}}, [c("m", "visual.color.ink", "MIN_CONTRAST", {"against": "visual.color.paper", "ratio": 4.5})])], None),
        ("contrast value none", [layer("brand", "b1", "APPROVED", {"visual": {"color.ink": None, "color.paper": "#ffffff"}}, [c("m", "visual.color.ink", "MIN_CONTRAST", {"against": "visual.color.paper", "ratio": 4.5})])], None),
        ("allowed list value", [layer("brand", "b1", "APPROVED", {"verbal": {"voice.tone": ["warm", "x"]}}, [c("a", "verbal.voice.tone", "ALLOWED_VALUES", {"values": ["warm", "calm"]})])], None),
        ("allowed bool vs int", [layer("brand", "b1", "APPROVED", {"production": {"output.flag": True}}, [c("a", "production.output.flag", "ALLOWED_VALUES", {"values": [1, "x"]})])], None),
        ("range bool value", [layer("brand", "b1", "APPROVED", {"production": {"output.n": True}}, [c("a", "production.output.n", "RANGE", {"min": 0, "max": 5})])], None),
        ("range string value", [layer("brand", "b1", "APPROVED", {"production": {"output.n": "3"}}, [c("a", "production.output.n", "RANGE", {"min": 0, "max": 5})])], None),
        ("range float boundary", [layer("brand", "b1", "APPROVED", {"production": {"output.n": 5.0}}, [c("a", "production.output.n", "RANGE", {"min": 0.5, "max": 5})])], None),
        ("range outside float", [layer("brand", "b1", "APPROVED", {"production": {"output.n": 7.0}}, [c("a", "production.output.n", "RANGE", {"min": 0.5, "max": 5.0})])], None),
        ("range outside list", [layer("brand", "b1", "APPROVED", {"production": {"output.n": ["a"]}}, [c("a", "production.output.n", "RANGE", {"min": 0, "max": 5})])], None),
        ("hex trailing newline", [layer("brand", "b1", "APPROVED", {"visual": {"color.ink": "#aabbcc\n", "color.paper": "#ffffff"}},
                                         [c("h", "visual.color.ink", "HEX_COLOR"), c("m", "visual.color.ink", "MIN_CONTRAST", {"against": "visual.color.paper", "ratio": 1.5})])], None),
        ("hex uppercase", [layer("brand", "b1", "APPROVED", {"visual": {"color.ink": "#AABBCC"}}, [c("h", "visual.color.ink", "HEX_COLOR")])], None),
        ("contrast ratio decimal in message", [layer("brand", "b1", "APPROVED", {"visual": {"color.ink": "#777777", "color.paper": "#ffffff"}},
                                                     [c("m", "visual.color.ink", "MIN_CONTRAST", {"against": "visual.color.paper", "ratio": 4.6})])], None),
        ("contrast ratio int in message", [layer("brand", "b1", "APPROVED", {"visual": {"color.ink": "#777777", "color.paper": "#ffffff"}},
                                                 [c("m", "visual.color.ink", "MIN_CONTRAST", {"against": "visual.color.paper", "ratio": 7})])], None),
        ("contrast ratio 21 float message", [layer("brand", "b1", "APPROVED", {"visual": {"color.ink": "#ffffff", "color.paper": "#ffffff"}},
                                                   [c("m", "visual.color.ink", "MIN_CONTRAST", {"against": "visual.color.paper", "ratio": 21.0})])], None),
        ("unicode scope refs", [layer("brand", "é", "APPROVED", {"visual": {"a": "x"}}), layer("project", "日本/x", "DRAFT", {"visual": {"a": "y"}})], "日本/x"),
        ("severity levels", [layer("brand", "b1", "APPROVED", {}, [c(f"s{i}", "visual.q", "REQUIRED", None, sev) for i, sev in enumerate(["INFO", "WARNING", "ERROR", "BLOCKING"])])], None),
    ]
    for note, layers, preview in scenarios:
        case("resolve", lambda L=layers, p=preview: resolve_out(L, p), {"layers": layers, "preview_ref": preview}, note)
    for i in range(110):
        layers = rand_layers(r)
        refs = [x["scope_ref"] for x in layers]
        preview = r.choice(refs + [None, None]) if r.random() < 0.4 else None
        case("resolve", lambda L=layers, p=preview: resolve_out(L, p), {"layers": layers, "preview_ref": preview}, f"random {i}")
    for i in range(80):
        vals = {k: r.choice(POOLS[k]) for k in r.sample(KEYS, k=r.randint(1, 6))}
        cons = [g.GenomeConstraint.model_validate(rand_constraint(r)) for _ in range(r.randint(1, 4))]
        cons = list({x.constraint_id: x for x in cons}.values())
        owner = {x.constraint_id: r.choice(["b1", "p1"]) for x in cons} if r.random() < 0.5 else None
        case("evaluate_constraints", lambda v=vals, cs=cons, o=owner: [f.model_dump(mode="json") for f in g.evaluate_constraints(v, cs, o)],
             {"values": vals, "constraints": [x.model_dump(mode="json") for x in cons], "owner": owner}, f"random {i}")


def mutate(r: random.Random, doc: dict[str, Any]) -> dict[str, Any]:
    out = json.loads(json.dumps(doc))
    for _ in range(r.randint(0, 3)):
        key = r.choice(KEYS)
        head, _, rest = key.partition(".")
        op = r.choice(["set", "set", "del", "con", "delcon", "modcon"])
        if op == "set":
            out["chromosomes"].setdefault(head, {})[rest] = r.choice(POOLS[key])
        elif op == "del" and out["chromosomes"].get(head):
            out["chromosomes"][head].pop(r.choice(list(out["chromosomes"][head])), None)
        elif op == "con":
            cc = rand_constraint(r)
            out["constraints"] = [x for x in out["constraints"] if x["constraint_id"] != cc["constraint_id"]] + [cc]
        elif op == "delcon" and out["constraints"]:
            out["constraints"].pop(r.randrange(len(out["constraints"])))
        elif op == "modcon" and out["constraints"]:
            out["constraints"][0] = {**out["constraints"][0], "severity": r.choice(["INFO", "ERROR"])}
    return out


def diff_cases(r: random.Random) -> None:
    for i in range(100):
        a = rand_doc(r)
        b = mutate(r, a) if r.random() < 0.7 else rand_doc(r)
        case("diff_documents", lambda x=a, y=b: _diff(x, y), {"before": a, "after": b}, f"random {i}")


def _diff(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    d = g.diff_documents(g.GenomeDocument.model_validate(a), g.GenomeDocument.model_validate(b))
    return {"diff": d.model_dump(mode="json"), "is_empty": d.is_empty}


# --------------------------------------------------------------------------- graph

KINDS = [k.value for k in gr.NodeKind]
EDGE_KINDS = [k.value for k in gr.EdgeKind]


def rand_graph(r: random.Random) -> dict[str, Any]:
    n = r.randint(3, 11)
    nodes = []
    for i in range(n):
        kind = r.choice(KINDS)
        start = f"2026-0{r.randint(1, 5)}-0{r.randint(1, 9)}T00:00:00Z"
        end = r.choice([None, None, f"2026-0{r.randint(6, 9)}-1{r.randint(0, 9)}T12:00:00Z"])
        node = {"node_id": f"n{i}", "kind": kind, "label": r.choice(["alpha", "béta", "γ"]), "attributes": r.choice([{}, {"k": 1}, {"f": 2.0, "l": [1, "a"]}]),
                "content_hash": r.choice(["", "h1", "h2"]), "valid_from": start, "valid_to": end, "superseded_by": None}
        nodes.append(node)
    for i in range(1, n):  # an acyclic supersession chain among same-kind nodes
        if r.random() < 0.25:
            nodes[i - 1]["superseded_by"] = f"n{i}"
    edges = []
    for j in range(r.randint(2, 16)):
        a, b = r.sample(range(n), 2)
        edges.append({"edge_id": f"e{r.randint(0, 99):02d}-{j}", "kind": r.choice(EDGE_KINDS), "src_node_id": f"n{a}", "dst_node_id": f"n{b}",
                      "provenance": r.choice([{}, {"by": "x"}]), "valid_from": f"2026-0{r.randint(1, 3)}-01T00:00:00Z",
                      "valid_to": r.choice([None, None, None, "2026-08-01T00:00:00Z"])})
    if r.random() < 0.2 and len(edges) > 2:  # extra edge making a cycle on purpose
        edges.append({"edge_id": "ecycle1", "kind": "DEPENDS_ON", "src_node_id": "n0", "dst_node_id": "n1", "provenance": {}, "valid_from": "2026-01-01T00:00:00Z", "valid_to": None})
        edges.append({"edge_id": "ecycle2", "kind": "DEPENDS_ON", "src_node_id": "n1", "dst_node_id": "n0", "provenance": {}, "valid_from": "2026-01-01T00:00:00Z", "valid_to": None})
    return {"nodes": nodes, "edges": edges}


def build_graph(index: int, as_of: Optional[str]) -> gr.Graph:
    spec = GRAPHS[index]
    return gr.Graph([gr.Node.model_validate(x) for x in spec["nodes"]], [gr.Edge.model_validate(x) for x in spec["edges"]], as_of=as_of)


def graph_view(index: int, as_of: Optional[str]) -> dict[str, Any]:
    grp = build_graph(index, as_of)
    return {"nodes": list(grp.nodes), "all_nodes": list(grp.all_nodes), "edges": [e.edge_id for e in grp.edges], "all_edges": [e.edge_id for e in grp.all_edges],
            "cycles": grp.find_cycles(), "snapshot": grp.snapshot()}


def graph_cases(r: random.Random) -> None:
    for gi in range(34):
        GRAPHS.append(rand_graph(r))
        ids = [x["node_id"] for x in GRAPHS[gi]["nodes"]]
        for as_of in [None, "2026-02-15T00:00:00Z", "2026-07-01T00:00:00Z", "2026-12-31T00:00:00Z", "2025-01-01T00:00:00Z"]:
            case("graph_view", lambda i=gi, a=as_of: graph_view(i, a), {"graph": gi, "as_of": as_of})
            case("graph_upstream", lambda i=gi, a=as_of: build_graph(i, a).upstream("n0"), {"graph": gi, "as_of": as_of, "node": "n0"})
        for q in range(4):
            as_of = r.choice([None, "2026-02-15T00:00:00Z", "2026-07-01T00:00:00Z"])
            changed = r.sample(ids + ["ghost"], k=r.randint(0, 3)) + ([ids[0]] if r.random() < 0.2 else [])
            case("graph_impact", lambda i=gi, a=as_of, ch=changed: build_graph(i, a).impact(ch), {"graph": gi, "as_of": as_of, "changed": changed})
            node = r.choice(ids + ["ghost"])
            case("graph_evidence", lambda i=gi, a=as_of, nd=node: build_graph(i, a).evidence_for(nd), {"graph": gi, "as_of": as_of, "node": node})
            case("graph_history", lambda i=gi, nd=node: build_graph(i, None).history(nd), {"graph": gi, "as_of": None, "node": node})
            for _ in range(3):
                kind, a, b = r.choice(EDGE_KINDS), r.choice(ids + ["ghost"]), r.choice(ids)
                case("graph_check_edge", lambda i=gi, ak=as_of, k=kind, s=a, d=b: build_graph(i, ak).check_edge(gr.EdgeKind(k), s, d),
                     {"graph": gi, "as_of": as_of, "kind": kind, "src": a, "dst": b})
    pairs = [(0, 1), (2, 3), (4, 5)]
    for a, b in pairs:
        for ta, tb in [(None, "2026-07-01T00:00:00Z"), ("2026-02-15T00:00:00Z", None)]:
            case("graph_diff_snapshots", lambda x=a, y=b, p=ta, q=tb: gr.diff_snapshots(build_graph(x, p).snapshot(), build_graph(y, q).snapshot()),
                 {"a": a, "b": b, "as_of_a": ta, "as_of_b": tb})
    for kind in KINDS:
        case("node_hash", lambda k=kind: gr.node_hash(gr.NodeKind(k), "label é", {"a": 1, "b": 2.0, "c": [True, None]}), {"kind": kind})
    for rec, as_of in [({"valid_from": "2026-01-01", "valid_to": None}, None), ({"valid_from": "2026-01-01", "valid_to": "2026-02-01"}, None),
                       ({"valid_from": "2026-01-01", "valid_to": "2026-02-01"}, "2026-02-01"), ({"valid_from": "2026-01-01", "valid_to": None}, "2026-01-01"),
                       ({"valid_from": "2026-01-01", "valid_to": ""}, "2026-01-01"), ({"valid_from": "𝒜", "valid_to": None}, "￿"),
                       ({"valid_from": "￿", "valid_to": None}, "𝒜")]:
        case("valid_at", lambda x=rec, a=as_of: gr.valid_at(gr.Node.model_validate({"node_id": "n", "kind": "Brand", "label": "l", **x}), a), {"record": rec, "as_of": as_of})
    for note, nd in [("missing label", {"node_id": "n", "kind": "Brand"}), ("bad kind", {"node_id": "n", "kind": "Thing", "label": "l", "valid_from": "x"}),
                     ("extra ignored", {"node_id": "n", "kind": "Brand", "label": "l", "valid_from": "x", "zzz": 1}), ("attributes not a dict", {"node_id": "n", "kind": "Brand", "label": "l", "valid_from": "x", "attributes": []})]:
        case("parse_node", lambda d=nd: gr.Node.model_validate(d).model_dump(mode="json"), {"input": nd}, note)
    for note, ed in [("ok", {"edge_id": "e", "kind": "DEPENDS_ON", "src_node_id": "a", "dst_node_id": "b", "valid_from": "x"}), ("bad kind", {"edge_id": "e", "kind": "LIKES", "src_node_id": "a", "dst_node_id": "b", "valid_from": "x"})]:
        case("parse_edge", lambda d=ed: gr.Edge.model_validate(d).model_dump(mode="json"), {"input": ed}, note)


# --------------------------------------------------------------------------- multiverse


def rand_changes(r: random.Random, doc: dict[str, Any]) -> dict[str, Any]:
    flat = list(g.GenomeDocument.model_validate(doc).flatten())
    sets = {}
    for _ in range(r.randint(0, 3)):
        key = r.choice(KEYS)
        sets[key] = r.choice(POOLS[key])
    if r.random() < 0.08:
        sets["visual.Bad"] = 1
    unset = [k for k in r.sample(flat, k=min(len(flat), r.randint(0, 2))) if k not in sets] if flat else []
    if r.random() < 0.1:
        unset.append("visual.ghost")
    adds = [rand_constraint(r) for _ in range(r.randint(0, 2))]
    adds = list({x["constraint_id"]: x for x in adds}.values())
    removes = [x["constraint_id"] for x in doc["constraints"] if r.random() < 0.3]
    if r.random() < 0.1:
        removes.append("ghost")
    return {"set": sets, "unset": unset, "add_constraints": adds, "remove_constraints": removes}


def cs(d: dict[str, Any]) -> mv.ChangeSet:
    return mv.ChangeSet.model_validate(d)


def changeset_out(x: mv.ChangeSet) -> dict[str, Any]:
    return {"dump": x.model_dump(mode="json"), "hash": x.changes_hash}


def multiverse_cases(r: random.Random) -> None:
    for action in ["submit", "withdraw", "promote", "reject", "archive", "merge", ""]:
        for state in ["OPEN", "IN_REVIEW", "PROMOTED", "REJECTED", "ARCHIVED", "BOGUS"]:
            case("next_branch_state", lambda a=action, s=state: mv.next_branch_state(mv.BranchState(s), a).value, {"current": state, "action": action})
    for note, d in [("empty", {}), ("full", {"set": {"visual.a": 1.0}, "unset": ["visual.b"], "add_constraints": [c("a", "visual.a", "REQUIRED")], "remove_constraints": ["z"]}),
                    ("set and unset", {"set": {"visual.a": 1}, "unset": ["visual.a"]}), ("add and remove", {"add_constraints": [c("a", "visual.a", "REQUIRED")], "remove_constraints": ["a"]}),
                    ("too many", {"set": {f"visual.k{i}": i for i in range(401)}}), ("at limit", {"set": {f"visual.k{i}": i for i in range(400)}}),
                    ("unset duplicates", {"unset": ["visual.a"] * 401}), ("extra", {"zzz": 1}), ("bad value", {"set": {"visual.a": {"x": 1}}})]:
        case("parse_changeset", lambda d=d: changeset_out(cs(d)), {"input": d}, note)
    for i in range(55):
        base = rand_doc(r)
        ch = rand_changes(r, base)
        case("apply_changes", lambda b=base, c_=ch: doc_dump(mv.apply_changes(g.GenomeDocument.model_validate(b), cs(c_))), {"base": base, "changes": ch}, f"random {i}")
        ch2 = rand_changes(r, base)
        case("compose", lambda a=ch, b=ch2: changeset_out(mv.compose(cs(a), cs(b))), {"parent": ch, "child": ch2}, f"random {i}")
        case("compare_branches", lambda a=ch, b=ch2: mv.compare_branches(cs(a), cs(b)), {"a": ch, "b": ch2}, f"random {i}")
        case("merge_change_sets", lambda a=ch, b=ch2: _merge(a, b), {"a": ch, "b": ch2}, f"random {i}")
        new_base = mutate(r, base)
        case("rebase", lambda o=base, n=new_base, c_=ch: _rebase(o, n, c_), {"old_base": base, "new_base": new_base, "changes": ch}, f"random {i}")
        ancestors = [x for x in rand_layers(r)[:2] if x["scope"] in ("brand", "project")]
        for x in ancestors:
            x["status"] = "APPROVED"
        scope = r.choice(["page", "component", "asset"]) if r.random() < 0.9 else "planet"
        ref = {"page": "p1/home", "component": "p1/home/hero", "asset": "p1/home/hero/img", "planet": "p1/x"}[scope]
        case("compare_with_base", lambda b=base, c_=ch, a=ancestors, s=scope, rf=ref: _cwb(b, c_, a, rf, s), {"base": base, "changes": ch, "ancestors": ancestors, "scope_ref": ref, "scope": scope}, f"random {i}")


def _merge(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    merged, report = mv.merge_change_sets(cs(a), cs(b))
    return {"merged": changeset_out(merged) if merged else None, "report": report}


def _rebase(o: dict[str, Any], n: dict[str, Any], c_: dict[str, Any]) -> dict[str, Any]:
    out, report = mv.rebase(g.GenomeDocument.model_validate(o), g.GenomeDocument.model_validate(n), cs(c_))
    conflicts = report["conflicts"]
    if any("validation error" in x for x in conflicts):
        report = {**report, "conflicts": ["<apply error>"]}
    return {"changes": changeset_out(out) if out else None, "report": report}


def _cwb(b: dict[str, Any], c_: dict[str, Any], a: list[dict[str, Any]], ref: str, scope: str) -> dict[str, Any]:
    return mv.compare_with_base(g.GenomeDocument.model_validate(b), cs(c_), [g.GenomeLayer.model_validate(x) for x in a], scope_ref=ref, scope=scope)


# --------------------------------------------------------------------------- immune / colour

HEX_DIGITS = "0123456789abcdefABCDEF"


def rand_hex(r: random.Random) -> str:
    return "#" + "".join(r.choice(HEX_DIGITS[:16]) for _ in range(6))


def near(r: random.Random, colour: str, spread: int) -> str:
    chans = [max(0, min(255, int(colour[i:i + 2], 16) + r.randint(-spread, spread))) for i in (1, 3, 5)]
    return "#" + "".join(f"{x:02x}" for x in chans)


def colour_cases(r: random.Random) -> None:
    fixed = ["#000000", "#ffffff", "#777777", "#767676", "#0a66c2", "#ff00ff", "#00ff00", "#010101", "#fefefe", "#808080"]
    for a in fixed:
        for b in fixed:
            case("wcag_contrast_ratio", lambda x=a, y=b: wcag_contrast_ratio(x, y), {"a": a, "b": b})
            case("delta_e76", lambda x=a, y=b: delta_e76(x, y), {"a": a, "b": b})
    for i in range(800):
        a = rand_hex(r)
        b = near(r, a, r.choice([2, 6, 20, 90])) if i % 2 else rand_hex(r)
        case("wcag_contrast_ratio", lambda x=a, y=b: wcag_contrast_ratio(x, y), {"a": a, "b": b})
        case("delta_e76", lambda x=a, y=b: delta_e76(x, y), {"a": a, "b": b})
    for text in ["", "no colours", "#abcdef", "#ABCDEF #abcdef", "#abcdefa", "#abcde", "#abcdef_", "#abcdefé", "#abcdef-x", "x#abcdef", "#abcdef\n#012345", "#ABCDEF٣", "#abcdef²", "#abcdef ",
                 'fill="#FFAA00" stroke="#ffaa00"', "#12345g", "##123456", "#1234567890", "#abcdefK", "#abcdef٠", "#abcdef​"]:
        case("colors_in", lambda t=text: list(colors_in(t)), {"text": text})
    for c1 in range(256):
        case("wcag_contrast_ratio", lambda x=c1: wcag_contrast_ratio("#%02x%02x%02x" % (x, x, x), "#ffffff"), {"a": "#%02x%02x%02x" % (c1, c1, c1), "b": "#ffffff"})


def svg(r: random.Random, palette: list[str]) -> str:
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{r.choice([100, 1080, 1200])}" height="{r.choice([100, 1080, 630])}">']
    if r.random() < 0.8:
        parts.append(f'<rect width="100" height="100" fill="{r.choice(palette + ["#ffffff"])}"/>')
    for _ in range(r.randint(0, 4)):
        colour = r.choice(palette + [near(r, r.choice(palette), 4), near(r, r.choice(palette), 30), rand_hex(r)])
        if r.random() < 0.3:
            colour = colour.upper()
        family = r.choice(["Inter, sans-serif", "Georgia, serif", "Papyrus, fantasy", "monospace", "Comic Sans MS"])
        parts.append(f'<text x="1" y="2" fill="{colour}" font-family="{family}">hi</text>')
        if r.random() < 0.3:
            parts.append(f'<path fill="{colour}" stroke="{r.choice(palette)}"/>')
    parts.append("</svg>")
    return "".join(parts)


def immune_cases(r: random.Random) -> None:
    for code, sev in [("A", "ERROR"), ("B", "INFO")]:
        case("finding", lambda c_=code, s=sev: immune.finding(c_, s, "subj é", "detail", evidence={"x": 1.0, "y": [1, 2]}, remediation={"kind": "K"}), {"code": code, "severity": sev, "subject": "subj é", "detail": "detail", "evidence": {"x": 1.0, "y": [1, 2]}, "remediation": {"kind": "K"}})
    case("finding", lambda: immune.finding("A", "ERROR", "s", "d"), {"code": "A", "severity": "ERROR", "subject": "s", "detail": "d", "evidence": None, "remediation": None})
    palettes = [["#101010", "#fafafa", "#0a66c2", "#e63946"], ["#000000", "#ffffff"], ["#777777"], []]
    for i in range(100):
        palette = r.choice(palettes)
        markup = svg(r, palette or ["#123456"])
        fonts = set(r.choice([["Inter"], ["Inter", "Georgia"], [], ["Papyrus"]]))
        expected = r.choice([None, (1080, 1080), (1200, 630), (100, 100)])
        args = {"name": f"out-{i}.svg", "svg": markup, "palette": {f"c{j}": p for j, p in enumerate(palette)}, "fonts": sorted(fonts), "expected": list(expected) if expected else None}
        case("svg_findings", lambda a=args, f=fonts, e=expected: immune.svg_findings(a["name"], a["svg"], palette=a["palette"], fonts=f, expected=e), args, f"random {i}")
    odd = ['<svg width="٣٠" height="٤٠"></svg>', '<svg\twidth="10"\nheight="20"></svg>', '<svg width="10" height="20"></svg>', '<svg width="99999999999999999999" height="1"></svg>',
           '<svg width="1" height="2"><text fill="#000000">x</text><rect width="1" height="2" fill="#000001"/></svg>', '<svg width="1"><rect width="٣" height="4" fill="#ffffff"/><text fill="#fefefe">a</text></svg>',
           '<text ﻿fill="#000000">x</text><rect width="1" height="1" fill="#000000"/>', '<text fill="#AABBCC" font-family="Inter">x</text><rect width="1" height="1" fill="#aabbcc"/>',
           '<text font-family="\'Inter\', sans-serif" x="1">a</text>', '<text font-family=" Inter , serif" x="1">a</text>', '<text font-family="Inter">a</text><text font-family="Georgia">b</text>']
    for markup in odd:
        for exp in [None, (30, 40), (10, 20)]:
            args = {"name": "odd.svg", "svg": markup, "palette": {"a": "#000000", "b": "#ffffff"}, "fonts": ["Georgia"], "expected": list(exp) if exp else None}
            case("svg_findings", lambda a=args, e=exp: immune.svg_findings(a["name"], a["svg"], palette=a["palette"], fonts=set(a["fonts"]), expected=e), args, "odd markup")
    for data in [b"", b"\x89PNG\r\n\x1a\n", b"\x89PNG\r\n\x1a\n" + bytes(8) + (1080).to_bytes(4, "big") + (1920).to_bytes(4, "big"), b"\x89PNG\r\n\x1a\n" + bytes(8) + b"\x01\x02",
                 b"GIF89a" + bytes(30), b"\x89PNG\r\n\x1a\n" + bytes(8) + b"\xff\xff\xff\xff" + b"\xff\xff\xff\xff", b"\x89PNG\r\n\x1a"]:
        case("png_dims", lambda d=data: immune.png_dims(d), {"hex": data.hex()})
    for i in range(30):
        svg_text = svg(r, ["#aabbcc", "#AABBCC", "#112233"])
        swaps = r.choice([{"#aabbcc": "#abbacc"}, {"#aabbcc": "#000000", "#112233": "#ffffff"}, {}, {"#AABBCC": "#010203"}, {"#nothere": "#ffffff"}])
        case("snap_colours", lambda s=svg_text, w=swaps: immune.snap_colours(s, w), {"svg": svg_text, "swaps": swaps}, f"random {i}")
    for markup, swaps, note in [("a.b", {".": "-"}, "regex metacharacter"), ("price $5", {"$5": "$6"}, "dollar"), ("x", {"": "-"}, "empty pattern"), ("abc", {"b": "$&"}, "template-like dollar replacement")]:
        case("snap_colours", lambda s=markup, w=swaps: immune.snap_colours(s, w), {"svg": markup, "swaps": swaps}, note)
    for markup, swaps, note in [("a\\b", {"a": "\\g<0>x"}, "backslash replacement"), ("é", {"é": "e"}, "non-ascii"), ("\u212a s i", {"k": "x"}, "kelvin sign in text")]:
        before = len(CASES)
        case("snap_colours", lambda s=markup, w=swaps: immune.snap_colours(s, w), {"svg": markup, "swaps": swaps}, note)
        CASES[before]["snap_refusal"] = True
    for i in range(22):
        layers = rand_layers(r)
        res = g.resolve([g.GenomeLayer.model_validate(x) for x in layers])
        case("immune_genome", lambda res=res: {"findings": immune.genome_findings(res), "palette": immune.palette_from(res), "fonts": sorted(immune.approved_fonts(res))}, {"layers": layers}, f"random {i}")


# --------------------------------------------------------------------------- marketing, art director, prompt genome


def marketing_cases(r: random.Random) -> None:
    for i in range(400):
        p1 = r.choice([r.random(), r.random() * 0.1, 0.5, 0.0005, 0.9, 0.99, 1e-9])
        lift = r.choice([0.1, 0.05, 0.5, 1.0, 2.0, r.random() * 2, 0.01, 1e-9, 5.0, -0.5])
        alpha = r.choice([0.05, 0.01, 0.1, 0.001, r.random() * 0.4, 0.5, 1e-9])
        power = r.choice([0.8, 0.9, 0.95, 0.6, r.random() * 0.49 + 0.51, 0.999999, 1.0, 0.0])
        case("sample_size", lambda a=p1, b=lift, c_=alpha, d=power: marketing.sample_size_per_arm(a, b, alpha=c_, power=d), {"p1": p1, "lift": lift, "alpha": alpha, "power": power}, f"random {i}")
    case("sample_size", lambda: marketing.sample_size_per_arm(0.1, 1e-17, alpha=0.05, power=0.8), {"p1": 0.1, "lift": 1e-17, "alpha": 0.05, "power": 0.8}, "zero gap")
    for i in range(700):
        p = r.choice([r.random(), r.random() * 0.1, 1 - r.random() * 0.1, r.random() * 1e-6, 0.5, 0.975, 0.025, 0.8, 0.9])
        if p <= 0.0 or p >= 1.0:
            continue
        case("inv_cdf", lambda x=p: statistics.NormalDist().inv_cdf(x), {"p": p}, f"random {i}")
    for p in [0.0, 1.0, -0.5, 1.5, 0.5, 1e-300, 1 - 1e-16]:
        case("inv_cdf", lambda x=p: statistics.NormalDist().inv_cdf(x), {"p": p}, "edge")
    for i in range(700):
        x = r.choice([r.random(), r.random() * 1e-3, 1 - r.random() * 0.1, r.random() * 1e-9, 1.0 + r.random(), r.random() * 100])
        if x > 0:
            case("log", lambda v=x: math.log(v), {"x": x}, f"random {i}")
    bases = [None, "", "https://example.com/p", "https://example.com/p?x=1", "https://example.com/?"]
    for ch in ["social_feed", "social_story", "email", "web_landing", "search", "video"]:
        for base in bases:
            for content in ["a-b", "café & crème", "x=1&y=2", "!*'()~_.-", "日本語", "a b/c?d#e"]:
                case("utm", lambda c_=ch, b=base, t=content: _utm(c_, b, t), {"campaign": "camp-1", "channel": ch, "content": content, "base": base})
    for aud, rate, src in [(1000, 0.05, "last quarter"), (1, 0.5, "s"), (10000, 0.001, "survey"), (500, 0.3333, "x"), (123456, 0.0123, "é"), (0, 0.5, "s"), (10, 0.0, "s"), (10, 1.0, "s"), (10, 0.5, ""),
                          (10, 0.5, "  \t"), (10, 0.5, " "), (10, 0.5, "​"), (100, 0.01, "s"), (3, 0.999, "s"), (7, 1e-9, "s"), (-5, 0.5, "s")]:
        case("forecast", lambda a=aud, b=rate, s=src: marketing.forecast(audience_size=a, assumed_rate=b, assumption_source=s), {"audience_size": aud, "assumed_rate": rate, "source": src})
    for i in range(60):
        aud = r.choice([r.randint(1, 100000), r.randint(1, 50)])
        rate = r.choice([r.random(), r.random() * 0.1, 0.5])
        if 0 < rate < 1:
            case("forecast", lambda a=aud, b=rate: marketing.forecast(audience_size=a, assumed_rate=b, assumption_source="src"), {"audience_size": aud, "assumed_rate": rate, "source": "src"}, f"random {i}")
    plan = {"campaign_ref": "camp-1", "measurement_contracts": [
        {"name": "ctr", "numerator_event": "click", "denominator_event": "impression"}, {"name": "signups", "numerator_event": "signup", "denominator_event": None},
        {"name": "empty_den", "numerator_event": "click", "denominator_event": ""}, {"name": "unseen", "numerator_event": "ghost", "denominator_event": "ghost2"}]}
    sets: list[tuple[str, list[dict[str, Any]]]] = [
        ("none", []), ("click only", [{"metric": "click", "value": 10, "source": "ga"}]),
        ("click and impression", [{"metric": "click", "value": 10, "source": "ga"}, {"metric": "impression", "value": 400, "source": "ads"}, {"metric": "click", "value": 5.5, "source": "ga"}]),
        ("zero denominator", [{"metric": "click", "value": 3, "source": "ga"}, {"metric": "impression", "value": 0, "source": "ads"}]),
        ("integral float sums", [{"metric": "signup", "value": 1.5, "source": "crm"}, {"metric": "signup", "value": 1.5, "source": "crm"}]),
        ("bool values", [{"metric": "signup", "value": True, "source": "z"}]), ("many sources", [{"metric": "signup", "value": i, "source": s} for i, s in enumerate(["b", "a", "é", "b"])]),
        ("rate rounding", [{"metric": "click", "value": 1, "source": "a"}, {"metric": "impression", "value": 3, "source": "b"}]),
        ("tiny rate", [{"metric": "click", "value": 1, "source": "a"}, {"metric": "impression", "value": 7000000, "source": "b"}]),
        ("missing source", [{"metric": "click", "value": 1}]), ("missing metric", [{"value": 1, "source": "a"}]), ("missing value", [{"metric": "click", "source": "a"}]),
        ("string value", [{"metric": "click", "value": "3.5", "source": "a"}])]
    for note, ms in sets:
        before = len(CASES)
        case("report", lambda m=ms: marketing.report(plan, m), {"plan": plan, "measurements": ms}, note)
        if note == "string value":
            CASES[before]["lax_divergence"] = True
    case("report", lambda: marketing.report({"campaign_ref": "x"}, []), {"plan": {"campaign_ref": "x"}, "measurements": []}, "plan without contracts")


def _utm(channel: str, base: Optional[str], content: str) -> dict[str, Any]:
    return marketing.utm("camp-1", marketing.Channel(channel), content, base)


def art_cases(r: random.Random) -> None:
    for medium in [m.value for m in art_director.Medium]:
        case("rubric", lambda m=medium: art_director.rubric(art_director.Medium(m)), {"medium": medium})
    rb = art_director.rubric(art_director.Medium.WEB)
    names = [x["criterion"] for x in rb]
    for i in range(40):
        ev = {n: {"passed": r.random() < 0.6, "detail": r.choice(["ok", "é", ""])} for n in r.sample(names, k=r.randint(0, len(names)))}
        if r.random() < 0.2:
            ev["visual_coherence"] = {"passed": True}
        if r.random() < 0.2 and ev:
            ev[next(iter(ev))].pop("detail", None)
        case("score", lambda e=ev: art_director.score({"rubric": rb}, e), {"rubric": rb, "evidence": ev}, f"random {i}")
    case("score", lambda: art_director.score({"rubric": rb}, {"legibility": {"detail": "x"}}), {"rubric": rb, "evidence": {"legibility": {"detail": "x"}}}, "missing passed")
    for name, spec in art_director.PLATFORM_PRESETS.items():
        case("platform_preset", lambda n=name: art_director.PLATFORM_PRESETS[n], {"name": name})


def prompt_cases(r: random.Random) -> None:
    sets: list[list[dict[str, Any]]] = [
        [], [{"kind": "IMMUTABLE", "key": "visual.color.ink", "params": {}}], [{"kind": "ALLOWED_VALUES", "key": "visual.typography.display", "params": {"values": ["Inter", "Georgia"]}}],
        [{"kind": "MIN_CONTRAST", "key": "visual.color.ink", "params": {"against": "visual.color.paper", "ratio": 4.5}}, {"kind": "MIN_CONTRAST", "key": "visual.color.ink", "params": {"against": "visual.color.paper", "ratio": 7}},
         {"kind": "REQUIRED", "key": "x.y", "params": {}}, {"kind": "IMMUTABLE", "key": "visual.color.ink", "params": {}}, {"kind": "IMMUTABLE", "key": "visual.color.ink", "params": {}}],
        [{"kind": "ALLOWED_VALUES", "key": "k.é", "params": {"values": [1, 2.0, "x", True]}}],
    ]
    for ss in sets:
        case("inherited_constraints", lambda s=ss: prompt_genome.inherited_constraints(s), {"constraints": ss})
    packages = [{"generic_master_prompt": "m", "asset_spec": {"production": {"width": 100, "height": 0, "fps": 24, "aspect_ratio": "16:9", "duration_seconds": 1.5}, "negative_constraints": ["a", "b"]}},
                {"generic_master_prompt": "m"}, {"asset_spec": {"production": {}, "negative_constraints": None}}, {"generic_master_prompt": "é", "asset_spec": "nope"},
                {"asset_spec": {"negative_constraints": [1]}}, {"asset_spec": {"production": {"width": 100.0}, "negative_constraints": []}}]
    for pkg in packages:
        for target in ["generic_text_to_image", "generic_text_to_video", "structured_json", "mystery"]:
            case("adapt", lambda p=pkg, t=target: prompt_genome.adapt(p, target=t), {"package": pkg, "target": target})
    for text in ["", "abc", "é日本🎨", "line\r\nbreak", "\x00", "a" * 5000]:
        case("source_hash", lambda t=text: prompt_genome.source_hash(t), {"text": text})
    inventories = [[], [{"source_kind": "DERIVED", "prompt_id": "a"}], [{"source_kind": "ORIGINAL_IMPORT", "prompt_id": f"p{i}"} for i in range(14)],
                   [{"source_kind": "ORIGINAL_IMPORT", "prompt_id": f"p{i % 20}"} for i in range(40)], [{"source_kind": "ORIGINAL_IMPORT", "prompt_id": "b"}, {"source_kind": "ORIGINAL_IMPORT", "prompt_id": "a"},
                   {"source_kind": "ORIGINAL_IMPORT", "prompt_id": "a"}]]
    for inv in inventories:
        case("inventory", lambda x=inv: prompt_genome.inventory(x), {"imported": inv})


# --------------------------------------------------------------------------- tables and assembly


def unicode_samples(r: random.Random) -> list[list[Any]]:
    points = {0, 9, 10, 11, 12, 13, 28, 29, 30, 31, 32, 0x85, 0xA0, 0x1680, 0x2028, 0x2029, 0x202F, 0x205F, 0x3000, 0xFEFF, 0x200B, 0x30, 0x39, 0x660, 0xB2, 0xB3, 0xB9, 0x41, 0x5F, 0x2160, 0x212A, 0x1F3A8}
    points |= {r.randrange(0x110000) for _ in range(1200)} | {r.randrange(0x2000) for _ in range(1000)} | {r.randrange(0x30000, 0x32000) for _ in range(500)}
    rows = []
    for cp in sorted(points):
        if 0xD800 <= cp <= 0xDFFF:
            continue
        ch = chr(cp)
        digit = unicodedata.decimal(ch, None) if re.match(r"\d", ch) else None
        rows.append([cp, bool(re.match(r"\w", ch)), bool(re.match(r"\d", ch)), ch.isspace(), digit])
    return rows


def build() -> dict[str, Any]:
    CASES.clear()
    GRAPHS.clear()
    r = random.Random(20260117)
    genome_cases(r)
    resolve_cases(r)
    diff_cases(r)
    graph_cases(r)
    multiverse_cases(r)
    colour_cases(r)
    immune_cases(r)
    marketing_cases(r)
    art_cases(r)
    prompt_cases(r)
    return {"protocol": "amc-vnexus-core-parity/v1", "python": "3.11", "graphs": enc(GRAPHS), "unicode": unicode_samples(r), "srgb_linear": [enc(_lin(c_)) for c_ in range(256)], "cases": CASES}


def _lin(channel: int) -> float:
    x = channel / 255
    return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4


def dump(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"


def test_vnexus_core_parity_fixture_matches_python() -> None:
    fresh = build()
    tables = render_tables()
    if os.environ.get("AMC_REGENERATE_FIXTURES") == "1" or not FIXTURE.exists():
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(dump(fresh), encoding="utf-8")
        TABLES.write_text(tables, encoding="utf-8")
        return
    stored = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert stored["protocol"] == fresh["protocol"]
    assert stored["graphs"] == json.loads(dump(fresh))["graphs"], "graph inputs drifted; regenerate with AMC_REGENERATE_FIXTURES=1"
    assert stored["unicode"] == json.loads(dump(fresh))["unicode"]
    assert stored["srgb_linear"] == json.loads(dump(fresh))["srgb_linear"]
    assert len(stored["cases"]) == len(fresh["cases"])
    reloaded = json.loads(dump(fresh))["cases"]
    for index, (want, got) in enumerate(zip(stored["cases"], reloaded)):
        assert want == got, f"case {index} ({got['call']}: {got.get('note', '')}) no longer matches Python; regenerate with AMC_REGENERATE_FIXTURES=1"
    assert TABLES.read_text(encoding="utf-8") == tables, "python-tables.ts drifted; regenerate with AMC_REGENERATE_FIXTURES=1"


def test_fixture_is_small_and_covers_every_group() -> None:
    stored = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert FIXTURE.stat().st_size < 3_000_000
    calls = {x["call"] for x in stored["cases"]}
    assert {"parse_document", "resolve", "diff_documents", "graph_view", "compare_with_base", "svg_findings", "sample_size", "score", "adapt"} <= calls
