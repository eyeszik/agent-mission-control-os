"""One model abstraction for all three engines.

``MockSeatModel`` is deterministic and offline: it derives each seat's output
from the idea text with fixed rules, makes no network call and is labelled
``MOCK_DETERMINISTIC`` everywhere it appears. ``RouterSeatModel`` sends the same
prompt through the repository's canonical model router (``generate_structured``)
with the mission's pinned profile; a degraded outcome is an error, never
substitute content.

Engines talk to models through text (CrewAI's ``BaseLLM``, AutoGen's
``ChatCompletionClient``), so a prompt carries its seat and a machine-readable
context block. ``parse_prompt`` recovers both, which is how the framework
bridges route a call to the right seat.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from typing import Any, Protocol

from .contracts import ModelMode

SEAT_MARKER = "COUNCIL_SEAT:"
CONTEXT_MARKER = "COUNCIL_CONTEXT_JSON:"
_TRUTHY = {"1", "true", "yes", "on"}
REAL_PROVIDERS = ("openai", "anthropic", "gemini", "ollama")


class ModelUnavailable(RuntimeError):
    """The selected model could not produce output (no credential, provider error, degraded)."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


class SeatModel(Protocol):
    mode: ModelMode

    def complete(self, prompt: str) -> str: ...


def render_prompt(seat: str, instructions: str, context: Mapping[str, Any]) -> str:
    return (f"{SEAT_MARKER} {seat}\n{instructions.strip()}\n\nRespond with one JSON object only.\n"
            f"{CONTEXT_MARKER} {json.dumps(context, sort_keys=True, ensure_ascii=False)}\n")


def parse_prompt(text: str) -> tuple[str | None, dict]:
    """The last seat and context blocks in ``text`` (frameworks prepend their own framing)."""
    seat = None
    for match in re.finditer(rf"{re.escape(SEAT_MARKER)}\s*([a-z]+)", text):
        seat = match.group(1)
    context: dict = {}
    idx = text.rfind(CONTEXT_MARKER)
    if idx >= 0:
        try:
            context, _ = json.JSONDecoder().raw_decode(text[idx + len(CONTEXT_MARKER):].lstrip())
        except ValueError:
            context = {}
    return seat, context if isinstance(context, dict) else {}


def extract_json(text: str) -> dict:
    """The first JSON object in ``text``; model output often wraps JSON in prose or fences."""
    decoder = json.JSONDecoder()
    for start in [m.start() for m in re.finditer(r"\{", text)]:
        try:
            value, _ = decoder.raw_decode(text[start:])
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("no JSON object in model output")


# --------------------------------------------------------------------------------------- mock


_STOP = {"the", "and", "with", "for", "into", "from", "that", "this", "a", "an", "of", "to", "in", "on", "our", "their"}
_ARCHITECTURE = (
    (("dashboard", "ui", "page", "frontend", "interface", "screen", "timeline"),
     "Next.js route in apps/web using the design tokens and motion primitives"),
    (("api", "endpoint", "service", "backend", "webhook"),
     "FastAPI route in services/langgraph with Pydantic request and response contracts"),
    (("data", "store", "persist", "database", "history", "record"),
     "Durable tables through the persistence layer (SQLite locally, PostgreSQL in production)"),
    (("agent", "council", "workflow", "pipeline", "orchestrat"),
     "Orchestration through the mission council engines with checkpointed state"),
    (("auth", "permission", "security", "secret", "approval", "compliance"),
     "Server-side authorization, approval gates and audit through the Sentinel gateway"),
)


def _clauses(text: str) -> list[str]:
    parts = [p.strip(" -*\t") for p in re.split(r"[.;\n]+", text)]
    return [p[:160] for p in parts if len(p) >= 8][:4]


def _pascal(text: str, suffix: str) -> str:
    words = [w for w in re.findall(r"[A-Za-z0-9]+", text) if w.lower() not in _STOP][:3]
    base = "".join(w[:1].upper() + w[1:].lower() for w in words if w) or "Feature"
    if not base[0].isalpha():
        base = "V" + base
    return (base + suffix)[:60]


