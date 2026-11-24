#!/usr/bin/env python3
"""PAARA Connector Audit — thin MCP server wrapper (stdio, stdlib only).

Exposes the PAARA seven-factor connector scoring rule and the published
13-connector audit dataset as MCP tools, speaking JSON-RPC 2.0 over
stdin/stdout (newline-delimited), with no third-party dependencies.

Tools:
  score_connector   Score any connector from its F1-F7 codes (Y/N/U).
  lookup_connector  Look up one of the 13 coded connectors by name.
  list_connectors   List the 13 coded connectors with their bands.

Scoring: if the PAARA Connector Audit Kit's `paara_scanner` package is
importable (via $PAARA_KIT_SRC or a sibling ../paara-repo checkout), its
scoring module is used directly. Otherwise an exact local replica of the
kit's scoring rule (src/paara_scanner/scoring.py) is used, so this file
also works standalone. The test suite verifies the replica against the
published bands for all 13 connectors.

Methodology: Kumar, V. (2026). Privacy-Aware AI Risk Architecture
(PAARA). SSRN. https://doi.org/10.2139/ssrn.6784078
Kit: https://github.com/vkktask/paara-connector-audit-kit
Archived kit + dataset: https://doi.org/10.5281/zenodo.24325766
"""

from __future__ import annotations

import csv
import difflib
import json
import os
import sys
from pathlib import Path

SERVER_NAME = "paara-connector-audit"
SERVER_VERSION = "1.2.2"  # matches PAARA Connector Audit Kit v1.2.2
DEFAULT_PROTOCOL = "2025-03-26"
HERE = Path(__file__).resolve().parent
DATASET_CSV = HERE / "data" / "coding-sheet.csv"
FACTORS = ("F1", "F2", "F3", "F4", "F5", "F6", "F7")
HIGH_FACTORS = ("F1", "F2", "F3", "F4", "F5")
MEDIUM_FACTORS = ("F6",)

# Human-readable factor labels and scoring weights, matching the kit's
# paara_scanner.models.FACTOR_LABELS / FACTOR_WEIGHTS. Included in tool
# payloads so results are self-describing (codes plus names, not codes alone).
FACTOR_LABELS = {
    "F1": "Sensitive-data reach",
    "F2": "Cross-system aggregation",
    "F3": "Non-user-bound credentials",
    "F4": "Absent logging",
    "F5": "Prompt-injection exposure",
    "F6": "External sharing",
    "F7": "Agentic action capability",
}
FACTOR_WEIGHTS = {
    "F1": "High",
    "F2": "High",
    "F3": "High",
    "F4": "High",
    "F5": "High",
    "F6": "Medium",
    "F7": "Critical",
}
CODE_MEANINGS = {
    "Y": "documented present",
    "N": "documented absent",
    "U": "documentation silent (unknown)",
}
BAND_MEANINGS = {
    "Low": (
        "No High-weighted factor (F1-F5) is present and the connector has "
        "no agentic action capability (F7)."
    ),
    "Moderate": (
        "Exactly one High-weighted factor (one of F1-F5) is present and "
        "the connector has no agentic action capability (F7)."
    ),
    "High": (
        "Agentic action capability (F7) on its own, or two or more "
        "High-weighted factors (F1-F5)."
    ),
    "Critical": (
        "Agentic action capability (F7) combined with sensitive-data "
        "reach (F1), non-user-bound credentials (F3), or absent logging "
        "(F4)."
    ),
}
# All three tools only read bundled data / compute scores locally: they
# never mutate anything, never call external services, and the same input
# always yields the same output.
READ_ONLY_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}


def factor_details(codes: dict[str, str]) -> list[dict]:
    """Per-factor breakdown pairing each code with its name and meaning."""
    return [
        {
            "factor": f,
            "name": FACTOR_LABELS[f],
            "weight": FACTOR_WEIGHTS[f],
            "code": codes[f],
            "code_meaning": CODE_MEANINGS[codes[f]],
        }
        for f in FACTORS
    ]

# ---------------------------------------------------------------------------
# Scoring rule — exact replica of paara_scanner/scoring.py (kit), used when
# the kit package itself is not importable. Highest-severity condition met,
# not a sum. Every score is a band: lower bound (U as N), upper (U as Y).
# ---------------------------------------------------------------------------


