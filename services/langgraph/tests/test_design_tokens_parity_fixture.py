"""DTCG compiler cross-language parity fixture (Python is the reference).

`packages/design-tokens/tests/fixtures/dtcg-compiler.json` records inputs and what
`agency/design_tokens.py` produces for each: generated CSS, resolved graphs, source
hashes, normalized values, and every error (class, message, token path, cycle
chain). `@amc/design-tokens` must reproduce every entry. This test checks the
stored entries still match Python, so a change to the compiler fails here before
it silently breaks the TypeScript twin. Regenerate with AMC_REGENERATE_FIXTURES=1.

Tagged values: {"$float": "<python repr>"} is a float and {"$int": "<decimal>"} an
int beyond 2^53 (JSON cannot carry either distinctly); every other object is a
mapping, every array a list. Fixture strings never contain lone surrogates.
"""
from __future__ import annotations

import json
import os
import random
from pathlib import Path
from typing import Any, Callable

from services.langgraph.agency import design_tokens as dt

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "packages/design-tokens/tests/fixtures/dtcg-compiler.json"
TOKEN_SOURCE = "apps/web/tokens/amc.tokens.json"
GENERATED_CSS = "apps/web/app/tokens.css"
TAGS = ("$int", "$float")
SAFE = 2**53 - 1


def tag(value: Any) -> Any:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int):
        return value if abs(value) <= SAFE else {"$int": str(value)}
    if isinstance(value, float):
        return {"$float": repr(value)}
    if isinstance(value, (list, tuple)):
        return [tag(item) for item in value]
    return {key: tag(item) for key, item in value.items()}


def decode(node: Any) -> Any:
    if isinstance(node, list):
        return [decode(item) for item in node]
    if not isinstance(node, dict):
        return node
    if len(node) == 1 and next(iter(node)) in TAGS:
        name, raw = next(iter(node.items()))
        return int(raw) if name == "$int" else float(raw)
    return {key: decode(item) for key, item in node.items()}


def error_of(exc: Exception) -> dict[str, Any]:
    return {
        "error": type(exc).__name__,
        "message": str(exc),
        "path": getattr(exc, "path", None),
        "chain": getattr(exc, "chain", None),
    }


def outcome(run: Callable[[], Any]) -> dict[str, Any]:
    try:
        return {"ok": run()}
    except (ValueError, TypeError, OverflowError, AttributeError, KeyError) as exc:
        return {"raises": error_of(exc)}


# --------------------------------------------------------------------------- runners


def graph_view(graph: dt.TokenGraph) -> dict[str, Any]:
    tokens = [
        {"path": t.path, "type": t.type, "value": tag(t.value), "css": t.css,
         "alias_of": t.alias_of, "description": tag(t.description), "tier": t.tier}
        for t in graph.tokens.values()
    ]
    return {"source_hash": graph.source_hash, "tiered": graph.tiered, "tokens": tokens,
            "flat": dt.flatten(graph)}


def run_compile(case: dict[str, Any]) -> dict[str, Any]:
    opts = case["options"]
    themes = decode(opts["themes"]) if opts.get("themes") is not None else None

    def go() -> dict[str, Any]:
        graph, css = dt.compile_css(
            decode(case["document"]), prefix=opts["prefix"], tiered=opts["tiered"],
            source_label=opts["source_label"], themes=themes,
        )
        if opts.get("selector") is not None:
            css = dt.generate_css(graph, prefix=opts["prefix"], source_label=opts["source_label"],
                                  selector=opts["selector"])
        return {"css": css, "graph": graph_view(graph)}

    return outcome(go)


def run_read(case: dict[str, Any]) -> dict[str, Any]:
    def go() -> list[dict[str, Any]]:
        return [
            {"path": r.path, "value": tag(r.value), "declared_type": r.declared_type,
             "inherited_type": r.inherited_type, "description": tag(r.description)}
            for r in dt.read_tokens(decode(case["document"])).values()
        ]

    return outcome(go)


RUNNERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "compile": run_compile,
    "read_tokens": run_read,
    "hex_to_color": lambda c: outcome(lambda: tag(dt.hex_to_color(decode(c["input"])))),
    "normalize": lambda c: outcome(lambda: dt.normalize_value(c["type"], decode(c["value"]), c["path"])),
    "css_variable": lambda c: outcome(lambda: dt.css_variable(c["path"], c["prefix"])),
    "canonical_json": lambda c: outcome(
        lambda: {"json": dt.canonical_json(decode(c["input"])), "hash": dt.source_hash(decode(c["input"]))}
    ),
    "deep_merge": lambda c: outcome(lambda: tag(dt._deep_merge(decode(c["base"]), decode(c["override"])))),
}


def case(kind: str, name: str, **fields: Any) -> dict[str, Any]:
    entry = {"kind": kind, "name": name, **fields}
    entry["expect"] = RUNNERS[kind](entry)
    return entry


def compile_case(name: str, document: Any, *, prefix: str = "", tiered: bool = False,
                 source_label: str = "tokens", themes: Any = None, selector: str | None = None) -> dict[str, Any]:
    options = {"prefix": prefix, "tiered": tiered, "source_label": source_label,
               "themes": tag(themes) if themes is not None else None, "selector": selector}
    return case("compile", name, document=tag(document), options=options)


# --------------------------------------------------------------------------- handwritten cases


def srgb(*comps: Any, **extra: Any) -> dict[str, Any]:
    return {"colorSpace": "srgb", "components": list(comps), **extra}


def tok(type_: str | None, value: Any, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"$value": value, **extra}
    if type_ is not None:
        out["$type"] = type_
    return out


def _schema_cases() -> list[dict[str, Any]]:
    n1 = tok("number", 1)
    docs: list[tuple[str, Any]] = [
        ("document is a list", [n1]), ("document is a string", "x"), ("document is null", None),
        ("empty document", {}), ("only metadata", {"$description": "d", "$schema": "s"}),
        ("unknown group property", {"$foo": 1, "a": n1}),
        ("unknown nested group property", {"g": {"$bar": True, "a": n1}}),
        ("invalid name with space", {"a b": n1}), ("invalid name with dot", {"a.b": n1}),
        ("invalid non-ascii name", {"é": n1}), ("invalid quoted name", {"it's": n1}),
        ("name with trailing newline quirk", {"a\n": n1, "b": n1}),
        ("child is a number", {"a": 1}), ("child is a list", {"g": {"a": [1]}}),
        ("child is null", {"a": None}),
        ("root $type not a string", {"$type": 1, "a": n1}),
        ("group $type null", {"g": {"$type": None, "a": n1}}),
        ("token $type not a string", {"a": {"$value": 1, "$type": ["number"]}}),
        ("token $type null is undeclared", {"g": {"$type": "number", "a": {"$value": 2, "$type": None}}}),
        ("unknown token properties", {"a": {"$value": 1, "$type": "number", "foo": 1, "$x": 2}}),
        ("token metadata allowed", {"a": {"$value": 1, "$type": "number", "$deprecated": True,
                                          "$extensions": {"x": [1]}, "$description": {"d": 1.5}}}),
        ("group metadata allowed", {"g": {"$extensions": {}, "$deprecated": "x", "$description": "",
                                          "$type": "number", "a": {"$value": 3}}}),
        ("token $value null", {"a": tok("number", None)}),
        ("sorted walk reports first bad key", {"b": 1, "a": 2}),
    ]
    return [compile_case(name, doc) for name, doc in docs]