def _jsx_text(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9 ,.'()\-:/]", "", text)[:200]


def mock_george(context: Mapping[str, Any]) -> dict:
    idea = context.get("idea") or {}
    title, description = str(idea.get("title", "")), str(idea.get("description", ""))
    goals = _clauses(description) or [title or "Deliver the requested capability"]
    text = f"{title} {description}".lower()
    architecture = [line for keys, line in _ARCHITECTURE if any(k in text for k in keys)] or [
        "Single Next.js page backed by an existing API route"]
    tasks = [{"id": "clarify", "title": f"Confirm scope and success criteria for {title}"[:160], "seat": "george",
              "depends_on": [], "acceptance": "Acceptance criteria written and agreed before build starts"}]
    builds = []
    for i, goal in enumerate(goals, start=1):
        tasks.append({"id": f"design-{i}", "title": f"Design: {goal}"[:160], "seat": "arty", "depends_on": ["clarify"],
                      "acceptance": "Component spec uses design tokens and covers empty, loading and error states"})
        tasks.append({"id": f"build-{i}", "title": f"Build: {goal}"[:160], "seat": "arty", "depends_on": [f"design-{i}"],
                      "acceptance": "Implemented behind the existing API with typed contracts and tests"})
        builds.append(f"build-{i}")
    tasks.append({"id": "security-review", "title": "Security, permission and secret-handling review", "seat": "fable",
                  "depends_on": builds, "acceptance": "No unapproved side effects; secrets never logged or rendered"})
    tasks.append({"id": "verify", "title": "Verify accessibility, performance and acceptance criteria", "seat": "george",
                  "depends_on": ["security-review"], "acceptance": "WCAG 2.2 AA checks pass and acceptance criteria are met"})
    return {"summary": f"Decomposed '{title}' into {len(goals)} goal(s) and a {len(tasks)}-task dependency graph "
                       f"spanning {len(architecture)} architecture area(s).",
            "goals": goals, "architecture": architecture, "tasks": tasks}


def mock_fable(context: Mapping[str, Any]) -> dict:
    policy = context.get("policy") or {}
    findings = policy.get("findings") or []
    level = policy.get("level", "LOW")
    needs = "required" if policy.get("requires_approval") else "not required"
    codes = ", ".join(sorted({f.get("code", "") for f in findings})) or "none"
    # The mock never invents findings: it summarizes the deterministic policy scan.
    return {"narrative": f"Policy scan level {level}; findings: {codes}. Human approval {needs} before any side effect.",
            "additional_findings": []}


def mock_arty(context: Mapping[str, Any]) -> dict:
    idea = context.get("idea") or {}
    strategy = context.get("strategy") or {}
    title = str(idea.get("title", "Feature"))
    page = _pascal(title, "Page")
    components = [{"name": page, "purpose": f"Route-level layout for {title}"[:300], "props": []}]
    seen = {page}
    for goal in (strategy.get("goals") or [])[:6]:
        name = _pascal(goal, "Panel")
        n = 2
        while name in seen:
            name, n = f"{_pascal(goal, 'Panel')}{n}", n + 1
        seen.add(name)
        components.append({"name": name, "purpose": str(goal)[:300], "props": ["title"]})
    tokens = ["semantic.color.surface", "semantic.color.foreground", "semantic.color.accent",
              "semantic.font.size.h2", "semantic.space.section", "semantic.motion.duration.reveal"]
    files = [{"path": "README.md", "content": "\n".join(
        [f"# {title} scaffold", "", "Generated by the mission council (deterministic mock model).", "",
         "## Components", *[f"- `{c['name']}`: {c['purpose']}" for c in components], "",
         "## Tokens", *[f"- `{t}`" for t in tokens], ""])}]
    for comp in components:
        slug = re.sub(r"(?<!^)([A-Z])", r"-\1", comp["name"]).lower()
        files.append({"path": f"components/{comp['name']}.tsx", "content": (
            f"export function {comp['name']}({{ title }}: {{ title: string }}) {{\n"
            f"  return (\n"
            f"    <section aria-labelledby=\"{slug}-title\" className=\"py-section\">\n"
            f"      <h2 id=\"{slug}-title\" className=\"text-h2 text-fg-strong\">{{title}}</h2>\n"
            f"      <p className=\"text-body text-fg-muted\">{_jsx_text(comp['purpose'])}</p>\n"
            f"    </section>\n"
            f"  );\n"
            f"}}\n")})
    return {"summary": f"Scaffold for '{title}': {len(components)} component(s) on the shared tokens.",
            "components": components, "design_tokens": tokens, "files": files}


_MOCK_SEATS = {"george": mock_george, "fable": mock_fable, "arty": mock_arty}


class MockSeatModel:
    """Deterministic, offline, labelled. Same prompt in, same JSON out."""

    mode: ModelMode = "MOCK_DETERMINISTIC"

    def complete(self, prompt: str) -> str:
        seat, context = parse_prompt(prompt)
        if seat not in _MOCK_SEATS:
            raise ModelUnavailable("MOCK_UNKNOWN_SEAT", f"mock model cannot answer for seat {seat!r}")
        return json.dumps(_MOCK_SEATS[seat](context), sort_keys=True)


class RouterSeatModel:
    """Real provider through the canonical model router with the mission's pinned profile."""

    mode: ModelMode = "PROVIDER"

    def __init__(self, run_metadata: Mapping[str, Any], authorization_ref: str) -> None:
        self._metadata = dict(run_metadata)
        self._authorization = authorization_ref

    def complete(self, prompt: str) -> str:
        from services.langgraph.graph.agency.llm import generate_structured

        seat, _ = parse_prompt(prompt)
        outcome = generate_structured(prompt, {}, schema_version=f"council-{seat or 'seat'}-v1",
                                      run_metadata=self._metadata, authorization_ref=f"{self._authorization}:{seat}")
        if outcome.degraded:
            raise ModelUnavailable(outcome.error_class or "PROVIDER_DEGRADED",
                                   f"model provider returned {outcome.mode}; no substitute output is used")
        return json.dumps(outcome.data)


def real_models_enabled(env: Mapping[str, str] | None = None) -> bool:
    env = os.environ if env is None else env
    return (env.get("ENABLE_REAL_MODELS") or "").strip().lower() in _TRUTHY


def default_provider(env: Mapping[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    return (env.get("DEFAULT_MODEL_PROVIDER") or "mock").strip().lower()


def selected_mode(env: Mapping[str, str] | None = None) -> ModelMode:
    """PROVIDER only when real models are enabled and a real provider is named; otherwise the mock."""
    provider = default_provider(env)
    return "PROVIDER" if real_models_enabled(env) and provider in REAL_PROVIDERS else "MOCK_DETERMINISTIC"


def profile_pin(env: Mapping[str, str] | None = None) -> dict | None:
    """The model profile a PROVIDER mission pins at dispatch (``AMC_LLM_PROVIDER`` := provider)."""
    if selected_mode(env) != "PROVIDER":
        return None
    from services.langgraph.agency.model_profiles import pin_metadata

    base = dict(os.environ if env is None else env)
    base["AMC_LLM_PROVIDER"] = default_provider(env)
    return pin_metadata(base)


def model_for(model_mode: ModelMode, run_metadata: Mapping[str, Any], authorization_ref: str) -> SeatModel:
    if model_mode == "PROVIDER":
        return RouterSeatModel(run_metadata, authorization_ref)
    return MockSeatModel()


__all__ = [
    "CONTEXT_MARKER",
    "REAL_PROVIDERS",
    "SEAT_MARKER",
    "MockSeatModel",
    "ModelUnavailable",
    "RouterSeatModel",
    "SeatModel",
    "default_provider",
    "extract_json",
    "model_for",
    "parse_prompt",
    "profile_pin",
    "real_models_enabled",
    "render_prompt",
    "selected_mode",
]
