"""Quality engines and bounded repair for the UI/UX compiler.

Engines: ANTI_GENERIC, SALIENCE_BUDGET, INTERACTION_DEBT, STATE_ENTROPY,
COUNTERFACTUAL_UX, LAYOUT_GRAMMAR, TRACEABILITY, CONTRAST.

Repair is bounded (``MAX_REPAIR_ITERATIONS``) and only performs edits that are
true by construction -- adding a missing EMPTY state, demoting an over-weighted
P3 region, adding a keyboard fallback. It never invents what it cannot know:
a missing *justification* for a nonstandard interaction, or a brand palette
that fails contrast, is escalated to ``approval_required`` instead of papered
over.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .models import (
    EvaluationEngine,
    EvaluationFinding,
    Priority,
    Severity,
    TokenSystemSpec,
    UIState,
    WCAGRequirement,
)

if TYPE_CHECKING:  # pragma: no cover
    from .compiler import Draft

MAX_REPAIR_ITERATIONS = 3

_GENERIC_MOTIFS = (
    ("purple gradient", "Purple gradients read as template AI branding."),
    ("gradient", "Decorative gradients need a brand reason."),
    ("glow", "Glows add noise without meaning."),
    ("glassmorphism", "Glass effects hurt contrast and read as templated."),
    ("glass", "Glass effects hurt contrast and read as templated."),
    ("floating blob", "Floating blobs are generic decoration."),
    ("blob", "Floating blobs are generic decoration."),
    ("card everything", "Card-everything layouts flatten hierarchy."),
    ("pill", "Pill overload blurs the difference between tags, actions, and status."),
    ("ai badge", "Decorative AI badges without provenance mislead."),
    ("sparkle", "Sparkle 'AI' iconography is decoration, not provenance."),
)

_STATUS_STATES = {
    UIState.error, UIState.warning, UIState.invalid, UIState.success, UIState.degraded,
    UIState.offline, UIState.unavailable, UIState.pending_approval, UIState.approved,
    UIState.rejected, UIState.stale, UIState.selected, UIState.checked, UIState.current,
    UIState.focus_visible, UIState.disabled,
}

_COUNTERFACTUALS = (
    "color removed", "motion removed", "pointer unavailable", "viewport halved", "copy +200%",
    "data empty", "permission denied", "network degraded", "AI unavailable",
)


@dataclass
class EvaluationState:
    findings: list[EvaluationFinding] = field(default_factory=list)
    iterations: int = 0
    approval_required: list[str] = field(default_factory=list)


def _key(finding: EvaluationFinding) -> tuple[str, str, str]:
    return (finding.engine.value, finding.subject, finding.message)


def _tagged(draft: "Draft", tag: str) -> list[str]:
    return [name for name, spec in draft.components.items() if tag in spec["template"].tags]


# --------------------------------------------------------------------------- #
# Engines. Each returns findings; a finding with ``repair`` set is repairable.
# --------------------------------------------------------------------------- #


@dataclass
class _Issue:
    finding: EvaluationFinding
    repair: Any = None  # callable(draft) -> str description, or None if not repairable
    approval: str | None = None


def _anti_generic(draft: "Draft", request_text: dict[str, Any]) -> list[_Issue]:
    issues: list[_Issue] = []
    justification = " ".join(request_text["constraints"]).lower()
    haystacks = {
        "request.content": " ".join(request_text["content"]).lower(),
        "design_genome": " ".join(str(v) for k, v in draft.genome.model_dump().items() if k != "genome_hash").lower(),
    }
    for subject, text in haystacks.items():
        seen: set[str] = set()
        for motif, reason in _GENERIC_MOTIFS:
            if motif in text and not any(motif in item for item in seen):
                seen.add(motif)
                justified = motif in justification and ("brand" in justification or "required" in justification)
                if justified:
                    continue
                issues.append(_Issue(
                    EvaluationFinding(engine=EvaluationEngine.anti_generic, severity=Severity.warning,
                                      subject=subject, message=f"unjustified '{motif}': {reason}"),
                    repair=lambda d, m=motif: _replace_motif(d, m),
                ))
    for phrase in request_text["generic_copy"]:
        issues.append(_Issue(
            EvaluationFinding(engine=EvaluationEngine.anti_generic, severity=Severity.warning,
                              subject="request.copy", message=f"generic SaaS phrase '{phrase}'"),
            repair=lambda d, p=phrase: _add_rule(d, "content_rules",
                                                 f"Replace generic phrasing ('{p}') with a specific, verifiable claim about the product."),
        ))
    return issues


def _replace_motif(draft: "Draft", motif: str) -> str:
    rule = f"Do not use '{motif}' decoration; express the brand through the product-specific signature element instead."
    _add_rule(draft, "patterns", rule)
    return f"added pattern rule against '{motif}'"


def _add_rule(draft: "Draft", key: str, rule: str) -> str:
    if rule not in draft.design_system[key]:
        draft.design_system[key].append(rule)
    return f"design_system.{key} += rule"


def _salience(draft: "Draft") -> list[_Issue]:
    issues: list[_Issue] = []
    for screen in draft.screens:
        regions = screen["regions"]
        p0 = [r.emphasis for r in regions if r.priority is Priority.p0]
        if not p0:
            issues.append(_Issue(EvaluationFinding(
                engine=EvaluationEngine.salience_budget, severity=Severity.blocking,
                subject=f"screens.{screen['id']}", message="no P0 region: the primary task has no home")))
            continue
        top = max(p0)
        for index, region in enumerate(regions):
            if region.priority is Priority.p3 and region.emphasis >= top:
                def repair(d, s=screen, i=index):
                    s["regions"][i] = s["regions"][i].model_copy(update={"emphasis": 1})
                    return f"demoted {s['regions'][i].id} emphasis to 1"
                issues.append(_Issue(EvaluationFinding(
                    engine=EvaluationEngine.salience_budget, severity=Severity.blocking,
                    subject=f"screens.{screen['id']}.{region.id}",
                    message=f"P3 region emphasis {region.emphasis} >= P0 emphasis {top}"), repair=repair))
    return issues


def _interaction_debt(draft: "Draft") -> list[_Issue]:
    issues: list[_Issue] = []
    for index, interaction in enumerate(draft.interactions):
        if interaction.standard:
            continue
        if not interaction.fallback:
            def repair(d, i=index):
                current = d.interactions[i]
                modes = list(dict.fromkeys([*current.input_modes, "KEYBOARD", "SCREEN_READER"]))
                d.interactions[i] = current.model_copy(update={
                    "fallback": "Standard control alternative: 'Move up/down' buttons and a position menu, operable by keyboard.",
                    "input_modes": modes,
                })
                return f"added standard keyboard fallback to {current.id}"
            issues.append(_Issue(EvaluationFinding(
                engine=EvaluationEngine.interaction_debt, severity=Severity.blocking,
                subject=interaction.id, message="nonstandard interaction has no standard fallback"), repair=repair))
        if not interaction.justification:
            issues.append(_Issue(
                EvaluationFinding(engine=EvaluationEngine.interaction_debt, severity=Severity.warning,
                                  subject=interaction.id,
                                  message="nonstandard interaction lacks a stated user-value justification"),
                approval=f"DECISION: justify or remove nonstandard interaction {interaction.id}.",
            ))
    return issues


def _state_entropy(draft: "Draft", states_for) -> list[_Issue]:
    issues: list[_Issue] = []
    for name, spec in draft.components.items():
        seen: dict[tuple[str, str], UIState] = {}
        for state in spec["states"]:
            row = states_for(state)
            key = (row[1], row[2])
            if key in seen and seen[key] is not state:
                issues.append(_Issue(EvaluationFinding(
                    engine=EvaluationEngine.state_entropy, severity=Severity.blocking, subject=name,
                    message=f"{state.value} is visually/contentually identical to {seen[key].value}")))
            seen.setdefault(key, state)
    return issues


def _counterfactual(draft: "Draft", has_ai: bool, states_for) -> list[_Issue]:
    issues: list[_Issue] = []

    def need_state(tag: str, state: UIState, scenario: str) -> None:
        for name in _tagged(draft, tag):
            if state not in draft.components[name]["states"]:
                def repair(d, n=name, s=state):
                    d.components[n]["states"].append(s)
                    return f"added {s.value} to {n}"
                issues.append(_Issue(EvaluationFinding(
                    engine=EvaluationEngine.counterfactual, severity=Severity.blocking, subject=name,
                    message=f"'{scenario}': missing {state.value} state"), repair=repair))

    # color removed: every status-like state needs a non-color channel
    for name, spec in draft.components.items():
        for state in spec["states"]:
            if state in _STATUS_STATES and not states_for(state)[9]:
                issues.append(_Issue(EvaluationFinding(
                    engine=EvaluationEngine.counterfactual, severity=Severity.blocking, subject=f"{name}.{state.value}",
                    message="'color removed': status state has no non-color channel")))
    # motion removed
    if not any("reduced-motion" in rule or "prefers-reduced-motion" in rule for rule in draft.design_system["motion_rules"]):
        issues.append(_Issue(
            EvaluationFinding(engine=EvaluationEngine.counterfactual, severity=Severity.blocking,
                              subject="design_system.motion_rules", message="'motion removed': no reduced-motion rule"),
            repair=lambda d: _add_rule(d, "motion_rules",
                                       "prefers-reduced-motion: reduce disables non-essential animation; meaning never depends on motion."),
        ))
    # pointer unavailable
    for index, interaction in enumerate(draft.interactions):
        if "KEYBOARD" not in interaction.input_modes:
            def repair(d, i=index):
                current = d.interactions[i]
                d.interactions[i] = current.model_copy(update={"input_modes": [*current.input_modes, "KEYBOARD"]})
                return f"added KEYBOARD input to {current.id}"
            issues.append(_Issue(EvaluationFinding(
                engine=EvaluationEngine.counterfactual, severity=Severity.blocking, subject=interaction.id,
                message="'pointer unavailable': no keyboard path"), repair=repair))
    # viewport halved + copy +200%: every region must declare a transform and a non-clipping overflow
    for screen in draft.screens:
        for region in screen["regions"]:
            if region.overflow not in {"WRAP", "SCROLL", "TRUNCATE_WITH_DISCLOSURE", "GROW"}:
                issues.append(_Issue(EvaluationFinding(
                    engine=EvaluationEngine.counterfactual, severity=Severity.blocking,
                    subject=f"{screen['id']}.{region.id}", message="'copy +200%': region clips content")))
    need_state("data", UIState.empty, "data empty")
    need_state("data", UIState.loading, "network degraded")
    need_state("data", UIState.offline, "network degraded")
    need_state("action", UIState.disabled, "permission denied")
    if has_ai:
        need_state("ai", UIState.unavailable, "AI unavailable")
        need_state("ai", UIState.degraded, "AI unavailable")
    return issues


def _layout_grammar(draft: "Draft", token_paths: set[str]) -> list[_Issue]:
    issues: list[_Issue] = []
    for screen in draft.screens:
        for index, region in enumerate(screen["regions"]):
            if region.spacing_token not in token_paths:
                def repair(d, s=screen, i=index):
                    s["regions"][i] = s["regions"][i].model_copy(update={"spacing_token": "semantic.space.stack"})
                    return f"reset {s['regions'][i].id} spacing to semantic.space.stack"
                issues.append(_Issue(EvaluationFinding(
                    engine=EvaluationEngine.layout_grammar, severity=Severity.blocking,
                    subject=f"{screen['id']}.{region.id}",
                    message=f"spacing token '{region.spacing_token}' is not a defined token"), repair=repair))
    return issues


def _traceability(draft: "Draft", token_paths: set[str], component_tokens) -> list[_Issue]:
    issues: list[_Issue] = []
    for screen in draft.screens:
        for name in screen["components"]:
            if name not in draft.components:
                issues.append(_Issue(EvaluationFinding(
                    engine=EvaluationEngine.traceability, severity=Severity.blocking,
                    subject=f"screens.{screen['id']}", message=f"references undefined component {name}")))
    for name, spec in draft.components.items():
        missing = [t for t in component_tokens(spec["template"].tags) if t not in token_paths]
        if missing:
            issues.append(_Issue(EvaluationFinding(
                engine=EvaluationEngine.traceability, severity=Severity.blocking, subject=name,
                message=f"references undefined tokens {missing}")))
    return issues


def _contrast(token_system: TokenSystemSpec) -> list[_Issue]:
    issues: list[_Issue] = []
    for check in token_system.contrast:
        if check.passes:
            continue
        essential = check.wcag_requirement in {WCAGRequirement.aaa_normal, WCAGRequirement.non_text} or \
            check.foreground.endswith(("on-accent", "foreground"))
        issues.append(_Issue(
            EvaluationFinding(
                engine=EvaluationEngine.contrast,
                severity=Severity.blocking if essential else Severity.warning,
                subject=f"{check.foreground} on {check.background}",
                message=f"{check.wcag_ratio}:1 fails {check.wcag_requirement.value} (WCAG 2.2); "
                        f"APCA Lc {check.apca_lc_advisory} reported as advisory only"),
            approval=f"DECISION: token pair {check.foreground}/{check.background} fails WCAG 2.2 "
                     f"{check.wcag_requirement.value}; adjust the palette.",
        ))
    return issues


# --------------------------------------------------------------------------- #
# Loop
# --------------------------------------------------------------------------- #


def _run_engines(draft: "Draft", token_system: TokenSystemSpec, request_text: dict[str, Any], has_ai: bool) -> list[_Issue]:
    from .compiler import _STATE_TABLE, _component_tokens  # local: avoid import cycle

    def states_for(state: UIState):
        return _STATE_TABLE[state]

    token_paths = _token_paths(token_system.document)
    return [
        *_anti_generic(draft, request_text),
        *_salience(draft),
        *_interaction_debt(draft),
        *_state_entropy(draft, states_for),
        *_counterfactual(draft, has_ai, states_for),
        *_layout_grammar(draft, token_paths),
        *_traceability(draft, token_paths, _component_tokens),
        *_contrast(token_system),
    ]


def _token_paths(document: dict[str, Any], prefix: str = "") -> set[str]:
    paths: set[str] = set()
    for key, value in document.items():
        if key.startswith("$") or not isinstance(value, dict):
            continue
        path = f"{prefix}.{key}" if prefix else key
        if "$value" in value:
            paths.add(path)
        else:
            paths |= _token_paths(value, path)
    return paths


def evaluate_and_repair(*, draft: "Draft", token_system: TokenSystemSpec,
                        request_text: dict[str, Any], has_ai: bool) -> EvaluationState:
    state = EvaluationState()
    recorded: dict[tuple[str, str, str], EvaluationFinding] = {}

    for _ in range(MAX_REPAIR_ITERATIONS + 1):
        issues = _run_engines(draft, token_system, request_text, has_ai)
        for issue in issues:
            recorded.setdefault(_key(issue.finding), issue.finding)
            if issue.approval and issue.approval not in state.approval_required:
                state.approval_required.append(issue.approval)
        repairable = [issue for issue in issues if issue.repair is not None]
        if not repairable or state.iterations >= MAX_REPAIR_ITERATIONS:
            break
        state.iterations += 1
        for issue in repairable:
            action = issue.repair(draft)
            key = _key(issue.finding)
            recorded[key] = recorded[key].model_copy(update={"repaired": True, "repair_action": action})

    # Anything the final pass still reports is unrepaired, whatever earlier passes did.
    final = {_key(issue.finding) for issue in _run_engines(draft, token_system, request_text, has_ai)}
    for key, finding in recorded.items():
        if key in final and finding.repaired:
            recorded[key] = finding.model_copy(update={"repaired": False})
    state.findings = sorted(recorded.values(), key=lambda f: (f.engine.value, f.subject, f.message))
    return state