def _alias_cases() -> list[dict[str, Any]]:
    n1 = tok("number", 1)
    docs: list[tuple[str, Any]] = [
        ("missing alias", {"a": tok(None, "{nope.x}")}),
        ("self cycle", {"a": tok(None, "{a}")}),
        ("two cycle", {"a": tok(None, "{b}"), "b": tok(None, "{a}")}),
        ("cycle entered from outside", {"a": tok(None, "{b}"), "b": tok(None, "{c}"), "c": tok(None, "{b}")}),
        ("alias chain", {"a": n1, "b": tok(None, "{a}"), "c": tok(None, "{b}"), "d": tok("number", " {c} ")}),
        ("alias to group path", {"g": {"a": n1}, "b": tok(None, "{g}")}),
        ("malformed alias open", {"a": tok("number", "{a")}), ("malformed alias close", {"a": tok("number", "x}")}),
        ("malformed double alias", {"a": n1, "b": tok("number", "{a}{a}")}),
        ("empty alias braces", {"a": tok("number", "{}")}),
        ("alias with newline inside", {"a": tok(None, "{a\n.b}")}),
        ("declared type mismatches alias", {"a": n1, "b": tok("color", "{a}")}),
        ("inherited type mismatches alias", {"a": n1, "g": {"$type": "dimension", "b": tok(None, "{a}")}}),
        ("empty-string group type", {"g": {"$type": "", "a": tok(None, 1)}}),
        ("empty-string declared type falls back", {"g": {"$type": "number", "a": tok("", 4)}}),
        ("literal without type", {"a": tok(None, 1)}),
        ("unsupported type", {"a": tok("shadow", {"x": 1})}),
        ("typography type unsupported", {"g": {"$type": "typography", "a": tok(None, "x")}}),
        ("alias keeps description", {"a": tok("number", 2, **{"$description": "base"}),
                                     "b": tok(None, "{a}", **{"$description": ["alias", 1]})}),
        ("camel and snake names", {"fontSize": {"bodyLarge_2x": tok("dimension", {"value": 1.5, "unit": "rem"})},
                                   "ABC": n1, "a1B": tok(None, "{fontSize.bodyLarge_2x}")}),
    ]
    return [compile_case(name, doc) for name, doc in docs]


def _color_values() -> list[tuple[str, Any]]:
    return [
        ("srgb opaque", srgb(0.1, 0.5, 0.9)), ("srgb ints", srgb(0, 1, 0)), ("srgb float ones", srgb(1.0, 0.0, 1.0)),
        ("srgb alpha half", srgb(0.3, 0.5, 1, alpha=0.5)), ("srgb alpha zero int", srgb(0.2, 0.4, 0.6, alpha=0)),
        ("srgb alpha float one", srgb(0.2, 0.4, 0.6, alpha=1.0)), ("srgb alpha tie", srgb(0, 0, 0, alpha=0.03125)),
        ("srgb with hex", srgb(0.1, 0.2, 0.3, hex="#ABCDEF")), ("srgb out of range", srgb(1.5, 0, 0)),
        ("srgb negative", srgb(-0.1, 0, 0)), ("display-p3 with hex", {"colorSpace": "display-p3",
                                                                       "components": [1, 0.5, 2], "hex": "#ABCDEF"}),
        ("oklch with newline hex quirk", {"colorSpace": "oklch", "components": [0.7, 0.1, 120], "hex": "#abcdef\n"}),
        ("oklch without hex", {"colorSpace": "oklch", "components": [0.7, 0.1, 120]}),
        ("unknown colorSpace", srgb(0, 0, 0) | {"colorSpace": "hsl"}), ("missing colorSpace", {"components": [0, 0, 0]}),
        ("colorSpace list", {"colorSpace": ["srgb"], "components": [0, 0, 0]}),
        ("colorSpace dict", {"colorSpace": {"a": 1}, "components": [0, 0, 0]}),
        ("colorSpace float", {"colorSpace": 1.0, "components": [0, 0, 0]}),
        ("two components", srgb(0, 0)), ("bool component", srgb(True, 0, 0)), ("string component", srgb("0", 0, 0)),
        ("alpha above one", srgb(0, 0, 0, alpha=1.5)), ("alpha null", srgb(0, 0, 0, alpha=None)),
        ("alpha string", srgb(0, 0, 0, alpha="1")), ("bad hex fallback", srgb(0, 0, 0, hex="#abc")),
        ("hex fallback number", srgb(0, 0, 0, hex=7)), ("unknown color properties", srgb(0, 0, 0, b=1, a=2)),
        ("color is a string", "#ffffff"), ("color is a list", [0, 0, 0]),
        ("nan component", srgb(float("nan"), 0, 0)), ("big int component", srgb(2**70, 0, 0)),
    ]