def _resolve(codes: dict[str, str], unknown_as_yes: bool) -> dict[str, bool]:
    return {
        f: (c == "Y" or (c == "U" and unknown_as_yes)) for f, c in codes.items()
    }


def _score_single(resolved: dict[str, bool]) -> tuple[str, str]:
    if resolved["F7"] and (resolved["F1"] or resolved["F3"] or resolved["F4"]):
        triggers = [x for x in ("F1", "F3", "F4") if resolved[x]]
        return "Critical", f"F7 (write/action) with {', '.join(triggers)}"
    if resolved["F7"]:
        return "High", "F7 (write/action) alone"
    high = [x for x in HIGH_FACTORS if resolved[x]]
    if len(high) >= 2:
        return "High", f"{len(high)} High-weighted factors: {', '.join(high)}"
    if len(high) == 1:
        return "Moderate", f"one High-weighted factor: {high[0]}"
    medium = [x for x in MEDIUM_FACTORS if resolved[x]]
    if len(medium) >= 2:  # unreachable with one Medium factor; kept for parity
        return "Moderate", "multiple Medium-weighted factors"
    return "Low", "no High-weighted factor and no write/action capability"


def score_codes_local(
    codes: dict[str, str], restricted: bool = False
) -> dict:
    """Score F1-F7 codes with the local replica. Returns bands + reasons."""
    lower, lower_reason = _score_single(_resolve(codes, False))
    upper, upper_reason = _score_single(_resolve(codes, True))
    out = {
        "default_lower": lower,
        "default_upper": upper,
        "restricted_lower": None,
        "restricted_upper": None,
        "reasons": [
            f"lower bound (U as N): {lower} — {lower_reason}",
            f"upper bound (U as Y): {upper} — {upper_reason}",
        ],
        "unknowns": [f for f in FACTORS if codes[f] == "U"],
    }
    if restricted:
        rcodes = dict(codes)
        rcodes["F7"] = "N"
        r_lower, r_lo_reason = _score_single(_resolve(rcodes, False))
        r_upper, r_up_reason = _score_single(_resolve(rcodes, True))
        out["restricted_lower"] = r_lower
        out["restricted_upper"] = r_upper
        out["reasons"].append(
            f"restricted (F7=N): {r_lower} -> {r_upper} "
            f"— lower: {r_lo_reason}; upper: {r_up_reason}"
        )
    return out


# ---------------------------------------------------------------------------
# Prefer the kit's own scoring module when it is importable by path.
# ---------------------------------------------------------------------------

_kit_score = None


def _load_kit_scoring():
    global _kit_score
    if _kit_score is not None:
        return _kit_score
    candidates = []
    if os.environ.get("PAARA_KIT_SRC"):
        candidates.append(Path(os.environ["PAARA_KIT_SRC"]))
    candidates.append(HERE.parent / "paara-repo" / "src")
    candidates.append(HERE / "paara_scanner_src")
    for src in candidates:
        if (src / "paara_scanner" / "scoring.py").is_file():
            sys.path.insert(0, str(src))
            try:
                from paara_scanner.models import Connector
                from paara_scanner.scoring import score_connector as kit_score

                _kit_score = (Connector, kit_score)
                return _kit_score
            except Exception:
                sys.path.remove(str(src))
    _kit_score = False
    return _kit_score


def score_codes(codes: dict[str, str], restricted: bool = False) -> dict:
    """Score with the kit module when available, else the local replica."""
    kit = _load_kit_scoring()
    if kit:
        Connector, kit_score = kit
        connector = Connector.from_code_string(
            "adhoc", "".join(codes[f] for f in FACTORS),
            has_write_limiting_control=restricted,
        )
        result = kit_score(connector)
        return {
            "default_lower": result.lower.value,
            "default_upper": result.upper.value,
            "restricted_lower": (
                result.restricted_lower.value if result.restricted_lower else None
            ),
            "restricted_upper": (
                result.restricted_upper.value if result.restricted_upper else None
            ),
            "reasons": list(result.reasons),
            "unknowns": [f.value for f in result.unknowns],
            "engine": "paara_scanner (kit)",
        }
    out = score_codes_local(codes, restricted)
    out["engine"] = "local replica of paara_scanner.scoring"
    return out


# ---------------------------------------------------------------------------
# Bundled dataset (the published 13-connector audit, snapshot 9 Nov 2026)
# ---------------------------------------------------------------------------

