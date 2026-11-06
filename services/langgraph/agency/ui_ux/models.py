"""Strict contracts for the UI/UX design compiler.

Every model forbids extra fields and every vocabulary that a consumer branches
on is a closed enum. The IR describes a *specification*: nothing in here claims
an interface was generated, rendered, deployed, or measured. Metrics carry a
truth label, accessibility claims carry a verification class, and AI confidence
is never a number unless a calibrated backend contract supplies one.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

UIUX_SCHEMA_VERSION = "amc-uiux-ir/v1"
UIUX_COMPILER_VERSION = "amc-uiux-compiler/v1"
# The compiler's success terminal. There is deliberately no UI_GENERATED /
# ASSET_GENERATED / DEPLOYED value: this compiler stops at a governed spec.
UIUX_SPEC_READY = "UIUX_SPEC_READY"


class _Strict(BaseModel):
    model_config = {"extra": "forbid"}


# --------------------------------------------------------------------------- #
# Closed vocabularies
# --------------------------------------------------------------------------- #


class SurfaceMode(str, Enum):
    landing_page = "LANDING_PAGE"
    application = "APPLICATION"
    dashboard = "DASHBOARD"
    ai_interface = "AI_INTERFACE"
    form_flow = "FORM_FLOW"


class Platform(str, Enum):
    web_responsive = "WEB_RESPONSIVE"
    mobile_web = "MOBILE_WEB"
    desktop_web = "DESKTOP_WEB"


class Priority(str, Enum):
    p0 = "P0"  # primary task
    p1 = "P1"  # important support
    p2 = "P2"  # context
    p3 = "P3"  # enhancement


class UIState(str, Enum):
    default = "DEFAULT"
    hover = "HOVER"
    focus_visible = "FOCUS_VISIBLE"
    pressed = "PRESSED"
    selected = "SELECTED"
    checked = "CHECKED"
    current = "CURRENT"
    expanded = "EXPANDED"
    disabled = "DISABLED"
    read_only = "READ_ONLY"
    loading = "LOADING"
    streaming = "STREAMING"
    skeleton = "SKELETON"
    empty = "EMPTY"
    valid = "VALID"
    invalid = "INVALID"
    warning = "WARNING"
    error = "ERROR"
    success = "SUCCESS"
    pending = "PENDING"
    pending_approval = "PENDING_APPROVAL"
    approved = "APPROVED"
    rejected = "REJECTED"
    degraded = "DEGRADED"
    stale = "STALE"
    drag = "DRAG"
    drop_target = "DROP_TARGET"
    offline = "OFFLINE"
    unavailable = "UNAVAILABLE"


class ResponsiveTransform(str, Enum):
    wrap = "WRAP"
    stack = "STACK"
    reorder = "REORDER"
    collapse = "COLLAPSE"
    scroll = "SCROLL"
    menu = "MENU"
    drawer = "DRAWER"
    full_width = "FULL_WIDTH"
    priority_reduction = "PRIORITY_REDUCTION"


class A11yVerification(str, Enum):
    verified_static = "VERIFIED_STATIC"
    verified_browser = "VERIFIED_BROWSER"
    requires_assistive_tech = "REQUIRES_ASSISTIVE_TECH"
    requires_human_evaluation = "REQUIRES_HUMAN_EVALUATION"


class MetricTruth(str, Enum):
    measured = "MEASURED"
    derived = "DERIVED"
    estimated = "ESTIMATED"
    not_measured = "NOT_MEASURED"
    unavailable = "UNAVAILABLE"


class SourceKind(str, Enum):
    request = "REQUEST"
    brand_core = "BRAND_CORE"
    design_brief = "DESIGN_BRIEF"
    strategy = "STRATEGY"
    compiler_default = "COMPILER_DEFAULT"


class PrincipleFamily(str, Enum):
    usability = "USABILITY"
    heuristics = "HEURISTICS"
    gestalt = "GESTALT"
    cognitive = "COGNITIVE"
    behavioral = "BEHAVIORAL"
    visual = "VISUAL"
    interaction = "INTERACTION"
    platform = "PLATFORM"
    system = "SYSTEM"


class ImplementationStatus(str, Enum):
    verified_existing = "VERIFIED_EXISTING"
    extend = "EXTEND"
    proposed = "PROPOSED"


class EvaluationEngine(str, Enum):
    anti_generic = "ANTI_GENERIC"
    salience_budget = "SALIENCE_BUDGET"
    interaction_debt = "INTERACTION_DEBT"
    state_entropy = "STATE_ENTROPY"
    counterfactual = "COUNTERFACTUAL_UX"
    layout_grammar = "LAYOUT_GRAMMAR"
    traceability = "TRACEABILITY"
    contrast = "CONTRAST"


class Severity(str, Enum):
    blocking = "BLOCKING"
    warning = "WARNING"
    info = "INFO"


class CheckStatus(str, Enum):
    passed = "PASS"
    failed = "FAIL"
    not_run = "NOT_RUN"


class WCAGRequirement(str, Enum):
    aaa_normal = "AAA_NORMAL"  # 7:1
    aaa_large = "AAA_LARGE"  # 4.5:1
    aa_normal = "AA_NORMAL"  # 4.5:1
    aa_large = "AA_LARGE"  # 3:1
    non_text = "NON_TEXT"  # 3:1 (SC 1.4.11)


class UIUXTerminal(str, Enum):
    spec_ready = UIUX_SPEC_READY
    requires_approval = "REQUIRES_APPROVAL"
    blocked = "BLOCKED"


# --------------------------------------------------------------------------- #
# Request
# --------------------------------------------------------------------------- #


class BrandContext(_Strict):
    """The slice of canonical brand state the compiler may read. Never written."""

    brand_name: str = Field(min_length=1)
    positioning: str | None = None
    tone_attributes: list[str] = Field(default_factory=list)
    typography_direction: str | None = None
    imagery_style: str | None = None
    motion_pace: str | None = None
    reduced_motion_fallback: str | None = None
    palette_hex: list[str] = Field(default_factory=list)
    palette_source: SourceKind = SourceKind.compiler_default


class UIUXRequest(_Strict):
    project_ref: str = Field(min_length=1)
    surface: SurfaceMode | None = None
    surface_hint: str = ""
    platform: Platform | None = None
    purpose: str = ""
    primary_user: str = ""
    primary_task: str = ""
    business_goal: str = ""
    content_requirements: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    negative_constraints: list[str] = Field(default_factory=list)
    ai_features: bool | None = None
    ai_provider_known: bool = False
    existing_components: list[str] = Field(default_factory=list)
    locale_rtl: bool = False
    brand: BrandContext | None = None
    sources: list["SourceRef"] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# IR building blocks
# --------------------------------------------------------------------------- #


class SourceRef(_Strict):
    kind: SourceKind
    ref: str = Field(min_length=1)
    detail: str = ""


class Assumption(_Strict):
    id: str
    statement: str
    reason: str
    impact: str


class Unknown(_Strict):
    id: str
    question: str
    blocks: bool = False


class ProductModel(_Strict):
    purpose: str
    platform: Platform
    primary_user: str
    primary_task: str
    business_goal: str


class IAItem(_Strict):
    id: str
    label: str
    purpose: str
    priority: Priority
    children: list[str] = Field(default_factory=list)


class InformationArchitecture(_Strict):
    primary_nav: list[IAItem] = Field(min_length=1)
    hierarchy_depth: int = Field(ge=1, le=4)
    labeling_rule: str


class FlowStep(_Strict):
    id: str
    screen_ref: str
    user_action: str
    system_response: str
    failure_path: str


class Flow(_Strict):
    id: str
    name: str
    goal: str
    steps: list[FlowStep] = Field(min_length=1)
    success_signal: str


class Territory(_Strict):
    id: str
    name: str
    thesis: str
    score: float = Field(ge=0.0, le=1.0)
    fit_rationale: str
    selected: bool = False
    rejection_reason: str | None = None


class PrincipleApplication(_Strict):
    id: str
    name: str
    family: PrincipleFamily
    user_problem: str
    relevance: str
    application: str
    tradeoff: str
    a11y_effect: str
    responsive_effect: str
    implementation_effect: str
    changes: list[str] = Field(min_length=1)  # IR paths this principle altered


class DesignGenome(_Strict):
    hierarchy: str
    density: Literal["LOW", "MEDIUM", "HIGH"]
    geometry: str
    typography: str
    color: str
    material: str
    motion: str
    interaction: str
    signature: str
    genome_hash: str = ""


class ContrastCheck(_Strict):
    foreground: str
    background: str
    foreground_value: str
    background_value: str
    wcag_requirement: WCAGRequirement
    wcag_ratio: float
    passes: bool
    verification: A11yVerification = A11yVerification.verified_static
    # Advisory only. Never a WCAG conformance claim; never merged with the ratio.
    apca_lc_advisory: float
    apca_note: str = "APCA Lc is advisory perceptual analysis, not WCAG 2.2 conformance."


class TokenSystemSpec(_Strict):
    format: Literal["DTCG 2025.10"] = "DTCG 2025.10"
    tiers: list[str] = Field(default_factory=lambda: ["primitive", "semantic", "component"])
    css_prefix: str
    document: dict
    source_hash: str
    token_count: int = Field(ge=1)
    css: str
    contrast: list[ContrastCheck] = Field(default_factory=list)
    palette_resolution: str


class LayoutRegion(_Strict):
    id: str
    purpose: str
    parent_layout: Literal["STACK", "GRID", "CLUSTER", "SIDEBAR", "SPLIT"]
    axis: Literal["BLOCK", "INLINE"]
    spacing_token: str
    priority: Priority
    emphasis: int = Field(ge=1, le=3)  # 3 = strongest visual weight
    overflow: Literal["WRAP", "SCROLL", "TRUNCATE_WITH_DISCLOSURE", "GROW"]
    min_inline: str
    max_inline: str
    responsive_transform: ResponsiveTransform


class ScreenTrace(_Strict):
    user_task: str = Field(min_length=1)
    content: str = Field(min_length=1)
    contract: str = Field(min_length=1)
    component: str = Field(min_length=1)
    token: str = Field(min_length=1)
    state: str = Field(min_length=1)
    interaction: str = Field(min_length=1)
    responsive_rule: str = Field(min_length=1)
    a11y_rule: str = Field(min_length=1)
    performance_rule: str = Field(min_length=1)
    implementation_path: str = Field(min_length=1)
    test: str = Field(min_length=1)
    evidence: str = Field(min_length=1)


class Screen(_Strict):
    id: str
    name: str
    purpose: str
    user_task: str
    priority: Priority
    regions: list[LayoutRegion] = Field(min_length=1)
    components: list[str] = Field(min_length=1)
    trace: ScreenTrace


class ComponentSpec(_Strict):
    id: str
    name: str
    semantic_role: str
    purpose: str
    tokens: list[str] = Field(default_factory=list)
    states: list[UIState] = Field(min_length=1)
    interactions: list[str] = Field(default_factory=list)
    a11y: list[str] = Field(default_factory=list)
    implementation: ImplementationStatus = ImplementationStatus.proposed


class StateSpec(_Strict):
    component_ref: str
    state: UIState
    trigger: str
    visual_delta: str
    content_delta: str
    semantics: str
    keyboard: str
    announcement: str
    motion: str
    recovery: str
    persistence: str
    non_color_channel: str | None = None


class InteractionSpec(_Strict):
    id: str
    component_ref: str
    trigger: str
    input_modes: list[Literal["POINTER", "TOUCH", "KEYBOARD", "SCREEN_READER"]] = Field(min_length=1)
    feedback: str
    standard: bool = True
    justification: str | None = None
    fallback: str | None = None


class ResponsiveRule(_Strict):
    region_ref: str
    condition: str
    transform: ResponsiveTransform
    rationale: str


class A11yRequirement(_Strict):
    id: str
    criterion: str
    rule: str
    verification: A11yVerification


class AccessibilitySpec(_Strict):
    target: Literal["WCAG 2.2"] = "WCAG 2.2"
    requirements: list[A11yRequirement] = Field(default_factory=list)
    predicted: list[str] = Field(default_factory=list)
    verified: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    tests_required: list[str] = Field(default_factory=list)


class Metric(_Strict):
    name: str
    target: str
    truth: MetricTruth
    source: str
    formula: str
    timestamp: str | None = None
    freshness: str
    uncertainty: str
    fallback: str

    @model_validator(mode="after")
    def _measured_needs_evidence(self) -> "Metric":
        if self.truth is MetricTruth.measured and not self.timestamp:
            raise ValueError("a MEASURED metric requires a measurement timestamp")
        return self


class PerformanceSpec(_Strict):
    requirements: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    budgets: list[Metric] = Field(default_factory=list)


class AITrustSpec(_Strict):
    required: bool
    provenance_rules: list[str] = Field(default_factory=list)
    attribution_rules: list[str] = Field(default_factory=list)
    uncertainty_rules: list[str] = Field(default_factory=list)
    feedback_rules: list[str] = Field(default_factory=list)
    confidence_display: Literal["NOT_MEASURED", "CALIBRATED_BACKEND_ONLY"] = "NOT_MEASURED"


class ImplementationMapping(_Strict):
    verified_existing: list[str] = Field(default_factory=list)
    extend: list[str] = Field(default_factory=list)
    proposed: list[str] = Field(default_factory=list)
    contracts: list[str] = Field(default_factory=list)
    state_dependencies: list[str] = Field(default_factory=list)
    events: list[str] = Field(default_factory=list)
    tests: list[str] = Field(default_factory=list)


class DesignSystemSpec(_Strict):
    foundations: list[str]
    patterns: list[str]
    templates: list[str]
    content_rules: list[str]
    state_rules: list[str]
    motion_rules: list[str]
    accessibility_rules: list[str]
    responsive_rules: list[str]


class EvaluationFinding(_Strict):
    engine: EvaluationEngine
    severity: Severity
    subject: str
    message: str
    repaired: bool = False
    repair_action: str | None = None


class ValidationCheck(_Strict):
    id: str
    status: CheckStatus
    evidence: str


class Confidence(_Strict):
    value: float = Field(ge=0.0, le=1.0)
    basis: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)


class UIUXDesignIR(_Strict):
    schema_version: Literal["amc-uiux-ir/v1"] = UIUX_SCHEMA_VERSION
    compiler_version: Literal["amc-uiux-compiler/v1"] = UIUX_COMPILER_VERSION
    project_ref: str
    mode: SurfaceMode
    product_model: ProductModel
    sources: list[SourceRef]
    assumptions: list[Assumption]
    unknowns: list[Unknown]
    constraints: list[str]
    capabilities: list[str]
    information_architecture: InformationArchitecture
    flows: list[Flow] = Field(min_length=1)
    territories: list[Territory] = Field(min_length=1)
    selected_direction: str
    principles_applied: list[PrincipleApplication]
    design_genome: DesignGenome
    design_system: DesignSystemSpec
    tokens: TokenSystemSpec
    screens: list[Screen] = Field(min_length=1)
    components: list[ComponentSpec] = Field(min_length=1)
    states: list[StateSpec] = Field(min_length=1)
    interactions: list[InteractionSpec] = Field(min_length=1)
    responsive_rules: list[ResponsiveRule] = Field(min_length=1)
    accessibility: AccessibilitySpec
    performance: PerformanceSpec
    ai_trust: AITrustSpec
    implementation_mapping: ImplementationMapping
    generation_prompts: list[str]
    evaluation: list[EvaluationFinding]
    repair_iterations: int = Field(ge=0, le=3)
    validation_checks: list[ValidationCheck]
    approval_required: list[str]
    confidence: Confidence
    handoff_only: Literal[True] = True
    terminal: UIUXTerminal
    spec_hash: str = ""


UIUXRequest.model_rebuild()