def _measure_values() -> list[tuple[str, str, Any]]:
    return [
        ("dimension", "px", {"value": 16, "unit": "px"}), ("dimension", "rem float", {"value": 1.125, "unit": "rem"}),
        ("dimension", "negative", {"value": -0.5, "unit": "px"}), ("dimension", "tie", {"value": 0.03125, "unit": "px"}),
        ("dimension", "negative tie", {"value": -0.03125, "unit": "px"}),
        ("dimension", "tiny negative", {"value": -0.00001, "unit": "px"}),
        ("dimension", "huge float", {"value": 1e300, "unit": "px"}),
        ("dimension", "big int", {"value": 2**70 + 1, "unit": "px"}),
        ("dimension", "int overflow", {"value": 10**400, "unit": "px"}),
        ("dimension", "nan", {"value": float("nan"), "unit": "px"}),
        ("dimension", "infinity", {"value": float("inf"), "unit": "px"}),
        ("dimension", "em unit", {"value": 1, "unit": "em"}), ("dimension", "unit list", {"value": 1, "unit": ["px"]}),
        ("dimension", "unit dict", {"value": 1, "unit": {"u": "px"}}), ("dimension", "unit null", {"value": 1, "unit": None}),
        ("dimension", "missing unit", {"value": 1}), ("dimension", "extra key", {"value": 1, "unit": "px", "x": 0}),
        ("dimension", "string value", {"value": "1", "unit": "px"}), ("dimension", "bool value", {"value": True, "unit": "px"}),
        ("dimension", "plain number", 4), ("duration", "ms", {"value": 150, "unit": "ms"}),
        ("duration", "s", {"value": 0.25, "unit": "s"}), ("duration", "negative", {"value": -1, "unit": "ms"}),
        ("duration", "negative zero", {"value": -0.0, "unit": "ms"}), ("duration", "px unit", {"value": 1, "unit": "px"}),
    ]


def _other_values() -> list[tuple[str, str, Any]]:
    return [
        ("fontFamily", "single", "Inter"), ("fontFamily", "stack", ["Inter Tight", "system-ui", "sans-serif", "ui_x"]),
        ("fontFamily", "empty list", []), ("fontFamily", "empty member", ["Inter", ""]), ("fontFamily", "number", 1),
        ("fontFamily", "quote inside", ['Bob"s']),
        ("fontWeight", "400", 400), ("fontWeight", "1", 1), ("fontWeight", "1000", 1000), ("fontWeight", "0", 0),
        ("fontWeight", "1001", 1001), ("fontWeight", "float", 450.5), ("fontWeight", "bold", "bold"),
        ("fontWeight", "Bold", "Bold"), ("fontWeight", "bool", True), ("fontWeight", "semi-bold", "semi-bold"),
        ("cubicBezier", "ok", [0.2, 0, 0, 1]), ("cubicBezier", "overshoot", [0.34, 1.56, 0.64, -0.5]),
        ("cubicBezier", "x out of range", [1.2, 0, 0, 1]), ("cubicBezier", "x2 negative", [0, 0, -0.1, 1]),
        ("cubicBezier", "three numbers", [0, 0, 1]), ("cubicBezier", "strings", ["0", 0, 0, 1]),
        ("cubicBezier", "y overflow", [0, 10**400, 1, 1]),
        ("number", "int", 3), ("number", "float", 1.5), ("number", "float one", 1.0), ("number", "string", "1"),
        ("number", "nan", float("nan")), ("number", "-inf", float("-inf")), ("number", "-0.0", -0.0),
        ("number", "null", None),
    ]


def _type_cases() -> list[dict[str, Any]]:
    out = [compile_case(f"color: {name}", {"c": tok("color", value)}) for name, value in _color_values()]
    out += [compile_case(f"{t}: {name}", {"v": tok(t, value)}) for t, name, value in _measure_values() + _other_values()]
    out += [case("normalize", f"normalize {t}: {name}", type=t, value=tag(value), path="x.y")
            for t, name, value in _measure_values() + _other_values()]
    out += [case("normalize", f"normalize color: {name}", type="color", value=tag(value), path="c")
            for name, value in _color_values()]
    out += [case("normalize", "normalize unsupported type", type="shadow", value=1, path="p"),
            case("normalize", "normalize empty path", type="number", value="x", path="")]
    return out