_ABBREV = {"Crit": "Critical", "Mod": "Moderate", "High": "High", "Low": "Low"}


def _full(value: str) -> str | None:
    value = (value or "").strip()
    return _ABBREV.get(value, value) if value else None


def load_dataset() -> list[dict]:
    rows = []
    with DATASET_CSV.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            name = (row.get("connector") or "").strip()
            if not name:
                continue
            rows.append(
                {
                    "name": name,
                    "codes": {f: row[f].strip().upper() for f in FACTORS},
                    "published_default_lower": _full(row["default_lower"]),
                    "published_default_upper": _full(row["default_upper"]),
                    "published_restricted_lower": _full(row["restricted_lower"]),
                    "published_restricted_upper": _full(row["restricted_upper"]),
                    "documentation_retrieved": (
                        row.get("documentation_retrieved") or ""
                    ).strip(),
                }
            )
    return rows


DATASET = load_dataset()


def _norm(text: str) -> str:
    return " ".join(text.lower().replace(".", " ").split())


def find_connector(query: str) -> dict | None:
    q = _norm(query)
    for row in DATASET:
        if _norm(row["name"]) == q:
            return row
    for row in DATASET:
        n = _norm(row["name"])
        if q in n or n in q:
            return row
    names = {_norm(r["name"]): r for r in DATASET}
    close = difflib.get_close_matches(q, list(names), n=1, cutoff=0.5)
    if close:
        return names[close[0]]
    tokens = set(q.split())
    best, best_overlap = None, 0
    for row in DATASET:
        overlap = len(tokens & set(_norm(row["name"]).split()))
        if overlap > best_overlap:
            best, best_overlap = row, overlap
    return best


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def tool_score_connector(args: dict) -> dict:
    codes = {}
    for f in FACTORS:
        value = str(args.get(f, "")).strip().upper()
        if value not in ("Y", "N", "U"):
            raise ValueError(f"{f} must be one of Y, N, U (got {args.get(f)!r})")
        codes[f] = value
    restricted = bool(args.get("restricted", False))
    scored = score_codes(codes, restricted)
    return {
        "name": args.get("name") or "adhoc connector",
        "codes": codes,
        "code_string": "".join(codes[f] for f in FACTORS),
        "factors": factor_details(codes),
        "band_meanings": BAND_MEANINGS,
        **scored,
        "note": (
            "Bands, not points: U (documentation silent) is not evidence of "
            "absence, so the lower bound treats U as N and the upper as Y. "
            "Restricted bands apply only where a documented write-limiting "
            "control exists (restricted=true sets F7 to N)."
        ),
    }


def tool_lookup_connector(args: dict) -> dict:
    query = str(args.get("name", "")).strip()
    if not query:
        raise ValueError("name is required")
    row = find_connector(query)
    if row is None:
        return {
            "found": False,
            "query": query,
            "known_connectors": [r["name"] for r in DATASET],
            "note": (
                "No connector in the published 13-connector audit matches "
                "the query. Retry with one of known_connectors, or score "
                "the connector directly with score_connector."
            ),
        }
    restricted = row["published_restricted_lower"] is not None
    scored = score_codes(row["codes"], restricted)
    return {
        "found": True,
        "name": row["name"],
        "codes": row["codes"],
        "code_string": "".join(row["codes"][f] for f in FACTORS),
        "factors": factor_details(row["codes"]),
        "band_meanings": BAND_MEANINGS,
        "default_lower": scored["default_lower"],
        "default_upper": scored["default_upper"],
        "restricted_lower": scored["restricted_lower"],
        "restricted_upper": scored["restricted_upper"],
        "published_bands_match": (
            scored["default_lower"] == row["published_default_lower"]
            and scored["default_upper"] == row["published_default_upper"]
            and scored["restricted_lower"] == row["published_restricted_lower"]
            and scored["restricted_upper"] == row["published_restricted_upper"]
        ),
        "documentation_retrieved": row["documentation_retrieved"],
        "source": "PAARA 13-connector audit (documentation snapshot, 9 Nov 2026)",
    }


