"""Selective, deterministic UX principle routing.

A principle is data: the features that make it relevant (``triggers``) and the
concrete edits it makes to the design spec (``effects``). The compiler applies
the effects and records the principle only when at least one effect changed the
IR -- a principle that changes nothing is not "applied", however relevant it
sounds. No LLM is involved; identical requests select identical principles.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import PrincipleFamily, SurfaceMode, UIState

# --------------------------------------------------------------------------- #
# Feature extraction
# --------------------------------------------------------------------------- #

_KEYWORDS: dict[str, tuple[str, ...]] = {
    "forms": ("form", "sign up", "signup", "register", "checkout", "onboard", "input", "apply", "booking"),
    "search": ("search", "filter", "sort", "find", "browse", "catalog"),
    "data": ("dashboard", "metric", "kpi", "analytics", "report", "chart", "table", "data"),
    "ai": ("ai", "assistant", "chat", "copilot", "llm", "generate", "agent", "recommend"),
    "multi_step": ("wizard", "step", "stepper", "checkout", "onboarding", "multi-step", "flow"),
    "destructive": ("delete", "remove", "cancel", "archive", "revoke", "refund"),
    "approvals": ("approve", "approval", "review", "sign-off", "hitl"),
    "realtime": ("real-time", "realtime", "live", "stream", "streaming", "sync"),
    "long_content": ("article", "docs", "documentation", "long-form", "blog", "content"),
    "mobile_first": ("mobile", "phone", "on the go", "field"),
    "high_density": ("power user", "operator", "dense", "trading", "ops", "console", "admin"),
    "onboarding": ("onboard", "first run", "getting started", "welcome"),
}
_WORD = re.compile(r"[a-z0-9][a-z0-9\- ]*")


def extract_features(
    mode: SurfaceMode,
    text: str,
    *,
    ai_features: bool | None,
    rtl: bool,
) -> frozenset[str]:
    haystack = " " + " ".join(_WORD.findall(text.lower())) + " "
    features: set[str] = {f"surface:{mode.value}"}
    for feature, words in _KEYWORDS.items():
        if any(f" {word} " in haystack or f" {word}s " in haystack for word in words):
            features.add(feature)
    if mode is SurfaceMode.dashboard:
        features.update({"data", "high_density"})
    if mode is SurfaceMode.form_flow:
        features.update({"forms", "multi_step"})
    if mode is SurfaceMode.application:
        features.add("stateful")
    if mode is SurfaceMode.landing_page:
        features.add("persuasion")
    # An explicit flag beats keyword inference in both directions...
    if ai_features is True:
        features.add("ai")
    elif ai_features is False:
        features.discard("ai")
    # ...except that an AI interface is AI output by definition.
    if mode is SurfaceMode.ai_interface:
        features.update({"ai", "realtime"})
    if rtl:
        features.add("rtl")
    features.add("interactive")
    return frozenset(sorted(features))


# --------------------------------------------------------------------------- #
# Principle catalog
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Effect:
    """One concrete edit. ``kind`` names the IR surface the compiler mutates."""

    kind: str  # pattern | state_rule | content_rule | motion_rule | a11y | component_state |
    # responsive | perf | genome | interaction_input
    target: str = ""
    value: str = ""
    state: UIState | None = None


@dataclass(frozen=True)
class Principle:
    id: str
    name: str
    family: PrincipleFamily
    triggers: frozenset[str]  # any-of
    user_problem: str
    application: str
    tradeoff: str
    a11y_effect: str
    responsive_effect: str
    implementation_effect: str
    effects: tuple[Effect, ...] = field(default_factory=tuple)


def _p(id_, name, family, triggers, problem, application, tradeoff, a11y, responsive, impl, *effects):
    return Principle(
        id=id_, name=name, family=family, triggers=frozenset(triggers), user_problem=problem,
        application=application, tradeoff=tradeoff, a11y_effect=a11y,
        responsive_effect=responsive, implementation_effect=impl, effects=tuple(effects),
    )


F = PrincipleFamily
CATALOG: tuple[Principle, ...] = (
    _p("usability.system_status", "Visibility of system status", F.heuristics, {"interactive"},
       "Users act blindly when the system hides what it is doing.",
       "Every async action exposes LOADING and a terminal SUCCESS/ERROR with a live-region announcement.",
       "More states to design and test.",
       "Status changes are announced via polite live regions.",
       "Status stays visible when layouts collapse (never inside a collapsed drawer only).",
       "Components expose explicit async state props, not implicit spinners.",
       Effect("state_rule", value="Async actions render LOADING then SUCCESS or ERROR; never a silent completion."),
       Effect("component_state", target="*action", state=UIState.loading),
       Effect("component_state", target="*action", state=UIState.success)),
    _p("usability.error_prevention", "Error prevention and recovery", F.usability, {"forms", "destructive"},
       "Irreversible mistakes and unrecoverable errors.",
       "Destructive actions require confirmation naming the object; errors state cause and a recovery action.",
       "Adds a confirmation step to destructive paths.",
       "Error text is programmatically associated with the field (aria-describedby).",
       "Confirmation surfaces become full-width sheets on narrow viewports.",
       "Form controls carry error message slots and recovery handlers.",
       Effect("content_rule", value="Error messages state what happened, why, and the next recovery action."),
       Effect("pattern", value="Destructive actions: explicit confirmation naming the affected object; undo where the backend supports it."),
       Effect("a11y", target="WCAG 2.2 SC 3.3.1 Error Identification", value="Errors are identified in text and linked to the field.")),
    _p("usability.user_control", "User control and freedom", F.usability, {"multi_step", "forms", "stateful"},
       "Users get trapped in flows they cannot leave or undo.",
       "Every step offers back/cancel without data loss; drafts persist.",
       "Draft persistence needs storage and conflict handling.",
       "Focus returns to a logical element after cancel.",
       "Back/cancel stay reachable in the collapsed layout.",
       "Flow state is serializable so drafts survive navigation.",
       Effect("pattern", value="Multi-step flows keep back/cancel available and preserve entered data."),
       Effect("state_rule", value="Draft state persists across navigation; STALE drafts are labeled with their age.")),
    _p("heuristics.recognition", "Recognition over recall", F.heuristics, {"search", "stateful", "data"},
       "Users must remember identifiers, filters, or prior choices.",
       "Show current filters, selections, and recent items in place.",
       "Persistent chips consume horizontal space.",
       "Active filters are exposed as a labeled list, not color alone.",
       "Filter chips WRAP, then collapse into a count + drawer on narrow viewports.",
       "Filter state lives in the URL for shareability and back-button support.",
       Effect("pattern", value="Active filters/selections are always visible with a single clear-all control."),
       Effect("responsive", target="filter", value="WRAP")),
    _p("gestalt.proximity", "Proximity and common region", F.gestalt, {"forms", "data", "high_density"},
       "Related controls read as unrelated noise.",
       "Group related fields/metrics in labeled regions; spacing inside groups is tighter than between groups.",
       "Requires disciplined spacing tokens.",
       "Groups use fieldset/legend or region landmarks with names.",
       "Groups STACK as units; they never split across columns.",
       "Spacing uses semantic tokens (inline < stack < panel).",
       Effect("pattern", value="Spacing hierarchy: semantic.space.inline < semantic.space.stack < semantic.space.panel."),
       Effect("a11y", target="WCAG 2.2 SC 1.3.1 Info and Relationships", value="Visual groups are programmatic groups (fieldset/legend, labeled regions).")),
    _p("cognitive.progressive_disclosure", "Progressive disclosure", F.cognitive, {"high_density", "forms", "data"},
       "Everything-at-once screens overload working memory.",
       "Primary fields and metrics first; advanced options behind an explicit disclosure.",
       "Hidden options are less discoverable.",
       "Disclosures use aria-expanded and keep focus in place.",
       "Secondary panels COLLAPSE before primary content shrinks.",
       "Disclosure components expose EXPANDED state.",
       Effect("component_state", target="*disclosure", state=UIState.expanded),
       Effect("responsive", target="detail", value="COLLAPSE")),
    _p("behavioral.hick", "Hick's law — limit simultaneous choices", F.behavioral, {"surface:LANDING_PAGE", "onboarding", "persuasion"},
       "Too many equal-weight choices stall the decision.",
       "One primary call to action per view; secondary actions are visually subordinate.",
       "Secondary paths get less attention.",
       "The primary action is first in reading and focus order.",
       "Secondary actions move into a menu before the primary shrinks.",
       "CTA components accept a single `primary` variant per region.",
       Effect("pattern", value="Exactly one primary action per view; secondary actions use the subordinate variant."),
       Effect("genome", target="interaction", value="single dominant action per view")),
    _p("behavioral.fitts", "Fitts's law — target size and distance", F.behavioral, {"mobile_first", "interactive"},
       "Small or distant targets cause missed taps and slow pointing.",
       "Interactive targets are at least 24x24 CSS px (WCAG 2.2 SC 2.5.8), 44x44 for primary touch actions.",
       "Larger targets reduce density.",
       "Meets WCAG 2.2 SC 2.5.8 Target Size (Minimum).",
       "Primary actions go FULL_WIDTH on narrow touch viewports.",
       "Buttons enforce a min-block-size token.",
       Effect("a11y", target="WCAG 2.2 SC 2.5.8 Target Size (Minimum)", value="Interactive targets are at least 24x24 CSS px; primary touch targets 44x44."),
       Effect("responsive", target="cta", value="FULL_WIDTH")),
    _p("behavioral.jakob", "Jakob's law — follow platform conventions", F.behavioral, {"interactive"},
       "Novel interaction patterns force users to relearn basics.",
       "Use native controls and standard placements; nonstandard interactions must justify themselves.",
       "Less room for novelty in core controls.",
       "Native elements carry correct roles and keyboard behavior by default.",
       "Standard navigation transforms (MENU/DRAWER) instead of bespoke gestures.",
       "Prefer semantic HTML elements over div-based widgets.",
       Effect("pattern", value="Core controls are native elements (button, a, input, select, dialog) before any custom widget.")),
    _p("behavioral.tesler", "Tesler's law — own the irreducible complexity", F.behavioral, {"high_density", "data", "approvals"},
       "Pushing complexity onto users produces errors and abandonment.",
       "The system pre-fills, validates, and explains; users confirm rather than compute.",
       "Moves logic into the backend contract.",
       "Explanations are text, not tooltips-only.",
       "Explanations remain inline on narrow viewports.",
       "Backend contracts return derived values with provenance.",
       Effect("content_rule", value="Derived values show how they were derived (source + formula) where users act on them.")),
    _p("behavioral.von_restorff", "Von Restorff — reserve distinctiveness", F.behavioral, {"persuasion", "data", "approvals"},
       "When everything is emphasized nothing is.",
       "Only the P0 element and critical status get the accent treatment.",
       "Brand accent appears less often.",
       "Distinctiveness never relies on color alone.",
       "Accent emphasis survives stacking (it moves with the P0 region).",
       "Accent tokens are only mapped to primary/critical variants.",
       Effect("genome", target="color", value="accent reserved for the P0 action and critical status only")),
    _p("behavioral.truthful_progress", "Truthful progress", F.behavioral, {"multi_step", "realtime", "ai"},
       "Fake progress bars and invented ETAs destroy trust.",
       "Show determinate progress only when the backend reports it; otherwise indeterminate + elapsed time.",
       "Less reassuring than a fabricated percentage.",
       "Progress uses role=progressbar with aria-valuenow only when determinate.",
       "Progress stays in the primary region when layouts stack.",
       "Progress components accept `determinate: false` without a value.",
       Effect("state_rule", value="Determinate progress only from backend-reported values; never a synthetic percentage or ETA."),
       Effect("component_state", target="*progress", state=UIState.pending)),
    _p("visual.hierarchy", "Visual hierarchy through salience budget", F.visual, {"interactive"},
       "Users cannot find the primary task among decoration.",
       "Salience is budgeted: P0 strongest, P3 never outweighs P0.",
       "Decorative elements lose visual weight.",
       "Heading levels mirror the visual hierarchy.",
       "PRIORITY_REDUCTION drops P3 before compressing P0.",
       "Regions carry priority + emphasis metadata.",
       Effect("pattern", value="Salience budget: P0 > P1 > P2 > P3; P3 regions are removed first under constraint."),
       Effect("a11y", target="WCAG 2.2 SC 2.4.6 Headings and Labels", value="Heading structure mirrors the visual hierarchy.")),
    _p("interaction.feedback", "Immediate, proportionate feedback", F.interaction, {"interactive"},
       "Actions without feedback get repeated or abandoned.",
       "Every press shows PRESSED within one frame and a result within the async contract.",
       "Needs motion/state design per control.",
       "Feedback is perceivable without motion or color.",
       "Feedback anchors to the control, not a region that may collapse.",
       "Controls expose PRESSED and disabled-while-pending states.",
       Effect("component_state", target="*action", state=UIState.pressed),
       Effect("motion_rule", value="Feedback motion <= semantic.motion.duration.feedback; disabled under prefers-reduced-motion.")),
    _p("interaction.forms", "Forms: labels, inline validation, preserved input", F.interaction, {"forms"},
       "Unlabeled fields and late validation cause rework.",
       "Persistent visible labels; validate on blur/submit, never on first keystroke; keep input on error.",
       "Longer forms visually.",
       "Labels are programmatic; required state is text, not asterisk color.",
       "Fields STACK single-column on narrow viewports.",
       "Field components expose VALID/INVALID/WARNING/READ_ONLY.",
       Effect("component_state", target="*field", state=UIState.invalid),
       Effect("component_state", target="*field", state=UIState.valid),
       Effect("a11y", target="WCAG 2.2 SC 3.3.2 Labels or Instructions", value="Every input has a persistent visible label."),
       Effect("responsive", target="form", value="STACK")),
    _p("interaction.search", "Search, filter, sort", F.interaction, {"search"},
       "Users cannot narrow large collections.",
       "Search is debounced, results count is announced, empty results suggest recovery.",
       "More states (no-results, partial).",
       "Result counts announced via live region.",
       "Filters move into a DRAWER on narrow viewports.",
       "Query state is URL-backed.",
       Effect("component_state", target="*result", state=UIState.empty),
       Effect("responsive", target="filter", value="DRAWER")),
    _p("interaction.empty_loading_error", "Designed empty, loading, and error states", F.interaction, {"data", "stateful", "ai"},
       "Blank screens look broken; spinners hide structure.",
       "Skeletons mirror final layout; empty states explain and offer the first action; errors offer retry.",
       "Three extra designs per data surface.",
       "Skeletons are aria-hidden with a live 'Loading' status.",
       "Empty states keep the primary action visible at every width.",
       "Data components expose SKELETON/EMPTY/ERROR/STALE.",
       Effect("component_state", target="*data", state=UIState.skeleton),
       Effect("component_state", target="*data", state=UIState.empty),
       Effect("component_state", target="*data", state=UIState.error),
       Effect("component_state", target="*data", state=UIState.stale)),
    _p("interaction.modals", "Modal discipline", F.interaction, {"destructive", "approvals"},
       "Modals interrupt and trap focus incorrectly.",
       "Modals only for decisions that block progress; focus is trapped and restored.",
       "Some confirmations become inline.",
       "dialog element with focus trap and Escape to close.",
       "Modals become full-screen sheets on narrow viewports.",
       "Use the native <dialog> element.",
       Effect("a11y", target="WCAG 2.2 SC 2.4.3 Focus Order", value="Dialogs trap focus while open and restore it to the invoking control on close.")),
    _p("platform.responsive_semantic_zoom", "Semantic zoom", F.platform, {"interactive"},
       "Shrinking a desktop layout produces an unusable mobile one.",
       "Responsive changes transform representation (table -> list, sidebar -> drawer), not just scale.",
       "More layout variants.",
       "Reflow at 320 CSS px without two-dimensional scrolling (SC 1.4.10).",
       "Each region declares its transform.",
       "Container queries where regions are reused.",
       Effect("a11y", target="WCAG 2.2 SC 1.4.10 Reflow", value="Content reflows at 320 CSS px without two-dimensional scrolling (data tables excepted with scroll containers)."),
       Effect("responsive", target="table", value="SCROLL")),
    _p("platform.keyboard", "Full keyboard operability", F.platform, {"interactive"},
       "Keyboard and switch users are locked out.",
       "Every interaction has a keyboard path; focus is always visible and never obscured.",
       "Custom widgets need roving tabindex work.",
       "WCAG 2.2 SC 2.1.1 Keyboard, 2.4.7 Focus Visible, 2.4.11 Focus Not Obscured.",
       "Sticky headers must not cover the focused element.",
       "Focus ring uses semantic.color.focus-ring.",
       Effect("interaction_input", value="KEYBOARD"),
       Effect("a11y", target="WCAG 2.2 SC 2.4.11 Focus Not Obscured (Minimum)", value="Sticky/fixed regions never fully hide the focused element."),
       Effect("component_state", target="*action", state=UIState.focus_visible)),
    _p("platform.rtl", "Bidirectional layout", F.platform, {"rtl"},
       "Mirrored locales break physical-direction layouts.",
       "Use logical properties (inline-start/end) everywhere; icons with direction mirror.",
       "Directional icons need variants.",
       "Reading order matches visual order in both directions.",
       "Transforms are expressed in logical axes.",
       "No left/right CSS in components.",
       Effect("pattern", value="Layout uses logical properties only (margin-inline-start, inset-inline-end)."),
       Effect("genome", target="geometry", value="direction-agnostic logical geometry")),
    _p("system.ai_trust", "Truthful AI provenance", F.system, {"ai"},
       "Users over-trust or mis-attribute machine output.",
       "AI output is wrapped in one trust envelope stating involvement, known provider/model, sources, and review status; no decorative confidence.",
       "Less 'magical' presentation.",
       "Provenance is text, reachable by keyboard, announced when streaming completes.",
       "The provenance label never collapses away on narrow viewports.",
       "A single AITrustEnvelope scope per AI response.",
       Effect("component_state", target="*ai", state=UIState.streaming),
       Effect("component_state", target="*ai", state=UIState.degraded),
       Effect("component_state", target="*ai", state=UIState.unavailable),
       Effect("content_rule", value="AI content is labeled AI-generated or AI-assisted; confidence is shown only from a calibrated backend value, otherwise 'Confidence not measured'.")),
    _p("system.approvals", "Human approval is a first-class state", F.system, {"approvals"},
       "Users cannot tell draft, pending, and approved work apart.",
       "PENDING_APPROVAL, APPROVED, REJECTED are distinct in text and icon, not color alone.",
       "More status vocabulary.",
       "Status is exposed as text.",
       "Status badges stay attached to their item when lists stack.",
       "Status comes from the backend lifecycle, never inferred in the client.",
       Effect("component_state", target="*status", state=UIState.pending_approval),
       Effect("component_state", target="*status", state=UIState.approved),
       Effect("component_state", target="*status", state=UIState.rejected)),
    _p("system.realtime_resilience", "Degraded-network resilience", F.system, {"realtime", "data", "ai"},
       "Live surfaces silently show stale data when the connection drops.",
       "OFFLINE and STALE are explicit; reconnection is automatic with a visible manual retry.",
       "Extra connection-state UI.",
       "Connection changes announced politely.",
       "Connection status remains visible in collapsed layouts.",
       "Stream/socket clients expose connection state and clean up on unmount.",
       Effect("component_state", target="*data", state=UIState.offline),
       Effect("perf", value="Streams, sockets, observers, and timers are cleaned up on unmount.")),
    _p("system.reduced_motion", "Motion is optional", F.system, {"interactive"},
       "Motion causes vestibular harm and distracts.",
       "All non-essential motion is disabled under prefers-reduced-motion; meaning never depends on motion.",
       "Some delight is lost for those users.",
       "WCAG 2.2 SC 2.3.3 Animation from Interactions (AAA) respected via reduced-motion.",
       "No motion-dependent reveal of content at any width.",
       "Motion reads semantic.motion tokens and a reduced-motion guard.",
       Effect("motion_rule", value="prefers-reduced-motion: reduce disables non-essential animation; state changes remain perceivable statically.")),
    _p("cognitive.structured_density", "Structured density for expert users", F.cognitive, {"high_density"},
       "Experts are slowed by consumer-grade whitespace.",
       "Denser rows with strict alignment and tabular numerals; density never drops below target sizes.",
       "Harder for novices.",
       "Density respects the 24px minimum target size.",
       "Density relaxes on touch viewports.",
       "Density is a token scale, not ad hoc spacing.",
       Effect("genome", target="density", value="HIGH"),
       Effect("pattern", value="Numeric data uses tabular numerals and right alignment.")),
    _p("visual.anti_generic_signature", "Product-specific signature", F.visual, {"persuasion", "surface:LANDING_PAGE"},
       "Template-looking pages are indistinguishable and untrustworthy.",
       "One product-specific signature element derived from the brand thesis replaces generic decoration.",
       "Requires real brand input.",
       "Signature is decorative-only (aria-hidden) or has a text equivalent.",
       "Signature scales down or drops (P3) before content.",
       "Signature is a single component, not scattered effects.",
       Effect("pattern", value="Replace generic decoration (gradients, glows, floating blobs) with one brand-derived signature element.")),
)


def select_principles(features: frozenset[str]) -> list[Principle]:
    return [principle for principle in CATALOG if principle.triggers & features]