def _tier_doc() -> dict[str, Any]:
    return {
        "primitive": {"color": {"$type": "color", "zinc": {"50": tok(None, srgb(0.98, 0.98, 0.98)),
                                                            "900": tok(None, srgb(0.09, 0.09, 0.11))}},
                      "space": {"4": tok("dimension", {"value": 16, "unit": "px"})}},
        "semantic": {"color": {"bg": tok("color", "{primitive.color.zinc.50}"),
                               "fg": tok(None, "{primitive.color.zinc.900}")},
                     "space": {"block": tok("dimension", {"value": 2, "unit": "rem"})}},
        "component": {"button": {"bg": tok(None, "{semantic.color.bg}")}},
    }


def _tier_and_theme_cases() -> list[dict[str, Any]]:
    base = _tier_doc()
    light = {"semantic": {"color": {"bg": tok(None, "{primitive.color.zinc.900}")}}}
    out = [
        compile_case("tiered ok", base, prefix="amc", tiered=True),
        compile_case("tiered off ignores tiers", base | {"other": tok("number", 1)}),
        compile_case("tiered foreign top-level group", base | {"other": tok("number", 1)}, tiered=True),
        compile_case("primitive alias", base | {"primitive": base["primitive"] | {"x": tok(None, "{primitive.space.4}")}},
                     tiered=True),
        compile_case("semantic raw color", base | {"semantic": {"c": tok("color", srgb(0, 0, 0))}}, tiered=True),
        compile_case("component aliases primitive",
                     base | {"component": {"c": tok(None, "{primitive.color.zinc.50}")}}, tiered=True),
        compile_case("theme ok", base, prefix="amc", tiered=True, themes={"light": light}),
        compile_case("themes sorted", base, themes={"zeta": light, "Alpha": light, "a\"q": light}),
        compile_case("theme unknown token", base, themes={"t": {"semantic": {"new": tok("number", 1)}}}),
        compile_case("theme changes type", base, themes={"t": {"semantic": {"space": {"block": tok("number", 1)}}}}),
        compile_case("theme empty", base, themes={"t": {}}),
        compile_case("theme is a list", base, themes={"t": [1]}),
        compile_case("theme is null", base, themes={"t": None}),
        compile_case("theme invalid in tiered merge", base, tiered=True,
                     themes={"t": {"semantic": {"color": {"bg": tok("color", srgb(1, 1, 1))}}}}),
        compile_case("theme replaces token with group", base, themes={"t": {"semantic": {"space": {"block": {"x": tok("number", 1)}}}}}),
        compile_case("custom selector and label", base, prefix="x", selector=".scope", source_label="custom/src.json"),
        compile_case("non-ascii and control strings hash", {"a": tok("fontFamily", ["Ünïcode", "\U0001f3a8 Font", "tab\tx"]),
                                                            "$description": "～\U0001f600\x7f\x00é"}),
    ]
    return out


def _helper_cases() -> list[dict[str, Any]]:
    hexes: list[Any] = ["#AABBCC", " #aabbcc\n", "#abc", "aabbcc", "#aabbcc\n", "#aabbcc\x1c", "﻿#aabbcc",
                        "\x85#00ff00　", 123, 1.0, None, True, ["#aabbcc"], {"b": 1.0, "a": [None, True, "x'y", 'q"\'']},
                        "it's", 'say "hi"', "both ' and \"", "back\\slash", "ctl\x01\x7f\x9f", "​ zw",
                        "\U0001f600 astral", "\U000e0001 tag", " private", 2**70, float("inf")]
    out = [case("hex_to_color", f"hex_to_color {i}", input=tag(h)) for i, h in enumerate(hexes)]
    out += [case("hex_to_color", f"hex_to_color all channels {k}", input=f"#{k:02x}{k:02X}{255 - k:02x}") for k in range(256)]
    paths = [("fooBar.baz_qux", ""), ("fooBar.baz_qux", "amc"), ("ABC", ""), ("a1B.c2D3e", "p"), ("ÀbC", ""),
             ("x__y.Z", "amc"), ("", ""), ("a..b", "q")]
    out += [case("css_variable", f"css_variable {p!r} {x!r}", path=p, prefix=x) for p, x in paths]
    merges = [({"a": 1, "g": {"x": 1, "y": 2}}, {"g": {"y": 3, "z": 4}, "b": 2}),
              ({"g": {"t": {"$value": 1, "$type": "number"}}}, {"g": {"t": {"$value": 2}}}),
              ({"g": 1}, {"g": {"x": 1}}), ({"g": {"x": 1}}, {"g": 5}), ({"a": 1}, [1]), ({"a": 1}, "s")]
    out += [case("deep_merge", f"deep_merge {i}", base=tag(b), override=tag(o)) for i, (b, o) in enumerate(merges)]
    reads = [{"z": {"$type": "number", "b": tok(None, 1), "a": {"c": tok("color", "x", **{"$description": 5})}},
              "a": tok("x", None)}, {"x": {}}, {"g": {"$type": "dimension", "h": {"$type": "number", "t": tok(None, 1)}}}]
    out += [case("read_tokens", f"read_tokens {i}", document=tag(d)) for i, d in enumerate(reads)]
    return out