def tool_list_connectors(_args: dict) -> dict:
    return {
        "count": len(DATASET),
        "snapshot": "documentation retrieved 2026-11-09",
        "source": "PAARA 13-connector audit (documentation snapshot, 9 Nov 2026)",
        "factors": [
            {"factor": f, "name": FACTOR_LABELS[f], "weight": FACTOR_WEIGHTS[f]}
            for f in FACTORS
        ],
        "band_meanings": BAND_MEANINGS,
        "bands_explained": (
            "Each connector carries a band range, not a point score: "
            "default_lower treats unknown (U) codes as N, default_upper "
            "treats them as Y. restricted_lower/restricted_upper are the "
            "same range with a documented write-limiting control applied "
            "(F7 set to N); null when no such control is documented."
        ),
        "connectors": [
            {
                "name": r["name"],
                "codes": r["codes"],
                "code_string": "".join(r["codes"][f] for f in FACTORS),
                "default_lower": r["published_default_lower"],
                "default_upper": r["published_default_upper"],
                "restricted_lower": r["published_restricted_lower"],
                "restricted_upper": r["published_restricted_upper"],
            }
            for r in DATASET
        ],
    }


_FACTOR_INPUT_DESCRIPTIONS = {
    "F1": (
        "F1 Sensitive-data reach: 'Y' if the documentation shows the "
        "connector can reach sensitive data (message bodies, files, "
        "records), 'N' if documented as unable to, 'U' if silent."
    ),
    "F2": (
        "F2 Cross-system aggregation: 'Y' if the connector aggregates or "
        "correlates data across multiple systems or sources, 'N' if "
        "documented as single-system only, 'U' if silent."
    ),
    "F3": (
        "F3 Non-user-bound credentials: 'Y' if calls run on service or "
        "app credentials not bound to the acting user (e.g. a bot token), "
        "'N' if calls run on the user's own tokens, 'U' if silent."
    ),
    "F4": (
        "F4 Absent logging: 'Y' if audit logging of connector activity "
        "is documented as absent, 'N' if audit logging is documented, "
        "'U' if silent. Note the polarity: Y means logging is absent."
    ),
    "F5": (
        "F5 Prompt-injection exposure: 'Y' if the connector retrieves "
        "content authored by other people or external sources that could "
        "carry injected instructions, 'N' if it only processes the user's "
        "own content, 'U' if silent."
    ),
    "F6": (
        "F6 External sharing: 'Y' if the connector can send or share "
        "content outside the organisation (post messages, share files), "
        "'N' if documented as internal-only, 'U' if silent."
    ),
    "F7": (
        "F7 Agentic action capability: 'Y' if the connector exposes "
        "write/action tools (send, create, modify, delete, execute), "
        "'N' if read-only, 'U' if silent."
    ),
}

_BAND_SCHEMA = {"type": "string", "enum": ["Low", "Moderate", "High", "Critical"]}
_BAND_OR_NULL_SCHEMA = {
    "type": ["string", "null"],
    "enum": ["Low", "Moderate", "High", "Critical", None],
    "description": (
        "A score band, or null when no documented write-limiting control "
        "exists so no restricted band applies."
    ),
}
_CODES_SCHEMA = {
    "type": "object",
    "description": "The connector's F1-F7 factor codes (Y/N/U per factor).",
    "properties": {
        f: {"type": "string", "enum": ["Y", "N", "U"]} for f in FACTORS
    },
    "required": list(FACTORS),
}
_FACTORS_SCHEMA = {
    "type": "array",
    "description": (
        "Per-factor breakdown pairing each F1-F7 code with the factor's "
        "name, scoring weight, and what the code means, so results are "
        "readable without a separate codebook."
    ),
    "items": {
        "type": "object",
        "properties": {
            "factor": {"type": "string", "enum": list(FACTORS)},
            "name": {"type": "string", "description": "Human-readable factor name."},
            "weight": {"type": "string", "enum": ["High", "Medium", "Critical"]},
            "code": {"type": "string", "enum": ["Y", "N", "U"]},
            "code_meaning": {
                "type": "string",
                "description": "What the code means (documented present / absent / silent).",
            },
        },
        "required": ["factor", "name", "weight", "code", "code_meaning"],
    },
}
_BAND_MEANINGS_SCHEMA = {
    "type": "object",
    "description": "Plain-language meaning of each score band under the PAARA rule.",
    "properties": {
        band: {"type": "string"}
        for band in ("Low", "Moderate", "High", "Critical")
    },
}

