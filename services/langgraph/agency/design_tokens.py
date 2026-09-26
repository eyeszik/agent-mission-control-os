"""The one DTCG design-token compiler for this repository.

Every token consumer goes through this module: the repository's own frontend
token build (``compile_tokens.py``), the runtime brand design-system package
(``graph/agency/nodes.py::_build_design_system``), and the UI/UX compiler
(``agency/ui_ux``). There is deliberately no second implementation.

Format: the Design Tokens Community Group format, 2025.10 revision. That is a
*token interchange/serialization* specification -- it defines how tokens are
written down and referenced. It says nothing about accessibility; contrast
conformance is WCAG 2.2's job and lives elsewhere.

Pipeline, each step fail-closed with the offending token path::

    READ -> VALIDATE -> RESOLVE_ALIASES -> DETECT_CYCLES -> TYPECHECK
         -> NORMALIZE -> GENERATE_CSS -> (caller) VERIFY_DETERMINISM

Supported ``$type`` values are the subset this codebase actually emits. An
unknown ``$type`` is an error, not a pass-through: silently forwarding a type
the compiler cannot normalize would produce CSS nobody validated.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

COMPILER_VERSION = "amc-dtcg-compiler/v1"
DTCG_FORMAT = "DTCG 2025.10"

SUPPORTED_TYPES = frozenset(
    {"color", "dimension", "duration", "fontFamily", "fontWeight", "cubicBezier", "number"}
)
# Token-level properties the format defines. Anything else starting with `$`
# inside a token is a schema error.
_TOKEN_PROPERTIES = frozenset({"$value", "$type", "$description", "$extensions", "$deprecated"})
_GROUP_PROPERTIES = frozenset({"$type", "$description", "$extensions", "$deprecated", "$schema"})

_ALIAS = re.compile(r"^\{([^{}]+)\}$")
_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_CAMEL = re.compile(r"(?<=[a-z0-9])([A-Z])")

_DIMENSION_UNITS = frozenset({"px", "rem"})
_DURATION_UNITS = frozenset({"ms", "s"})
_FONT_WEIGHT_NAMES = frozenset(
    {"thin", "hairline", "extra-light", "ultra-light", "light", "normal", "regular", "book",
     "medium", "semi-bold", "demi-bold", "bold", "extra-bold", "ultra-bold", "black", "heavy",
     "extra-black", "ultra-black"}
)
# sRGB is always renderable. Wider/perceptual spaces are emitted only with a
# validated sRGB `hex` fallback, so an engine without support keeps the meaning.
_COLOR_SPACES = frozenset({"srgb", "display-p3", "oklch"})

# Tier vocabulary for tiered sources (the frontend's canonical token file).
TIER_PRIMITIVE = "primitive"
TIER_SEMANTIC = "semantic"
TIER_COMPONENT = "component"
TIERS = (TIER_PRIMITIVE, TIER_SEMANTIC, TIER_COMPONENT)


class TokenError(ValueError):
    """Base class: every failure names the token path that caused it."""

    code = "TOKEN_ERROR"

    def __init__(self, message: str, path: str = "") -> None:
        self.path = path
        super().__init__(f"{self.code}: {path + ': ' if path else ''}{message}")


class TokenSchemaError(TokenError):
    code = "TOKEN_SCHEMA"


class MissingAliasError(TokenError):
    code = "TOKEN_MISSING_ALIAS"


class TokenCycleError(TokenError):
    code = "TOKEN_ALIAS_CYCLE"

    def __init__(self, chain: list[str]) -> None:
        self.chain = chain
        super().__init__(" -> ".join(chain), chain[0])


class TokenTypeError(TokenError):
    code = "TOKEN_TYPE"


class TokenTierError(TokenError):
    code = "TOKEN_TIER"


@dataclass(frozen=True)
class RawToken:
    path: str
    value: Any
    declared_type: str | None
    inherited_type: str | None
    description: str | None


@dataclass(frozen=True)
class ResolvedToken:
    path: str
    type: str
    value: Any  # the literal (post-alias) DTCG value
    css: str  # normalized CSS value of the literal
    alias_of: str | None  # direct alias target, preserved for var() emission
    description: str | None = None

    @property
    def tier(self) -> str | None:
        head = self.path.split(".", 1)[0]
        return head if head in TIERS else None


@dataclass(frozen=True)
class TokenGraph:
    tokens: dict[str, ResolvedToken]
    source_hash: str
    tiered: bool = False
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def get(self, path: str) -> ResolvedToken:
        return self.tokens[path]


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def source_hash(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# READ / VALIDATE
# --------------------------------------------------------------------------- #


def _walk(node: Mapping[str, Any], prefix: tuple[str, ...], inherited: str | None,
          out: dict[str, RawToken]) -> None:
    if not isinstance(node, Mapping):
        raise TokenSchemaError("group must be an object", ".".join(prefix))
    group_type = node.get("$type", inherited)
    if "$type" in node and not isinstance(node["$type"], str):
        raise TokenSchemaError("$type must be a string", ".".join(prefix))
    for key in sorted(node):
        if key.startswith("$"):
            if key not in _GROUP_PROPERTIES:
                raise TokenSchemaError(f"unknown group property {key!r}", ".".join(prefix))
            continue
        if not _NAME.match(key):
            raise TokenSchemaError(
                f"invalid token/group name {key!r} (letters, digits, '-', '_' only)",
                ".".join(prefix),
            )
        child = node[key]
        path = prefix + (key,)
        dotted = ".".join(path)
        if isinstance(child, Mapping) and "$value" in child:
            unknown = sorted(k for k in child if k not in _TOKEN_PROPERTIES)
            if unknown:
                raise TokenSchemaError(f"unknown token properties {unknown}", dotted)
            declared = child.get("$type")
            if declared is not None and not isinstance(declared, str):
                raise TokenSchemaError("$type must be a string", dotted)
            out[dotted] = RawToken(
                path=dotted,
                value=child["$value"],
                declared_type=declared,
                inherited_type=group_type,
                description=child.get("$description"),
            )
        elif isinstance(child, Mapping):
            _walk(child, path, group_type, out)
        else:
            raise TokenSchemaError("expected a token (object with $value) or a group", dotted)


def read_tokens(document: Mapping[str, Any]) -> dict[str, RawToken]:
    if not isinstance(document, Mapping):
        raise TokenSchemaError("token document must be a JSON object")
    out: dict[str, RawToken] = {}
    _walk(document, (), None, out)
    if not out:
        raise TokenSchemaError("token document defines no tokens")
    return out


# --------------------------------------------------------------------------- #
# TYPECHECK / NORMALIZE
# --------------------------------------------------------------------------- #


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _fmt(number: float) -> str:
    text = f"{float(number):.4f}".rstrip("0").rstrip(".")
    return text if text not in {"", "-0"} else "0"


def hex_to_color(hex_value: str) -> dict[str, Any]:
    """Convert '#rrggbb' to a DTCG 2025.10 sRGB color value (with hex fallback)."""
    if not isinstance(hex_value, str) or not _HEX.match(hex_value.strip()):
        raise TokenTypeError(f"not a 6-digit hex color: {hex_value!r}")
    clean = hex_value.strip().lower()
    comps = [round(int(clean[i:i + 2], 16) / 255, 4) for i in (1, 3, 5)]
    return {"colorSpace": "srgb", "components": comps, "hex": clean}


def _srgb_hex(components: list[float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02x}" for c in components)


def normalize_value(token_type: str, value: Any, path: str) -> str:
    """Validate a literal DTCG value for its type and return its CSS form."""
    if token_type == "color":
        if not isinstance(value, Mapping):
            raise TokenTypeError(
                "color $value must be a DTCG color object {colorSpace, components, alpha?, hex?}",
                path,
            )
        space = value.get("colorSpace")
        comps = value.get("components")
        alpha = value.get("alpha", 1)
        hex_fallback = value.get("hex")
        extra = sorted(set(value) - {"colorSpace", "components", "alpha", "hex"})
        if extra:
            raise TokenTypeError(f"unknown color properties {extra}", path)
        if space not in _COLOR_SPACES:
            raise TokenTypeError(f"unsupported colorSpace {space!r}", path)
        if not (isinstance(comps, list) and len(comps) == 3 and all(_is_number(c) for c in comps)):
            raise TokenTypeError("color components must be 3 numbers", path)
        if not _is_number(alpha) or not 0 <= alpha <= 1:
            raise TokenTypeError("color alpha must be within [0, 1]", path)
        if hex_fallback is not None and not (isinstance(hex_fallback, str) and _HEX.match(hex_fallback)):
            raise TokenTypeError("color hex fallback must be '#rrggbb'", path)
        if space == "srgb":
            if not all(0 <= c <= 1 for c in comps):
                raise TokenTypeError("srgb components must be within [0, 1]", path)
            if alpha == 1:
                return _srgb_hex(comps)
            channels = " ".join(str(max(0, min(255, round(c * 255)))) for c in comps)
            return f"rgb({channels} / {_fmt(alpha)})"
        # Wide-gamut / perceptual spaces require an sRGB fallback (edge case E04).
        if hex_fallback is None:
            raise TokenTypeError(
                f"{space} color requires an sRGB 'hex' fallback for engines without support",
                path,
            )
        return hex_fallback.lower()
    if token_type in {"dimension", "duration"}:
        units = _DIMENSION_UNITS if token_type == "dimension" else _DURATION_UNITS
        if not (isinstance(value, Mapping) and set(value) == {"value", "unit"}):
            raise TokenTypeError(f"{token_type} $value must be {{value, unit}}", path)
        if not _is_number(value["value"]):
            raise TokenTypeError(f"{token_type} value must be a number", path)
        if value["unit"] not in units:
            raise TokenTypeError(f"{token_type} unit must be one of {sorted(units)}", path)
        if token_type == "duration" and value["value"] < 0:
            raise TokenTypeError("duration must be non-negative", path)
        return f"{_fmt(value['value'])}{value['unit']}"
    if token_type == "fontFamily":
        families = [value] if isinstance(value, str) else value
        if not (isinstance(families, list) and families and all(isinstance(f, str) and f for f in families)):
            raise TokenTypeError("fontFamily must be a non-empty string or string list", path)
        return ", ".join(f if re.fullmatch(r"[A-Za-z-]+", f) else f'"{f}"' for f in families)
    if token_type == "fontWeight":
        if _is_number(value) and 1 <= value <= 1000:
            return _fmt(value)
        if isinstance(value, str) and value in _FONT_WEIGHT_NAMES:
            return value
        raise TokenTypeError("fontWeight must be 1..1000 or a DTCG weight name", path)
    if token_type == "cubicBezier":
        if not (isinstance(value, list) and len(value) == 4 and all(_is_number(v) for v in value)):
            raise TokenTypeError("cubicBezier must be 4 numbers", path)
        if not (0 <= value[0] <= 1 and 0 <= value[2] <= 1):
            raise TokenTypeError("cubicBezier x-coordinates must be within [0, 1]", path)
        return f"cubic-bezier({', '.join(_fmt(v) for v in value)})"
    if token_type == "number":
        if not _is_number(value):
            raise TokenTypeError("number token must be numeric", path)
        return _fmt(value)
    raise TokenTypeError(f"unsupported $type {token_type!r}", path)


# --------------------------------------------------------------------------- #
# RESOLVE_ALIASES / DETECT_CYCLES
# --------------------------------------------------------------------------- #


def _alias_target(value: Any) -> str | None:
    if isinstance(value, str):
        match = _ALIAS.match(value.strip())
        if match:
            return match.group(1)
    return None


def _enforce_tiers(raw: dict[str, RawToken], resolved: dict[str, ResolvedToken]) -> None:
    for path, token in resolved.items():
        tier = token.tier
        if tier is None:
            raise TokenTierError(
                f"tiered sources may only contain {list(TIERS)} top-level groups", path
            )
        target = token.alias_of
        if tier == TIER_PRIMITIVE and target is not None:
            raise TokenTierError("primitive (T1) tokens must be literal values", path)
        if tier in {TIER_SEMANTIC, TIER_COMPONENT} and token.type == "color" and target is None:
            raise TokenTierError(
                f"{tier} color tokens must alias a lower tier, not hold a raw value", path
            )
        if tier == TIER_COMPONENT and target is not None and target.startswith(f"{TIER_PRIMITIVE}."):
            raise TokenTierError(
                "component (T3) tokens must alias semantic (T2) tokens, not primitives", path
            )
        if tier == TIER_PRIMITIVE and raw[path].declared_type is None and raw[path].inherited_type is None:
            raise TokenTierError("primitive tokens must declare $type", path)


def compile_graph(document: Mapping[str, Any], *, tiered: bool = False) -> TokenGraph:
    raw = read_tokens(document)
    resolved: dict[str, ResolvedToken] = {}

    def resolve(path: str, stack: list[str]) -> ResolvedToken:
        if path in resolved:
            return resolved[path]
        if path in stack:
            raise TokenCycleError(stack[stack.index(path):] + [path])
        if path not in raw:
            referrer = stack[-1] if stack else path
            raise MissingAliasError(f"alias references unknown token {{{path}}}", referrer)
        token = raw[path]
        target = _alias_target(token.value)
        explicit = token.declared_type or token.inherited_type
        if target is not None:
            if target not in raw:
                raise MissingAliasError(f"alias references unknown token {{{target}}}", path)
            base = resolve(target, stack + [path])
            if explicit is not None and explicit != base.type:
                raise TokenTypeError(
                    f"declared $type {explicit!r} does not match alias target type {base.type!r}"
                    f" ({{{target}}})",
                    path,
                )
            result = ResolvedToken(
                path=path, type=base.type, value=base.value, css=base.css,
                alias_of=target, description=token.description,
            )
        else:
            if isinstance(token.value, str) and ("{" in token.value or "}" in token.value):
                raise TokenSchemaError("malformed alias; expected exactly '{group.token}'", path)
            if explicit is None:
                raise TokenTypeError("literal token has no $type (declared or inherited)", path)
            if explicit not in SUPPORTED_TYPES:
                raise TokenTypeError(f"unsupported $type {explicit!r}", path)
            result = ResolvedToken(
                path=path, type=explicit, value=token.value,
                css=normalize_value(explicit, token.value, path),
                alias_of=None, description=token.description,
            )
        resolved[path] = result
        return result

    for path in sorted(raw):
        resolve(path, [])

    if tiered:
        _enforce_tiers(raw, resolved)
    ordered = {path: resolved[path] for path in sorted(resolved)}
    return TokenGraph(tokens=ordered, source_hash=source_hash(document), tiered=tiered)


# --------------------------------------------------------------------------- #
# GENERATE_CSS
# --------------------------------------------------------------------------- #


def css_variable(path: str, prefix: str = "") -> str:
    segments = [_CAMEL.sub(r"-\1", part).lower().replace("_", "-") for part in path.split(".")]
    name = "-".join(segments)
    return f"--{prefix}-{name}" if prefix else f"--{name}"


def _declarations(graph: TokenGraph, prefix: str, only: set[str] | None = None) -> list[str]:
    lines: list[str] = []
    for path, token in graph.tokens.items():
        if only is not None and path not in only:
            continue
        value = f"var({css_variable(token.alias_of, prefix)})" if token.alias_of else token.css
        lines.append(f"  {css_variable(path, prefix)}: {value};")
    return lines


def generate_css(
    graph: TokenGraph,
    *,
    prefix: str = "",
    source_label: str = "tokens",
    selector: str = ":root",
    themes: Mapping[str, TokenGraph] | None = None,
) -> str:
    """Deterministic CSS custom properties. Aliases stay aliases (``var()``), so
    the semantic layer keeps pointing at the primitive it names."""
    header = [
        "/* GENERATED FILE -- do not edit by hand.",
        f" * compiler: {COMPILER_VERSION} ({DTCG_FORMAT})",
        f" * source: {source_label}",
        f" * source-sha256: {graph.source_hash}",
        " */",
    ]
    body = [f"{selector} {{", *_declarations(graph, prefix), "}"]
    for name in sorted(themes or {}):
        theme = (themes or {})[name]
        overridden = sorted(set(theme.tokens) & set(graph.tokens))
        unknown = sorted(set(theme.tokens) - set(graph.tokens))
        if unknown:
            raise TokenSchemaError(f"theme {name!r} defines tokens absent from the base: {unknown}")
        for path in overridden:
            if theme.tokens[path].type != graph.tokens[path].type:
                raise TokenTypeError(f"theme {name!r} changes the token type", path)
        body += ["", f'[data-amc-theme="{name}"] {{', *_declarations(theme, prefix, set(overridden)), "}"]
    return "\n".join(header + body) + "\n"


def compile_css(
    document: Mapping[str, Any],
    *,
    prefix: str = "",
    tiered: bool = False,
    source_label: str = "tokens",
    themes: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[TokenGraph, str]:
    graph = compile_graph(document, tiered=tiered)
    theme_graphs = {}
    for name, theme_doc in (themes or {}).items():
        # A theme may alias base tokens, so it is resolved against base + override.
        merged = _deep_merge(document, theme_doc)
        merged_graph = compile_graph(merged, tiered=tiered)
        override_paths = set(read_tokens(theme_doc))
        theme_graphs[name] = TokenGraph(
            tokens={p: merged_graph.tokens[p] for p in sorted(override_paths)},
            source_hash=source_hash(theme_doc),
            tiered=tiered,
        )
    css = generate_css(graph, prefix=prefix, source_label=source_label, themes=theme_graphs)
    return graph, css


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {key: value for key, value in base.items()}
    for key, value in override.items():
        if isinstance(value, Mapping) and "$value" not in value and isinstance(merged.get(key), Mapping):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def flatten(graph: TokenGraph) -> dict[str, str]:
    """Path -> normalized CSS literal, for reporting and contrast checks."""
    return {path: token.css for path, token in graph.tokens.items()}