# --------------------------------------------------------------------------- seeded random cases


def _random_float(r: random.Random) -> float:
    kind = r.randrange(4)
    if kind == 0:
        return r.uniform(-1, 1) * 10 ** r.randint(-30, 30)
    if kind == 1:
        return round(r.uniform(-1000, 1000), r.randint(0, 6))
    if kind == 2:
        return r.randint(-(10**6), 10**6) / 2 ** r.randint(0, 20)
    return float(r.randint(-(2**60), 2**60))


def _random_text(r: random.Random, alphabet: str = "aZ0 é中～\U0001f600\n\"'\\\x00\x7f") -> str:
    return "".join(r.choice(alphabet) for _ in range(r.randint(0, 8)))


def _random_json(r: random.Random, depth: int) -> Any:
    kind = r.randrange(8 if depth < 3 else 6)
    leaves = [None, r.random() < 0.5, r.randint(-(2**80), 2**80), r.randint(-100, 100), _random_float(r), _random_text(r)]
    if kind < 6:
        return leaves[kind]
    if kind == 6:
        return [_random_json(r, depth + 1) for _ in range(r.randint(0, 4))]
    keys = {_random_text(r) for _ in range(r.randint(0, 4))} - set(TAGS)
    return {k: _random_json(r, depth + 1) for k in keys}


def _random_literal(r: random.Random, type_: str) -> Any:
    if type_ == "color":
        space = r.choice(["srgb", "srgb", "srgb", "display-p3", "oklch"])
        value: dict[str, Any] = {"colorSpace": space, "components": [round(r.random(), r.randint(0, 5)) for _ in range(3)]}
        if r.random() < 0.4:
            value["alpha"] = r.choice([0, 1, 1.0, round(r.random(), 3)])
        if space != "srgb" or r.random() < 0.3:
            value["hex"] = "#" + "".join(r.choice("0123456789abcdefABCDEF") for _ in range(6))
        return value
    if type_ in {"dimension", "duration"}:
        units = ["px", "rem"] if type_ == "dimension" else ["ms", "s"]
        return {"value": abs(_random_float(r)) if type_ == "duration" else _random_float(r), "unit": r.choice(units)}
    if type_ == "fontFamily":
        return r.choice(["Inter", ["Inter Tight", "sans-serif"], [_random_text(r, "ab -Z9") or "x"]])
    if type_ == "fontWeight":
        return r.choice([r.randint(1, 1000), round(r.uniform(1, 1000), 2), "bold", "light"])
    if type_ == "cubicBezier":
        return [round(r.random(), 3), _random_float(r), round(r.random(), 3), round(r.uniform(-2, 2), 3)]
    return _random_float(r)


TYPES = ["color", "dimension", "duration", "fontFamily", "fontWeight", "cubicBezier", "number"]