TOOLS = [
    {
        "name": "score_connector",
        "title": "Score a connector with the PAARA rule",
        "description": (
            "Score any AI/MCP connector with the PAARA seven-factor risk "
            "rule and get a risk band (Low / Moderate / High / Critical).\n\n"
            "WHEN TO USE: Use this when you have coded a connector's "
            "documentation yourself — for example when auditing a connector "
            "that is NOT one of the 13 in the published dataset (for those, "
            "use lookup_connector instead), or when testing how a "
            "connector's band changes under different assumptions.\n\n"
            "INPUT: All seven factor codes F1-F7 are required. Code each "
            "factor from the connector's documentation: 'Y' = documented "
            "present, 'N' = documented absent, 'U' = documentation silent "
            "(unknown). The factors are F1 sensitive-data reach, F2 "
            "cross-system aggregation, F3 non-user-bound credentials, F4 "
            "absent logging (note: Y means logging is absent), F5 "
            "prompt-injection exposure, F6 external sharing, F7 agentic "
            "action capability. Optionally pass 'name' (a label echoed back "
            "in the result) and 'restricted': set restricted=true only when "
            "a documented write-limiting control applies to this connector; "
            "the result then also includes restricted bands (scored with "
            "F7 forced to N).\n\n"
            "RETURNS: A band range, not a point score: default_lower "
            "(unknowns treated as N) and default_upper (unknowns treated "
            "as Y), restricted_lower/restricted_upper when requested (null "
            "otherwise), a per-factor breakdown with factor names and "
            "weights, the reason for each bound, the list of unknown (U) "
            "factors, and the plain-language meaning of every band.\n\n"
            "EXAMPLE: {\"name\": \"Example Chat MCP\", \"F1\": \"Y\", "
            "\"F2\": \"N\", \"F3\": \"N\", \"F4\": \"N\", \"F5\": \"Y\", "
            "\"F6\": \"Y\", \"F7\": \"Y\"} scores Critical/Critical; adding "
            "\"restricted\": true gives a restricted band of High/High."
        ),
        "annotations": {"title": "Score a connector (read-only)", **READ_ONLY_ANNOTATIONS},
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": (
                        "Optional label for the connector being scored; "
                        "echoed back as 'name' in the result. Defaults to "
                        "'adhoc connector'."
                    ),
                },
                **{
                    f: {
                        "type": "string",
                        "enum": ["Y", "N", "U"],
                        "description": _FACTOR_INPUT_DESCRIPTIONS[f],
                    }
                    for f in FACTORS
                },
                "restricted": {
                    "type": "boolean",
                    "description": (
                        "Set to true only if a documented write-limiting "
                        "control applies to this connector (e.g. read-only "
                        "scopes enforced). When true, the result also "
                        "includes restricted_lower/restricted_upper bands "
                        "scored with F7 forced to N. Defaults to false."
                    ),
                },
            },
            "required": list(FACTORS),
        },
        "outputSchema": {
            "type": "object",
            "description": "PAARA score for one connector, as a band range with full reasoning.",
            "properties": {
                "name": {"type": "string", "description": "The connector label that was scored."},
                "codes": _CODES_SCHEMA,
                "code_string": {
                    "type": "string",
                    "description": "The seven factor codes as one string in F1-F7 order, e.g. 'YNNNYYY'.",
                },
                "factors": _FACTORS_SCHEMA,
                "band_meanings": _BAND_MEANINGS_SCHEMA,
                "default_lower": {**_BAND_SCHEMA, "description": "Lower bound of the default band (unknown U codes treated as N)."},
                "default_upper": {**_BAND_SCHEMA, "description": "Upper bound of the default band (unknown U codes treated as Y)."},
                "restricted_lower": _BAND_OR_NULL_SCHEMA,
                "restricted_upper": _BAND_OR_NULL_SCHEMA,
                "reasons": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Human-readable reason for each band bound, naming the triggering factors.",
                },
                "unknowns": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(FACTORS)},
                    "description": "Factors coded U (documentation silent); these drive the gap between the lower and upper bounds.",
                },
                "engine": {
                    "type": "string",
                    "description": "Which scoring engine produced the result (the kit's paara_scanner module, or the built-in exact replica).",
                },
                "note": {
                    "type": "string",
                    "description": "Method note explaining why results are band ranges rather than point scores.",
                },
            },
            "required": [
                "name", "codes", "code_string", "factors", "default_lower",
                "default_upper", "reasons", "unknowns",
            ],
        },
    },
    {
        "name": "lookup_connector",
        "title": "Look up a connector in the published PAARA audit",
        "description": (
            "Look up one of the 13 connectors in the published PAARA audit "
            "(documentation snapshot, 9 Nov 2026) and get its coded factors "
            "and score bands.\n\n"
            "WHEN TO USE: Use this when you need the audited result for a "
            "known connector (e.g. Slack MCP, Stripe MCP, GitHub MCP, MS "
            "Graph permissions) instead of coding it yourself. To score a "
            "connector that is not in the dataset, use score_connector; to "
            "see all 13 connectors at once, use list_connectors.\n\n"
            "INPUT: 'name' — the connector's name. Matching is forgiving: "
            "exact names, substrings, and close spellings all work (e.g. "
            "'slack', 'Stripe MCP', 'graph').\n\n"
            "RETURNS: If found: found=true, the connector's canonical "
            "name, its F1-F7 codes with a per-factor breakdown (names, "
            "weights, code meanings), its default and restricted score "
            "bands (restricted bands are null when no write-limiting "
            "control was documented), published_bands_match confirming the "
            "live score reproduces the published audit, the meaning of "
            "every band, and the documentation retrieval date. If not "
            "found: found=false, the query echoed back, and "
            "known_connectors listing the 13 valid names.\n\n"
            "EXAMPLE: {\"name\": \"slack\"} returns Slack MCP with codes "
            "YNNNYYY, default band Critical/Critical and restricted band "
            "High/High."
        ),
        "annotations": {"title": "Look up an audited connector (read-only)", **READ_ONLY_ANNOTATIONS},
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": (
                        "Name of a connector from the published "
                        "13-connector PAARA audit, e.g. 'Slack MCP', "
                        "'Stripe MCP' or 'MS Graph perms.'. Matching is "
                        "case-insensitive and fuzzy: substrings and close "
                        "spellings are accepted."
                    ),
                },
            },
            "required": ["name"],
        },
        "outputSchema": {
            "type": "object",
            "description": "One audited connector's codes and published bands, or a not-found result listing the valid names.",
            "properties": {
                "found": {"type": "boolean", "description": "True when a dataset connector matched the query."},
                "query": {"type": "string", "description": "The query as received (present when found is false)."},
                "known_connectors": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "The 13 valid connector names (present when found is false).",
                },
                "note": {"type": "string", "description": "Guidance when no connector matched."},
                "name": {"type": "string", "description": "The connector's canonical dataset name (present when found is true)."},
                "codes": _CODES_SCHEMA,
                "code_string": {
                    "type": "string",
                    "description": "The seven factor codes as one string in F1-F7 order, e.g. 'YNNNYYY'.",
                },
                "factors": _FACTORS_SCHEMA,
                "band_meanings": _BAND_MEANINGS_SCHEMA,
                "default_lower": {**_BAND_SCHEMA, "description": "Published lower bound of the default band (unknown U codes treated as N)."},
                "default_upper": {**_BAND_SCHEMA, "description": "Published upper bound of the default band (unknown U codes treated as Y)."},
                "restricted_lower": _BAND_OR_NULL_SCHEMA,
                "restricted_upper": _BAND_OR_NULL_SCHEMA,
                "published_bands_match": {
                    "type": "boolean",
                    "description": "True when re-scoring the stored codes reproduces the published bands exactly.",
                },
                "documentation_retrieved": {
                    "type": "string",
                    "description": "Date the connector's documentation was retrieved for the audit (ISO date).",
                },
                "source": {"type": "string", "description": "Provenance of the dataset row."},
            },
            "required": ["found"],
        },
    },
    {
        "name": "list_connectors",
        "title": "List the connectors in the published PAARA audit",
        "description": (
            "List all 13 connectors in the published PAARA audit "
            "(documentation snapshot, 9 Nov 2026) with their factor codes "
            "and score bands.\n\n"
            "WHEN TO USE: Use this to browse or compare the whole audited "
            "set — for example to see which connectors score Critical, or "
            "to find the exact canonical name to pass to lookup_connector. "
            "For one connector's full detail use lookup_connector; to "
            "score a connector outside the dataset use score_connector.\n\n"
            "INPUT: No arguments.\n\n"
            "RETURNS: count (13), the snapshot date and source, the F1-F7 "
            "factor legend (factor code, name, and scoring weight for "
            "each), the plain-language meaning of every band, an "
            "explanation of how the band ranges are derived, and one entry "
            "per connector with its name, F1-F7 codes, code string, and "
            "default/restricted band ranges (restricted bands are null "
            "when no write-limiting control was documented).\n\n"
            "EXAMPLE: {} returns 13 connectors; the first entry is MCP "
            "Filesystem with code string UNUUYNY and default band "
            "High to Critical."
        ),
        "annotations": {"title": "List audited connectors (read-only)", **READ_ONLY_ANNOTATIONS},
        "inputSchema": {
            "type": "object",
            "properties": {},
            "description": "Takes no arguments; call with an empty object.",
        },
        "outputSchema": {
            "type": "object",
            "description": "The full published 13-connector audit dataset with codes, bands, and the factor/band legends.",
            "properties": {
                "count": {"type": "integer", "description": "Number of connectors in the dataset (13)."},
                "snapshot": {"type": "string", "description": "When the underlying documentation was retrieved."},
                "source": {"type": "string", "description": "Provenance of the dataset."},
                "factors": {
                    "type": "array",
                    "description": "Legend for the seven PAARA factors.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "factor": {"type": "string", "enum": list(FACTORS)},
                            "name": {"type": "string"},
                            "weight": {"type": "string", "enum": ["High", "Medium", "Critical"]},
                        },
                        "required": ["factor", "name", "weight"],
                    },
                },
                "band_meanings": _BAND_MEANINGS_SCHEMA,
                "bands_explained": {
                    "type": "string",
                    "description": "How the lower/upper band ranges and restricted bands are derived.",
                },
                "connectors": {
                    "type": "array",
                    "description": "One entry per audited connector.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "codes": _CODES_SCHEMA,
                            "code_string": {"type": "string"},
                            "default_lower": _BAND_SCHEMA,
                            "default_upper": _BAND_SCHEMA,
                            "restricted_lower": _BAND_OR_NULL_SCHEMA,
                            "restricted_upper": _BAND_OR_NULL_SCHEMA,
                        },
                        "required": [
                            "name", "codes", "code_string",
                            "default_lower", "default_upper",
                        ],
                    },
                },
            },
            "required": ["count", "factors", "band_meanings", "connectors"],
        },
    },
]

