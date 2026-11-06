"""Deterministic UI/UX design compiler.

    REQUEST -> PRODUCT -> USER -> TASK -> IA -> FLOW -> PRINCIPLES -> DIRECTION
    -> DESIGN_GENOME -> TOKENS -> SCREENS -> COMPONENTS -> STATES -> INTERACTIONS
    -> RESPONSIVE -> A11Y -> PERFORMANCE -> AI_TRUST -> IMPLEMENTATION
    -> (evaluate + bounded repair) -> UIUXDesignIR

Pure: no provider calls, no I/O, no clock. The same request always yields the
same IR and the same ``spec_hash``. The compiler produces a governed
*specification*; it does not generate, render, or ship an interface.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from .evaluator import evaluate_and_repair
from .models import (
    UIUX_SPEC_READY,
    A11yRequirement,
    A11yVerification,
    AccessibilitySpec,
    AITrustSpec,
    Assumption,
    CheckStatus,
    ComponentSpec,
    Confidence,
    DesignGenome,
    DesignSystemSpec,
    Flow,
    FlowStep,
    IAItem,
    ImplementationMapping,
    ImplementationStatus,
    InformationArchitecture,
    InteractionSpec,
    LayoutRegion,
    Metric,
    MetricTruth,
    PerformanceSpec,
    Platform,
    PrincipleApplication,
    Priority,
    ProductModel,
    ResponsiveRule,
    ResponsiveTransform,
    Screen,
    ScreenTrace,
    Severity,
    SourceKind,
    SourceRef,
    StateSpec,
    SurfaceMode,
    Territory,
    UIState,
    UIUXDesignIR,
    UIUXRequest,
    UIUXTerminal,
    Unknown,
    ValidationCheck,
)
from .principles import Effect, Principle, extract_features, select_principles
from .tokens import compile_token_system


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def stable_hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "item"


# --------------------------------------------------------------------------- #
# Surface inference
# --------------------------------------------------------------------------- #

_SURFACE_KEYWORDS: tuple[tuple[SurfaceMode, tuple[str, ...]], ...] = (
    (SurfaceMode.ai_interface, ("assistant", "chat", "copilot", "ai interface", "agent console", "conversational")),
    (SurfaceMode.dashboard, ("dashboard", "analytics", "kpi", "metrics", "reporting", "monitoring")),
    (SurfaceMode.form_flow, ("checkout", "signup", "sign up", "registration", "application form", "wizard", "onboarding flow", "booking")),
    (SurfaceMode.landing_page, ("landing", "homepage", "home page", "marketing site", "website", "launch page", "microsite")),
    (SurfaceMode.application, ("app", "application", "saas", "tool", "workspace", "portal", "platform", "admin")),
)


def infer_surface(request: UIUXRequest) -> tuple[SurfaceMode, Assumption | None]:
    if request.surface is not None:
        return request.surface, None
    # The surface hint (e.g. a brief's product type) is the more deliberate
    # statement, so it is consulted on its own before the free-text description:
    # "a booking app" is an app whose description happens to mention booking.
    for label, text in (
        ("surface hint", request.surface_hint),
        ("request wording", " ".join([request.purpose, request.primary_task])),
    ):
        lowered = text.lower()
        for mode, words in _SURFACE_KEYWORDS:
            if any(re.search(rf"\b{re.escape(word)}\b", lowered) for word in words):
                return mode, Assumption(
                    id="assume.surface",
                    statement=f"Surface treated as {mode.value}.",
                    reason=f"Inferred from the {label}; no explicit surface was given.",
                    impact="Selects the screen/flow template and principle set.",
                )
    return SurfaceMode.application, Assumption(
        id="assume.surface",
        statement="Surface treated as APPLICATION.",
        reason="No surface was given and the request wording did not identify one.",
        impact="Default application template; confirm before implementation.",
    )


# --------------------------------------------------------------------------- #
# Component library and surface templates
# --------------------------------------------------------------------------- #

_INTERACTIVE_BASE = (UIState.default, UIState.hover, UIState.focus_visible, UIState.disabled)


@dataclass(frozen=True)
class _ComponentTemplate:
    role: str
    purpose: str
    tags: frozenset[str]
    states: tuple[UIState, ...]
    a11y: tuple[str, ...] = ()


_COMPONENTS: dict[str, _ComponentTemplate] = {
    "SiteHeader": _ComponentTemplate("banner + nav landmark", "Brand identity and primary navigation.", frozenset({"nav"}), _INTERACTIVE_BASE + (UIState.current,), ("Skip link to main content precedes the header.",)),
    "HeroSection": _ComponentTemplate("region with the page h1", "State the offer and the single primary action.", frozenset({"content"}), (UIState.default,), ("Exactly one h1 per page.",)),
    "PrimaryCTA": _ComponentTemplate("button or link (by effect: navigation=a, action=button)", "The one primary action for the view.", frozenset({"action", "cta"}), _INTERACTIVE_BASE),
    "FeatureList": _ComponentTemplate("list", "Specific capabilities stated as user outcomes.", frozenset({"content"}), (UIState.default,)),
    "EvidenceBlock": _ComponentTemplate("figure / blockquote with cite", "Sourced proof only (quotes, logos, figures carry a source).", frozenset({"content", "evidence"}), (UIState.default, UIState.empty), ("Quotes carry a visible attribution.",)),
    "SiteFooter": _ComponentTemplate("contentinfo landmark", "Secondary links and legal.", frozenset({"nav"}), _INTERACTIVE_BASE),
    "AppShell": _ComponentTemplate("layout with banner/nav/main landmarks", "Stable frame for the primary task.", frozenset({"layout"}), (UIState.default,), ("One main landmark; landmarks are labeled.",)),
    "NavRail": _ComponentTemplate("nav landmark with aria-current", "Move between top-level areas.", frozenset({"nav", "action"}), _INTERACTIVE_BASE + (UIState.current,)),
    "TaskList": _ComponentTemplate("list or grid with row actions", "Scan and pick the item to work on.", frozenset({"data", "result", "action"}), _INTERACTIVE_BASE + (UIState.selected, UIState.loading)),
    "TaskDetail": _ComponentTemplate("region labeled by item title", "Inspect and act on one item.", frozenset({"data", "disclosure"}), (UIState.default, UIState.loading)),
    "EditForm": _ComponentTemplate("form with fieldset/legend groups", "Create or change an item.", frozenset({"field", "action", "form"}), _INTERACTIVE_BASE + (UIState.read_only,)),
    "StatusToast": _ComponentTemplate("status live region (polite)", "Confirm async outcomes without stealing focus.", frozenset({"status"}), (UIState.default, UIState.success, UIState.error)),
    "FilterBar": _ComponentTemplate("search landmark + form controls", "Narrow the data shown.", frozenset({"filter", "field", "action"}), _INTERACTIVE_BASE + (UIState.checked,)),
    "MetricTile": _ComponentTemplate("figure with figcaption", "One metric with its truth label (measured/estimated/not measured).", frozenset({"data", "metric"}), (UIState.default, UIState.loading)),
    "ChartPanel": _ComponentTemplate("figure with an equivalent data table", "Show a trend; the table is the accessible equivalent.", frozenset({"data"}), (UIState.default, UIState.loading)),
    "DataTable": _ComponentTemplate("table with caption and scoped headers", "Exact values for comparison.", frozenset({"data", "result"}), (UIState.default, UIState.loading, UIState.selected)),
    "ActivityFeed": _ComponentTemplate("feed / log", "Recent events with timestamps.", frozenset({"data", "status"}), (UIState.default, UIState.loading)),
    "MessageList": _ComponentTemplate("log live region", "Conversation history; new messages announced once complete.", frozenset({"ai", "data"}), (UIState.default, UIState.loading)),
    "Composer": _ComponentTemplate("form with labeled textarea", "Write the prompt/request.", frozenset({"field", "action"}), _INTERACTIVE_BASE),
    "AITrustEnvelope": _ComponentTemplate("group labeled 'AI provenance'", "One truthful provenance scope per AI response.", frozenset({"ai", "status"}), (UIState.default,)),
    "SourcePanel": _ComponentTemplate("complementary landmark", "Sources and context behind an AI answer, when available.", frozenset({"ai", "disclosure"}), (UIState.default, UIState.empty)),
    "ProgressStepper": _ComponentTemplate("ordered list with aria-current=step", "Where the user is in a multi-step flow.", frozenset({"progress", "status", "nav"}), (UIState.default, UIState.current)),
    "ReviewSummary": _ComponentTemplate("region with description list", "Check everything before committing.", frozenset({"data"}), (UIState.default,)),
    "ConfirmationPanel": _ComponentTemplate("status region", "Outcome of the flow with next step.", frozenset({"status"}), (UIState.default, UIState.success, UIState.error)),
}


def _region(id_, purpose, layout, axis, spacing, priority, emphasis, overflow, transform, minimum="16rem", maximum="80rem") -> LayoutRegion:
    return LayoutRegion(
        id=id_, purpose=purpose, parent_layout=layout, axis=axis, spacing_token=spacing,
        priority=priority, emphasis=emphasis, overflow=overflow, min_inline=minimum,
        max_inline=maximum, responsive_transform=transform,
    )


P0, P1, P2, P3 = Priority.p0, Priority.p1, Priority.p2, Priority.p3
T = ResponsiveTransform
SP, ST, PN, SE = "semantic.space.inline", "semantic.space.stack", "semantic.space.panel", "semantic.space.section"


def _template(mode: SurfaceMode) -> dict[str, Any]:
    if mode is SurfaceMode.landing_page:
        return {
            "nav": [("overview", "Overview", "What it is", P0), ("how-it-works", "How it works", "Mechanism", P1), ("pricing", "Pricing", "Cost clarity", P1)],
            "screens": [("landing", "Landing page", "Convert a qualified visitor", P0, [
                _region("header-nav", "Identity and navigation", "CLUSTER", "INLINE", SP, P1, 1, "WRAP", T.menu),
                _region("hero", "Offer + primary action", "STACK", "BLOCK", SE, P0, 3, "WRAP", T.stack),
                _region("features", "Specific outcomes", "GRID", "INLINE", PN, P1, 2, "WRAP", T.stack),
                _region("evidence", "Sourced proof", "STACK", "BLOCK", PN, P2, 2, "WRAP", T.stack),
                _region("final-cta", "Repeat the primary action", "STACK", "BLOCK", PN, P1, 2, "WRAP", T.full_width),
                _region("footer", "Secondary links", "CLUSTER", "INLINE", SP, P3, 1, "WRAP", T.stack),
            ], ["SiteHeader", "HeroSection", "PrimaryCTA", "FeatureList", "EvidenceBlock", "SiteFooter"])],
            "flows": [("convert", "Understand and act", "Visitor takes the primary action", [
                ("landing", "Reads the headline", "States the offer in one sentence", "Unclear offer -> visitor leaves; test headline comprehension"),
                ("landing", "Activates the primary CTA", "Navigates to the next step or confirms", "Target unavailable -> explain and offer an alternative contact path"),
            ], "Primary CTA activation")],
        }
    if mode is SurfaceMode.dashboard:
        return {
            "nav": [("overview", "Overview", "Current state at a glance", P0), ("reports", "Reports", "Detail and export", P1), ("settings", "Settings", "Configuration", P2)],
            "screens": [("overview", "Overview dashboard", "Decide what needs attention", P0, [
                _region("filters", "Scope the data", "CLUSTER", "INLINE", SP, P1, 1, "WRAP", T.wrap),
                _region("metrics", "Key metrics with truth labels", "GRID", "INLINE", ST, P0, 3, "WRAP", T.stack),
                _region("trend", "Trend with table equivalent", "STACK", "BLOCK", PN, P1, 2, "SCROLL", T.stack),
                _region("table", "Exact values", "STACK", "BLOCK", PN, P1, 2, "SCROLL", T.scroll),
                _region("activity", "Recent events", "STACK", "BLOCK", ST, P2, 1, "TRUNCATE_WITH_DISCLOSURE", T.collapse),
            ], ["FilterBar", "MetricTile", "ChartPanel", "DataTable", "ActivityFeed"])],
            "flows": [("triage", "Find what needs attention", "Operator identifies and opens the item that needs action", [
                ("overview", "Scans metrics", "Shows each metric with its truth label and freshness", "Data unavailable -> UNAVAILABLE state with reason, never a zero"),
                ("overview", "Applies a filter", "Updates metrics/table and announces the result count", "No results -> EMPTY state with clear-filters action"),
            ], "Operator reaches the item needing action")],
        }
    if mode is SurfaceMode.ai_interface:
        return {
            "nav": [("conversation", "Conversation", "Work with the assistant", P0), ("history", "History", "Earlier sessions", P3)],
            "screens": [("assistant", "Assistant", "Get a trustworthy answer or draft", P0, [
                _region("conversation", "Messages with provenance", "STACK", "BLOCK", ST, P0, 3, "GROW", T.full_width),
                _region("composer", "Write the request", "STACK", "BLOCK", SP, P0, 2, "WRAP", T.full_width),
                _region("sources", "Sources and context", "STACK", "BLOCK", ST, P2, 1, "SCROLL", T.drawer),
                _region("history", "Past sessions", "STACK", "BLOCK", ST, P3, 1, "SCROLL", T.priority_reduction),
            ], ["MessageList", "AITrustEnvelope", "Composer", "SourcePanel"])],
            "flows": [("ask", "Ask and verify", "User gets an answer and can see where it came from", [
                ("assistant", "Submits a request", "Streams the response inside a provenance envelope", "Provider unavailable -> UNAVAILABLE state; input preserved; retry offered"),
                ("assistant", "Checks provenance", "Shows AI involvement, provider/model if known, sources if available", "No sources -> states 'Sources unavailable' explicitly"),
            ], "Answer reviewed with provenance visible")],
        }
    if mode is SurfaceMode.form_flow:
        return {
            "nav": [("details", "Details", "Enter information", P0), ("review", "Review", "Check before committing", P0), ("done", "Confirmation", "Outcome", P1)],
            "screens": [
                ("details", "Details step", "Enter required information", P0, [
                    _region("progress", "Step position", "CLUSTER", "INLINE", SP, P1, 1, "WRAP", T.collapse),
                    _region("form", "Grouped fields", "STACK", "BLOCK", ST, P0, 3, "WRAP", T.stack),
                    _region("actions", "Back / continue", "CLUSTER", "INLINE", SP, P0, 2, "WRAP", T.full_width),
                ], ["ProgressStepper", "EditForm", "PrimaryCTA"]),
                ("review", "Review step", "Confirm entered information", P0, [
                    _region("summary", "Everything entered", "STACK", "BLOCK", ST, P0, 3, "WRAP", T.stack),
                    _region("actions", "Edit / submit", "CLUSTER", "INLINE", SP, P0, 2, "WRAP", T.full_width),
                ], ["ReviewSummary", "PrimaryCTA"]),
                ("done", "Confirmation", "Know the outcome and next step", P1, [
                    _region("outcome", "Result + next step", "STACK", "BLOCK", PN, P0, 3, "WRAP", T.stack),
                ], ["ConfirmationPanel"]),
            ],
            "flows": [("complete", "Complete the flow", "User submits correct information once", [
                ("details", "Fills grouped fields", "Validates on blur/submit, keeps input on error", "Invalid -> field-level error with recovery text; focus moves to first error"),
                ("review", "Reviews and submits", "Submits once (idempotent) and shows progress", "Network failure -> OFFLINE state; submission retried safely"),
                ("done", "Reads the outcome", "Shows the result and the next step", "Server rejection -> ERROR with reason and support path"),
            ], "Successful single submission")],
        }
    return {
        "nav": [("work", "Work", "The primary task", P0), ("detail", "Detail", "One item", P1), ("settings", "Settings", "Configuration", P2)],
        "screens": [("workspace", "Workspace", "Complete the primary task", P0, [
            _region("nav", "Top-level navigation", "SIDEBAR", "BLOCK", SP, P1, 1, "SCROLL", T.drawer),
            _region("main", "Primary task list", "STACK", "BLOCK", ST, P0, 3, "SCROLL", T.full_width),
            _region("detail", "Selected item", "STACK", "BLOCK", PN, P2, 2, "SCROLL", T.collapse),
        ], ["AppShell", "NavRail", "TaskList", "TaskDetail", "EditForm", "StatusToast"])],
        "flows": [("do-work", "Complete the task", "User finds an item and updates it", [
            ("workspace", "Selects an item", "Shows its detail without losing list position", "Item deleted elsewhere -> STALE notice with refresh"),
            ("workspace", "Edits and saves", "Validates, saves, confirms via status toast", "Save fails -> ERROR with retry; edits preserved"),
        ], "Item updated and confirmed")],
    }


# --------------------------------------------------------------------------- #
# State semantics (one row per UIState)
# --------------------------------------------------------------------------- #

_STATE_TABLE: dict[UIState, tuple[str, str, str, str, str, str, str, str, str, str | None]] = {
    # trigger, visual, content, semantics, keyboard, announcement, motion, recovery, persistence, non-color channel
    UIState.default: ("initial render", "base tokens", "base content", "native role", "reachable in tab order if interactive", "none", "none", "n/a", "none", None),
    UIState.hover: ("pointer over target", "surface-raised background", "none", "none", "n/a (pointer only; never the sole affordance)", "none", "feedback duration", "n/a", "none", None),
    UIState.focus_visible: ("keyboard focus", "2px focus-ring outline, offset, never removed", "none", "focused element", "Tab / Shift+Tab", "accessible name announced", "none", "n/a", "none", "outline shape"),
    UIState.pressed: ("activation start", "inset/darker surface", "none", "aria-pressed only for toggles", "Enter / Space", "none", "feedback duration", "n/a", "none", None),
    UIState.selected: ("item chosen", "accent border + check icon", "selected label", "aria-selected=true", "Space toggles; arrows move", "'selected'", "none", "deselect", "session", "check icon"),
    UIState.checked: ("option enabled", "filled control + check mark", "none", "checked=true", "Space", "'checked'", "none", "uncheck", "form state", "check mark"),
    UIState.current: ("location in set", "accent indicator bar + bold label", "none", "aria-current", "n/a", "'current'", "none", "n/a", "route", "indicator bar + weight"),
    UIState.expanded: ("disclosure opened", "chevron rotated, panel shown", "revealed content", "aria-expanded=true", "Enter / Space toggles", "'expanded'", "reduced-motion safe reveal", "collapse", "session", "chevron direction"),
    UIState.disabled: ("action unavailable", "reduced-contrast control (still >=3:1 border)", "reason text nearby", "disabled or aria-disabled with reason", "skipped or focusable with reason", "reason on focus", "none", "state what enables it", "none", "reason text"),
    UIState.read_only: ("no edit permission", "no input chrome, plain text", "'Read only' label", "readonly", "focusable, not editable", "'read only'", "none", "request access path", "none", "'Read only' label"),
    UIState.loading: ("async request in flight", "indeterminate indicator; layout reserved", "'Loading…' text", "aria-busy=true", "focus retained", "polite 'Loading'", "reduced-motion safe spinner", "timeout -> ERROR", "none", "'Loading…' text"),
    UIState.streaming: ("response arriving incrementally", "caret/progress indicator on the growing block", "partial content, marked incomplete", "aria-busy until complete", "stop control focusable", "announce once on completion", "no per-token motion", "stop / retry", "none", "'Generating…' text"),
    UIState.skeleton: ("first load of structured data", "neutral placeholder shapes mirroring layout", "none (aria-hidden)", "aria-hidden placeholders + live status", "no focusable placeholders", "polite 'Loading'", "static under reduced motion", "timeout -> ERROR", "none", "status text"),
    UIState.empty: ("no data for the current scope", "explanatory illustration-free panel", "why it is empty + first action", "status region", "first action focusable", "result count '0' announced", "none", "primary action / clear filters", "none", "explanatory text"),
    UIState.valid: ("field passes validation", "subtle success border + icon", "optional confirmation text", "aria-invalid=false", "n/a", "none", "none", "n/a", "form state", "success icon"),
    UIState.invalid: ("field fails validation on blur/submit", "danger border + error icon", "error message: cause + fix", "aria-invalid=true + aria-describedby", "focus moves to first invalid field on submit", "error text announced", "none", "correct the value", "form state", "error icon + message text"),
    UIState.warning: ("risky but allowed value", "warning border + icon", "warning text", "aria-describedby warning", "n/a", "polite warning", "none", "confirm or change", "form state", "warning icon + text"),
    UIState.error: ("operation failed", "danger surface + error icon", "what failed, why, what to do", "role=alert for blocking errors", "retry control focusable", "assertive for blocking, polite otherwise", "none", "retry / alternative path", "until dismissed or resolved", "error icon + text"),
    UIState.success: ("operation succeeded", "success icon + message", "what changed", "status region", "focus not stolen", "polite confirmation", "reduced-motion safe", "undo where supported", "transient (toast) or inline", "success icon + text"),
    UIState.pending: ("awaiting backend confirmation", "clock icon + muted label", "'Pending' label", "status text", "n/a", "polite 'Pending'", "none", "cancel if supported", "until resolved", "clock icon + label"),
    UIState.pending_approval: ("awaiting human approval", "hourglass icon + 'Awaiting approval' badge", "who approves, since when", "status text", "n/a", "polite", "none", "view approval request", "until decision", "icon + text badge"),
    UIState.approved: ("approval granted", "check-seal icon + 'Approved' badge", "approver + time", "status text", "n/a", "polite", "none", "n/a", "durable", "icon + text badge"),
    UIState.rejected: ("approval denied", "cross icon + 'Rejected' badge", "reason + next step", "status text", "n/a", "polite", "none", "revise and resubmit", "durable", "icon + text badge"),
    UIState.degraded: ("fallback path used", "warning icon + 'Degraded' label", "what is reduced and why", "status text", "n/a", "polite", "none", "retry with full capability", "until recovered", "icon + text label"),
    UIState.stale: ("data older than freshness budget", "clock icon + age label", "'Updated N min ago'", "status text", "refresh focusable", "polite on transition", "none", "refresh", "until refreshed", "age label"),
    UIState.drag: ("item being dragged", "lifted surface + drag handle", "none", "aria-grabbed legacy avoided; live instructions", "keyboard move alternative required", "instructions announced", "reduced-motion safe", "Escape cancels", "none", "handle icon + instruction text"),
    UIState.drop_target: ("valid drop zone under drag", "dashed accent outline", "'Drop here' text", "live instruction", "keyboard move alternative", "polite", "none", "Escape cancels", "none", "dashed outline + text"),
    UIState.offline: ("network lost", "offline icon + banner", "what still works, what is queued", "status region", "retry focusable", "polite", "none", "auto-reconnect + manual retry", "until online", "icon + banner text"),
    UIState.unavailable: ("capability/provider not available", "unavailable icon + reason", "reason + alternative", "status text", "alternative focusable", "polite", "none", "alternative path", "until available", "icon + reason text"),
}


def _state_spec(component: str, state: UIState) -> StateSpec:
    row = _STATE_TABLE[state]
    return StateSpec(
        component_ref=component, state=state, trigger=row[0], visual_delta=row[1],
        content_delta=row[2], semantics=row[3], keyboard=row[4], announcement=row[5],
        motion=row[6], recovery=row[7], persistence=row[8], non_color_channel=row[9],
    )


# --------------------------------------------------------------------------- #
# Territories and genome
# --------------------------------------------------------------------------- #

_TERRITORIES = (
    ("quiet-precision", "Quiet Precision", "Restrained neutrals, exact alignment, one accent reserved for the primary action.",
     {"precise", "calm", "technical", "premium", "trustworthy", "minimal", "clear"}, {SurfaceMode.application, SurfaceMode.dashboard, SurfaceMode.ai_interface}),
    ("editorial-warmth", "Editorial Warmth", "Content-led pages with generous type scale and sourced imagery doing the persuading.",
     {"warm", "friendly", "human", "playful", "inviting", "approachable", "bold"}, {SurfaceMode.landing_page}),
    ("operational-clarity", "Operational Clarity", "Dense, scannable, status-first layouts for people who work in the tool all day.",
     {"efficient", "direct", "practical", "operational", "fast", "reliable"}, {SurfaceMode.dashboard, SurfaceMode.application, SurfaceMode.form_flow}),
)


def _territories(mode: SurfaceMode, tones: list[str], features: frozenset[str]) -> list[Territory]:
    tone_tokens = {word for tone in tones for word in re.findall(r"[a-z]+", tone.lower())}
    scored = []
    for id_, name, thesis, affinities, modes in _TERRITORIES:
        score = 0.5 * (mode in modes) + 0.1 * min(len(tone_tokens & affinities), 3)
        if id_ == "operational-clarity" and "high_density" in features:
            score += 0.2
        scored.append((round(min(score, 1.0), 3), id_, name, thesis, affinities))
    scored.sort(key=lambda item: (-item[0], item[1]))
    best = scored[0][1]
    result = []
    for score, id_, name, thesis, affinities in scored:
        matched = sorted(tone_tokens & affinities)
        rationale = f"surface fit={'yes' if score >= 0.5 else 'no'}; tone matches={matched or 'none'}"
        result.append(Territory(
            id=id_, name=name, thesis=thesis, score=score, fit_rationale=rationale,
            selected=id_ == best,
            rejection_reason=None if id_ == best else f"lower fit ({score:.2f}) than the selected territory",
        ))
    return result


def _genome(mode: SurfaceMode, territory: Territory, brand_typography: str | None, features: frozenset[str],
            brand_name: str) -> DesignGenome:
    density = "HIGH" if "high_density" in features else ("LOW" if mode is SurfaceMode.landing_page else "MEDIUM")
    base = {
        "quiet-precision": ("strict typographic hierarchy; one focal element per view", "4px-based radius, hairline borders, no shadows as decoration", "neutral surfaces; accent reserved for the P0 action", "flat surfaces separated by borders and space", "short, purposeful state transitions only"),
        "editorial-warmth": ("large display type leading a single narrative column", "generous radius on media, square text blocks", "brand color used in imagery and the primary action, neutral text", "content and real imagery as the material", "gentle entrance of content, never looping decoration"),
        "operational-clarity": ("status first, then values, then context", "tight grid, tabular alignment, small radius", "neutral data surfaces; status colors always paired with icon + text", "bordered panels on a single surface level", "instant feedback, no ornamental motion"),
    }[territory.id]
    return DesignGenome(
        hierarchy=base[0],
        density=density,
        geometry=base[1],
        typography=brand_typography or "system sans for UI, monospace for data; scale by role not by page",
        color=base[2],
        material=base[3],
        motion=base[4],
        interaction="native controls, explicit states, keyboard-complete",
        signature=f"one product-specific element derived from {brand_name}'s thesis (not generic decoration)",
    )


# --------------------------------------------------------------------------- #
# Draft and principle application
# --------------------------------------------------------------------------- #


@dataclass
class Draft:
    mode: SurfaceMode
    features: frozenset[str]
    screens: list[dict[str, Any]]
    components: dict[str, dict[str, Any]]  # name -> {template, states(list), status}
    interactions: list[InteractionSpec]
    genome: DesignGenome
    design_system: dict[str, list[str]]
    a11y: list[A11yRequirement]
    performance_requirements: list[str]
    assumptions: list[Assumption] = field(default_factory=list)
    approval_required: list[str] = field(default_factory=list)


def _components_with_tag(draft: Draft, tag: str) -> list[str]:
    return [name for name, spec in draft.components.items() if tag in spec["template"].tags]


def _add_unique(items: list[str], value: str) -> bool:
    if value in items:
        return False
    items.append(value)
    return True


def _a11y_verification(criterion: str) -> A11yVerification:
    if "1.4.3" in criterion or "1.4.11" in criterion:
        return A11yVerification.verified_static
    if "4.1.2" in criterion or "1.3.1" in criterion or "3.3.1" in criterion:
        return A11yVerification.requires_assistive_tech
    return A11yVerification.requires_human_evaluation


def _apply_effect(draft: Draft, effect: Effect) -> list[str]:
    changes: list[str] = []
    ds = draft.design_system
    if effect.kind in {"pattern", "state_rule", "content_rule", "motion_rule"}:
        key = {"pattern": "patterns", "state_rule": "state_rules", "content_rule": "content_rules", "motion_rule": "motion_rules"}[effect.kind]
        if _add_unique(ds[key], effect.value):
            changes.append(f"design_system.{key}")
    elif effect.kind == "a11y":
        if not any(item.criterion == effect.target for item in draft.a11y):
            draft.a11y.append(A11yRequirement(
                id=f"a11y.{_slug(effect.target)}", criterion=effect.target, rule=effect.value,
                verification=_a11y_verification(effect.target),
            ))
            changes.append("accessibility.requirements")
    elif effect.kind == "component_state":
        tag = effect.target.lstrip("*")
        for name in _components_with_tag(draft, tag):
            states = draft.components[name]["states"]
            if effect.state not in states:
                states.append(effect.state)
                changes.append(f"components.{name}.states")
    elif effect.kind == "responsive":
        transform = ResponsiveTransform(effect.value)
        for screen in draft.screens:
            for index, region in enumerate(screen["regions"]):
                if effect.target in region.id and region.responsive_transform is not transform:
                    screen["regions"][index] = region.model_copy(update={"responsive_transform": transform})
                    changes.append(f"screens.{screen['id']}.regions.{region.id}.responsive_transform")
    elif effect.kind == "perf":
        if _add_unique(draft.performance_requirements, effect.value):
            changes.append("performance.requirements")
    elif effect.kind == "genome":
        if getattr(draft.genome, effect.target) != effect.value:
            draft.genome = draft.genome.model_copy(update={effect.target: effect.value})
            changes.append(f"design_genome.{effect.target}")
    elif effect.kind == "interaction_input":
        for index, interaction in enumerate(draft.interactions):
            if effect.value not in interaction.input_modes:
                draft.interactions[index] = interaction.model_copy(
                    update={"input_modes": [*interaction.input_modes, effect.value]}
                )
                changes.append(f"interactions.{interaction.id}.input_modes")
    else:  # pragma: no cover - catalog is closed
        raise ValueError(f"unknown principle effect kind {effect.kind!r}")
    return changes


def _apply_principles(draft: Draft, principles: list[Principle]) -> list[PrincipleApplication]:
    applied: list[PrincipleApplication] = []
    for principle in principles:
        changes: list[str] = []
        for effect in principle.effects:
            changes.extend(_apply_effect(draft, effect))
        if not changes:
            continue  # relevant but changed nothing -> not applied
        matched = sorted(principle.triggers & draft.features)
        applied.append(PrincipleApplication(
            id=principle.id, name=principle.name, family=principle.family,
            user_problem=principle.user_problem, relevance=f"triggered by {matched}",
            application=principle.application, tradeoff=principle.tradeoff,
            a11y_effect=principle.a11y_effect, responsive_effect=principle.responsive_effect,
            implementation_effect=principle.implementation_effect,
            changes=list(dict.fromkeys(changes)),
        ))
    return applied


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

_GENERIC_COPY = ("unlock", "supercharge", "seamless", "revolutionize", "revolutionise", "next-gen",
                 "game-changing", "game changer", "10x", "cutting-edge", "world-class", "synergy")


def compile_uiux(request: UIUXRequest) -> UIUXDesignIR:
    assumptions: list[Assumption] = []
    unknowns: list[Unknown] = []
    sources: list[SourceRef] = [SourceRef(kind=SourceKind.request, ref=request.project_ref, detail="UIUXRequest")]
    sources.extend(request.sources)

    mode, surface_assumption = infer_surface(request)
    if surface_assumption:
        assumptions.append(surface_assumption)
    platform = request.platform or Platform.web_responsive
    if request.platform is None:
        assumptions.append(Assumption(
            id="assume.platform", statement="Platform treated as responsive web.",
            reason="No platform was given.", impact="Responsive rules cover 320px through desktop.",
        ))

    def need(value: str, key: str, question: str, default: str) -> str:
        if value.strip():
            return value.strip()
        unknowns.append(Unknown(id=f"unknown.{key}", question=question, blocks=False))
        assumptions.append(Assumption(
            id=f"assume.{key}", statement=f"{key.replace('_', ' ')}: {default}",
            reason="Not provided in the request.", impact="Treated as provisional until confirmed.",
        ))
        return default

    brand = request.brand
    brand_name = brand.brand_name if brand else request.project_ref
    purpose = need(request.purpose, "purpose", "What is this interface for?", f"Help {brand_name}'s users complete their primary task")
    primary_user = need(request.primary_user, "primary_user", "Who is the primary user?", "The product's primary audience (unspecified)")
    primary_task = need(request.primary_task, "primary_task", "What single task must the interface make easy?", purpose)
    business_goal = need(request.business_goal, "business_goal", "What business outcome does this serve?", "Unstated; do not invent metrics for it")

    text = " ".join([request.surface_hint, purpose, primary_task, business_goal, *request.content_requirements, *request.constraints])
    features = extract_features(mode, text, ai_features=request.ai_features, rtl=request.locale_rtl)
    has_ai = "ai" in features
    has_data = "data" in features

    template = _template(mode)
    if has_ai and mode is not SurfaceMode.ai_interface:
        # Any AI output anywhere needs exactly one truthful provenance scope.
        for screen in template["screens"]:
            if screen[3] is P0 and "AITrustEnvelope" not in screen[5]:
                screen[5].append("AITrustEnvelope")
                break

    component_names: list[str] = []
    for screen in template["screens"]:
        for name in screen[5]:
            if name not in component_names:
                component_names.append(name)
    existing = {item.strip().lower() for item in request.existing_components}
    components = {
        name: {
            "template": _COMPONENTS[name],
            "states": list(_COMPONENTS[name].states),
            "status": ImplementationStatus.extend if name.lower() in existing else ImplementationStatus.proposed,
        }
        for name in component_names
    }

    interactions: list[InteractionSpec] = []
    for name in component_names:
        tags = _COMPONENTS[name].tags
        if tags & {"action", "field", "nav", "filter"}:
            interactions.append(InteractionSpec(
                id=f"ix.{_slug(name)}.activate", component_ref=name,
                trigger="activate" if "field" not in tags else "enter value",
                input_modes=["POINTER", "TOUCH", "SCREEN_READER"],
                feedback="PRESSED within one frame; outcome via state change and status text",
                standard=True,
            ))
    if re.search(r"\b(drag|reorder|kanban)\b", text.lower()):
        target = next((n for n in component_names if "data" in _COMPONENTS[n].tags), component_names[0])
        interactions.append(InteractionSpec(
            id=f"ix.{_slug(target)}.reorder", component_ref=target, trigger="drag to reorder",
            input_modes=["POINTER", "TOUCH"], feedback="lifted item + drop target outline",
            standard=False,
            justification="Requested reordering of items by direct manipulation." if "reorder" in text.lower() else None,
            fallback=None,
        ))

    draft = Draft(
        mode=mode, features=features,
        screens=[{"id": s[0], "name": s[1], "purpose": s[2], "priority": s[3], "regions": list(s[4]), "components": list(s[5])} for s in template["screens"]],
        components=components,
        interactions=interactions,
        genome=DesignGenome(hierarchy="", density="MEDIUM", geometry="", typography="", color="", material="", motion="", interaction="", signature=""),
        design_system={key: [] for key in ("patterns", "state_rules", "content_rules", "motion_rules")},
        a11y=[
            A11yRequirement(id="a11y.contrast", criterion="WCAG 2.2 SC 1.4.3 Contrast (Minimum)", rule="Text meets 4.5:1 (AA); body text targets 7:1 (AAA) where tokens allow.", verification=A11yVerification.verified_static),
            A11yRequirement(id="a11y.non-text-contrast", criterion="WCAG 2.2 SC 1.4.11 Non-text Contrast", rule="Focus indicators, control borders and meaningful graphics reach 3:1.", verification=A11yVerification.verified_static),
            A11yRequirement(id="a11y.name-role-value", criterion="WCAG 2.2 SC 4.1.2 Name, Role, Value", rule="Every control exposes an accessible name, role, and state.", verification=A11yVerification.requires_assistive_tech),
            A11yRequirement(id="a11y.use-of-color", criterion="WCAG 2.2 SC 1.4.1 Use of Color", rule="Status and state are never conveyed by color alone.", verification=A11yVerification.requires_human_evaluation),
            A11yRequirement(id="a11y.forced-colors", criterion="Forced colors (Windows High Contrast)", rule="Under forced-colors: active, states keep icon + text channels and borders use system colors.", verification=A11yVerification.requires_human_evaluation),
            A11yRequirement(id="a11y.resize", criterion="WCAG 2.2 SC 1.4.4 Resize Text", rule="Text resizes to 200% without loss of content or function.", verification=A11yVerification.requires_human_evaluation),
        ],
        performance_requirements=[
            "Prefer semantic HTML and CSS over client JavaScript for layout and state styling.",
            "Keep client components at the interaction boundary; render static content on the server.",
            "Subscribe to the smallest stable store slice a component needs.",
        ],
        assumptions=assumptions,
    )

    tones = list(brand.tone_attributes) if brand else []
    territories = _territories(mode, tones, features)
    selected = next(item for item in territories if item.selected)
    draft.genome = _genome(mode, selected, brand.typography_direction if brand else None, features, brand_name)

    principles = select_principles(features)
    applied = _apply_principles(draft, principles)
    draft.genome = draft.genome.model_copy(update={"genome_hash": stable_hash(draft.genome.model_dump(exclude={"genome_hash"}))})

    token_system = compile_token_system(brand, draft.genome, include_ai=has_ai, include_data=has_data)
    if not (brand and brand.palette_hex):
        assumptions.append(Assumption(
            id="assume.palette", statement="Brand palette unresolved; structural tokens use neutral placeholders.",
            reason="No palette reference was supplied.",
            impact="design_token_set must compile the brand color story before visual sign-off.",
        ))
        draft.approval_required.append("DECISION: brand palette must be compiled by the design_token_set role before visual sign-off.")

    lowered = f"{purpose} {business_goal}".lower()
    generic_phrases = sorted(word for word in _GENERIC_COPY if word in lowered)
    for item in request.content_requirements:
        if re.search(r"\b(testimonial|review|logo|customer count|case stud|award|rating)", item.lower()):
            _add_unique(draft.design_system["content_rules"],
                        f"'{item}' renders only sourced items with visible attribution; no placeholder or invented proof.")

    ir_state = evaluate_and_repair(
        draft=draft,
        token_system=token_system,
        request_text={
            "content": list(request.content_requirements),
            "constraints": list(request.constraints) + list(request.negative_constraints),
            "generic_copy": generic_phrases,
        },
        has_ai=has_ai,
    )

    screens = []
    for screen in draft.screens:
        p0_components = ", ".join(screen["components"][:3])
        screens.append(Screen(
            id=screen["id"], name=screen["name"], purpose=screen["purpose"],
            user_task=primary_task, priority=screen["priority"], regions=screen["regions"],
            components=screen["components"],
            trace=ScreenTrace(
                user_task=primary_task,
                content=f"{screen['purpose']}; content requirements: {', '.join(request.content_requirements) or 'none stated'}",
                contract=f"async state contract for {p0_components}",
                component=p0_components,
                token=screen["regions"][0].spacing_token,
                state=", ".join(sorted({s.value for name in screen["components"] for s in draft.components[name]["states"]})),
                interaction=", ".join(i.id for i in draft.interactions if i.component_ref in screen["components"]) or "read-only screen",
                responsive_rule=", ".join(f"{r.id}:{r.responsive_transform.value}" for r in screen["regions"]),
                a11y_rule=", ".join(sorted({req.id for req in draft.a11y})[:4]),
                performance_rule=draft.performance_requirements[0],
                implementation_path=f"screens/{screen['id']} -> components/{{{p0_components}}}",
                test=f"e2e: {screen['id']} primary task, keyboard-only, 320px reflow",
                evidence=f"spec-level (compiler {selected.id}); implementation evidence pending",
            ),
        ))

    component_specs = [
        ComponentSpec(
            id=f"cmp.{_slug(name)}", name=name, semantic_role=spec["template"].role,
            purpose=spec["template"].purpose,
            tokens=_component_tokens(spec["template"].tags),
            states=spec["states"],
            interactions=[i.id for i in draft.interactions if i.component_ref == name],
            a11y=list(spec["template"].a11y),
            implementation=spec["status"],
        )
        for name, spec in draft.components.items()
    ]
    states = [_state_spec(name, state) for name, spec in draft.components.items() for state in spec["states"]]
    responsive = [
        ResponsiveRule(
            region_ref=f"{screen['id']}.{region.id}", condition="container inline-size < 40rem",
            transform=region.responsive_transform,
            rationale=f"{region.priority.value} region; {region.purpose.lower()}",
        )
        for screen in draft.screens for region in screen["regions"]
    ]

    ai_trust = AITrustSpec(
        required=has_ai,
        provenance_rules=[
            "Label every AI output 'AI-generated' or 'AI-assisted' inside a single AITrustEnvelope scope.",
            "Show provider/model only when the backend reports them; otherwise 'Not disclosed'."
            if not request.ai_provider_known else "Show the provider/model reported by the backend for this response.",
            "Degraded or fallback output is labeled as such, never presented as model output.",
        ] if has_ai else [],
        attribution_rules=["Show sources when the backend returns them; otherwise state 'Sources unavailable'."] if has_ai else [],
        uncertainty_rules=["No numeric confidence unless a calibrated backend value exists; display 'Confidence not measured'."] if has_ai else [],
        feedback_rules=["Offer feedback/retry only when a backend endpoint records it."] if has_ai else [],
    )

    budgets = [
        Metric(name="Largest Contentful Paint", target="<= 2.5 s (p75)", truth=MetricTruth.not_measured,
               source="Core Web Vitals target", formula="p75 field LCP", freshness="no measurement exists",
               uncertainty="unmeasured", fallback="measure with RUM in staging before any claim"),
        Metric(name="Interaction to Next Paint", target="<= 200 ms (p75)", truth=MetricTruth.not_measured,
               source="Core Web Vitals target", formula="p75 field INP", freshness="no measurement exists",
               uncertainty="unmeasured", fallback="measure with RUM in staging before any claim"),
        Metric(name="Cumulative Layout Shift", target="<= 0.1 (p75)", truth=MetricTruth.not_measured,
               source="Core Web Vitals target", formula="p75 field CLS", freshness="no measurement exists",
               uncertainty="unmeasured", fallback="reserve space for async content (skeleton states)"),
    ]
    risks = []
    if "realtime" in features:
        risks.append("Streaming/live updates can re-render on every chunk; batch updates per animation frame.")
    if has_data:
        risks.append("Large tables need virtualization or pagination beyond a few hundred rows.")
    if has_ai:
        risks.append("Token-by-token rendering must not re-render the whole conversation.")

    mapping = ImplementationMapping(
        verified_existing=[],  # the pure compiler cannot verify a repository; see docs
        extend=[name for name, spec in draft.components.items() if spec["status"] is ImplementationStatus.extend],
        proposed=[name for name, spec in draft.components.items() if spec["status"] is ImplementationStatus.proposed],
        contracts=[
            "Async action contract: {status: idle|pending|success|error, error?: {message, recovery}}",
            *(["AI response contract: {mode, provider?, model?, sources?[], review_status}"] if has_ai else []),
            *(["Metric contract: {value, truth, source, formula, timestamp?, freshness}"] if has_data else []),
        ],
        state_dependencies=[f"{name}: {', '.join(s.value for s in spec['states'])}" for name, spec in draft.components.items()],
        events=[f"proposed analytics event: ui.{screen['id']}.primary_task" for screen in draft.screens],
        tests=[
            "unit: each component renders every declared state with its non-color channel",
            "e2e: primary flow keyboard-only",
            "e2e: 320px reflow and 200% text zoom",
            "a11y: automated axe scan (partial coverage only)",
            "a11y: screen reader walkthrough (NVDA + VoiceOver) — requires assistive tech",
            "visual: forced-colors and prefers-reduced-motion snapshots",
        ],
    )

    accessibility = AccessibilitySpec(
        requirements=sorted(draft.a11y, key=lambda item: item.id),
        predicted=["Keyboard-complete flows if native elements are used as specified.",
                   "Reflow at 320px given the declared region transforms."],
        verified=[f"{c.foreground} on {c.background}: {c.wcag_ratio}:1 meets {c.wcag_requirement.value} (static token check)"
                  for c in token_system.contrast if c.passes],
        risks=[f"{c.foreground} on {c.background}: {c.wcag_ratio}:1 fails {c.wcag_requirement.value}"
               for c in token_system.contrast if not c.passes],
        tests_required=[test for test in mapping.tests if test.startswith(("a11y", "e2e", "visual"))],
    )

    design_system = DesignSystemSpec(
        foundations=[f"Tokens: DTCG 2025.10, {token_system.token_count} tokens in T1/T2/T3 tiers (prefix --{token_system.css_prefix}-)",
                     f"Genome: {draft.genome.genome_hash[:12]}", f"Territory: {selected.name}"],
        patterns=draft.design_system["patterns"],
        templates=[screen["id"] for screen in draft.screens],
        content_rules=draft.design_system["content_rules"],
        state_rules=draft.design_system["state_rules"],
        motion_rules=draft.design_system["motion_rules"],
        accessibility_rules=[f"{req.criterion}: {req.rule}" for req in sorted(draft.a11y, key=lambda item: item.id)],
        responsive_rules=[f"{rule.region_ref} -> {rule.transform.value}" for rule in responsive],
    )

    generation_prompts = [
        (f"Screen '{screen.name}' ({screen.priority.value}): {screen.purpose}. Regions in priority order: "
         + "; ".join(f"{r.id} [{r.priority.value}, {r.parent_layout.lower()}, {r.responsive_transform.value.lower()} when narrow]"
                     for r in sorted(screen.regions, key=lambda r: (r.priority.value, -r.emphasis)))
         + f". Components: {', '.join(screen.components)}. Use only --{token_system.css_prefix}-semantic-* and "
           f"--{token_system.css_prefix}-component-* tokens. Every state keeps a non-color channel. "
           "Do not invent testimonials, logos, metrics, or AI confidence.")
        for screen in screens
    ]

    blocking = [f for f in ir_state.findings if f.severity is Severity.blocking and not f.repaired]
    approval = list(dict.fromkeys([*draft.approval_required, *ir_state.approval_required,
                                   "Design lead (design_lead, Department.design) sign-off before implementation (HITL)."]))
    if blocking:
        terminal = UIUXTerminal.blocked
    elif any(item.startswith("DECISION:") for item in approval) or any(u.blocks for u in unknowns):
        terminal = UIUXTerminal.requires_approval
    else:
        terminal = UIUXTerminal.spec_ready

    degraded_sources = [s for s in sources if "FALLBACK_DEGRADED" in s.detail]
    confidence_value = 0.9 - min(0.05 * len(assumptions), 0.3) - 0.1 * sum(u.blocks for u in unknowns)
    basis = [f"{len(assumptions)} assumption(s)", f"{len(applied)} principle(s) applied", f"territory {selected.id}"]
    if not (brand and brand.palette_hex):
        confidence_value -= 0.1
        basis.append("palette unresolved")
    if degraded_sources:
        confidence_value -= 0.2
        basis.append("derived from degraded (fallback) upstream output")
    if blocking:
        confidence_value = min(confidence_value, 0.3)
    confidence = Confidence(value=round(max(0.2, min(confidence_value, 0.95)), 2), basis=basis,
                            unknowns=[u.question for u in unknowns])

    checks = [
        ValidationCheck(id="schema_strict", status=CheckStatus.passed, evidence="pydantic extra=forbid on every model"),
        ValidationCheck(id="dtcg_tokens_compiled", status=CheckStatus.passed, evidence=f"{token_system.token_count} tokens, tiered, sha256 {token_system.source_hash[:12]}"),
        ValidationCheck(id="wcag_contrast_static",
                        status=CheckStatus.passed if all(c.passes for c in token_system.contrast) else CheckStatus.failed,
                        evidence=f"{sum(c.passes for c in token_system.contrast)}/{len(token_system.contrast)} pairs meet their WCAG 2.2 requirement"),
        ValidationCheck(id="evaluation_engines", status=CheckStatus.failed if blocking else CheckStatus.passed,
                        evidence=f"{len(ir_state.findings)} finding(s), {len(blocking)} blocking unresolved, {ir_state.iterations} repair iteration(s)"),
        ValidationCheck(id="principles_selective", status=CheckStatus.passed, evidence=f"{len(applied)} of {len(principles)} triggered principles changed the IR"),
        ValidationCheck(id="generation_firewall", status=CheckStatus.passed, evidence="terminal is a spec state; no generated/deployed state exists"),
        ValidationCheck(id="browser_and_assistive_tech", status=CheckStatus.not_run, evidence="spec-level compiler; requires implementation"),
    ]

    ir = UIUXDesignIR(
        project_ref=request.project_ref,
        mode=mode,
        product_model=ProductModel(purpose=purpose, platform=platform, primary_user=primary_user,
                                   primary_task=primary_task, business_goal=business_goal),
        sources=sources,
        assumptions=assumptions,
        unknowns=unknowns,
        constraints=[*request.constraints, *(f"NOT: {item}" for item in request.negative_constraints)],
        capabilities=sorted(features),
        information_architecture=InformationArchitecture(
            primary_nav=[IAItem(id=i[0], label=i[1], purpose=i[2], priority=i[3]) for i in template["nav"]],
            hierarchy_depth=2,
            labeling_rule="Labels name the user's object or task in plain language; no internal jargon.",
        ),
        flows=[Flow(id=f[0], name=f[1], goal=f[2],
                    steps=[FlowStep(id=f"{f[0]}.{i + 1}", screen_ref=s[0], user_action=s[1], system_response=s[2], failure_path=s[3])
                           for i, s in enumerate(f[3])],
                    success_signal=f[4]) for f in template["flows"]],
        territories=territories,
        selected_direction=f"{selected.name}: {selected.thesis}",
        principles_applied=applied,
        design_genome=draft.genome,
        design_system=design_system,
        tokens=token_system,
        screens=screens,
        components=component_specs,
        states=states,
        interactions=draft.interactions,
        responsive_rules=responsive,
        accessibility=accessibility,
        performance=PerformanceSpec(requirements=draft.performance_requirements, risks=risks, budgets=budgets),
        ai_trust=ai_trust,
        implementation_mapping=mapping,
        generation_prompts=generation_prompts,
        evaluation=ir_state.findings,
        repair_iterations=ir_state.iterations,
        validation_checks=checks,
        approval_required=approval,
        confidence=confidence,
        terminal=terminal,
    )
    return ir.model_copy(update={"spec_hash": stable_hash(ir.model_dump(mode="json", exclude={"spec_hash"}))})


def _component_tokens(tags: frozenset[str]) -> list[str]:
    tokens = ["semantic.color.foreground", "semantic.color.surface", "semantic.space.stack"]
    if tags & {"action", "cta"}:
        tokens += ["component.button.primary.background", "component.button.primary.foreground", "component.focus.ring"]
    if tags & {"field", "filter", "nav"}:
        tokens += ["semantic.color.border-strong", "component.focus.ring"]
    if "ai" in tags:
        tokens += ["component.ai-trust.border", "component.ai-trust.label", "component.ai-trust.degraded"]
    if "metric" in tags:
        tokens += ["component.metric.value", "component.metric.truth-label"]
    if "status" in tags:
        tokens += ["semantic.color.status.success", "semantic.color.status.warning", "semantic.color.status.danger"]
    return list(dict.fromkeys(tokens))


__all__ = ["compile_uiux", "infer_surface", "stable_hash", "UIUX_SPEC_READY"]