def _mutate(r: random.Random, token: dict[str, Any], paths: list[str]) -> None:
    roll = r.randrange(7)
    if roll == 0:
        token["$type"] = r.choice(["shadow", "", "border"])
    elif roll == 1:
        token["$value"] = _random_json(r, 1)
    elif roll == 2:
        token["$value"] = "{" + r.choice(paths + ["missing.path"]) + "}"
    elif roll == 3:
        token["$extra" if r.random() < 0.5 else "extra"] = 1
    elif roll == 4:
        token.pop("$type", None)
    elif roll == 5:
        token["$value"] = "{" + r.choice(paths + ["x"])
    else:
        token["$type"] = r.choice(TYPES)


def _random_document(r: random.Random, broken: bool) -> dict[str, Any]:
    doc: dict[str, Any] = {}
    paths: list[str] = []
    for _ in range(r.randint(1, 9)):
        group = r.choice(["color", "space", "motion", "typeScale", "misc_1"])
        name = r.choice(["a", "b", "c", "bodyLarge", "x-1", "Y_2", "50", "900"])
        type_ = r.choice(TYPES)
        if paths and r.random() < 0.3:
            token: dict[str, Any] = {"$value": "{" + r.choice(paths) + "}"}
        else:
            token = {"$value": _random_literal(r, type_), "$type": type_}
        doc.setdefault(group, {})[name] = token
        paths.append(f"{group}.{name}")
    if broken:
        group = r.choice(list(doc))
        _mutate(r, doc[group][r.choice(list(doc[group]))], paths)
    return doc


def _random_cases() -> list[dict[str, Any]]:
    r = random.Random(2025_10)
    out = [compile_case(f"random document {i}", _random_document(r, broken=i % 3 == 0), prefix=r.choice(["", "amc"]))
           for i in range(240)]
    out += [case("normalize", f"random number {i}", type="number", value=tag(_random_float(r)), path="n")
            for i in range(200)]
    out += [case("hex_to_color", f"random repr {i}", input=tag(_random_json(r, 2))) for i in range(80)]
    out += [case("canonical_json", f"random json {i}", input=tag(_random_json(r, 0))) for i in range(120)]
    return out


def _real_source_case() -> dict[str, Any]:
    document = json.loads((ROOT / TOKEN_SOURCE).read_text(encoding="utf-8"))
    declared = ((document.get("$extensions") or {}).get("amc") or {}).get("themes") or {}
    themes = {name: theme["tokens"] for name, theme in declared.items()}
    return compile_case("real source apps/web/tokens/amc.tokens.json", document, prefix="amc", tiered=True,
                        source_label=TOKEN_SOURCE, themes=themes)


def build_fixture() -> dict[str, Any]:
    cases = [_real_source_case()]
    for group in (_schema_cases, _alias_cases, _type_cases, _tier_and_theme_cases, _helper_cases, _random_cases):
        cases += group()
    return {"compiler": dt.COMPILER_VERSION, "format": dt.DTCG_FORMAT, "cases": cases}


def _load() -> dict[str, Any]:
    if os.environ.get("AMC_REGENERATE_FIXTURES") == "1" or not FIXTURE.exists():
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(json.dumps(build_fixture(), indent=1, ensure_ascii=True) + "\n")
    return json.loads(FIXTURE.read_text())


def test_fixture_cases_match_python_reference() -> None:
    fixture = _load()
    assert fixture["compiler"] == dt.COMPILER_VERSION
    assert len(fixture["cases"]) > 1000
    for entry in fixture["cases"]:
        assert RUNNERS[entry["kind"]](entry) == entry["expect"], entry["name"]


def test_fixture_covers_every_error_class_and_type() -> None:
    raised = {e["expect"]["raises"]["error"] for e in _load()["cases"] if "raises" in e["expect"]}
    assert {"TokenSchemaError", "MissingAliasError", "TokenCycleError", "TokenTypeError", "TokenTierError",
            "TypeError", "OverflowError", "AttributeError"} <= raised
    compiled = {t["type"] for e in _load()["cases"] if e["kind"] == "compile" and "ok" in e["expect"]
                for t in e["expect"]["ok"]["graph"]["tokens"]}
    assert compiled == dt.SUPPORTED_TYPES


def test_real_source_case_matches_generated_css() -> None:
    real = _load()["cases"][0]
    assert real["name"].startswith("real source")
    assert real["expect"]["ok"]["css"] == (ROOT / GENERATED_CSS).read_text(encoding="utf-8")