TOOL_FUNCS = {
    "score_connector": tool_score_connector,
    "lookup_connector": tool_lookup_connector,
    "list_connectors": tool_list_connectors,
}

# ---------------------------------------------------------------------------
# MCP JSON-RPC over stdio (newline-delimited)
# ---------------------------------------------------------------------------


def _result(req_id, payload) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": payload}


def _error(req_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def handle(request: dict) -> dict | None:
    method = request.get("method", "")
    req_id = request.get("id")
    params = request.get("params") or {}

    if method == "initialize":
        client_version = params.get("protocolVersion")
        return _result(
            req_id,
            {
                "protocolVersion": client_version or DEFAULT_PROTOCOL,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        )
    if method == "ping":
        return _result(req_id, {})
    if method == "tools/list":
        return _result(req_id, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name", "")
        func = TOOL_FUNCS.get(name)
        if func is None:
            return _error(req_id, -32602, f"unknown tool: {name}")
        try:
            payload = func(params.get("arguments") or {})
        except Exception as exc:  # tool errors are reported, not fatal
            return _result(
                req_id,
                {
                    "content": [{"type": "text", "text": f"Error: {exc}"}],
                    "isError": True,
                },
            )
        text = json.dumps(payload, indent=2)
        return _result(
            req_id,
            {"content": [{"type": "text", "text": text}], "structuredContent": payload},
        )
    if req_id is None:  # notification (e.g. notifications/initialized)
        return None
    return _error(req_id, -32601, f"method not found: {method}")


def main() -> None:
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            response = _error(None, -32700, "parse error")
            stdout.write(json.dumps(response).encode() + b"\n")
            stdout.flush()
            continue
        response = handle(request)
        if response is not None:
            stdout.write(json.dumps(response).encode() + b"\n")
            stdout.flush()


if __name__ == "__main__":
    main()
